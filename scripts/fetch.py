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


def find_kaufland(today, upcoming=False):
    """Kaufland's shop site lists flyer IDs (same Schwarz flyer system as Lidl); the weekly one is *_KDZ_*.
    The default store on the page is Poprad; the weekly KDZ flyer is the same nationwide."""
    html = get("https://predajne.kaufland.sk/aktualna-ponuka/letak.html")
    ids = sorted(set(re.findall(r"SK_sk_KDZ_\d+_[A-Za-z0-9\-]+", html)))
    flyers = []
    for fid in ids:
        region = fid.split("_")[3]
        f = json.loads(get(f"https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier={fid}"
                           f"&region_id={region}&region_code={region}"))["flyer"]
        start = dt.date.fromisoformat(f.get("offerStartDate") or f["startDate"])
        end = dt.date.fromisoformat(f.get("offerEndDate") or f["endDate"])
        flyers.append((start, end, f["pdfUrl"], fid, region))
    flyers.sort()
    if upcoming:
        pick = [x for x in flyers if x[0] > today]
    else:
        pick = [x for x in flyers if x[0] <= today <= x[1]] or [x for x in flyers if x[0] <= today]
        pick = pick[-1:] if pick else []
    if not pick:
        return None
    start, end, pdf, fid, region = pick[0]
    return dict(pdf=pdf, valid_from=iso(start), valid_to=iso(end),
                web=f"https://leaflets.kaufland.com/sk-SK/{fid}/ar/{region}")


FINDERS = {"tesco": find_tesco, "billa": find_billa, "lidl": find_lidl, "kaufland": find_kaufland}
# (folder, store, upcoming): current flyers plus next week's Tesco and Billa when already published.
TARGETS = [("tesco", "tesco", False), ("billa", "billa", False), ("lidl", "lidl", False),
           ("tesco_next", "tesco", True), ("billa_next", "billa", True)]
IMAGE_STORES = {"lidl"}
NAMES = {"tesco": "Tesco", "billa": "Billa", "lidl": "Lidl", "kaufland": "Kaufland", "biedronka": "Biedronka"}

# ---------------------------------------------------------------- Biedronka
# Its flyers are only page images in a Flexpaper viewer (the text layer is empty), so we save the
# page images and the AI step reads the deals straight from them.
BIEDRONKA = "https://www.biedronka.sk"


def find_biedronka(today):
    """{folder: (press_url, start, end)} for the current and next weekly flyer and the current "fresh" flyer."""
    html = get(BIEDRONKA + "/sk/letaky")
    found = set()
    for pid, slug, fresh, d1, m1, d2, m2, y in re.findall(
            r"press,id,([a-z0-9]+),title,(w\d+-\d{4}-(fresh-)?letak-(\d{1,2})-(\d{1,2})-(\d{1,2})-(\d{1,2})-(\d{4}))", html):
        start = dt.date(int(y) if int(m1) <= int(m2) else int(y) - 1, int(m1), int(d1))
        found.add((bool(fresh), start, dt.date(int(y), int(m2), int(d2)), f"{BIEDRONKA}/sk/press,id,{pid},title,{slug}"))
    weekly = sorted(f for f in found if not f[0])
    fresh = sorted(f for f in found if f[0] and f[2] >= today)
    out = {}
    cur = [f for f in weekly if f[1] <= today <= f[2]]
    if cur:
        out["biedronka"] = cur[-1]
    nxt = [f for f in weekly if f[1] > today]
    if nxt:
        out["biedronka_next"] = nxt[0]
    if fresh:
        out["biedronka_fresh"] = fresh[0]
    return {k: (v[3], v[1], v[2]) for k, v in out.items()}


def biedronka_images(press_url, img_dir):
    """Download all page images of one flyer; returns the page count."""
    page = get(press_url).replace("&amp;", "&")
    doc = re.search(r"doc=([^&\"']+\.pdf)", page).group(1)
    sub = re.search(r"subfolder=([^&\"']+)", page).group(1)
    base = f"{BIEDRONKA}/flexpaper/view?subfolder={sub}&doc={doc}"
    pages = json.loads(get(base + "&format=json&page=1"))[0]["pages"]
    img_dir.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
    except ImportError:
        Image = None
    import io
    for p in range(1, pages + 1):
        data = get(f"{base}&format=jpg&page={p}", binary=True)
        target = img_dir / f"p{p:03d}.jpg"
        if Image:  # ~1000 px wide; re-save smaller so the weekly image branch stays light
            Image.open(io.BytesIO(data)).convert("RGB").save(target, "JPEG", quality=72, optimize=True)
        else:
            target.write_bytes(data)
    return pages


