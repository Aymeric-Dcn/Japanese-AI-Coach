"""
Small client for the local LLM (Ollama), shared by the scripts and the app.

    ask_json(model, messages, schema)   → dict        (structured output)
    chat_stream(model, messages)        → yields text  (for the chat, word by word)
"""

import json
import re
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:14b"


class OllamaUnavailable(Exception):
    pass


def _post(path: str, payload: dict, timeout: int):
    request = urllib.request.Request(OLLAMA_URL + path, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError as e:
        raise OllamaUnavailable("Cannot reach Ollama on localhost:11434. Is it running?") from e


def _with_think_fallback(payload: dict, send):
    """Asks without "thinking" (faster with qwen3); retries without the option for models that reject it."""
    try:
        return send(dict(payload, think=False))
    except urllib.error.HTTPError as e:
        if e.code == 400:
            return send(payload)
        raise


def ask_json(model: str, messages: list, schema: dict, temperature: float = 0.2, timeout: int = 300) -> dict:
    payload = {"model": model, "messages": messages, "stream": False, "format": schema,
               "options": {"temperature": temperature}}

    def send(p):
        with _post("/api/chat", p, timeout) as r:
            return json.loads(r.read().decode("utf-8"))["message"]["content"]

    raw = _with_think_fallback(payload, send)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON in the model's answer")
    return json.loads(raw[start:end + 1])


def chat_stream(model: str, messages: list, temperature: float = 0.3, timeout: int = 300):
    """Yields the answer piece by piece."""
    payload = {"model": model, "messages": messages, "stream": True, "options": {"temperature": temperature}}
    response = _with_think_fallback(payload, lambda p: _post("/api/chat", p, timeout))
    with response:
        in_think = False
        for line in response:
            if not line.strip():
                continue
            chunk = json.loads(line.decode("utf-8"))
            text = chunk.get("message", {}).get("content", "")
            # Hide <think>…</think> blocks if the model still emits them.
            if "<think>" in text:
                in_think = True
                text = text.split("<think>")[0]
            if in_think:
                if "</think>" in text:
                    in_think = False
                    text = text.split("</think>", 1)[1]
                else:
                    continue
            if text:
                yield text
            if chunk.get("done"):
                break
