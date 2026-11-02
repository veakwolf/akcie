"""Weekly flyer fetcher.

Finds the current Tesco (hypermarket), Billa and Lidl flyers, downloads the PDFs,
extracts the text of food pages into weeks/<date>/<store>/, and writes a
rule-based fallback docs/deals.json so the app has data even before the
weekly AI pass.

Run:  python3 scripts/fetch.py            (uses today's date)
      python3 scripts/fetch.py --local tesco=a.pdf billa=b.pdf lidl=c.pdf
"""
import datetime as dt
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEEKS = ROOT / "weeks"
KEEP_WEEKS = 3
UA = {"User-Agent": "Mozilla/5.0 (akcie weekly flyer reader; personal use)"}

FOOD = re.compile(r"(\b\d+(?:[,.]\d+)? ?(?:g|kg|ml|l)\b|cena za|chladen|mrazen|pultov|voľn|čerstv|mäso|syr|"
                  r"jogurt|pivo|víno|káva|čokolád|ovoc|zelenin|pečivo|nápoj|prac[íi]|praní|aviváž|toaletn|"
                  r"papierov|čistiac|umývačk|šampón|sprchov|zubn|plienk|vrecia na odpad)", re.I)


def get(url, binary=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def iso(d):
    return d.isoformat() if d else None


# ---------------------------------------------------------------- discovery

def find_tesco(today, upcoming=False):
    html = get("https://www.tesco.sk/akciove-ponuky/letaky-a-katalogy")
    slugs = sorted(set(re.findall(r"hypermarkety/tesco-letak-(\d{4}-\d{2}-\d{2})", html)))
    if upcoming:
        future = [s for s in slugs if dt.date.fromisoformat(s) > today]
        if not future:
            return None
        slug = future[0]
    else:
        started = [s for s in slugs if dt.date.fromisoformat(s) <= today] or slugs
        slug = started[-1]
    page = get(f"https://www.tesco.sk/akciove-ponuky/letaky-a-katalogy/hypermarkety/tesco-letak-{slug}/1")
    pdf = re.search(r'"leafletUrl":"([^"]+\.pdf)"', page).group(1)
    vf = re.search(r'"validFrom":"(\d{4}-\d{2}-\d{2})', page)
    vt = re.search(r'"validTo":"(\d{4}-\d{2}-\d{2})', page)
    return dict(pdf=pdf, valid_from=vf and vf.group(1), valid_to=vt and vt.group(1),
                web=f"https://www.tesco.sk/akciove-ponuky/letaky-a-katalogy/hypermarkety/tesco-letak-{slug}/1")


def find_billa(today, upcoming=False):
    html = get("https://www.billa.sk/letaky-a-akcie/letaky").replace("\\u002F", "/")
    found = []
    for m in re.finditer(r"view\.publitas\.com/\d+/\d+/pdfs/[0-9a-f\-]+\.pdf", html):
        before = html[max(0, m.start() - 800):m.start()]
        d = re.findall(r"od (\d{1,2})\. ?(\d{1,2})\. do (\d{1,2})\. ?(\d{1,2})\. (\d{4})", before)
        if not d:
            continue
        d1, m1, d2, m2, y = map(int, d[-1])
        start = dt.date(y if m1 <= m2 else y - 1, m1, d1)
        found.append((start, dt.date(y, m2, d2), "https://" + m.group(0)))
    found = sorted(set(found))
    if upcoming:
        future = [f for f in found if f[0] > today]
        if not future:
            return None
        start, end, pdf = future[0]
    else:
        current = [f for f in found if f[0] <= today <= f[1]] or [f for f in found if f[0] > today] or found
        start, end, pdf = current[0]
    return dict(pdf=pdf, valid_from=iso(start), valid_to=iso(end), web="https://www.billa.sk/letaky-a-akcie/letaky")


def find_lidl(today, upcoming=False):
    if upcoming:
        return None  # Lidl publishes only the current flyer
    html = get("https://www.lidl.sk/c/online-letak/s10008489")
    ids = set(re.findall(r"/l/sk/letak/(online-letak-platny-od-(\d{2})-(\d{2})-(\d{4}))", html))
    dated = sorted((dt.date(int(y), int(m), int(d)), slug) for slug, d, m, y in ids)
    started = [x for x in dated if x[0] <= today] or dated
    _, slug = started[-1]
    api = json.loads(get(f"https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier={slug}&region_id=0&region_code=0"))
    f = api["flyer"]
    return dict(pdf=f["pdfUrl"], valid_from=f.get("offerStartDate") or f.get("startDate"),
                valid_to=f.get("offerEndDate") or f.get("endDate"),
                web=f"https://www.lidl.sk/l/sk/letak/{slug}/ar/0")


FINDERS = {"tesco": find_tesco, "billa": find_billa, "lidl": find_lidl}
# (folder, store, upcoming): current flyers plus next week's Tesco and Billa when already published.
TARGETS = [("tesco", "tesco", False), ("billa", "billa", False), ("lidl", "lidl", False),
           ("tesco_next", "tesco", True), ("billa_next", "billa", True)]
IMAGE_STORES = {"lidl"}
NAMES = {"tesco": "Tesco", "billa": "Billa", "lidl": "Lidl"}


# ---------------------------------------------------------------- extraction

def page_count(pdf):
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    return int(re.search(r"Pages:\s+(\d+)", out).group(1))


def page_text(pdf, p):
    return subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), "-raw", str(pdf), "-"],
                          capture_output=True, text=True).stdout


