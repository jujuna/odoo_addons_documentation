# Property Tax (Form 15) Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 13 verified defects of `gec_property_tax_report` found by the 2026-10-21 bug hunt.

**Architecture:** Every fix stays inside the module. Column 6 gets one shared reader on `account.asset` so the generator and the explanation cannot disagree. The other fixes are local guards in the generator, the plot model, the views and the data file. Nothing writes to accounting.

**Tech Stack:** Odoo 20 Enterprise (`account_asset` with asset variants), Python, XML views, `TransactionCase` tests.

**Spec:** the verified findings list in this session (bug hunter report + verifier table, 2026-10-21). Decisions taken for the two open questions:
- D1: "Value at Lease-Out" applies **only** when `company.rs_form15_is_leasing_company` is set (README.md §2.4 and the field help already say so).
- D2: archived assets and plots **still count** for the years they had value or were owned. An archived plot **without** a Sold On date keeps today's meaning (archive = removed).

## Global Constraints

- Module path: `gec_property_tax_report/` in `customAddons/gec_odoo_basic_modules`. Version becomes `20.0.1.3.0`.
- Never write to accounting; generation only reads.
- Georgian text in `i18n/ka_GE.po` for every new user-facing string.
- Do **not** commit (user rule: commit only when asked). Leave the work uncommitted on branch `20.0`.
- Test runs need `--http-port=8079` (the dev server holds 8069). Test command (throwaway DB, drop after):
  `docker exec odoo20_odoo python3 /opt/odoo/odoo-bin -c /etc/odoo.conf --db_host odoo20_db --db_user odoo --db_password odoo -d ptax_fix_tmp -i gec_property_tax_report --test-enable --test-tags /gec_property_tax_report --stop-after-init --http-port=8079`
- Sample-data regression (no fix may change it): 2025 Part III 19 rows, total 36 060.04; Part IV 3 rows, 1 682.00; months=10 → Tbilisi head office col. 15 = 8 325.00; leasing company → 711.00 / 2 190.00.

## Review Focus

1. A leased-out asset in its sale year or activation year: the frozen value must count for the half of the year it existed, not twice and not in full. → test in Task 1.
2. An archived plot that was archived the old way (no Sold On): must stay out. → test in Task 2.
3. A movable asset with the IFRS flag: must not create a second row. → test in Task 3.
4. A declaration regenerated while a previous year exists: typed column 12 is replaced by last year's column 11 (unchanged rule). → test in Task 5.
5. A plot re-linked from asset A to asset B where another plot still links A: A must stay excluded. → test in Task 9.

---

### Task 1: One column-6 reader; lease-out value only for leasing companies, only while the asset exists (findings 1, 11)

**Files:**
- Modify: `models/account_asset.py` (new method; help of `rs_form15_leased_out_base_value`)
- Modify: `models/rs_form15_declaration.py` `_part3_line_vals` (lines ~236-244), `RsForm15Part3Line._explain` (sources loop ~935-947, step 6 detail)
- Test: `tests/test_named_rows.py` (class `TestForm15NamedRows`)

**Interfaces:**
- Produces: `AccountAsset._rs_form15_average(self, year: int) -> float`. Average of book value at 1 Jan and 31 Dec of `year`. When `self.company_id.rs_form15_is_leasing_company and self.rs_form15_leased_out and self.rs_form15_leased_out_base_value`: `base × n / 2`, where `n` = how many of the two dates have a non-zero book value (so 0 when the asset did not exist, half in its sale or activation year).

- [ ] **Step 1: Write the failing tests**
  - `test_lease_out_value_ignored_for_ordinary_company`: company flag False; 5.1 asset, value 1000, base 50 000, leased out → row average = book average (not 50 000).
  - `test_lease_out_value_not_declared_after_sale`: leasing company; asset base 50 000 with `rs_form15_excluded=False`, main variant `state='close'`, `disposal_date='2022-06-30'` → no 2025 row.
  - `test_lease_out_value_halved_in_sale_year`: leasing company; disposal 2025-06-30 → average 25 000.
  - `test_explanation_matches_lease_out_row`: leasing company, asset in use all 2025 → `line._explain()['sources'][0]['average'] == line.average_value == 50000`.
