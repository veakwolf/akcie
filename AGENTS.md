# Instructions for coding agents (Codex, Claude, …)

This repo powers the "Akcie Trnava" app (https://veakwolf.github.io/akcie/).

When the user asks to **"spracuj akcie"** (process this week's deals), follow
[`SPRACOVANIE.md`](SPRACOVANIE.md) exactly:

- Work on the newest folder in `weeks/`. First `git pull`.
  - If it is older than 7 days, the Wednesday download didn't run: tell the
    user to start it (GitHub → akcie → Actions → Stiahnuť letáky → Run
    workflow) and stop.
  - If `docs/deals.json` has `"complete": true` and `"week"` equal to that
    folder's name, everything is already done: say so in Slovak and stop.
  - Process **every store folder** in it, including `tesco_next` / `billa_next`
    (next week's flyers). Folders copied from an earlier week already have
    `ai.jsonl` + `ai_pages.txt` covering all pages: skip those. If a folder has
    only some pages done, continue from the missing ones.
- Write one JSON line per deal to `weeks/<date>/<store>/ai.jsonl` and the
  processed page numbers to `ai_pages.txt`.
- For Lidl (`meta.json` → `"images": true`), take the product ↔ price pairing from the page images on the
  `stranky` branch (`git fetch origin stranky`), not from the text order.
- Biedronka (`biedronka`, `biedronka_next`, `biedronka_fresh`; `"image_only": true`) has no text at all:
  read the deals from the page images on the `stranky` branch.
- Only household consumables (food, drinks, alcohol, drugstore and cleaning);
  never furniture, tools, clothes, toys, electronics, decorations.
- Never invent a price; skip unclear products.
- `kaufland` / `kaufland_next` are filled automatically from Kaufland's website: never edit them.
- Run `python3 scripts/merge.py`, fix what its report flags, then commit
  `weeks/`, `docs/deals.json` and `docs/history.json` and **push to `main`**.
- On Windows, `python3` may be called `python`.
- Reply in Slovak, 2–3 sentences: deals per store and anything that failed.

Do not change `scripts/`, `docs/index.html` or `.github/` during this task.
