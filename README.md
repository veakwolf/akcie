# Akcie Trnava

Vlastná náhrada za aplikáciu Dohliadač: týždenné akcie z letákov **Tesco**,
**Billa** a **Lidl** v jednej appke na iPhone, s vyhľadávaním, nákupným
zoznamom a sledovanými produktmi.

**Appka:** https://veakwolf.github.io/akcie/ (v Safari → Zdieľať → Pridať na
plochu)

## Ako to funguje

1. **Každú stredu ráno** GitHub Action (`.github/workflows/letaky.yml`) stiahne
   aktuálne letáky, vytiahne text strán s potravinami do `weeks/<dátum>/` a
   urobí základný zoznam akcií (časť Tesco a Billa) do `docs/deals.json`.
   Obrázky strán Lidla idú do vetvy `stranky` (každý týždeň sa prepíše).
2. **Raz týždenne** v Claude (model Haiku 5.5) napíšeš „spracuj akcie“. Claude
   podľa [`SPRACOVANIE.md`](SPRACOVANIE.md) prečíta letáky, vytvorí úplný zoznam
   akcií a uloží ho. Bez tohto kroku appka ukazuje len základný zoznam.
3. Appka (`docs/index.html`) číta `docs/deals.json`. Nákupný zoznam a sledované
   produkty sa ukladajú len v telefóne.

Kaufland nie je zahrnutý: jeho stránka blokuje automatické sťahovanie.

## Keď niečo nefunguje

- **Actions → Stiahnuť letáky → Run workflow** spustí sťahovanie ručne.
- Chyby jednotlivých obchodov sú v `weeks/<dátum>/status.json`. Ak obchod zmení
  web, treba upraviť príslušnú funkciu `find_*` v `scripts/fetch.py`.
- `python3 scripts/merge.py` skontroluje a znova zloží `docs/deals.json`.

Údaje pochádzajú z verejne dostupných letákov obchodov, sťahujú sa raz týždenne
a sú len na osobné použitie.