- [ ] **Step 2: Run, expect the first three to FAIL (50 000 declared)**
- [ ] **Step 3: Implement `_rs_form15_average`; use it in `_part3_line_vals` instead of the inline average + override; use it in `_explain` sources; step 6 detail says "frozen at the lease-out value" when the frozen rule applied. Field help: "Used instead of the average annual value for a leasing company."**
- [ ] **Step 4: Run module tests, expect PASS**

### Task 2: Archived assets and plots still count (finding 2)

**Files:** `models/rs_form15_declaration.py` `_part3_assets`, `_part4_line_vals`, `_explain` (`asset_ids` read); `models/rs_form15_land_plot.py` `_is_owned_on`; Test: `tests/test_form15.py`.

**Interfaces:** Produces: `RsForm15LandPlot._is_owned_on(day)` also returns False for an archived plot without `date_sold`.

- [ ] **Step 1: Tests**
  - `test_archived_sold_asset_counts_in_its_sale_year` (named rows class): asset disposed 2025-06-30, `active=False` → still in 2025 rows.
  - `test_archived_plot_sold_after_reference_date_is_declared`: plot `date_sold='2025-06-10'`, archived → in 2025 Part IV.
  - `test_archived_plot_without_sale_date_is_left_out`: plot archived, no dates → not declared.
- [ ] **Step 2: Run, expect FAIL**
- [ ] **Step 3: `with_context(active_test=False)` on both searches and on `self.asset_ids` in `_explain`; archived-without-date rule in `_is_owned_on`.**
- [ ] **Step 4: PASS**

### Task 3: Art. 202(2) flag decided per declared object (finding 7)

**Files:** `models/rs_form15_declaration.py` `_part3_line_vals`; Test: `tests/test_named_rows.py`.

- [ ] **Step 1: Tests**
  - `test_partly_audited_group_is_one_row`: group of two 1.13 assets, flag on one → one row, coefficient from the year band, warning mentions the revaluation flag.
  - `test_fully_audited_group_takes_coefficient_one`: flag on both → one row, coefficient 1.0 option.
  - `test_flag_on_movable_asset_does_not_split_the_row`: two 1.1 assets in Poti, flag on one → one row.
- [ ] **Step 2: FAIL ("declared twice" / two rows)**
- [ ] **Step 3: Drop the flag from the group key; the group collects `exempt_flags`; an immovable row is exempt only if all its assets are; mixed → warning "IFRS revaluation is set on only some assets of this object; the revaluation coefficient was applied."**
- [ ] **Step 4: PASS**

### Task 4: Exemption amount capped at the asset's own average (finding 5)

**Files:** `models/account_asset.py` `_rs_form15_exemption`; Test: `tests/test_form15.py`.

- [ ] **Step 1: `test_exemption_capped_at_the_asset_value`: amount 5000, average 1000 → `_rs_form15_exemption(1000) == 1000`.**
- [ ] **Step 2: FAIL; Step 3: `min(amount, average_value)`; Step 4: PASS**

### Task 5: Typed column 12 survives regeneration when there is no previous declaration (finding 6)

**Files:** `models/rs_form15_declaration.py` `action_generate_part3`, `_part3_line_vals`, `_part3_previous_advances`; Test: `tests/test_named_rows.py`.

**Interfaces:** `_part3_line_vals(self, typed_advances=None)`; `_part3_previous_advances(self, typed_advances=None) -> dict` returns `typed_advances or {}` when no previous-year declaration exists. Keys as today: `(type_id, territory_id, object_key)`.

- [ ] **Step 1: Tests**
  - `test_typed_advance_kept_without_previous_year`: generate, type 123 in `advance_amount`, generate again → 123.
  - `test_previous_year_still_wins_over_typed_advance`: previous year row exists → advance = its column 11.
- [ ] **Step 2: FAIL; Step 3: collect advances from the rows about to be deleted; Step 4: PASS**

