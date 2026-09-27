"""Synthetic edge inputs for the offline adapter and review boundary."""

import json
import tempfile
import unittest
from pathlib import Path

from intake_translator.core import IntakeError, analyze_intake
from intake_translator.mock_crm import apply_reviewed_intake
from intake_translator.review import submit_review
from intake_translator.sample_mapping import map_sample_sources
from intake_translator.store import process_once

ROOT = Path(__file__).parents[1] / "examples"
EVENT = json.loads((ROOT / "conflicting-intake.json").read_text())
SHAPES = json.loads((ROOT / "source-shapes.json").read_text())
CONFIG = json.loads((ROOT / "sample-mapping.json").read_text())


class MoreEdges(unittest.TestCase):
    def test_validation_none_empty_and_unrecognized_source(self):
        for event in [
            None,
            {},
            {**EVENT, "event_id": None},
            {**EVENT, "sources": {}},
            {**EVENT, "sources": {"form": {"bad": 1}}},
        ]:
            with self.subTest(event=str(event)[:30]), self.assertRaises(IntakeError):
                analyze_intake(event)

    def test_storage_review_and_mock_rejections(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "events.sqlite3")
            with self.assertRaises(IntakeError):
                submit_review(db, "not-stored", {})
            with self.assertRaises(IntakeError):
                apply_reviewed_intake(db, "not-stored")
            process_once(db, EVENT)
            for event_id, decision, version in [
                ("", {}, 0),
                (EVENT["event_id"], {}, 1),
                (EVENT["event_id"], [], 0),
                (EVENT["event_id"], {"launch_date": "nonexistent"}, 0),
            ]:
                with (
                    self.subTest(event_id=event_id, decision=str(decision)),
                    self.assertRaises(IntakeError),
                ):
                    submit_review(db, event_id, decision, version)
            submit_review(db, EVENT["event_id"], {"launch_date": "form"})
            with self.assertRaises(IntakeError):
                submit_review(db, EVENT["event_id"], {"launch_date": "crm"})

    def test_mapping_rejects_bad_config_and_missing_records(self):
        for raw, config in [({}, CONFIG), (SHAPES, {}), ([], CONFIG)]:
            with (
                self.subTest(raw=str(raw)[:10], config=str(config)[:10]),
                self.assertRaises(IntakeError),
            ):
                map_sample_sources(raw, config)
