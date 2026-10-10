"""SQLite persistence: chats, documents, scan records, news. Everything survives a restart."""
import json, sqlite3, threading, time, uuid
from . import config as C

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats(id TEXT PRIMARY KEY, title TEXT, kind TEXT DEFAULT 'chat', ref TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, role TEXT, content TEXT, image TEXT, meta TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS ix_msg ON messages(chat_id, id);
CREATE TABLE IF NOT EXISTS docs(id TEXT PRIMARY KEY, name TEXT, pages INTEGER, chars INTEGER, summary TEXT, created REAL);
CREATE TABLE IF NOT EXISTS chunks(doc_id TEXT, idx INTEGER, page INTEGER, text TEXT);
CREATE INDEX IF NOT EXISTS ix_chunk ON chunks(doc_id, idx);
CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, kind TEXT, title TEXT, data TEXT, images TEXT, created REAL);
CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY, source TEXT, title TEXT, url TEXT, published TEXT, excerpt TEXT, summary TEXT, fetched REAL);
"""

_db = sqlite3.connect(C.DATA / "agrilens.db", check_same_thread=False, isolation_level=None)
_db.row_factory = sqlite3.Row
_db.executescript("PRAGMA journal_mode=WAL;" + SCHEMA)
_lock = threading.Lock()


def q(sql, args=()):
    with _lock:
        return [dict(r) for r in _db.execute(sql, args).fetchall()]


def one(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def many(sql, rows):
    with _lock:
        _db.execute("BEGIN")
        _db.executemany(sql, rows)
        _db.execute("COMMIT")


def _id():
    return uuid.uuid4().hex[:10]


# ---- chats -----------------------------------------------------------------
def new_chat(title, kind="chat", ref=None):
    cid, now = _id(), time.time()
    q("INSERT INTO chats VALUES(?,?,?,?,?,?)", (cid, title[:60] or "—", kind, ref, now, now))
    return cid


def get_chat(cid):
    return one("SELECT * FROM chats WHERE id=?", (cid,)) if cid else None


def doc_chat(doc_id):
    r = one("SELECT id FROM chats WHERE kind='doc' AND ref=?", (doc_id,))
    return r["id"] if r else new_chat("doc", "doc", doc_id)


def add_msg(cid, role, content, image=None, meta=None):
    q("INSERT INTO messages(chat_id,role,content,image,meta,ts) VALUES(?,?,?,?,?,?)",
      (cid, role, content, image, json.dumps(meta) if meta else None, time.time()))
    q("UPDATE chats SET updated=? WHERE id=?", (time.time(), cid))


def messages(cid, limit=None):
    rows = q("SELECT role,content,image,meta,ts FROM messages WHERE chat_id=? ORDER BY id DESC" + (f" LIMIT {int(limit)}" if limit else ""), (cid,))
    rows.reverse()
    for r in rows:
        r["meta"] = json.loads(r["meta"]) if r["meta"] else None
    return rows


def list_chats(limit=50):
    return q("SELECT id,title,updated FROM chats WHERE kind='chat' ORDER BY updated DESC LIMIT ?", (limit,))


def del_chat(cid):
    q("DELETE FROM messages WHERE chat_id=?", (cid,))
    q("DELETE FROM chats WHERE id=?", (cid,))


# ---- scan records ----------------------------------------------------------
def add_record(kind, title, data, images):
    rid = _id()
    q("INSERT INTO records VALUES(?,?,?,?,?,?)", (rid, kind, (title or kind)[:80], json.dumps(data, ensure_ascii=False), json.dumps(images), time.time()))
    return rid


def get_record(rid):
    r = one("SELECT * FROM records WHERE id=?", (rid,)) if rid else None
    if r:
        r["data"], r["images"] = json.loads(r["data"]), json.loads(r["images"])
    return r


def set_record_data(rid, data):
    """Update a saved record's JSON (used to cache the 'learn more' info on a label)."""
    q("UPDATE records SET data=? WHERE id=?", (json.dumps(data, ensure_ascii=False), rid))


def list_records(kind, limit=30):
    rows = q("SELECT id,kind,title,images,created FROM records WHERE kind=? ORDER BY created DESC LIMIT ?", (kind, limit))
    for r in rows:
        r["images"] = json.loads(r["images"])
    return rows


def del_record(rid):
    q("DELETE FROM records WHERE id=?", (rid,))


# ---- docs ------------------------------------------------------------------
def add_doc(name, pages, chunks):
    did = _id()
    chars = sum(len(c[1]) for c in chunks)
    q("INSERT INTO docs VALUES(?,?,?,?,?,?)", (did, name[:120], pages, chars, None, time.time()))
    many("INSERT INTO chunks VALUES(?,?,?,?)", [(did, i, p, t) for i, (p, t) in enumerate(chunks)])
    return get_doc(did)


def get_doc(did):
    return one("SELECT * FROM docs WHERE id=?", (did,))


def list_docs():
    return q("SELECT id,name,pages,chars,summary,created FROM docs ORDER BY created DESC")


def chunks(did):
    return q("SELECT idx,page,text FROM chunks WHERE doc_id=? ORDER BY idx", (did,))


def del_doc(did):
    c = one("SELECT id FROM chats WHERE kind='doc' AND ref=?", (did,))
    if c:
        del_chat(c["id"])
    q("DELETE FROM chunks WHERE doc_id=?", (did,))
    q("DELETE FROM docs WHERE id=?", (did,))


def set_summary(did, text):
    q("UPDATE docs SET summary=? WHERE id=?", (text, did))
