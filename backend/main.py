import asyncio, json
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from . import config as C, db, llm, news, rag, services as S, tts
from .prompts import MSG

FRONT = C.ROOT / "frontend"


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(llm.warmup())   # load model in background; server is usable immediately
    yield
    task.cancel()
    await llm.close()


app = FastAPI(title="AgriLens", lifespan=lifespan)


async def rd(f):
    if not f:
        return None
    data = await f.read()
    if len(data) > C.MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    return data


def ndjson(agen, lang="ne"):
    async def gen():
        try:
            async for ev in agen:
                if ev.get("t") == "error" and ev.get("m") in MSG[lang]:
                    ev["m"] = MSG[lang][ev["m"]]
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except (httpx.ConnectError, httpx.ConnectTimeout):
            yield json.dumps({"t": "error", "m": MSG[lang]["down"]}, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"t": "error", "m": f"{type(e).__name__}: {e}"}, ensure_ascii=False) + "\n"
        yield json.dumps({"t": "done"}) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ---- status ----------------------------------------------------------------
@app.get("/api/health")
async def health():
    return {**await llm.health(), "tts": tts.available()}


# ---- plant / label ---------------------------------------------------------
@app.post("/api/plant")
async def plant(image: UploadFile = File(...), note: str = Form(""), lang: str = Form("ne"), force: bool = Form(False)):
    return ndjson(S.plant(await rd(image), note[:300], lang, force), lang)


@app.post("/api/label")
async def label(front: UploadFile = File(...), back: UploadFile = File(None), kind: str = Form("pesticide"),
                lang: str = Form("ne"), force: bool = Form(False)):
    kind = kind if kind in ("pesticide", "fertilizer") else "pesticide"
    return ndjson(S.label(await rd(front), await rd(back), kind, lang, force), lang)


@app.post("/api/match")
async def match(plant_id: str = Form(...), label_id: str = Form(...), lang: str = Form("ne")):
    return ndjson(S.match(plant_id, label_id, lang), lang)


@app.get("/api/records")
def records(kind: str):
    return db.list_records(kind)


@app.get("/api/records/{rid}")
def record(rid: str):
    r = db.get_record(rid)
    if not r:
        raise HTTPException(404)
    return r


@app.delete("/api/records/{rid}")
def del_record(rid: str):
    db.del_record(rid)
    return {"ok": True}


# ---- documents -------------------------------------------------------------
@app.post("/api/docs")
async def upload_doc(file: UploadFile = File(...), ocr: bool = Form(False), lang: str = Form("ne")):
    return ndjson(rag.ingest(file.filename or "file", await rd(file), ocr), lang)


@app.get("/api/docs")
def docs():
    return db.list_docs()


@app.get("/api/docs/{did}/thread")
def doc_thread(did: str):
    return db.messages(db.doc_chat(did))


@app.delete("/api/docs/{did}")
def del_doc(did: str):
    rag.forget(did)
    db.del_doc(did)
    return {"ok": True}


@app.post("/api/docs/{did}/ask")
async def doc_ask(did: str, question: str = Form(...), lang: str = Form("ne")):
    return ndjson(S.doc_ask(did, question[:500], lang), lang)


@app.post("/api/docs/{did}/summary")
async def doc_summary(did: str, lang: str = Form("ne")):
    return ndjson(S.doc_summary(did, lang), lang)


# ---- chat ------------------------------------------------------------------
@app.post("/api/chat")
async def chat(message: str = Form(""), chat_id: str = Form(""), record_id: str = Form(""), lang: str = Form("ne"), image: UploadFile = File(None)):
    return ndjson(S.chat(chat_id, message[:2000], await rd(image), lang, record_id or None), lang)


@app.get("/api/chats")
def chats():
    return db.list_chats()


@app.get("/api/chats/{cid}")
def get_chat(cid: str):
    c = db.get_chat(cid)
    if not c:
        raise HTTPException(404)
    return {**c, "messages": db.messages(cid)}


@app.delete("/api/chats/{cid}")
def del_chat(cid: str):
    db.del_chat(cid)
    return {"ok": True}


# ---- news ------------------------------------------------------------------
@app.get("/api/news")
def news_list(lang: str = "ne"):
    return news.listing(lang)


@app.post("/api/news/refresh")
async def news_refresh(lang: str = Form("ne")):
    return ndjson(news.refresh(), lang)


@app.post("/api/news/{aid}/summary")
async def news_summary(aid: str, lang: str = Form("ne")):
    return ndjson(news.summarize(aid, lang), lang)


# ---- voice -----------------------------------------------------------------
@app.post("/api/tts")
async def speak(text: str = Form(...)):
    if not tts.available():
        raise HTTPException(501, "Piper not installed")
    try:
        return FileResponse(await tts.synth(text), media_type="audio/wav")
    except Exception as e:
        raise HTTPException(500, str(e))


# ---- static ----------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(FRONT / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/img", StaticFiles(directory=C.DATA / "img"), name="img")
app.mount("/static", StaticFiles(directory=FRONT), name="static")
