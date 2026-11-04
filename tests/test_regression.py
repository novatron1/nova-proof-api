"""Regression: nothing the integration touched broke the old paths.

Run:  python -m unittest discover -s tests -p "test_regression.py" -v
       (from the repo root)

Covers:
  1. The original money path (tests/test_money.py, parser + ledger
     directly) still scores 100/100.
  2. The live HTTP API: /health, /reason (canonical example, 200 with
     answer 10), /reason with unparseable input (422, never a guess),
     /concept with text (shared-frame envelope), /concept with frames
     (external-LM input), /concept with an adapter task passthrough.
"""

import http.client
import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent


class TestOldMoneyPath(unittest.TestCase):
    def test_old_path_still_100(self):
        proc = subprocess.run(
            [sys.executable, "-m", "tests.test_money"],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("100/100 correct", proc.stdout)


class TestLiveAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from nova.api import Handler
        from http.server import ThreadingHTTPServer
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _req(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        conn.request(method, path,
                     json.dumps(body) if body is not None else None, headers)
        resp = conn.getresponse()
        data = json.loads(resp.read() or b"{}")
        conn.close()
        return resp.status, data

    def test_health(self):
        # The version is asserted against the source of truth, not a
        # hardcoded literal: the literal "0.2.0" broke on the v0.3.0
        # stabilization freeze (2026-10-26) and had to be bumped with
        # every release. Importing VERSION keeps the pin honest.
        from nova.api import VERSION
        status, data = self._req("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["service"], "nova-proof-api")
        self.assertEqual(data["version"], VERSION)

    def test_reason_canonical(self):
        status, data = self._req("POST", "/reason", {"question":
            "Marcus gave John $20. John gave Sarah $10. "
            "How much money does John have left from the $20?"})
        self.assertEqual(status, 200)
        self.assertEqual(data["answer"], 10)
        self.assertEqual(len(data["proof"]), 3)

    def test_reason_unparseable_is_422(self):
        status, data = self._req("POST", "/reason", {"question":
            "John handed Sarah a tenner."})
        self.assertEqual(status, 422)
        self.assertIn("error", data)

    def test_concept_text(self):
        status, data = self._req("POST", "/concept", {"text":
            "Marcus gave John $20. John gave Sarah $10. "
            "How much money does John have left from the $20?"})
        self.assertEqual(status, 200)
        self.assertEqual(data["answer"], 10)
        self.assertEqual(data["status"], "verified")
        self.assertTrue(data["complete"])
        self.assertEqual(len(data["frames"]), 3)
        self.assertIn("John has $10", data["answer_text"])

    def test_concept_frames_input(self):
        # An external language model submits structured frames directly.
        status, data = self._req("POST", "/concept", {"frames": [
            {"kind": "transfer", "who": "Marcus", "what": "give",
             "recipient": "John", "object": "dollars", "quantity": 20,
             "units": "dollars", "polarity": "positive",
             "certainty": "known", "status": "verified"},
            {"kind": "transfer", "who": "John", "what": "give",
             "recipient": "Sarah", "object": "dollars", "quantity": 10,
             "units": "dollars", "polarity": "positive",
             "certainty": "known", "status": "verified"},
            {"kind": "query", "who": "John", "what": "balance",
             "quantity": 20, "units": "dollars", "polarity": "positive",
             "certainty": "known", "status": "verified"}]})
        self.assertEqual(status, 200)
        self.assertEqual(data["answer"], 10)

    def test_concept_adapter_passthrough(self):
        status, data = self._req("POST", "/concept",
                                 {"task": "calculate",
                                  "expression": "15*120*8"})
        self.assertEqual(status, 200)
        self.assertEqual(data["answer"], 14400)
        self.assertEqual(data["status"], "verified")

    def test_concept_unparseable_is_422(self):
        status, data = self._req("POST", "/concept",
                                 {"text": "blorp glorp wubble."})
        self.assertEqual(status, 422)

    def test_concept_yes_no(self):
        status, data = self._req("POST", "/concept", {"text":
            "John did not give Sarah $10. Did John give Sarah $10?"})
        self.assertEqual(status, 200)
        self.assertEqual(data["verdict"], "no")


if __name__ == "__main__":
    unittest.main()
