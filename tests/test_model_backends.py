"""Phase 4 (Req 6): the model-agnostic interface — registry, generic
OpenAI-compatible transport, /concept model selection.

Run:  python -m unittest discover -s tests -p "test_model_backends.py" -v
       (from the repo root)

No live calls here: the Meta adapter's live path is validated by
``eval/run_phase4_smoke.py`` (small, costed) and the Baseten
adapter's by ``eval/run_baseten_smoke.py``. The generic transport
is validated against a loopback stub server speaking the
OpenAI-compatible chat-completions schema.
"""

import http.client
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nova.model_interface import (  # noqa: E402
    MetaModelAdapter, ModelConfig, OpenAICompatibleAdapter,
    RateLimitedError, get_model, list_models)
from nova.semantic.pipeline import answer_text  # noqa: E402

MONEY_Q = ("Marcus gave John $20. John gave Sarah $10. "
           "How much money does John have left from the $20?")


class TestRegistry(unittest.TestCase):
    def test_builtin_names(self):
        names = list_models()
        for expected in ("meta", "muse-spark", "baseten", "mock",
                         "openai-compatible"):
            self.assertIn(expected, names)

    def test_unknown_name_raises(self):
        with self.assertRaises(ValueError):
            get_model("definitely-not-a-model")

    def test_mock_resolves(self):
        model = get_model("mock")
        self.assertEqual(model.model_id, "mock")
        resp = model.complete("hello")
        self.assertEqual(resp.text, "mock")

    def test_meta_resolves_to_muse_spark(self):
        # Construction only — no network. The live path is the smoke
        # script, not this test.
        for name in ("meta", "muse-spark"):
            model = get_model(name)
            self.assertEqual(model.model_id, "muse-spark-1.3")
            self.assertEqual(model._max_tokens, 2048)

    def test_meta_adapter_rejects_other_models(self):
        with self.assertRaises(ValueError):
            MetaModelAdapter(ModelConfig(model_id="gpt-4"))

    def test_meta_adapter_default_cap(self):
        model = MetaModelAdapter()
        self.assertEqual(model.model_id, "muse-spark-1.3")
        self.assertEqual(model._max_tokens, 2048)


