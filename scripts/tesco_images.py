"""Product photos for the app, looked up in the Tesco e-shop.

Run on a home computer (Tesco blocks GitHub's servers):

    git pull
    python scripts/tesco_images.py          # look up deals without a photo
    python scripts/tesco_images.py --push   # ... and commit + push docs/images.json

For every deal in docs/deals.json that has no photo yet, searches
potravinydomov.itesco.sk, picks the best matching product and stores its photo
URL in docs/images.json (key = normalised product name, see `key()`; the app
uses the same rule). Only the URL is stored; the photo itself stays on Tesco's
server. Weak matches are stored as misses so they aren't searched again every
week (they are retried after RETRY_DAYS).

Only uses the Python standard library.
"""
import datetime as dt
import html
import json
import pathlib
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEALS = ROOT / "docs" / "deals.json"
IMAGES = ROOT / "docs" / "images.json"
SEARCH = "https://potravinydomov.itesco.sk/shop/sk-SK/search?query={q}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0 Safari/537.36", "Accept-Language": "sk-SK,sk;q=0.9"}
MAX_LOOKUPS = 400        # per run
PAUSE = 1.5              # seconds between searches, be gentle
MIN_SCORE = 0.5          # below this, no photo (better none than a wrong one)
RETRY_DAYS = 28

STOP = {"a", "s", "so", "z", "zo", "v", "na", "do", "pre", "bez", "alebo", "rozne", "druhy", "vybrane", "ks",
        "g", "kg", "ml", "l", "cl", "x", "tesco", "akcia", "cena", "za", "balenie", "bal", "cca"}
QTY = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|ml|cl|l)\b")


def strip(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def key(name):
    """Same normalisation as imgKey() in docs/index.html."""
    return re.sub(r"[^a-z0-9]+", " ", strip(name)).strip()


def tokens(s):
    return {t for t in re.findall(r"[a-z]+", strip(s)) if len(t) > 1 and t not in STOP}


def grams(s):
    m = QTY.search(strip(s).replace(",", "."))
    if not m:
        return None
    v, u = float(m.group(1)), m.group(2)
    return v * {"kg": 1000, "g": 1, "l": 1000, "ml": 1, "cl": 10}[u]


class Tiles(HTMLParser):
    """Collects (product name, photo URL) pairs from a search result page.

    A tile has a link with the product name and another link (same product URL)
    wrapping the photo, so both are joined by the product URL."""

    def __init__(self):
        super().__init__()
        self.href, self.text, self.names, self.imgs, self.order = None, "", {}, {}, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        href = a.get("href") or ""
        if tag == "a" and "/products/" in href:
            self.href, self.text = href.split("?")[0], ""
            if self.href not in self.order:
                self.order.append(self.href)
        elif tag == "img" and self.href and "digitalcontent.api.tesco.com/v2/media/ghs/" in (a.get("src") or ""):
            self.imgs.setdefault(self.href, a["src"])

    def handle_data(self, data):
        if self.href:
            self.text += data

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            name = " ".join(self.text.split())
            if name:
                self.names.setdefault(self.href, html.unescape(name))
            self.href = None

    @property
    def items(self):
        return [(self.names[h], self.imgs[h]) for h in self.order if h in self.names and h in self.imgs]


class Blocked(Exception):
    pass


def search(query):
    req = urllib.request.Request(SEARCH.format(q=urllib.parse.quote(query)), headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            page = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429, 503):
            raise Blocked(f"HTTP {e.code}")
        raise
    if "Access Denied" in page[:2000]:
        raise Blocked("Access Denied")
    p = Tiles()
    p.feed(page)
    seen, out = set(), []
    for name, img in p.items:
        if name not in seen:
            seen.add(name)
            out.append((name, img))
    return out


def score(deal, cand):
    want = tokens(deal["name"]) | tokens(deal.get("brand") or "")
    have = tokens(cand)
    if not want or not have:
        return 0
    s = len(want & have) / len(want)              # how much of our product the candidate covers
    brand = tokens(deal.get("brand") or "")
    if brand and not brand & have:
        s *= 0.5                                  # other brand: at most an illustration
    g1, g2 = grams(f"{deal['name']} {deal.get('unit') or ''}"), grams(cand)
    if g1 and g2:
        s *= 1.0 if abs(g1 - g2) / max(g1, g2) < 0.2 else 0.85
    return round(s, 2)


def query_for(deal):
    words = [w for w in re.sub(r"\d+(?:[.,]\d+)?\s*(kg|g|ml|cl|l|ks|x)\b", " ", deal["name"], flags=re.I).split()]
    q = " ".join(words[:5])
    brand = deal.get("brand")
    if brand and brand.lower() not in q.lower():
        q = f"{brand} {q}"
    return q


def main():
    deals = json.loads(DEALS.read_text(encoding="utf-8"))["deals"]
    images = json.loads(IMAGES.read_text(encoding="utf-8")) if IMAGES.exists() else {}
    today = dt.date.today()
    todo, seen = [], set()
    for d in deals:
        k = key(d["name"])
        if d.get("image") or not k or k in seen:
            continue
        seen.add(k)
        e = images.get(k)
        if e and (e.get("url") or (today - dt.date.fromisoformat(e["checked"])).days < RETRY_DAYS):
            continue
        todo.append((k, d))
    print(f"{len(todo)} products without a photo, looking up at most {MAX_LOOKUPS}")
    found = missed = 0
    try:
        for i, (k, d) in enumerate(todo[:MAX_LOOKUPS]):
            if i:
                time.sleep(PAUSE)
            cands = search(query_for(d))
            best = max(((score(d, n), n, img) for n, img in cands), default=(0, None, None))
            if best[0] >= MIN_SCORE:
                images[k] = dict(url=best[2], match=best[1], score=best[0], checked=today.isoformat())
                found += 1
                print(f"  OK   {d['name']}  ->  {best[1]} ({best[0]})")
            else:
                images[k] = dict(url=None, checked=today.isoformat())
                missed += 1
                print(f"  --   {d['name']}" + (f"  (best: {best[1]}, {best[0]})" if best[1] else ""))
    except Blocked as e:
        print(f"Tesco blocked the lookup ({e}). Saving what was found so far.")
    except KeyboardInterrupt:
        print("Interrupted. Saving what was found so far.")
    IMAGES.write_text(json.dumps(dict(sorted(images.items())), ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Found {found}, no good match {missed}. docs/images.json has "
          f"{sum(1 for e in images.values() if e.get('url'))} photos.")
    if "--push" in sys.argv and (found or missed):
        subprocess.run(["git", "add", "docs/images.json"], cwd=ROOT, check=True)
        subprocess.run(["git", "commit", "-m", f"Fotky produktov z Tesca ({found} nových)"], cwd=ROOT, check=True)
        subprocess.run(["git", "pull", "--rebase"], cwd=ROOT, check=True)
        subprocess.run(["git", "push"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
