"""Use-cases. Every function is an async generator that yields NDJSON events for the browser."""
import asyncio, hashlib, json
from . import config as C, db, images as I, llm, prompts as P, rag


def save_img(b: bytes) -> str:
    name = hashlib.sha1(b).hexdigest()[:16] + ".jpg"
    p = C.DATA / "img" / name
    if not p.exists():
        p.write_bytes(b)
    return name


def img_path(url_or_name: str):
    return C.DATA / "img" / url_or_name.rsplit("/", 1)[-1]


async def vision(kind, raws, user_prompt, schema, lang, force, max_side, enhance, title_key, blur_limit=40, num_predict=900):
    try:
        prepped = await asyncio.gather(*[asyncio.to_thread(I.prep, r, max_side, enhance) for r in raws])
    except Exception:
        yield {"t": "error", "m": P.MSG[lang]["badimg"]}
        return
    if not force:
        for _, m in prepped:
            bad = I.issues(m, blur_limit)
            if bad:
                yield {"t": "warn", "reasons": [P.QUALITY[lang][b][0] for b in bad], "suggestions": [P.QUALITY[lang][b][1] for b in bad]}
                return
    names = [save_img(j) for j, _ in prepped]
    msgs = [{"role": "system", "content": P.system(lang)}, {"role": "user", "content": user_prompt}]
    async for ev in llm.run_json(msgs, [j for j, _ in prepped], schema, num_predict=num_predict):
        if ev["t"] == "result":
            d = ev["v"]
            rid = db.add_record(kind, d.get(title_key) if isinstance(d.get(title_key), str) else kind, d, names)
            ev = {"t": "result", "v": d, "record_id": rid, "images": ["/img/" + n for n in names]}
        yield ev


def plant(raw, note, lang, force):
    return vision("plant", [raw], P.PLANT.format(note=note), P.PLANT_SCHEMA, lang, force, C.IMG_MAX, False, "crop_detected", blur_limit=20, num_predict=800)


def label(front, back, kind, lang, force):
    raws = [r for r in (front, back) if r]
    prompt = P.LABEL.format(side="front and back" if back else "front", kind=kind, nr=P.NR[lang])
    return vision("label", raws, prompt, P.LABEL_SCHEMA, lang, force, C.LABEL_IMG_MAX, True, "product_name", num_predict=1200)


async def label_learn(record_id, lang):
    """General knowledge about a scanned product: what it is used for and how it is generally applied.
    Offline (model knowledge only), never gives doses. Cached inside the label record."""
    r = db.get_record(record_id)
    if not r or r["kind"] != "label":
        yield {"t": "error", "m": P.MSG[lang]["nodoc"]}
        return
    d = r["data"]
    if d.get("learn"):
        yield {"t": "result", "v": d["learn"], "cached": True}
        return
    g = lambda k: d.get(k) if isinstance(d.get(k), str) else ""
    prompt = P.LEARN.format(name=g("product_name"), ai=g("active_ingredient"), cat=g("category"),
                            targets=", ".join(x for x in (d.get("target_pests_crops") or []) if isinstance(x, str)))
    msgs = [{"role": "system", "content": P.system(lang)}, {"role": "user", "content": prompt}]
    async for ev in llm.run_json(msgs, None, P.LEARN_SCHEMA, num_predict=700):
        if ev["t"] == "result":
            if not ev["v"].get("raw"):   # only cache a valid answer
                d["learn"] = ev["v"]
                db.set_record_data(record_id, d)
        yield ev


async def match(plant_id, label_id, lang):
    p, l = db.get_record(plant_id), db.get_record(label_id)
    if not p or not l:
        yield {"t": "error", "m": P.MSG[lang]["nodoc"]}
        return
    imgs = [img_path(p["images"][0]).read_bytes(), img_path(l["images"][0]).read_bytes()]
    msgs = [{"role": "system", "content": P.system(lang)}, {"role": "user", "content": P.MATCH}]
    async for ev in llm.run_json(msgs, imgs, P.MATCH_SCHEMA, num_predict=600):
        if ev["t"] == "result":
            ev["record_id"] = db.add_record("match", l["title"], ev["v"], [])
        yield ev