def reuse(folder, pdf_url, week_dir):
    """If an earlier week already has this exact flyer (e.g. Monday's *_next that started on
    Wednesday), copy that folder, including its AI results, instead of processing it again."""
    for old in sorted((p for p in WEEKS.iterdir() if p.is_dir() and p != week_dir), reverse=True):
        for cand in old.iterdir():
            meta = cand / "meta.json"
            if cand.is_dir() and meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get("pdf") == pdf_url:
                out = week_dir / folder
                if out.exists():
                    shutil.rmtree(out)
                shutil.copytree(cand, out, ignore=shutil.ignore_patterns("img"))
                return json.loads(meta.read_text(encoding="utf-8")), cand
    return None, None


def extract(store, pdf, info, week_dir, folder=None):
    out = week_dir / (folder or store)
    if out.exists():
        shutil.rmtree(out)
    (out / "pages").mkdir(parents=True)
    kept = []
    for p in range(1, page_count(pdf) + 1):
        t = page_text(pdf, p)
        if len(FOOD.findall(t)) >= 3:
            (out / "pages" / f"p{p:03d}.txt").write_text(t, encoding="utf-8")
            kept.append(p)
    if store in IMAGE_STORES:  # layout where text order doesn't match the price boxes
        (out / "img").mkdir()
        for p in kept:
            subprocess.run(["pdftoppm", "-f", str(p), "-l", str(p), "-r", "60", "-jpeg", "-jpegopt", "quality=70",
                            "-singlefile", str(pdf), str(out / "img" / f"p{p:03d}")], capture_output=True)
    meta = dict(store=NAMES[store], **info, pages_total=page_count(pdf), pages_kept=kept,
                images=store in IMAGE_STORES)
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def main():
    today = dt.date.today()
    local = {}
    if "--local" in sys.argv:
        for a in sys.argv[sys.argv.index("--local") + 1:]:
            k, v = a.split("=", 1)
            local[k] = pathlib.Path(v)

    week_dir = WEEKS / today.isoformat()
    week_dir.mkdir(parents=True, exist_ok=True)
    metas, errors = {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        for folder, store, upcoming in TARGETS:
            try:
                if store in local:
                    if upcoming:
                        continue
                    info, pdf = dict(pdf=str(local[store]), valid_from=None, valid_to=None, web=None), local[store]
                else:
                    info = FINDERS[store](today, upcoming=upcoming)
                    if info is None:
                        print(f"{folder}: not published yet")
                        continue
                    meta, src = reuse(folder, info["pdf"], week_dir)
                    if meta:
                        metas[folder] = meta
                        print(f"{folder}: same flyer as {src.parent.name}/{src.name}, reused (incl. AI results)")
                        continue
                    pdf = pathlib.Path(tmp) / f"{folder}.pdf"
                    pdf.write_bytes(get(info["pdf"], binary=True))
                metas[folder] = extract(store, pdf, info, week_dir, folder)
                print(f"{folder}: {len(metas[folder]['pages_kept'])}/{metas[folder]['pages_total']} pages, "
                      f"valid {info['valid_from']} – {info['valid_to']}")
            except Exception as e:  # one broken store must not stop the others
                errors[folder] = f"{type(e).__name__}: {e}"
                print(f"{folder}: FAILED {errors[folder]}", file=sys.stderr)
    (week_dir / "status.json").write_text(json.dumps(dict(fetched=today.isoformat(), errors=errors),
                                                      ensure_ascii=False, indent=1), encoding="utf-8")

    # Publish what we have: reused AI results where available, rule-based fallback elsewhere.
    deals_path = ROOT / "docs" / "deals.json"
    current = json.loads(deals_path.read_text(encoding="utf-8")) if deals_path.exists() else {}
    if current.get("week") == today.isoformat() and current.get("source") == "ai":
        print("AI deals for this week already exist; not rebuilt.")
    else:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "merge.py"), str(week_dir)], check=False)

    for old in sorted(p for p in WEEKS.iterdir() if p.is_dir())[:-KEEP_WEEKS]:
        shutil.rmtree(old)
    if errors and not metas:
        sys.exit(1)


if __name__ == "__main__":
    main()
