"""Validate the AI-extracted deals and publish docs/deals.json.

Each store folder of the latest week may contain ai.jsonl (one deal per line,
written during the weekly chat). Stores without ai.jsonl fall back to the
rule-based parser so the app never goes empty.

Run:  python3 scripts/merge.py            (latest week)
      python3 scripts/merge.py weeks/2026-11-04
"""
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import rules  # noqa: E402

CATEGORIES = ["Ovocie a zelenina", "Mäso a ryby", "Mliečne a vajcia", "Pečivo", "Trvanlivé potraviny",
              "Sladké a slané", "Nápoje", "Alkohol", "Mrazené", "Drogéria a čistenie", "Ostatné"]


import re

SIZE = re.compile(r"(?<![\d×x] )(?<![\d,.])(\d+(?:[,.]\d+)?)\s?(kg|g|ml|l)\b", re.I)
EXPLICIT = re.compile(r"1\s?(kg|l)\s?=\s?(\d+(?:[,.]\d+)?)", re.I)
WASHES = re.compile(r"(\d+)\s?(?:praní|pracích dávok|PD)\b", re.I)


def unit_price(unit, price):
    """Price per kg / l / wash from the pack size text. Returns (value, basis) or (None, None).

    Only unambiguous cases: an explicit "1 kg = 4,48", "cena za 100 g", or one plain size
    ("500 g", "0,75 l"). Multipacks ("10 × 0,5 l") and ranges ("385–450 g") are skipped,
    because the flyer price is often per piece there.
    """
    u = (unit or "").replace("\u00a0", " ")
    m = EXPLICIT.search(u)
    if m:
        return round(float(m.group(2).replace(",", ".")), 2), m.group(1).lower()
    if re.search(r"cena za 100 ?g", u, re.I):
        return round(price * 10, 2), "kg"
    if re.search(r"cena za 1 ?kg|^1 ?kg\b", u, re.I):
        return round(price, 2), "kg"
    w = WASHES.search(u)
    if w and int(w.group(1)) > 0:
        return round(price / int(w.group(1)), 3), "pranie"
    if re.search(r"[×x]\s?\d|\d\s?[–-]\s?\d+\s?(g|kg|ml|l)\b", u, re.I):
        return None, None
    sizes = SIZE.findall(u)
    if len(sizes) != 1:
        return None, None
    qty, unit_ = float(sizes[0][0].replace(",", ".")), sizes[0][1].lower()
    factor = {"g": 1000, "kg": 1, "ml": 1000, "l": 1}[unit_]
    if qty <= 0:
        return None, None
    basis = "kg" if unit_ in ("g", "kg") else "l"
    return round(price / qty * factor, 2), basis


def _norm(s):
    import unicodedata
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("&", "a").split())


def match_category(value):
    """Tolerate small spelling slips ("Ovocie a zeleniny") instead of dumping them into Ostatné."""
    import difflib
    if value in CATEGORIES:
        return value
    by_norm = {_norm(c): c for c in CATEGORIES}
    hit = difflib.get_close_matches(_norm(value), list(by_norm), n=1, cutoff=0.8)
    return by_norm[hit[0]] if hit else "Ostatné"


def check(row):
    """Return (clean_row, None) or (None, reason)."""
    try:
        name = str(row["name"]).strip()
        price = round(float(row["price"]), 2)
        old = row.get("old_price")
        old = round(float(old), 2) if old not in (None, "") else None
        club = row.get("club_price")
        club = round(float(club), 2) if club not in (None, "") else None
    except (KeyError, TypeError, ValueError) as e:
        return None, f"bad field: {e}"
    if not name or len(name) < 3:
        return None, "missing name"
    if not 0.01 <= price <= 2000:
        return None, f"price out of range: {price}"
    if old is not None and old <= price:
        return None, f"old_price {old} <= price {price}"
    disc = row.get("discount")
    if old:
        calc = round((1 - price / old) * 100)
        disc = calc if disc in (None, "") or abs(int(disc) - calc) > 3 else int(disc)
    cat = match_category(row.get("category"))
    return dict(name=name, brand=row.get("brand") or None, unit=(row.get("unit") or "").strip(),
                price=price, old_price=old, discount=disc, club_price=club, category=cat,
                note=row.get("note") or None, valid_from=row.get("valid_from"), valid_to=row.get("valid_to"),
                page=row.get("page")), None


