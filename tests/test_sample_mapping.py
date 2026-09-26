import copy
import json
import unittest
from pathlib import Path
from intake_translator.core import IntakeError, analyze_intake
from intake_translator.sample_mapping import map_sample_sources

ROOT = Path(__file__).parents[1] / 'examples' / 'gallery'
RAW = json.loads((ROOT / 'source-shapes.json').read_text())
CONFIG = json.loads((ROOT / 'sample-mapping.json').read_text())


class SampleMappingTests(unittest.TestCase):
    def test_shape_mapping_preserves_conflicting_dates(self):
        event = map_sample_sources(RAW, CONFIG)
        self.assertEqual(event['sources']['form']['seat_count'], '40')
        packet = analyze_intake(event)
        self.assertEqual(packet['status'], 'needs_review')
        self.assertEqual([x['source'] for x in packet['conflicts']['launch_date']], ['form', 'crm', 'notes'])
        self.assertEqual(packet['resolved']['seat_count'], 40)

    def test_configured_key_missing_blocks_instead_of_silent_drop(self):
        damaged = copy.deepcopy(RAW)
        del damaged['crm_deal_record']['properties']['Target_Go_Live']
        with self.assertRaisesRegex(IntakeError, 'missing configured keys'):
            map_sample_sources(damaged, CONFIG)

    def test_duplicate_form_key_blocks(self):
        damaged = copy.deepcopy(RAW)
        damaged['form_submission']['fields'].append({'key': 'licenses', 'answer': '99'})
        with self.assertRaisesRegex(IntakeError, 'duplicate keys'):
            map_sample_sources(damaged, CONFIG)


if __name__ == '__main__': unittest.main()
