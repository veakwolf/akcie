# Instructions for coding agents (Codex, Claude, …)

This repo powers the "Akcie Trnava" app (https://veakwolf.github.io/akcie/).

When the user asks to **"spracuj akcie"** (process this week's deals), follow
[`SPRACOVANIE.md`](SPRACOVANIE.md) exactly:

- Work on the newest folder in `weeks/`.
- Write one JSON line per deal to `weeks/<date>/<store>/ai.jsonl` and the
  processed page numbers to `ai_pages.txt`.
- For Lidl, take the product ↔ price pairing from the page images on the
  `stranky` branch (`git fetch origin stranky`), not from the text order.
- Only household consumables (food, drinks, alcohol, drugstore and cleaning);
  never furniture, tools, clothes, toys, electronics, decorations.
- Never invent a price; skip unclear products.
- Run `python3 scripts/merge.py`, fix what its report flags, then commit
  `weeks/` and `docs/deals.json`.
- Reply in Slovak, 2–3 sentences: deals per store and anything that failed.

Do not change `scripts/`, `docs/index.html` or `.github/` during this task.
