import json
import unittest
from pathlib import Path
from intake_translator.core import IntakeError, analyze_intake

ROOT = Path(__file__).parents[1] / 'examples'


class GalleryTests(unittest.TestCase):
    def test_valid_and_reviewable_examples(self):
        expected = {
            'good-agreement.json': ([], {'launch_date': '2026-12-01', 'seat_count': 40}),
            'bad-conflict.json': (['launch_date'], {'seat_count': 40}),
            'bad-missing-required.json': ([], {'customer_name': 'Marigold Labs'}),
        }
        for filename, (conflicts, resolved) in expected.items():
            with self.subTest(filename=filename):
                packet = analyze_intake(json.loads((ROOT / filename).read_text()))
                self.assertEqual(packet['status'], 'needs_review')
                self.assertEqual(sorted(packet['conflicts']), conflicts)
                for key, value in resolved.items(): self.assertEqual(packet['resolved'][key], value)
                if filename == 'bad-missing-required.json':
                    self.assertIn('What is the launch date?', packet['questions'])

    def test_rejected_examples(self):
        for filename, code in [('bad-invalid-date.json', 'invalid_field'), ('bad-unknown-field.json', 'invalid_field'), ('bad-unsupported-version.json', 'unsupported_version')]:
            with self.subTest(filename=filename), self.assertRaises(IntakeError) as caught:
                analyze_intake(json.loads((ROOT / filename).read_text()))
            self.assertEqual(caught.exception.code, code)

    def test_source_shapes_are_explicitly_not_normalized_input(self):
        source = json.loads((ROOT / 'source-shapes.json').read_text())
        self.assertIn('NOT vendor webhook', source['_note'])
        with self.assertRaisesRegex(IntakeError, 'schema_version'):
            analyze_intake(source)


if __name__ == '__main__': unittest.main()