### Task 6: Disposal date ignores cancelled moves (finding 8)

**Files:** `models/account_asset.py` (`_rs_form15_variant_book_value`, new `_rs_form15_disposal_date(variant)`); `models/rs_form15_land_plot.py` `_compute_dates` uses it; Test: `tests/test_named_rows.py` (`TestAccountAssetCommon` based class).

**Interfaces:** `AccountAsset._rs_form15_disposal_date(variant) -> date | False` (`@api.model`): False unless `variant.state == 'close'`, else max date of `variant.depreciation_move_ids` whose state is not `cancel`.

- [ ] **Step 1: `test_cancelled_moves_do_not_delay_disposal`: closed variant with a cancelled move dated after the disposal move → helper returns the disposal move date; book value at year end after disposal is 0.**
- [ ] **Step 2: FAIL; Step 3: implement, use in book value and plot dates; Step 4: PASS**

### Task 7: Named rows use the company language (finding 12)

**Files:** `models/rs_form15_declaration.py` (`_part3_line_vals` name read, `RsForm15Part3Line._compute_name`); Test: `tests/test_named_rows.py`.

- [ ] **Step 1: `test_name_is_read_in_the_company_language`: asset name translated (ka_GE loaded in the test with `self.env['res.lang']._activate_lang('ka_GE')`), company partner lang ka_GE, generate as an en_US user → row name is the Georgian one.**
- [ ] **Step 2: FAIL; Step 3: read names with `with_context(lang=company.partner_id.lang or self.env.lang)`; Step 4: PASS**

### Task 8: Acquisition years beyond the data file (finding 13)

**Files:** `data/rs.form15.year.csv` (add `year_2026`, code 2026, sequence 280); `models/rs_form15_classifier.py` `RsForm15Year._for_year(year, create=False)`; generator passes `create=True`; row warning; Test: `tests/test_form15.py`.

- [ ] **Step 1: `test_missing_year_is_created_for_generation`: immovable asset acquired 2031 → generation succeeds, year option code `2031` exists, row warning says the option was added and must be checked on the portal.**
- [ ] **Step 2: FAIL; Step 3: implement (create only for 2000 ≤ year); Step 4: PASS**

### Task 9: Forms and access (findings 3, 4, 9, 10)

**Files:** `views/account_asset_views.xml` (drop `required` on type and territory); `views/rs_form15_declaration_views.xml` (`months_of_existence` readonly unless draft); `models/rs_form15_declaration.py` `write` (refuse `months_of_existence` change on exported); `models/rs_form15_declaration_xlsx.py` (store the workbook with `sudo()`); `models/rs_form15_land_plot.py` `write` (on asset change, clear `rs_form15_excluded` on the previous asset unless another plot links it); `models/account_asset.py` (`tracking=True` on `rs_form15_excluded`); Tests: `tests/test_form15.py`.

- [ ] **Step 1: Tests**
  - `test_months_locked_after_export`: export, write months → UserError.
  - `test_readonly_user_can_download_explanation`: user in `account.group_account_readonly` only → `action_export_explanation()` returns the URL action.
  - `test_relinking_a_plot_releases_the_previous_asset`: link A, relink to B → A not excluded, B excluded.
  - `test_relinking_keeps_an_asset_another_plot_uses`: two plots on A, relink one → A still excluded.
- [ ] **Step 2: FAIL; Step 3: implement; Step 4: PASS**

### Task 10: Docs, translations, version, full regression

**Files:** `README.md`, `README_DEV.md`, `i18n/ka_GE.po`, `__manifest__.py`.

- [ ] **Step 1: README: lease-out only for leasing companies; archiving rules; Sold On.**
- [ ] **Step 2: ka_GE entries for every new string (warnings, errors, help); check they load (`-u` with `--i18n-overwrite` on the throwaway DB).**
- [ ] **Step 3: Version 20.0.1.3.0.**
- [ ] **Step 4: Full test run: `0 failed, 0 error(s)`.**
- [ ] **Step 5: Sample-data regression on a fresh DB: numbers in Global Constraints unchanged. Drop the DB.**
