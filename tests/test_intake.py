import copy
import json
import tempfile
import unittest
from pathlib import Path
from intake_translator import IntakeError, analyze_intake
from intake_translator.store import process_once

EXAMPLE = json.loads((Path(__file__).parents[1] / "examples/conflicting-intake.json").read_text())

class IntakeTests(unittest.TestCase):
    def test_conflict_preserves_both_sources_and_stops(self):
        packet = analyze_intake(EXAMPLE)
        self.assertEqual(packet["status"], "needs_review")
        self.assertEqual([c["source"] for c in packet["conflicts"]["launch_date"]], ["form", "crm"])
        self.assertNotIn("launch_date", packet["resolved"])
        self.assertEqual(packet["resolved"]["seat_count"], 75)

    def test_missing_required_field_becomes_question(self):
        event = copy.deepcopy(EXAMPLE)
        for source in event["sources"].values(): source.pop("customer_name", None)
        self.assertIn("What is the customer name?", analyze_intake(event)["questions"])

    def test_malformed_date_rejected(self):
        event = copy.deepcopy(EXAMPLE)
        event["sources"]["form"]["launch_date"] = "2026-02-30"
        with self.assertRaisesRegex(IntakeError, "calendar date"):
            analyze_intake(event)

    def test_duplicate_replays_and_changed_payload_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "events.db")
            first, replayed = process_once(db, EXAMPLE)
            self.assertFalse(replayed)
            second, replayed = process_once(db, EXAMPLE)
            self.assertTrue(replayed)
            self.assertEqual(first, second)
            changed = copy.deepcopy(EXAMPLE)
            changed["sources"]["form"]["seat_count"] = 80
            with self.assertRaisesRegex(IntakeError, "already used"):
                process_once(db, changed)

    def test_unknown_field_and_schema_version_rejected(self):
        event = copy.deepcopy(EXAMPLE)
        event["sources"]["crm"]["secret"] = "nope"
        with self.assertRaisesRegex(IntakeError, "unknown fields"):
            analyze_intake(event)
        event = copy.deepcopy(EXAMPLE)
        event["schema_version"] = "2"
        with self.assertRaisesRegex(IntakeError, "schema_version"):
            analyze_intake(event)

if __name__ == "__main__": unittest.main()
