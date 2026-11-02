"""Rule-based fallback parser (free, catches roughly half the deals).

Reads weeks/<date>/<store>/pages/*.txt and returns the deals.json structure.
The weekly AI pass (see SPRACOVANIE.md) replaces this with a complete list.
"""
import datetime as dt
import json
import pathlib
import re

PCT = re.compile(r"^[−-]\s?(\d{1,2})\s?[%﹪]$")
COMMA_PRICE = re.compile(r"^\d{1,3},\d{2}$")
BILLA_PRICE = re.compile(r"^\d{3,5}$")
NOISE = re.compile(r"(Ceny platia|vypredania|Clubcard|kupón|Bežná cena|S kupónom|Akcia neplatí|"
                   r"V akciovej ponuke|Záloha|^\d+$|indd|www\.|Cena pre všetkých|Do vypredania)", re.I)
BADGE = re.compile(r"^(SUPER|CENA|CENOVÝ|ŠOK|SUPER CENA|CENOVÝ ŠOK)$")


def name_and_unit(lines):
    name, detail = [], []
    for l in lines:
        l = l.lstrip("* ").strip()
        if not l or NOISE.search(l) or BADGE.match(l):
            continue
        if detail or re.search(r"\d\s?(g|kg|ml|l|ks)\b|predaj|balen|cena za|rôzne|viac druhov|=", l, re.I):
            detail.append(l)
        else:
            name.append(l)
    return " ".join(name).strip(), " ".join(detail).strip()


def tesco(page, L):
    out, i = [], 0
    while i < len(L) - 2:
        if COMMA_PRICE.match(L[i]) and COMMA_PRICE.match(L[i + 1]) and PCT.match(L[i + 2]):
            old, new, pct = float(L[i].replace(",", ".")), float(L[i + 1].replace(",", ".")), int(PCT.match(L[i + 2]).group(1))
            j, body = i + 3, []
            while j < len(L) and len(body) < 8 and not (
                    COMMA_PRICE.match(L[j]) and j + 2 < len(L) and PCT.match(L[j + 2])):
                body.append(L[j]); j += 1
            name, unit = name_and_unit(body)
            if name and old > new:
                out.append(dict(name=name, unit=unit, price=new, old_price=old, discount=pct, page=page))
            i = j
        else:
            i += 1
    return out


def billa(page, L):
    out, start = [], 0
    for i in range(2, len(L)):
        if PCT.match(L[i]) and BILLA_PRICE.match(L[i - 1]) and BILLA_PRICE.match(L[i - 2]):
            new, old, pct = int(L[i - 2]) / 100, int(L[i - 1]) / 100, int(PCT.match(L[i]).group(1))
            name, unit = name_and_unit(L[max(start, i - 10):i - 2])
            if name and old > new:
                out.append(dict(name=name, unit=unit, price=new, old_price=old, discount=pct, page=page))
            start = i + 1
    return out


DURABLE = re.compile(r"(stolík|stôl|stoličk|kreslo|pohovk|polic|skrin|LED|svietid|lamp|vianočný stromček|dekorác|"
                     r"náradi|vŕtačk|skrutkov|záhradn|mikin|tričk|nohavic|bund|ponožk|obuv|topánk|hračk|"
                     r"hrnc|panvic|tanier|pohár(?! ?\d)|príbor|nôž|posteľn|vankúš|paplón|uterák|deka|"
                     r"slúchadl|nabíjačk|kábel|reproduktor|bicykel|kolobežk|motokár)", re.I)
CATEGORY_RULES = [
    ("Drogéria a čistenie", r"prac[íi]|aviváž|toaletn|papierov|čistiac|umývačk|šampón|sprchov|zubn|mydl|plienk|"
                            r"vrecia|dezodor|kapsul|gél na pranie|jar\b|savo|wc\b"),
    ("Alkohol", r"pivo|víno|vodka|rum|whisk|borovičk|slivovic|likér|šumiv|prosecco|fľaša.*%|\d+(,\d)? ?%"),
    ("Nápoje", r"minerál|voda|džús|limonád|kofola|coca|pepsi|sirup|káva|čaj|nápoj"),
    ("Mäso a ryby", r"mäs|bravč|hovädz|kurac|kurč|morč|kač|husac|teľac|šunk|saláma|klobás|párk|slanin|"
                    r"ryb|losos|tuniak|filet|tilapi|pstruh|krevet|tresk|tresč|krkovič|karé|stehn|pliec|rezne|pečienk"),
    ("Mliečne a vajcia", r"mlieko|jogurt|syr|maslo|smotan|tvaroh|bryndz|vajc|kefír|mozzarell|eidam|niva|"
                         r"hermelín|pribináč|acidk|grana|parmez|gouda"),
    ("Mrazené", r"mrazen|zmrzlin|nanuk|pizza"),
    ("Pečivo", r"chlieb|rožk|bagety|bageta|pečivo|koláč|vianočk|croissant|buchty|toast|kaizerk|donut|zákusok|tramezzino"),
    ("Ovocie a zelenina", r"jablk|hrušk|banán|mango|kivi|kaki|pomaranč|mandarín|citrón|hrozno|kapust|zemiak|cibuľ|mrkv|petržl|"
                          r"paradajk|uhork|paprik|šalát|brokolic|tekvic|gaštan|granát|zelenin|ovocie|kiwi|avokád"),
    ("Sladké a slané", r"čokolád|sušienk|oblátk|cukrík|bonbón|chips|lupienk|tyčink|keks|bábovk|orech|praclík|"
                       r"popcorn|kakaov|rez\b|rezy|kinder|pom-bär"),
    ("Trvanlivé potraviny", r"múk|cukor|ryža|cestovin|olej|konzerv|kečup|horčic|omáčk|polievk|cereál|müsli|"
                            r"ocot|korenie|džem|med\b|fazuľ|šošovic|hotové jedl"),
]


def categorize(text):
    for cat, pattern in CATEGORY_RULES:
        if re.search(pattern, text, re.I):
            return cat
    return "Ostatné"


PARSERS = {"tesco": tesco, "billa": billa}  # Lidl's text is too jumbled for rules; AI pass only.


def build(week_dir):
    week_dir = pathlib.Path(week_dir)
    stores, deals = {}, []
    for store_dir in sorted(p for p in week_dir.iterdir() if p.is_dir()):
        meta = json.loads((store_dir / "meta.json").read_text(encoding="utf-8"))
        stores[meta["store"]] = {k: meta.get(k) for k in ("valid_from", "valid_to", "web")}
        parser = PARSERS.get(store_dir.name)
        if not parser:
            continue
        for f in sorted((store_dir / "pages").glob("p*.txt")):
            page = int(f.stem[1:])
            lines = [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            for d in parser(page, lines):
                text = f"{d['name']} {d['unit']}"
                if DURABLE.search(text):
                    continue
                deals.append(dict(store=meta["store"], category=categorize(text), club_price=None, note=None,
                                  valid_from=meta.get("valid_from"), valid_to=meta.get("valid_to"), **d))
    return dict(week=week_dir.name, generated=dt.datetime.now().isoformat(timespec="seconds"),
                source="rules", stores=stores, deals=deals)
