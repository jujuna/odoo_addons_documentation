# gec_property_tax_report code review (2026-10-23 → 2026-11-01)

Scope: the whole module (Form 15: Parts I–IV, land plots, asset tax fields, generate, export, explanation workbook).
Every fix has a test; last full run of `/gec_property_tax_report`: 95 tests, 0 failed.

Confidence tags: [Certain] = read in source or reproduced in a test; [Likely] = strong inference; [Guessing] = gap-filling.

---

## 1. Fixed — audit (commit `74f219a`, version 20.0.1.3.0)

Must fix (wrong tax or a filing that cannot be made):
- [x] 1. "Value at Lease-Out" replaced the book value for every company and kept sold assets for years → only for
  leasing companies and only while the asset exists (judged by dates, so a fully depreciated asset still counts).
- [x] 2. Archived assets and plots disappeared from the declaration → archived records read too; a plot archived
  without a sale date stays out.
- [x] 3. An IFRS flag on part of a group blocked Part III → decided per object, not per asset, with a warning when the
  parts disagree.
- [x] 4. Land had no dates → Acquired On and Sold On on the plot, plus an optional link to its asset (`asset_id`); the
  months come from the dates.
- [x] 5. Screens for fields that did not exist yet on `gec_main` → `gec_main` upgraded to 20.0.1.3.0 on 2026-10-29.

Should fix:
- [x] 6. Required tax fields blocked normal asset work → not required; Generate lists the untagged assets.
- [x] 7. Generate erased hand-typed column 12 → kept when there is no usable previous-year declaration.
- [x] 8. Explanation Workbook failed for read-only users → the file is stored with `sudo()`.
- [x] 9. Land assets stayed out of Part III only through a manual tick → assets linked to a plot are left out
  automatically and released when the link changes or the plot is deleted.
- [x] 10. Year list ended at 2025 → 2026 shipped; missing years created automatically with an XML ID.
- [x] 11. Reset to Draft kept the old export files → cleared on Reset to Draft and Generate; a part's file is cleared at
  Export when that part has no rows.
- [x] 12. Read-only users saw buttons that only gave errors → the 5 editing buttons for `account.group_account_user`.
- [x] 13. The Explanation Workbook was all English → texts and sheet names translatable and translated.
- [x] 14. Stale copies of the module elsewhere → moved to `stale_copies/` (nothing deleted).

Low:
- [x] 15. An exemption could exceed the asset's own value → `min(amount, average)`.
- [x] 16. A back-dated sale got a date that was too late (strict audit trail, hashed journal) → cancelled and reversed
  entries ignored when dating the sale.
- [x] 17. Months of Existence editable after Export → read-only unless draft, plus a server-side guard.
- [x] 18. The explanation window showed another number than the row for leased assets and "0 assets" for archived
  ones → one shared column-6 calculation; archived assets read.
- [x] 19. Asset names saved in the language of whoever pressed Generate → read in the company's language.
- [x] 20. Generate read every old sold asset each time → assets sold before the tax year skipped.
- [x] 21. Five row warnings could not be translated → `self.env._()`, translated.
- [x] 22. "rs.ge Rate" and other terms missing in Georgian → translated (only the placeholder "0.xxx" stays empty).
- [x] 23. Two companies with the same year got the same export file name → `form15_part<N>_<tax ID>_<year>.xml`.
- [x] 24. Remove deleted a grid row without asking → confirmation; page size 1000, and a note when the grid is paged
  (filters and totals cover the loaded page only).

Law (Tax Code of Georgia, matsne publication 247, October 2026):
- [x] 26. [Certain] Art. 205(3): the advance is the FULL previous-year tax, paid once by 15 June → "Next Year Advance"
  and "Advance Due" on the form.
- [x] Land year. [Certain] Art. 205(2): land is reported for the filing year → "Land as at" defaults to 1 April of the
  year AFTER the period (it was the same year).
- [x] 30. [Certain] 0.24 GEL/m², the coefficient cap 1.5 and the bands 3 / 2 / 1.5 (art. 202(1), 204(2)) confirmed;
  articles cited in the code. Source text in `tools/source/tax_code_art_202_205.txt`.
- [x] 27. README_DEV says Odoo 20; coupling map rows fixed; module doc written.

## 2. Removed — sample data script (2026-11-01, this commit)

- [x] `tools/load_sample_data.py` deleted: not needed for this module. The test data stays in `gec_test`;
  `TESTING_KA.md` step 0.3 removed and its examples refer to that database.

## 3. Open (need outside input)

- [ ] 25. Three rules still guessed until one test upload on the rs.ge portal: column 13 (column 15 or 11?), group 5 =
  leased out?, construction in progress = immovable?
- [ ] 29. `15_data_*.xlsx` and `temp_15_*.xml` need an rs.ge login: download into `tools/source/`, run
  `tools/generate_classifier_csv.py`, compare with the shipped CSVs.
- [ ] A run on real company data (old, split, sold and leased assets), on a copy of a client database.
- [ ] A click-through in the browser after the fixes (tester guide `TESTING_KA.md`).

## 4. Checked and fine (do not redo)

- Explanation window escapes values (a plot named `<img src=x onerror=alert(1)>` shows as text).
- Land rate data: 263 zones × 11 types = 2 893 rows, no gaps, duplicates or negatives; zone 78736 / type 33 = 1.3 is a
  deliberate override.
- Every model has access rows and company rules; locked grid columns cannot be edited; export column counts match the
  portal; no other module reads this module's fields.

## 5. Run the tests

Scratch DB, dropped afterwards:
```
docker exec odoo20_odoo python3 /opt/odoo/odoo-bin -c /etc/odoo.conf \
  --db_host odoo20_db --db_user odoo --db_password odoo -d ptax_tmp \
  -i gec_property_tax_report --test-enable --test-tags /gec_property_tax_report \
  --stop-after-init --http-port=8079
docker exec odoo20_db dropdb -U odoo --force ptax_tmp
```
