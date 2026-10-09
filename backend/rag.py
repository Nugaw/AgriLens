"""Document reading: PDF / photo / text -> pages -> chunks -> BM25 search.
Devanagari-aware: the old `\\w+` tokenizer split Nepali words at every vowel sign (matra)."""
import asyncio, math, re
from collections import Counter
from . import config as C, db, images as I, llm, prompts as P

TOK = re.compile(r"[\w\u0900-\u097F]+")
DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
SENT = re.compile(r"(?<=[।.!?])\s+|\n{2,}")
_IDX = {}


def grams(text):
    out = []
    for w in TOK.findall(text.translate(DIGITS).replace("\u200d", "").replace("\u200c", "").lower()):
        out += [w] if len(w) <= 3 else [w[i:i + 3] for i in range(len(w) - 2)]   # 3-grams survive suffixes: धानको/धानमा
    return out


def chunk_page(text, size=900):
    out, cur = [], ""
    for s in SENT.split(text):
        s = s.strip()
        if not s:
            continue
        if cur and len(cur) + len(s) + 1 > size:
            out.append(cur)
            cur = (cur[-150:].split(" ", 1)[-1] + " " + s).strip()
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return [c[i:i + 1800] for c in out for i in range(0, len(c), 1800)]


def search(doc_id, chunks, query, k=4):
    if doc_id not in _IDX:
        tfs = [Counter(grams(c["text"])) for c in chunks]
        df = Counter()
        for tf in tfs:
            df.update(tf.keys())
        _IDX[doc_id] = (tfs, df, sum(sum(t.values()) for t in tfs) / max(1, len(tfs)) or 1)
    tfs, df, avg = _IDX[doc_id]
    N, qg, scored = len(chunks), set(grams(query)), []
    for i, tf in enumerate(tfs):
        dl, s = sum(tf.values()), 0.0
        for g in qg:
            f = tf.get(g, 0)
            if f:
                s += math.log(1 + (N - df[g] + .5) / (df[g] + .5)) * f * 2.2 / (f + 1.2 * (.25 + .75 * dl / avg))
        scored.append((s, i))
    top = sorted(scored, reverse=True)[:k]
    idx = sorted(i for s, i in top if s > 0) or list(range(min(k, N)))
    return [chunks[i] for i in idx]


def forget(doc_id):
    _IDX.pop(doc_id, None)


def _pdf_text(data):
    import io
    from pypdf import PdfReader
    return [(p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages]


async def _ocr(jpg):
    return await llm.complete([{"role": "system", "content": "You are an OCR engine."},
                               {"role": "user", "content": P.OCR}], [jpg], temperature=0)


async def ingest(name, data, force_ocr=False):
    """Async generator. Events: progress | result | error."""
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    pages = []
    if ext in ("txt", "md"):
        pages = [data.decode("utf-8", "ignore")]
    elif ext == "pdf":
        if not force_ocr:
            pages = await asyncio.to_thread(_pdf_text, data)
        if force_ocr or sum(map(len, pages)) < 30 * max(1, len(pages)):   # scanned PDF, or old Preeti-font garbage
            try:
                import pypdfium2 as pdfium
            except ImportError:
                yield {"t": "error", "m": "Scanned PDF: run `pip install pypdfium2` to enable photo-reading."}
                return
            pdf, pages = pdfium.PdfDocument(data), []
            n = min(len(pdf), C.OCR_MAX_PAGES)
            for i in range(n):
                yield {"t": "progress", "msg": f"फोटोबाट पढ्दै… पृष्ठ {i + 1}/{n}"}
                jpg, _ = await asyncio.to_thread(lambda i=i: I.prep(_to_jpeg(pdf[i]), C.LABEL_IMG_MAX, True))
                pages.append(await _ocr(jpg))
    else:
        yield {"t": "progress", "msg": "फोटोबाट पढ्दै…"}
        jpg, _ = await asyncio.to_thread(I.prep, data, C.LABEL_IMG_MAX, True)
        pages = [await _ocr(jpg)]
    chunks = [(pn, t) for pn, txt in enumerate(pages, 1) for t in chunk_page(txt)]
    if not chunks:
        yield {"t": "error", "m": "empty"}
        return
    yield {"t": "result", "v": db.add_doc(name, len(pages), chunks)}


def _to_jpeg(page):
    import io
    buf = io.BytesIO()
    page.render(scale=1.6).to_pil().convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()
