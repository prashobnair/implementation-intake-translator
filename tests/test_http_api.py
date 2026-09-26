import copy
import http.client
import json
import socket
from unittest.mock import patch
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

    def test_non_loopback_bind_rejected(self):
        with self.assertRaisesRegex(ValueError, "127.0.0.1"):
            IntakeServer(("0.0.0.0", 0), str(Path(self.tmp.name) / "unsafe.db"))

    def test_partial_body_times_out_without_persisting_event(self):
        # A client promises more bytes than it sends. The connection must not
        # hold a server thread forever, nor persist the incomplete event.
        import intake_translator.http_api as api
        with patch.object(api, "READ_TIMEOUT_SECONDS", 0.15):
            with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2) as sock:
                sock.sendall(b"POST /intakes HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 20\r\nConnection: close\r\n\r\n{}")
                sock.settimeout(2)
                response = b""
                while True:
                    data = sock.recv(4096)
                    if not data: break
                    response += data
        self.assertIn(b"408 Request Timeout", response)
        self.assertIn(b'request_timeout', response)
        self.assertEqual(self.post(EXAMPLE)[0], 201)

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