class _StubHandler(BaseHTTPRequestHandler):
    """OpenAI-compatible chat-completions stub. The scenario and the
    last request are stored on the server object."""

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        self.server.last_request = {
            "path": self.path,
            "headers": dict(self.headers),
            "body": json.loads(raw or b"{}"),
        }
        scenario = self.server.scenario
        if scenario == "rate_limit":
            self._send_json(429, {"error": {"message": "slow down"}})
            return
        if scenario == "auth":
            self._send_json(401, {"error": {"message": "bad key"}})
            return
        self._send_json(200, {
            "id": "stub-1", "object": "chat.completion",
            "choices": [{"index": 0,
                         "message": {"role": "assistant",
                                     "content": "stub answer"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                      "total_tokens": 15}})

    def log_message(self, *args):
        pass


class TestOpenAICompatibleAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        cls.server.scenario = "ok"
        cls.server.last_request = None
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()
        os.environ["NOVA_PHASE4_TEST_KEY"] = "test-key-123"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        os.environ.pop("NOVA_PHASE4_TEST_KEY", None)

    def _adapter(self):
        return OpenAICompatibleAdapter(ModelConfig(
            model_id="stub-model",
            endpoint=f"http://127.0.0.1:{self.port}",
            api_key_env="NOVA_PHASE4_TEST_KEY"))

    def test_request_schema_and_response(self):
        adapter = self._adapter()
        resp = adapter.complete("What is 2+2?")
        req = self.server.last_request
        self.assertEqual(req["path"], "/chat/completions")
        body = req["body"]
        self.assertEqual(body["model"], "stub-model")
        self.assertEqual(body["messages"],
                         [{"role": "user", "content": "What is 2+2?"}])
        self.assertEqual(body["temperature"], 0.0)
        self.assertEqual(body["max_tokens"], 2048)
        self.assertEqual(req["headers"].get("Authorization"),
                         "Bearer test-key-123")
        self.assertEqual(resp.text, "stub answer")
        self.assertEqual(resp.model_id, "stub-model")
        self.assertEqual(resp.tokens_used, 15)
        self.assertEqual(resp.raw["finish_reason"], "stop")

    def test_explicit_max_tokens_forwarded(self):
        adapter = self._adapter()
        adapter.complete("hi", max_tokens=64)
        self.assertEqual(self.server.last_request["body"]["max_tokens"],
                         64)

    def test_rate_limit_is_hard_stop(self):
        self.server.scenario = "rate_limit"
        try:
            with self.assertRaises(RateLimitedError):
                self._adapter().complete("hi")
        finally:
            self.server.scenario = "ok"

    def test_auth_failure_raises(self):
        self.server.scenario = "auth"
        try:
            with self.assertRaises(RuntimeError):
                self._adapter().complete("hi")
        finally:
            self.server.scenario = "ok"

    def test_missing_config_raises(self):
        for key in ("NOVA_MODEL_ENDPOINT", "NOVA_MODEL_ID"):
            os.environ.pop(key, None)
        with self.assertRaises(ValueError):
            OpenAICompatibleAdapter(ModelConfig(model_id=""))

    def test_plain_http_rejected(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleAdapter(ModelConfig(
                model_id="x", endpoint="http://example.com"))


class TestBasetenAdapter(unittest.TestCase):
    """The Baseten-backed adapter: connector transport, no env key.

    Construction only — no network. The live path is
    ``eval/run_baseten_smoke.py``. The fake transport below proves
    the adapter routes through the injected transport (the
    surrogate path) rather than the env-key path.
    """

    def test_registry_resolves_baseten(self):
        for key in ("NOVA_MODEL_ENDPOINT", "NOVA_MODEL_ID",
                    "NOVA_MODEL_API_KEY", "BASETEN_API_KEY"):
            os.environ.pop(key, None)
        model = get_model("baseten")
        self.assertEqual(model.model_id,
                         "meta-models/muse-spark-open-1026")
        self.assertEqual(model._base_url,
                         "https://inference.baseten.co/v1")
        # The transport path holds no key at all.
        self.assertIsNone(model._api_key)
        self.assertIsNotNone(model._transport)

    def test_baseten_rejects_other_models(self):
        from nova.model_interface import BasetenAdapter
        with self.assertRaises(ValueError):
            BasetenAdapter(ModelConfig(model_id="gpt-4"))
        with self.assertRaises(ValueError):
            BasetenAdapter(ModelConfig(
                model_id="meta-models/muse-spark-open-1026",
                endpoint="https://example.com/v1"))

    def test_baseten_transport_is_surrogate_not_env_key(self):
        from nova.model_interface import BasetenAdapter
        from eval.live_baseten import baseten_post_chat
        for key in ("NOVA_MODEL_ENDPOINT", "NOVA_MODEL_ID",
                    "NOVA_MODEL_API_KEY", "BASETEN_API_KEY"):
            os.environ.pop(key, None)
        model = BasetenAdapter()
        # The adapter was built on the real Baseten transport.
        self.assertIs(model._transport, baseten_post_chat)
        # Swap in a fake transport: complete() must route through
        # it, with no env key and no network.
        calls = []

        def fake_transport(base_url, body):
            calls.append((base_url, body))
            return {"choices": [{"message": {"role": "assistant",
                                             "content": "fake answer"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10,
                              "completion_tokens": 5}}

        model._transport = fake_transport
        resp = model.complete("What is 2+2?")
        self.assertEqual(resp.text, "fake answer")
        self.assertEqual(resp.model_id,
                         "meta-models/muse-spark-open-1026")
        self.assertEqual(resp.tokens_used, 15)
        self.assertEqual(model.last_usage,
                         {"tokens_in": 10, "tokens_out": 5})
        self.assertEqual(model.last_finish_reason, "stop")
        self.assertEqual(len(calls), 1)
        base_url, body = calls[0]
        self.assertEqual(base_url, "https://inference.baseten.co/v1")
        self.assertEqual(body["model"],
                         "meta-models/muse-spark-open-1026")
        self.assertEqual(body["messages"],
                         [{"role": "user", "content": "What is 2+2?"}])
        self.assertEqual(body["max_tokens"], 2048)

    def test_generic_adapter_transport_injection(self):
        # The generic adapter accepts a transport and then reads no
        # env key: any connector-backed provider can attach this way.
        for key in ("NOVA_MODEL_ENDPOINT", "NOVA_MODEL_ID",
                    "NOVA_MODEL_API_KEY"):
            os.environ.pop(key, None)
        seen = []

        def fake_transport(base_url, body):
            seen.append((base_url, body))
            return {"choices": [{"message": {"role": "assistant",
                                             "content": "transport ok"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 7,
                              "completion_tokens": 3}}

        adapter = OpenAICompatibleAdapter(
            ModelConfig(model_id="some-model",
                        endpoint="https://provider.example/v1"),
            transport=fake_transport)
        self.assertIsNone(adapter._api_key)
        resp = adapter.complete("hi")
        self.assertEqual(resp.text, "transport ok")
        self.assertEqual(resp.tokens_used, 10)
        self.assertEqual(adapter.last_usage,
                         {"tokens_in": 7, "tokens_out": 3})
        self.assertEqual(seen[0][0], "https://provider.example/v1")
        self.assertEqual(seen[0][1]["model"], "some-model")


class TestPipelineBackendSwap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        cls.server.scenario = "ok"
        cls.server.last_request = None
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_mock_backend_end_to_end(self):
        # Same pipeline, different backend: the answer still comes
        # from the reasoner, the model output stays advisory.
        env = answer_text(MONEY_Q, model=get_model("mock"))
        self.assertEqual(env["answer"], 10)
        self.assertEqual(env["model_output"]["status"],
                         "unverified_model_output")
        self.assertEqual(env["model_output"]["model_id"], "mock")

    def test_stub_backend_end_to_end(self):
        adapter = OpenAICompatibleAdapter(ModelConfig(
            model_id="stub-model",
            endpoint=f"http://127.0.0.1:{self.port}",
            api_key_env="NOVA_PHASE4_TEST_KEY"))
        env = answer_text(MONEY_Q, model=adapter)
        self.assertEqual(env["answer"], 10)
        self.assertEqual(env["model_output"]["text"], "stub answer")
        self.assertEqual(env["model_output"]["model_id"], "stub-model")


class TestConceptModelSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from nova.api import Handler
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _req(self, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=10)
        conn.request("POST", "/concept", json.dumps(body),
                     {"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read() or b"{}")
        conn.close()
        return resp.status, data

    def test_concept_with_mock_model(self):
        status, data = self._req({"text": MONEY_Q, "model": "mock"})
        self.assertEqual(status, 200)
        self.assertEqual(data["answer"], 10)
        self.assertEqual(data["model"], "mock")
        self.assertEqual(data["model_output"]["model_id"], "mock")

    def test_concept_unknown_model_is_400(self):
        status, data = self._req({"text": MONEY_Q, "model": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("unknown model", data["error"])
        self.assertIn("mock", data["available_models"])
        self.assertIn("muse-spark", data["available_models"])

    def test_concept_no_model_is_deterministic(self):
        status, data = self._req({"text": MONEY_Q})
        self.assertEqual(status, 200)
        self.assertEqual(data["answer"], 10)
        self.assertIsNone(data["model"])
        self.assertNotIn("model_output", data)

    def test_concept_unbuildable_model_is_400(self):
        # openai-compatible is registered but has no endpoint
        # configured in this environment: a 400, not a silent
        # fallback to the deterministic path.
        for key in ("NOVA_MODEL_ENDPOINT", "NOVA_MODEL_ID"):
            os.environ.pop(key, None)
        status, data = self._req({"text": MONEY_Q,
                                  "model": "openai-compatible"})
        self.assertEqual(status, 400)
        self.assertIn("cannot build model", data["error"])


if __name__ == "__main__":
    unittest.main()
