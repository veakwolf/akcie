# Akcie

**Appka:** https://veakwolf.github.io/akcie/ (v Browseri → Share → Add to Desktop)

## Čo appka vie

- Akcie podľa obchodu, vyhľadávanie, rýchle filtre, cena za kg/l,
  „najlacnejšie“, „končí zajtra“.
- História cien a detail akcie (spodný panel).
- Prepínač **tento / budúci týždeň** (keď sú budúce letáky už zverejnené).
- Zamestnanecká karta Tesco (−15 %).
- **Môj zoznam** – nákupný zoznam uložený v telefóne.
- **Spoločný zoznam** – zdieľaný cez Supabase, pripája sa kódom alebo
  pozvánkou. Schéma databázy je v [`db/schema.sql`](db/schema.sql).
- **Sledované** produkty – osobné, uložené v telefóne.

Celá appka je jeden súbor `docs/index.html` (GitHub Pages z priečinka `docs/`).

## Odkiaľ sú dáta

1. **Každé ráno (~6:17)** GitHub Action „Stiahnuť letáky“
   (`.github/workflows/letaky.yml`) spustí `scripts/fetch.py`:
   - stiahne letáky Tesco, Billa a Lidl (PDF), vytiahne text strán s
     potravinami do `weeks/<dátum>/<obchod>/`; keď sú zverejnené, aj budúce
     letáky Tesco a Billa (`tesco_next`, `billa_next`),
   - Kaufland berie priamo z predajne.kaufland.sk (`scripts/kaufland_web.py`,
     bez AI) – aktuálny aj budúci týždeň,
   - leták, ktorý sa nezmenil, sa len prevezme z predošlého dňa, takže nové
     AI spracovanie netreba,
   - obrázky strán (Lidl) idú do vetvy `stranky`, ktorá sa zakaždým prepíše.
2. **AI spracovanie** („spracuj akcie“) robí Codex lokalne – naplánované
   úlohy v pondelok a stredu o 18:00 (`scripts/codex-weekly.ps1`). Z textu
   letákov vytiahne akcie do `ai.jsonl` podľa [`AGENTS.md`](AGENTS.md) a
   [`SPRACOVANIE.md`](SPRACOVANIE.md). Berie sa len spotrebný tovar
   (potraviny, nápoje, drogéria, čistiace prostriedky).
3. `scripts/merge.py` skontroluje riadky, dopočíta cenu za kg/l, aktualizuje
   históriu cien (`docs/history.json`) a zapíše `docs/deals.json`. Keď je
   všetko spracované, má `"complete": true`.

Kým AI spracovanie neprebehne, appka ukazuje len základný zoznam z pravidiel
(`scripts/rules.py`) a Kaufland.

## Keď niečo nefunguje

- **GitHub → Actions → Stiahnuť letáky → Run workflow** spustí sťahovanie ručne.
- Chyby jednotlivých obchodov sú v `weeks/<dátum>/status.json`. Ak obchod zmení
  web, treba upraviť príslušnú funkciu `find_*` v `scripts/fetch.py`
  (Kaufland: `scripts/kaufland_web.py`).
- Log Codexu je v `codex-weekly.log` na PC (necommituje sa).
- `python3 scripts/merge.py` skontroluje a znova zloží `docs/deals.json`.

## Na neskôr

- Upozornenia na sledované produkty (týždenný e-mail alebo notifikácia).

Údaje pochádzajú z verejne dostupných letákov a webov obchodov a sú len na
osobné použitie.
