"""NOVA proof-first reasoning API (stdlib only — no dependencies).

Routes:
  GET  /health  -> {"status": "ok", "service": "nova-proof-api", ...}
  POST /reason  -> {"question": "<money-transfer story + question>"}
                   returns {"answer", "person", "events", "proof"}
                   or 422 {"error": ...} when the story cannot be parsed —
                   an honest failure, never a guessed answer.
  POST /concept -> the universal cognitive-adapter endpoint. Accepts
                   {"text": "..."} (natural language), {"frames": [...]}
                   (structured ConceptFrames from an external language
                   model), or a vendored-adapter {"task": ...} request.
                   An optional {"model": "<name>"} selects the advisor
                   backend by registry name ("meta", "muse-spark",
                   "mock", "openai-compatible"); omitted means the
                   deterministic path with no model. Unknown names get
                   a 400 listing the registered models.
                   Returns the shared envelope: {status, verdict,
                   answer, answer_text, frames, proof, complete,
                   evidence, missing, unusable_frames, model}. This is how other
                   language models use NOVA as an external cognitive
                   adapter: they send words or frames, NOVA sends back
                   frames + a proof. 422 when nothing can be parsed.

Run locally:
  python3 -m nova.api            # listens on :8080
  python3 -m nova.api 9000       # custom port

Deploy (Cloud Run, same pattern as symbolic-reasoner-app):
  gcloud run deploy nova-proof-api --source . --region us-central1 \
      --allow-unauthenticated --memory 512Mi --cpu 1 --max-instances 5
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .concept import parse_story, run_story
from .model_interface import get_model, list_models
from .semantic import process_request

VERSION = "0.4.0"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server naming
        if self.path in ("/", "/health"):
            self._send(200, {"status": "ok", "service": "nova-proof-api",
                             "version": VERSION})
        else:
            self._send(404, {"error": f"unknown route: {self.path}"})

    def do_POST(self):  # noqa: N802 - http.server naming
        if self.path == "/concept":
            self._handle_concept()
            return
        if self.path != "/reason":
            self._send(404, {"error": f"unknown route: {self.path}"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self._send(400, {"error": "request body must be valid JSON"})
            return
        question = data.get("question")
        if not isinstance(question, str) or not question.strip():
            self._send(400, {"error": "missing 'question' string"})
            return
        try:
            events, query = parse_story(question)
        except ValueError as e:
            self._send(422, {"error": "cannot parse question into frames",
                             "detail": str(e),
                             "note": "NOVA answers only what it can prove; "
                                     "unparseable input fails honestly."})
            return
        result = run_story(events, query)
        self._send(200, result)

    def _handle_concept(self) -> None:
        """POST /concept: the shared-frame cognitive-adapter endpoint."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 65536:
                self._send(400, {"error": "request body must be 1-65536 bytes"})
                return
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            self._send(400, {"error": "request body must be valid JSON"})
            return
        if not isinstance(data, dict):
            self._send(400, {"error": "request body must be a JSON object"})
            return
        # Model selection (Req 6): an optional "model" name resolves
        # through the registry. Omitted -> deterministic path, no
        # model. A registered name that cannot be built (e.g.
        # openai-compatible with no endpoint configured) is a 400,
        # not a silent fallback to no model.
        model = None
        model_name = data.get("model")
        if model_name is not None:
            if not isinstance(model_name, str) or not model_name.strip():
                self._send(400, {"error": "'model' must be a model "
                                          "name string"})
                return
            try:
                model = get_model(model_name.strip())
            except ValueError as e:
                if model_name.strip().lower() in list_models():
                    self._send(400, {
                        "error": f"cannot build model "
                                 f"'{model_name}': {e}",
                        "available_models": list_models()})
                else:
                    self._send(400, {
                        "error": f"unknown model '{model_name}'",
                        "available_models": list_models()})
                return
        try:
            result = process_request(data, model=model)
        except ValueError as e:
            self._send(422, {"error": "cannot process request into frames",
                             "detail": str(e),
                             "note": "NOVA answers only what it can prove; "
                                     "unparseable input fails honestly."})
            return
        result["model"] = model.model_id if model is not None else None
        self._send(200, result)

    def log_message(self, *args):  # keep stdout clean
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"nova-proof-api v{VERSION} listening on :{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