def fetch_biedronka(today, week_dir, metas, errors):
    try:
        flyers = find_biedronka(today)
    except Exception as e:
        errors["biedronka"] = f"{type(e).__name__}: {e}"
        print(f"biedronka: FAILED {errors['biedronka']}", file=sys.stderr)
        return
    for folder in ("biedronka", "biedronka_next", "biedronka_fresh"):
        if folder not in flyers:
            print(f"{folder}: not published")
            continue
        url, start, end = flyers[folder]
        try:
            here = week_dir / folder / "meta.json"
            meta = json.loads(here.read_text(encoding="utf-8")) if here.exists() else None
            if not (meta and meta.get("pdf") == url):
                meta, _ = reuse(folder, url, week_dir)  # same flyer seen earlier: keep its AI results
            out = week_dir / folder
            if not meta:
                if out.exists():
                    shutil.rmtree(out)
                out.mkdir(parents=True)
            pages = biedronka_images(url, out / "img")  # images are not in git, so always (re)download them
            if not meta:
                meta = dict(store="Biedronka", pdf=url, valid_from=iso(start), valid_to=iso(end), web=url,
                            pages_total=pages, pages_kept=list(range(1, pages + 1)), images=True, image_only=True)
                (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            metas[folder] = meta
            print(f"{folder}: {pages} page images, valid {iso(start)} – {iso(end)}")
        except Exception as e:
            errors[folder] = f"{type(e).__name__}: {e}"
            print(f"{folder}: FAILED {errors[folder]}", file=sys.stderr)


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
                shutil.copytree(cand, out)
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
                    here = week_dir / folder / "meta.json"
                    if here.exists() and json.loads(here.read_text(encoding="utf-8")).get("pdf") == info["pdf"]:
                        metas[folder] = json.loads(here.read_text(encoding="utf-8"))
                        print(f"{folder}: already downloaded today, kept (incl. AI results)")
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
    # Kaufland: read the offers straight from its website (structured, no AI step needed).
    for folder, week in (("kaufland", "current"), ("kaufland_next", "next")):
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            import kaufland_web, rules
            deals, vf, vt = kaufland_web.parse(get(kaufland_web.URL.format(week=week)), today,
                                               rules.categorize, rules.DURABLE)
            if folder == "kaufland_next" and (not vf or vf <= today.isoformat() or vf == metas.get("kaufland", {}).get("valid_from")):
                print("kaufland_next: not published yet")
                continue
            out = week_dir / folder
            if out.exists():
                shutil.rmtree(out)
            out.mkdir(parents=True)
            (out / "ai.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in deals), encoding="utf-8")
            (out / "ai_pages.txt").write_text("", encoding="utf-8")
            metas[folder] = dict(store="Kaufland", pdf=None, valid_from=vf, valid_to=vt, web=kaufland_web.URL.format(week=week),
                                 pages_total=0, pages_kept=[], images=False, source="web")
            (out / "meta.json").write_text(json.dumps(metas[folder], ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{folder}: {len(deals)} deals from the website, valid {vf} – {vt}")
        except Exception as e:
            errors[folder] = f"{type(e).__name__}: {e}"
            print(f"{folder}: FAILED {errors[folder]}", file=sys.stderr)

    fetch_biedronka(today, week_dir, metas, errors)

    (week_dir / "status.json").write_text(json.dumps(dict(fetched=today.isoformat(), errors=errors),
                                                      ensure_ascii=False, indent=1), encoding="utf-8")

    # Publish what we have: reused AI results where available, rule-based fallback elsewhere.
    # merge.py keeps every processed (AI) result and marks the week incomplete if any flyer still needs processing.
    subprocess.run([sys.executable, str(ROOT / "scripts" / "merge.py"), str(week_dir)], check=False)

    for old in sorted(p for p in WEEKS.iterdir() if p.is_dir())[:-KEEP_WEEKS]:
        shutil.rmtree(old)
    if errors and not metas:
        sys.exit(1)


if __name__ == "__main__":
    main()