async def chat(chat_id, message, raw_img, lang, record_id):
    img = name = None
    if raw_img:
        try:
            img, _ = await asyncio.to_thread(I.prep, raw_img, C.IMG_MAX, False)
        except Exception:
            yield {"t": "error", "m": P.MSG[lang]["badimg"]}
            return
        name = save_img(img)
    message = message.strip() or ("यो फोटोमा के छ?" if lang == "ne" else "What is in this photo?")
    row = db.get_chat(chat_id)
    if not row:
        chat_id = db.new_chat(message, "chat", record_id)
        row = db.get_chat(chat_id)
    yield {"t": "meta", "chat_id": chat_id}
    ctx = ""
    rec = db.get_record(row["ref"]) if row["ref"] else None
    if rec:
        ctx = P.RECORD_CTX.format(kind=rec["kind"], data=json.dumps(rec["data"], ensure_ascii=False)[:3000])
    hist = [{"role": m["role"], "content": m["content"]} for m in db.messages(chat_id, 12)]
    msgs = [{"role": "system", "content": P.system(lang) + ctx}] + hist + [{"role": "user", "content": message}]
    db.add_msg(chat_id, "user", message, name)
    buf = []
    try:
        async for ev in llm.run_text(msgs, [img] if img else None, temperature=0.4, num_predict=700):
            if ev["t"] == "delta":
                buf.append(ev["v"])
            yield ev
    finally:
        if buf:   # a stopped answer is still kept, so the history is complete
            db.add_msg(chat_id, "assistant", "".join(buf))


async def doc_ask(doc_id, question, lang):
    doc = db.get_doc(doc_id)
    if not doc:
        yield {"t": "error", "m": P.MSG[lang]["nodoc"]}
        return
    chunks = db.chunks(doc_id)
    cid = db.doc_chat(doc_id)
    hist = db.messages(cid, 4)
    last_q = next((m["content"] for m in reversed(hist) if m["role"] == "user"), "")
    sel = chunks if doc["chars"] <= 6000 else rag.search(doc_id, chunks, f"{question} {last_q}")  # small doc: send it all
    ctx = "\n---\n".join(f"[पृष्ठ {c['page']}]\n{c['text']}" for c in sel)
    sources = [{"page": c["page"], "snippet": c["text"][:140]} for c in sel]
    yield {"t": "sources", "v": sources}
    prompt = P.DOC.format(nf=P.DOC_NF[lang], ctx=ctx, q=question)
    msgs = [{"role": "system", "content": P.system(lang)}] + [{"role": m["role"], "content": m["content"]} for m in hist] + [{"role": "user", "content": prompt}]
    db.add_msg(cid, "user", question)
    buf = []
    try:
        async for ev in llm.run_text(msgs, temperature=0.1, num_predict=600):
            if ev["t"] == "delta":
                buf.append(ev["v"])
            yield ev
    finally:
        if buf:
            db.add_msg(cid, "assistant", "".join(buf), meta={"sources": sources})


async def doc_summary(doc_id, lang):
    doc = db.get_doc(doc_id)
    if not doc:
        yield {"t": "error", "m": P.MSG[lang]["nodoc"]}
        return
    ctx, size = [], 0
    for c in db.chunks(doc_id):          # spread over the whole document, not just page 1
        if size > 5000:
            break
        ctx.append(f"[पृष्ठ {c['page']}] {c['text'][:700]}")
        size += len(ctx[-1])
    msgs = [{"role": "system", "content": P.system(lang)}, {"role": "user", "content": P.DOC_SUMMARY.format(ctx="\n".join(ctx))}]
    buf = []
    async for ev in llm.run_text(msgs, temperature=0.2, num_predict=500):
        if ev["t"] == "delta":
            buf.append(ev["v"])
        yield ev
    db.set_summary(doc_id, "".join(buf))
