"""Exercise the command boundary with synthetic inputs and a temporary ledger."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from intake_translator.cli import main

ROOT = Path(__file__).parents[1] / "examples"


class CliTests(unittest.TestCase):
    def test_create_replay_bad_payload_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "events.sqlite3")
            good = str(ROOT / "good-agreement.json")
            bad = str(ROOT / "bad-invalid-date.json")
            for path, expected, replayed in [
                (good, 0, False),
                (good, 0, True),
                (bad, 2, None),
                (str(Path(tmp) / "missing.json"), 2, None),
            ]:
                out, err = io.StringIO(), io.StringIO()
                with patch("sys.argv", ["intake", path, "--db", db]):
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        self.assertEqual(main(), expected)
                if expected == 0:
                    self.assertEqual(json.loads(out.getvalue())["replayed"], replayed)
                else:
                    self.assertIn("intake error:", err.getvalue())
