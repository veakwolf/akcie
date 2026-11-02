# Weekly processing (for Claude)

Every Wednesday the GitHub Action downloads the flyers and saves the text of the
food pages to `weeks/<date>/<store>/pages/pNNN.txt`. This step turns that text
into clean deals for the app.

## Steps

1. Use the **newest** folder in `weeks/`. Check its `status.json`; if a store
   failed (errors), tell the user and continue with the rest.
2. For each store (`tesco`, `billa`, `lidl`), work through the pages in batches
   of about 8 pages:
   - Read the batch's `pNNN.txt` files.
   - **Lidl** (`meta.json` has `"images": true`): its text lists price boxes out
     of order, so also look at each page's image and take the **pairing of
     product ↔ price from the image**, the spelling from the text. The images
     are on the `stranky` branch:
     `git fetch origin stranky && git worktree add ../stranky stranky`, then
     `../stranky/<date>/lidl/img/pNNN.jpg`. If the images are missing, skip
     Lidl and say so in the reply.
   - For each **deal** (a product with a sale price) append **one line** of JSON
     to `weeks/<date>/<store>/ai.jsonl` (format below).
   - Append the page numbers of the batch to `weeks/<date>/<store>/ai_pages.txt`
     (space separated), so we know which pages are done.
   - Repeat until every page in `meta.json` → `pages_kept` is done.
   - If a store's `ai.jsonl` already exists from an earlier, interrupted run,
     continue from the pages missing in `ai_pages.txt`; do not start over.
3. Run `python3 scripts/merge.py`. It checks every row, drops invalid ones and
   writes `docs/deals.json`. Read its report: fix any `pages NOT processed` and
   look at the rejected rows.
4. Commit `weeks/` and `docs/deals.json` with the message `AI akcie <date>` and push.
5. Reply to the user in Slovak in 2–3 sentences: how many deals per store, and
   whether something failed.

## Format of one line in ai.jsonl

```json
{"name": "Kuracie pečienky Mäsiarov výber", "brand": "Domäsko", "unit": "1 kg", "price": 2.49, "old_price": 3.39, "discount": 26, "club_price": null, "category": "Mäso a ryby", "note": null, "valid_from": null, "valid_to": null, "page": 6}
```

- `name`: product as a shopper would search for it, in Slovak, without
  advertising words (SUPER CENA, CENOVÝ ŠOK, Týždenná akcia…). Keep the type or
  variety ("horné stehno bez kosti").
- `brand`: brand if stated, otherwise `null`.
- `unit`: pack size or how it's sold: `"500 g"`, `"1 kg"`, `"cena za 100 g"`,
  `"3 × 80 g"`, `"1 ks"`, `"0,5 l"`.
- `price`: the price **everyone** pays during the deal, in euros, as a number.
  - Billa writes prices without a comma: `069` = `0.69`, `1299` = `12.99`.
  - Lidl uses a dot: `1.29`.
- `old_price`: the crossed-out / regular ("Bežná cena") price, or `null` if none
  is shown.
- `discount`: the % shown, as a whole number (`−35 %` → `35`), or `null`.
- `club_price`: a lower price only for card or app holders: Tesco **Clubcard**,
  Tesco **app coupon** (the lower of the two), Billa **Bonus**, **Lidl Plus**.
  - If there is a deal price for everyone, `price` is that and `club_price`
    the lower card/app price.
  - If the deal exists **only with the card** (Tesco "Clubcard cena" next to
    "Bežná cena"): `price` = the card price, `club_price` = the even lower app
    coupon price if there is one (else `null`), `old_price` = Bežná cena, and
    `note` = `"len s Clubcard"` (plus `", kupón v aplikácii"` if a coupon exists).
  - Tesco shows coupon prices only per kg/l ("S kupónom: 1 l = 0,98"); compute
    the pack price (0,5 l → 0,49) and check it against the big "−NN %" number.
- `category`: exactly one of: `Ovocie a zelenina`, `Mäso a ryby`,
  `Mliečne a vajcia`, `Pečivo`, `Trvanlivé potraviny`, `Sladké a slané`,
  `Nápoje`, `Alkohol`, `Mrazené`, `Drogéria a domácnosť`, `Ostatné`.
- `note`: short and only if important: `"len s Clubcard"`, `"pri kúpe 2 ks"`,
  `"platí len 29. 10. – 1. 11."`, `"neplatí v predajni …"` (mention the
  exclusion only if it applies to **Trnava** or to all small stores), else `null`.
- `valid_from` / `valid_to`: only when the deal's dates **differ** from the
  flyer (e.g. a weekend offer), format `YYYY-MM-DD`; otherwise `null`.
- `page`: page number from the file name (`p006.txt` → `6`).

## Rules

- Only real deals with a price. Skip pages of rules, contests, recipes, and
  products without a price.
- Never invent a price. If the text is ambiguous and you can't tell which number
  is the price, skip the product.
- Non-food (tools, clothes, furniture) only if it's on a food page: give it
  category `Ostatné`.
- Don't stop to ask the user anything during steps 1–4.
