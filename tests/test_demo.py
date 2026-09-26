import unittest
from pathlib import Path
from intake_translator.demo import walkthrough


class DemoTests(unittest.TestCase):
    def test_disposable_walkthrough_covers_every_sample_and_gate(self):
        result = walkthrough(Path(__file__).parents[1] / 'examples')
        self.assertEqual(len(result['samples']), 6)
        self.assertEqual(result['samples']['good-agreement']['status'], 'needs_review')
        self.assertEqual(result['samples']['bad-conflict']['status'], 'needs_review')
        self.assertEqual(result['samples']['bad-missing-required']['status'], 'needs_review')
        self.assertEqual(result['samples']['bad-invalid-date']['error'], 'invalid_field')
        self.assertEqual(result['samples']['bad-unknown-field']['error'], 'invalid_field')
        self.assertEqual(result['samples']['bad-unsupported-version']['error'], 'unsupported_version')
        self.assertEqual(result['before_review'], 'not_approved')
        self.assertEqual(result['selected_source'], 'crm')
        self.assertEqual(result['mock_project']['launch_date'], '2026-12-15')
        self.assertTrue(result['mock_project_replayed'])
        self.assertEqual(result['state'], 'disposed')


if __name__ == '__main__': unittest.main()