HISTORY = ROOT / "docs" / "history.json"


def hist_key(d):
    return f"{d['store']}|{_norm(d['name'])}|{_norm(d.get('unit'))}"


def update_history(deals):
    """Remember each flyer's price per product, and attach a short summary of earlier flyers to each deal.

    history.json: {key: [[valid_from, price, unit_price], ...]} with one entry per flyer (by start date).
    """
    hist = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else {}
    for d in deals:
        if not d.get("valid_from"):
            continue
        rows = hist.setdefault(hist_key(d), [])
        rows[:] = [r for r in rows if r[0] != d["valid_from"]] + [[d["valid_from"], d["price"], d.get("unit_price")]]
        rows.sort()
        del rows[:-60]  # about a year
    for d in deals:
        earlier = [r for r in hist.get(hist_key(d), []) if d.get("valid_from") and r[0] < d["valid_from"]]
        if earlier:
            d["hist"] = dict(n=len(earlier), min=min(r[1] for r in earlier), last=earlier[-1][1], since=earlier[0][0])
    HISTORY.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main():
    week = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(p for p in (ROOT / "weeks").iterdir() if p.is_dir())[-1]
    fallback = rules.build(week)
    stores, deals, report = fallback["stores"], [], []
    any_ai, complete = False, True
    for store_dir in sorted(p for p in week.iterdir() if p.is_dir()):
        meta = json.loads((store_dir / "meta.json").read_text(encoding="utf-8"))
        store, ai = meta["store"], store_dir / "ai.jsonl"
        upcoming = store_dir.name.endswith("_next")
        if not ai.exists():
            complete = False
            rows = [d for d in fallback["deals"] if d["_dir"] == store_dir.name]
            deals += rows
            report.append(f"{store_dir.name}: no ai.jsonl, using {len(rows)} rule-based deals")
            continue
        any_ai = True
        ok, bad, seen = 0, [], set()
        for n, line in enumerate(ai.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row, why = check(json.loads(line))
            except json.JSONDecodeError as e:
                row, why = None, f"invalid JSON: {e}"
            if not row:
                bad.append(f"  line {n}: {why}")
                continue
            key = (row["name"].lower(), row["price"])
            if key in seen:
                continue
            seen.add(key)
            row["valid_from"] = row["valid_from"] or meta.get("valid_from")
            row["valid_to"] = row["valid_to"] or meta.get("valid_to")
            deals.append(dict(store=store, upcoming=upcoming, **row))
            ok += 1
        done = sorted({int(p) for p in ([] if not (store_dir / "ai_pages.txt").exists() else
                                        (store_dir / "ai_pages.txt").read_text().split())})
        missing = [p for p in meta["pages_kept"] if p not in done]
        complete = complete and not missing
        report.append(f"{store_dir.name}: {ok} deals, {len(bad)} rejected"
                      + (f", pages NOT processed: {missing}" if missing else ", all pages processed"))
        report += bad[:15]
    for d in deals:
        d.pop("_dir", None)
        d["unit_price"], d["unit_basis"] = unit_price(d.get("unit"), d["price"])
    if any_ai:  # only learn prices from the checked AI list, not the rough fallback
        update_history(deals)
    out = dict(week=week.name, generated=dt.datetime.now().isoformat(timespec="seconds"),
               source="ai" if any_ai else "rules", complete=complete, stores=stores, deals=deals)
    (ROOT / "docs" / "deals.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(report))
    print(f"TOTAL {len(deals)} deals -> docs/deals.json ({'all flyers processed' if complete else 'NOT all flyers processed yet'})")


if __name__ == "__main__":
    main()
