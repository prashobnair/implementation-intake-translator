import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from intake_translator.core import IntakeError
from intake_translator.review import submit_review
from intake_translator.store import process_once

EXAMPLE = json.loads((Path(__file__).parents[1] / "examples/conflicting-intake.json").read_text())


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "events.sqlite3")
        process_once(self.db, EXAMPLE)
        self.event_id = EXAMPLE["event_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_source_selection_and_immutable_original(self):
        packet, replayed = submit_review(self.db, self.event_id, {"launch_date": "crm"})
        self.assertFalse(replayed)
        self.assertEqual(packet["status"], "approved")
        self.assertEqual(packet["review_version"], 1)
        self.assertEqual(
            packet["resolved"]["launch_date"], EXAMPLE["sources"]["crm"]["launch_date"]
        )
        original, _ = process_once(self.db, EXAMPLE)
        self.assertEqual(original["status"], "needs_review")
        self.assertIn("launch_date", original["conflicts"])
        replay, replayed = submit_review(self.db, self.event_id, {"launch_date": "crm"})
        self.assertTrue(replayed)
        self.assertEqual(packet, replay)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM review_decisions").fetchone()[0], 1)

    def test_missing_required_and_invalid_choices_block(self):
        missing = copy.deepcopy(EXAMPLE)
        missing["event_id"] = "missing-customer"
        for source in missing["sources"].values():
            source.pop("customer_name", None)
        process_once(self.db, missing)
        for event_id, decisions in [
            (self.event_id, {}),
            (self.event_id, {"launch_date": "unknown"}),
            (self.event_id, {"seat_count": "crm"}),
        ]:
            with self.assertRaises(IntakeError):
                submit_review(self.db, event_id, decisions)
        with self.assertRaisesRegex(IntakeError, "required field"):
            submit_review(self.db, missing["event_id"], {"launch_date": "crm"})
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'review_decisions'"
                ).fetchone()
            )

    def test_concurrent_decisions_cannot_overwrite(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(submit_review, self.db, self.event_id, {"launch_date": source})
                for source in ("form", "crm")
            ]
            results = []
            for future in futures:
                try:
                    results.append(future.result())
                except IntakeError as exc:
                    results.append(exc.code)
        self.assertEqual(sum(isinstance(r, tuple) for r in results), 1)
        self.assertIn("review_conflict", results)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM review_decisions").fetchone()[0], 1)

    def test_missing_event_cannot_create_approval(self):
        with self.assertRaisesRegex(IntakeError, "no stored intake"):
            submit_review(self.db, "unknown", {})


if __name__ == "__main__":
    unittest.main()
