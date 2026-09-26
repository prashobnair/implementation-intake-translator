import copy
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from intake_translator.dashboard import render_dashboard
from intake_translator.demo import walkthrough


class DashboardTests(unittest.TestCase):
    def test_all_scenarios_render_offline(self):
        result = walkthrough(Path(__file__).parents[1] / 'examples')
        html = render_dashboard(result)
        for text in ('Agreement', 'Conflicting launch dates', 'Missing launch date',
                     'Invalid calendar date', 'Unmapped field', 'Schema drift',
                     'not_approved', '2026-12-15', 'replayed: true', 'Offline demo'):
            self.assertIn(text, html)
        self.assertNotIn('<script', html)
        self.assertNotIn('https://', html)
        self.assertEqual(html.count('class="case"'), 6)
        class Parse(HTMLParser): pass
        Parse().feed(html)

    def test_dynamic_sample_content_is_escaped(self):
        result = walkthrough(Path(__file__).parents[1] / 'examples')
        damaged = copy.deepcopy(result)
        damaged['samples']['bad-invalid-date']['detail'] = '<script>alert(1)</script>'
        damaged['mock_project']['customer_name'] = '<img src=x onerror=alert(1)>'
        html = render_dashboard(damaged)
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('&lt;img', html)


if __name__ == '__main__': unittest.main()
