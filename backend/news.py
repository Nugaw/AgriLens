"""Agriculture news: fetch headlines (RSS/Atom or plain HTML list) -> cache in SQLite -> summarize in Nepali on demand.
Only sources listed in news_sources.json are contacted, and only when the user presses the button."""
import asyncio, hashlib, json, sys, time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup
from . import config as C, db, llm, prompts as P

_http = None


def http():
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": "AgriLens/2.0 (local farmer assistant)"})
    return _http


def sources():
    try:
        return [s for s in json.loads(C.NEWS_SOURCES.read_text("utf-8")) if s.get("enabled") and s.get("url")]
    except Exception:
        return []


def clean(html: str) -> str:
    return " ".join(BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True).split())


def parse_feed(content: bytes):
    root = ET.fromstring(content)
    out = []
    for it in list(root.iterfind(".//item")) + list(root.iterfind(".//{*}entry")):
        title = clean(it.findtext("title") or it.findtext("{*}title") or "")
        link = (it.findtext("link") or "").strip()
        if not link:
            for l in it.iterfind("{*}link"):
                if l.get("rel", "alternate") == "alternate" and l.get("href"):
                    link = l.get("href")
                    break
        body = it.findtext("{*}encoded") or it.findtext("description") or it.findtext("{*}summary") or it.findtext("{*}content") or ""
        date = it.findtext("pubDate") or it.findtext("{*}published") or it.findtext("{*}updated") or ""
        if title and link:
            out.append({"title": title, "url": link, "published": date.strip(), "excerpt": clean(body)[:1500]})
    return out


def parse_html_list(html: str, base: str, contains: str):
    soup, seen, out = BeautifulSoup(html, "html.parser"), set(), []
    for a in soup.find_all("a", href=True):
        url, title = urljoin(base, a["href"]), " ".join(a.get_text(" ", strip=True).split())
        if contains in url and len(title) > 15 and url not in seen:
            seen.add(url)
            out.append({"title": title, "url": url, "published": "", "excerpt": ""})
    return out


def same_site(url: str, feed_url: str) -> bool:
    a, b = urlparse(url), urlparse(feed_url)
    root = lambda h: ".".join((h or "").split(".")[-2:])
    return a.scheme in ("http", "https") and root(a.hostname) == root(b.hostname)


async def fetch_source(src):
    r = await http().get(src["url"])
    r.raise_for_status()
    items = parse_html_list(r.text, src["url"], src.get("link_contains", "")) if src.get("type") == "html" else parse_feed(r.content)
    return [i for i in items if same_site(i["url"], src["url"])][:25]


async def refresh():
    """Events: progress | result(new count)."""
    total = 0
    srcs = sources()
    if not srcs:
        yield {"t": "error", "m": "news_sources.json मा कुनै साइट सक्रिय छैन।"}
        return
    for s in srcs:
        yield {"t": "progress", "msg": f"{s['name']} …"}
        try:
            items = await fetch_source(s)
        except Exception as e:
            yield {"t": "progress", "msg": f"⚠ {s['name']}: {type(e).__name__} (इन्टरनेट छ?)"}
            continue
        for i in items:
            aid = hashlib.sha1(i["url"].encode()).hexdigest()[:12]
            if not db.one("SELECT id FROM articles WHERE id=?", (aid,)):
                db.q("INSERT INTO articles VALUES(?,?,?,?,?,?,?,?)", (aid, s["name"], i["title"], i["url"], i["published"], i["excerpt"], None, time.time()))
                total += 1
    yield {"t": "result", "v": {"new": total}}


def listing(lang, limit=60):
    rows = db.q("SELECT id,source,title,url,published,summary FROM articles ORDER BY fetched DESC, rowid DESC LIMIT ?", (limit,))
    for r in rows:
        r["summary"] = (json.loads(r["summary"]) if r["summary"] else {}).get(lang)
    return rows


async def fetch_text(url: str) -> str:
    r = await http().get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "aside", "header", "form"]):
        t.decompose()
    node = soup.find("article") or soup
    return " ".join(p for p in (x.get_text(" ", strip=True) for x in node.find_all("p")) if len(p) > 40)


async def summarize(aid, lang):
    a = db.one("SELECT * FROM articles WHERE id=?", (aid,))
    if not a:
        yield {"t": "error", "m": P.MSG[lang]["nodoc"]}
        return
    cache = json.loads(a["summary"]) if a["summary"] else {}
    if lang in cache:
        yield {"t": "result", "v": cache[lang], "cached": True}
        return
    text = a["excerpt"]
    if len(text) < 600:   # feed gave only a teaser: read the page (not stored)
        try:
            text = await fetch_text(a["url"]) or text
        except Exception:
            pass
    if len(text) < 80:
        text = a["title"]
    msgs = [{"role": "system", "content": P.system(lang)}, {"role": "user", "content": P.NEWS.format(title=a["title"], text=text[:3500])}]
    async for ev in llm.run_json(msgs, None, P.NEWS_SCHEMA, num_predict=450):
        if ev["t"] == "result":
            cache[lang] = ev["v"]
            db.q("UPDATE articles SET summary=? WHERE id=?", (json.dumps(cache, ensure_ascii=False), aid))
        yield ev


if __name__ == "__main__":   # python -m backend.news https://site/feed   -> check a source before adding it
    async def _t(url):
        items = await fetch_source({"url": url, "type": "rss"})
        print(f"{len(items)} items")
        for i in items[:5]:
            print("-", i["title"], "|", i["url"])
    asyncio.run(_t(sys.argv[1]))
