"""Async Ollama client: token streaming, one-job-at-a-time queue, keep-alive, warm-up."""
import asyncio, base64, json, time
import httpx
from . import config as C


class LLMError(Exception):
    pass


_client = None
LOCK = asyncio.Semaphore(1)   # a laptop runs one generation at a time; others wait in line


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=C.OLLAMA, timeout=httpx.Timeout(15.0, read=900.0))
    return _client


async def close():
    if _client:
        await _client.aclose()


async def warmup():
    """Load the model into RAM at start-up so the first farmer request is not slow."""
    try:
        await client().post("/api/generate", json={"model": C.MODEL, "keep_alive": C.KEEP_ALIVE}, timeout=300)
    except Exception:
        pass


async def health() -> dict:
    out = {"ollama": False, "installed": False, "loaded": False, "model": C.MODEL}
    try:
        r = await client().get("/api/tags", timeout=2)
        out["ollama"] = r.status_code == 200
        names = {n for m in r.json().get("models", []) for n in (m.get("name"), m.get("model"))}
        out["installed"] = C.MODEL in names or f"{C.MODEL}:latest" in names
        p = await client().get("/api/ps", timeout=2)
        loaded = {n for m in p.json().get("models", []) for n in (m.get("name"), m.get("model"))}
        out["loaded"] = C.MODEL in loaded or f"{C.MODEL}:latest" in loaded
    except Exception:
        pass
    return out


async def stream(messages, images=None, schema=None, temperature=0.2, num_predict=None):
    """Yield text pieces. `schema` = JSON-schema dict -> Ollama structured output (valid JSON, fewer retries)."""
    msgs = [dict(m) for m in messages]
    if images:
        msgs[-1]["images"] = [base64.b64encode(i).decode() for i in images]
    opts = {"temperature": temperature, "num_ctx": C.NUM_CTX}
    if num_predict:
        opts["num_predict"] = num_predict
    body = {"model": C.MODEL, "messages": msgs, "stream": True, "keep_alive": C.KEEP_ALIVE,
            "options": opts, "think": C.THINK}
    if schema:
        body["format"] = schema
    for attempt in range(2):
        r = await client().send(client().build_request("POST", "/api/chat", json=body), stream=True)
        try:
            if r.status_code >= 400:
                err = (await r.aread()).decode("utf-8", "ignore")
                if attempt == 0 and "think" in body and "think" in err.lower():
                    body.pop("think")          # this Ollama build does not know `think`; retry without it
                    continue
                raise LLMError(err[:300])
            async for line in r.aiter_lines():
                if not line:
                    continue
                d = json.loads(line)
                if d.get("error"):
                    raise LLMError(d["error"])
                c = (d.get("message") or {}).get("content")
                if c:
                    yield c
                if d.get("done"):
                    return
            return
        finally:
            await r.aclose()


def parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        s, e = text.find("{"), text.rfind("}")
        if s >= 0 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except Exception:
                pass
    return {"raw": text}


async def complete(messages, images=None, **kw) -> str:
    async with LOCK:
        return "".join([c async for c in stream(messages, images, **kw)])


async def run_text(messages, images=None, **kw):
    """Events: queued | delta."""
    if LOCK.locked():
        yield {"t": "queued"}
    async with LOCK:
        async for c in stream(messages, images, **kw):
            yield {"t": "delta", "v": c}


async def run_json(messages, images, schema, **kw):
    """Events: queued | progress(n tokens, seconds) | result. Progress lets the UI show it is alive."""
    if LOCK.locked():
        yield {"t": "queued"}
    buf, n, last, t0 = [], 0, 0.0, time.monotonic()
    async with LOCK:
        async for c in stream(messages, images, schema=schema, **kw):
            buf.append(c)
            n += 1
            now = time.monotonic()
            if now - last > 0.6:
                last = now
                yield {"t": "progress", "n": n, "s": round(now - t0, 1)}
    yield {"t": "result", "v": parse_json("".join(buf))}
