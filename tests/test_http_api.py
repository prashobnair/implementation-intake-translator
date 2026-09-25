import copy
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from intake_translator.http_api import IntakeServer, MAX_BODY_BYTES

EXAMPLE = json.loads((Path(__file__).parents[1] / "examples/conflicting-intake.json").read_text())


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = IntakeServer(("127.0.0.1", 0), str(Path(self.tmp.name) / "events.db"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = json.loads(response.read())
        status = response.status
        connection.close()
        return status, payload

    def post(self, event):
        return self.request("POST", "/intakes", json.dumps(event).encode(), {"Content-Type": "application/json"})

    def test_health_and_unknown_path(self):
        self.assertEqual(self.request("GET", "/health")[0], 200)
        self.assertEqual(self.request("GET", "/missing")[0], 404)

    def test_create_replay_conflict(self):
        status, packet = self.post(EXAMPLE)
        self.assertEqual(status, 201)
        self.assertFalse(packet["replayed"])
        self.assertEqual(packet["status"], "needs_review")
        self.assertEqual(self.post(EXAMPLE)[0], 200)
        altered = copy.deepcopy(EXAMPLE)
        altered["sources"]["form"]["seat_count"] = 80
        self.assertEqual(self.post(altered)[0], 409)

    def test_validation_and_body_boundaries(self):
        self.assertEqual(self.request("POST", "/intakes", b"{}", {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/intakes", b"{", {"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.request("POST", "/intakes", b"{}", {"Content-Type": "application/json", "Content-Length": str(MAX_BODY_BYTES + 1)})[0], 413)
        malformed = copy.deepcopy(EXAMPLE)
        malformed["sources"]["crm"]["launch_date"] = "tomorrow"
        code, data = self.post(malformed)
        self.assertEqual(code, 422)
        self.assertEqual(data["error"], "invalid_field")

if __name__ == "__main__": unittest.main()
