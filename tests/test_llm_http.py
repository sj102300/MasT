"""Exercise both LLM adapters against a local fake HTTP server (no network)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from mast.config import LLMConfig
from mast.llm import LLMError, Message, create_client


class _Handler(BaseHTTPRequestHandler):
    requests: list = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        path = self.path.split("?")[0]
        headers = {k.lower(): v for k, v in self.headers.items()}
        _Handler.requests.append((path, headers, body))
        if path.endswith("/chat/completions"):
            payload = {
                "id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "OK"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            }
            self._json(200, payload)
        elif path.endswith("/v1/messages"):
            if body.get("model") == "refuse":
                self._sse([("message_start", {"type": "message_start", "message": _msg(body, [], None)}),
                           ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "refusal"},
                                              "usage": {"output_tokens": 0}}),
                           ("message_stop", {"type": "message_stop"})])
                return
            self._sse([
                ("message_start", {"type": "message_start", "message": _msg(body, [], None)}),
                ("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": "OK"}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                                   "usage": {"output_tokens": 1}}),
                ("message_stop", {"type": "message_stop"}),
            ])
        else:
            self._json(404, {"error": "not found"})

    def _json(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self, events):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for name, data in events:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())


def _msg(body, content, stop):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
            "content": content, "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 5, "output_tokens": 0}}


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_openai_compat_roundtrip(server, monkeypatch):
    monkeypatch.setenv("CORP_KEY", "k")
    cfg = LLMConfig(provider="openai_compat", model="corp", api_key_env="CORP_KEY",
                    base_url=server + "/v1", max_retries=0)
    resp = create_client(cfg).chat("sys", [Message("user", "hi")])
    assert resp.text == "OK" and resp.output_tokens == 1
    path, headers, body = _Handler.requests[-1]
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert headers["authorization"] == "Bearer k"


def test_anthropic_roundtrip(server, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    cfg = LLMConfig(base_url=server, max_retries=0)
    resp = create_client(cfg).chat("sys", [Message("user", "hi")])
    assert resp.text == "OK"
    path, headers, body = _Handler.requests[-1]
    assert body["system"] == "sys"
    assert body["thinking"] == {"type": "adaptive"}
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in headers.get("anthropic-beta", "")


def test_anthropic_without_fallbacks(server, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    cfg = LLMConfig(base_url=server, max_retries=0, fallbacks=None, effort=None)
    create_client(cfg).chat("sys", [Message("user", "hi")])
    _, headers, body = _Handler.requests[-1]
    assert "fallbacks" not in body and "output_config" not in body
    assert "anthropic-beta" not in headers


def test_anthropic_refusal(server, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    cfg = LLMConfig(base_url=server, max_retries=0, model="refuse")
    with pytest.raises(LLMError, match="refusal"):
        create_client(cfg).chat("sys", [Message("user", "hi")])
