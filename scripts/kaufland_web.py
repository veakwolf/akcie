"""Kaufland weekly offers straight from predajne.kaufland.sk (no flyer, no AI needed).

The offers page is server-rendered: every product is a `.k-product-tile` inside a
`.k-product-section` whose heading names the category and the validity
("Platnosť od 29.10. do 04.11."). Prices sit in `.k-price-tag` blocks: the normal
deal price and, separately, the Kaufland Card XTRA price.
"""
import datetime as dt
import re

from bs4 import BeautifulSoup

URL = "https://predajne.kaufland.sk/aktualna-ponuka/prehlad.html?kloffer-week={week}"

# Section heading -> our category. Sections not listed (electronics, household, clothing) are skipped,
# except the mixed "top / card / half-price" sections, whose items are categorised by name.
SECTION_CATEGORY = {
    "čerstvé ovocie a zelenina": "Ovocie a zelenina",
    "mäso, hydina, údeniny": "Mäso a ryby",
    "čerstvé ryby": "Mäso a ryby",
    "čerstvé výrobky": "Mliečne a vajcia",
    "mrazené výrobky": "Mrazené",
    "lahôdky": None,              # mixed deli: categorise by name
    "trvanlivé potraviny": "Trvanlivé potraviny",
    "pečivo": "Pečivo",
    "káva, čaj, sladké, slané": None,
    "nápoje": None,
    "drogéria, potrava pre zvieratá": "Drogéria a čistenie",
}
SKIP_SECTIONS = ("elektro", "dom, domácnosť", "oblečenie")
MIXED_SECTIONS = ("top produkty", "kaufland card", "polovičné ceny", "ponuka od do")
NON_CONSUMABLE = re.compile(r"(kvet|chryzant|orchid|ruž[ae]|kytic|črepn|sviečk(?!ov)|kahan)", re.I)


def _num(s):
    m = re.search(r"\d+(?:[.,]\d+)?", s or "")
    return round(float(m.group(0).replace(",", ".")), 2) if m else None


def _tag(tag):
    if not tag:
        return None
    return dict(
        price=_num(tag.select_one(".k-price-tag__price") and tag.select_one(".k-price-tag__price").get_text()),
        old=_num(tag.select_one(".k-price-tag__old-price") and tag.select_one(".k-price-tag__old-price").get_text()),
        discount=_num(tag.select_one(".k-price-tag__discount") and tag.select_one(".k-price-tag__discount").get_text()),
    )


def _validity(text, today):
    m = re.search(r"od (\d{1,2})\.(\d{1,2})\. do (\d{1,2})\.(\d{1,2})\.", text or "")
    if m:
        d1, m1, d2, m2 = map(int, m.groups())
        y2 = today.year + (1 if m2 < today.month - 6 else 0)
        y1 = y2 - (1 if m1 > m2 else 0)
        return dt.date(y1, m1, d1).isoformat(), dt.date(y2, m2, d2).isoformat()
    m = re.search(r"platná (\d{1,2})\.(\d{1,2})\.", text or "")
    if m:
        d, mo = map(int, m.groups())
        day = dt.date(today.year, mo, d).isoformat()
        return day, day
    return None, None


def parse(html, today, categorize, durable):
    """Return (deals, valid_from, valid_to). `categorize`/`durable` come from rules.py."""
    soup = BeautifulSoup(html, "html.parser")
    by_name_category, raw = {}, []
    for sec in soup.select(".k-product-section"):
        heads = [h.get_text(" ", strip=True) for h in sec.select("h1, h2, h3, h4")]
        head = " ".join(heads).lower()
        if any(s in head for s in SKIP_SECTIONS):
            continue
        mixed = any(s in head for s in MIXED_SECTIONS)
        section_cat = next((c for k, c in SECTION_CATEGORY.items() if k in head), None)
        vf, vt = _validity(sec.get_text(" ", strip=True)[:400], today)
        for tile in sec.select(".k-product-tile"):
            txt = lambda sel: (tile.select_one(sel).get_text(" ", strip=True) if tile.select_one(sel) else "")
            title, sub, unit = txt(".k-product-tile__title"), txt(".k-product-tile__subtitle"), txt(".k-product-tile__unit-price")
            name = title if not sub or sub == unit or re.fullmatch(r"[\d,.\s×x–-]+\s?(g|kg|ml|l|ks)", sub) else f"{title} {sub}"
            if not name.strip():  # some tiles only name the product in the promo line or the photo's alt text
                promo = re.sub(r"^\s*Cena s Kaufland( Card)? XTRA\s*", "", txt(".k-product-tile__promo"), flags=re.I)
                img = tile.select_one("img[alt]")
                name = promo or (img["alt"].strip() if img else "") or sub
            name = name.strip()
            if not name:
                continue
            normal = _tag(tile.select_one(".k-product-tile__pricetags-normal .k-price-tag"))
            card = _tag(tile.select_one(".k-product-tile__pricetags-loyalty .k-price-tag"))
            raw.append(dict(name=name, unit=unit, normal=normal, card=card, vf=vf, vt=vt,
                            mixed=mixed, section_cat=section_cat))
            if not mixed and section_cat:
                by_name_category[name.lower()] = section_cat

    deals, seen = [], set()
    for r in raw:
        text = f"{r['name']} {r['unit']}"
        if durable.search(text) or NON_CONSUMABLE.search(r["name"]):
            continue
        cat = r["section_cat"] or by_name_category.get(r["name"].lower()) or categorize(text)
        if r["mixed"] and cat == "Ostatné":
            continue  # only seen in a mixed section and not recognisably a consumable
        n, c = r["normal"] or {}, r["card"] or {}
        note = None
        if n.get("discount"):                       # deal for everyone (maybe cheaper with the card)
            price, old, disc = n["price"], n.get("old"), int(n["discount"])
            club = c.get("price") if c.get("price") and c["price"] < price else None
        elif c.get("price"):                         # "iba 6,99" + card price: card-only deal
            price, old, disc, club = c["price"], c.get("old") or n.get("price"), int(c.get("discount") or 0) or None, None
            note = "len s Kaufland Card XTRA"
        elif n.get("price"):                         # plain low price, no discount shown
            price, old, disc, club = n["price"], n.get("old"), None, None
        else:
            continue
        if not price or (old and old <= price):
            old = None
        key = (r["name"].lower(), price)
        if key in seen:
            continue
        seen.add(key)
        deals.append(dict(name=r["name"], brand=None, unit=r["unit"], price=price, old_price=old, discount=disc,
                          club_price=club, category=cat, note=note, valid_from=r["vf"], valid_to=r["vt"], page=None))

    starts = sorted(d["valid_from"] for d in deals if d["valid_from"])
    ends = sorted(d["valid_to"] for d in deals if d["valid_to"])
    common = lambda xs: max(set(xs), key=xs.count) if xs else None
    return deals, common(starts), common(ends)
