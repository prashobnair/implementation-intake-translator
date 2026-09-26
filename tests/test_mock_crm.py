import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from intake_translator.core import IntakeError
from intake_translator.store import process_once
from intake_translator.review import submit_review
from intake_translator.mock_crm import apply_reviewed_intake

EXAMPLE = json.loads((Path(__file__).parents[1] / 'examples/conflicting-intake.json').read_text())


class MockCrmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'events.sqlite3')
        self.event_id = EXAMPLE['event_id']
        process_once(self.db, EXAMPLE)

    def tearDown(self):
        self.tmp.cleanup()

    def test_review_is_required_and_source_selection_is_preserved(self):
        with self.assertRaisesRegex(IntakeError, 'no reviewed decision'):
            apply_reviewed_intake(self.db, self.event_id)
        submit_review(self.db, self.event_id, {'launch_date': 'crm'})
        project, replayed = apply_reviewed_intake(self.db, self.event_id)
        self.assertFalse(replayed)
        self.assertEqual(project['launch_date'], EXAMPLE['sources']['crm']['launch_date'])
        self.assertEqual(project['system'], 'local_mock_crm')
        self.assertEqual(project['review_version'], 1)
        again, replayed = apply_reviewed_intake(self.db, self.event_id)
        self.assertTrue(replayed)
        self.assertEqual(project, again)

    def test_failure_rolls_back_and_retry_succeeds(self):
        submit_review(self.db, self.event_id, {'launch_date': 'form'})
        with self.assertRaisesRegex(IntakeError, 'failed before commit'):
            apply_reviewed_intake(self.db, self.event_id, fail_before_write=True)
        with sqlite3.connect(self.db) as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mock_projects'").fetchone())
        project, replayed = apply_reviewed_intake(self.db, self.event_id)
        self.assertFalse(replayed)
        self.assertEqual(project['launch_date'], EXAMPLE['sources']['form']['launch_date'])

    def test_concurrent_retries_create_single_mock_project(self):
        submit_review(self.db, self.event_id, {'launch_date': 'crm'})
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: apply_reviewed_intake(self.db, self.event_id), range(4)))
        self.assertEqual(sum(not replayed for _, replayed in results), 1)
        self.assertEqual(len({p['project_id'] for p, _ in results}), 1)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM mock_projects').fetchone()[0], 1)


if __name__ == '__main__': unittest.main()
