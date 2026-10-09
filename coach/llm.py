"""
Small client for the LLMs, shared by the scripts and the app (standard library only).

    ask_json(model, messages, schema)   → dict        (structured output)
    chat_stream(model, messages)        → yields text  (for the chat, word by word)

model: an Ollama model (« qwen3:14b », local), or a cloud model with its provider in front:
« anthropic:claude-haiku-4-5-20251001 », « openai:gpt-5.4-mini ». Cloud models need an API key
(API_KEYS, set by the app from data/settings.json, or ANTHROPIC_API_KEY / OPENAI_API_KEY).
"""

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA_URL = "http://localhost:11434"   # another computer's Ollama: --ollama, the « ollama_url » setting or this env
OLLAMA_URL = (os.environ.get("JAPANESE_COACH_OLLAMA") or OLLAMA_URL).rstrip("/")


def set_ollama_url(url: str) -> None:
    """« 100.64.0.2 », « pc.tailnet.ts.net:11434 » or a full URL → http://host:11434. Empty: keep the current one."""
    global OLLAMA_URL
    url = (url or "").strip().rstrip("/")
    if not url:
        return
    if "://" not in url:
        url = "http://" + url
    if url.count(":") < 2:   # no port
        url += ":11434"
    OLLAMA_URL = url
DEFAULT_MODEL = "qwen3:14b"
CLOUD = {
    "anthropic": {"url": "https://api.anthropic.com/v1/messages", "env": "ANTHROPIC_API_KEY",
                  "default": "claude-haiku-4-5-20251001"},
    "openai": {"url": "https://api.openai.com/v1/chat/completions", "env": "OPENAI_API_KEY",
               "default": "gpt-5.4-mini"},
}
API_KEYS = {}


class OllamaUnavailable(Exception):
    pass


class CloudError(Exception):
    pass


def provider(model: str) -> str:
    prefix = (model or "").split(":", 1)[0]
    return prefix if prefix in CLOUD else "ollama"


def api_key(name: str) -> str:
    return API_KEYS.get(name) or os.environ.get(CLOUD[name]["env"], "") or _saved_key(name)


def _saved_key(name: str) -> str:
    """The key saved in the app (Progress → Teacher), for the command-line scripts run outside the server."""
    try:
        settings = json.loads((Path("data") / "settings.json").read_text(encoding="utf-8"))
        return (settings.get("api_keys") or {}).get(name, "")
    except (OSError, ValueError):
        return ""


def _cloud_request(model: str, messages: list, temperature: float, stream: bool, max_tokens: int = 1500):
    name, model_id = model.split(":", 1)
    key = api_key(name)
    if not key:
        raise CloudError(f"No API key for {name}: add it in Progress → Teacher.")
    if name == "anthropic":
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        body = {"model": model_id, "max_tokens": max_tokens, "temperature": temperature, "messages": turns,
                "stream": stream}
        if system:
            body["system"] = system
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    else:
        body = {"model": model_id, "messages": messages, "stream": stream}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    request = urllib.request.Request(CLOUD[name]["url"], data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        return name, urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        if e.code in (401, 403):
            raise CloudError(f"{name}: API key refused ({e.code}).") from e
        raise CloudError(f"{name}: error {e.code} — {detail}") from e
    except urllib.error.URLError as e:
        raise CloudError(f"{name}: not reachable ({e.reason}).") from e


def _cloud_stream(model: str, messages: list, temperature: float):
    name, response = _cloud_request(model, messages, temperature, stream=True)
    with response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            if name == "anthropic":
                if event.get("type") == "content_block_delta":
                    text = event.get("delta", {}).get("text", "")
                    if text:
                        yield text
                elif event.get("type") == "error":
                    raise CloudError(str(event.get("error")))
            else:
                for choice in event.get("choices", []):
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        yield text


def _cloud_json(model: str, messages: list, schema: dict, temperature: float) -> str:
    messages = [dict(m) for m in messages]
    messages[-1]["content"] += ("\n\nAnswer with a single JSON object only (no other text), following this JSON "
                                "schema:\n" + json.dumps(schema, ensure_ascii=False))
    name, response = _cloud_request(model, messages, temperature, stream=False)
    with response:
        result = json.loads(response.read().decode("utf-8"))
    if name == "anthropic":
        return "".join(b.get("text", "") for b in result.get("content", []))
    return result["choices"][0]["message"]["content"]


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
    if provider(model) != "ollama":
        raw = _cloud_json(model, messages, schema, temperature)
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON in the model's answer")
        return json.loads(raw[start:end + 1])
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
    if provider(model) != "ollama":
        yield from _cloud_stream(model, messages, temperature)
        return
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
