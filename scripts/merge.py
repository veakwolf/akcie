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
    cat = row.get("category") if row.get("category") in CATEGORIES else "Ostatné"
    return dict(name=name, brand=row.get("brand") or None, unit=(row.get("unit") or "").strip(),
                price=price, old_price=old, discount=disc, club_price=club, category=cat,
                note=row.get("note") or None, valid_from=row.get("valid_from"), valid_to=row.get("valid_to"),
                page=row.get("page")), None


def main():
    week = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(p for p in (ROOT / "weeks").iterdir() if p.is_dir())[-1]
    fallback = rules.build(week)
    stores, deals, report = fallback["stores"], [], []
    any_ai = False
    for store_dir in sorted(p for p in week.iterdir() if p.is_dir()):
        meta = json.loads((store_dir / "meta.json").read_text(encoding="utf-8"))
        store, ai = meta["store"], store_dir / "ai.jsonl"
        if not ai.exists():
            rows = [d for d in fallback["deals"] if d["store"] == store]
            deals += rows
            report.append(f"{store}: no ai.jsonl, using {len(rows)} rule-based deals")
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
            deals.append(dict(store=store, **row))
            ok += 1
        done = sorted({int(p) for p in ([] if not (store_dir / "ai_pages.txt").exists() else
                                        (store_dir / "ai_pages.txt").read_text().split())})
        missing = [p for p in meta["pages_kept"] if p not in done]
        report.append(f"{store}: {ok} deals, {len(bad)} rejected"
                      + (f", pages NOT processed: {missing}" if missing else ", all pages processed"))
        report += bad[:15]
    out = dict(week=week.name, generated=dt.datetime.now().isoformat(timespec="seconds"),
               source="ai" if any_ai else "rules", stores=stores, deals=deals)
    (ROOT / "docs" / "deals.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(report))
    print(f"TOTAL {len(deals)} deals -> docs/deals.json")


if __name__ == "__main__":
    main()
