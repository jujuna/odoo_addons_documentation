# Georgia - Profit Tax Declaration (`gec_profit_tax_report`) — Developer guide

For developers who change this module. The business rules and user steps are in [README.md](README.md);
this file points there instead of repeating them.

## Purpose and facts

The module builds the monthly profit tax declaration (rs.ge form II-086, MoF Order 996 art. 40¹) from
posted `account.move.line` records. Each form row is an `rs.cit.cell`; each declaration holds one line
per row with two columns. The CIT wizard of `gec_localization` books the dividend tax; this module books
only the rest.

| | |
|---|---|
| Depends | `gec_localization`: Georgian chart, `l10n.ge.cit.wizard` (dividend accrual whose withholding tax 16.1 adds back), `is_company` from the Georgian personal number |
| New models | `rs.cit.cell`, `rs.cit.declaration`, `rs.cit.declaration.line`, `rs.cit.taxed.item`, `rs.cit.recovery`, `rs.cit.annex.line` |
| Extended models | `account.account`, `account.move.line`, `account.chart.template`, `res.partner`, `res.country`, `res.company`, `res.config.settings` |
| Hooks | `account.chart.template._post_load_data` seeds defaults when a company loads the `ge` chart |
| Crons, controllers | none |

Data files, in manifest order:

1. `data/rs.cit.cell.csv`: the 47 Part III rows.
2. `data/rs_cit_data.xml`: calls `account.account._gec_cit_seed_cells` for companies already on the `ge` chart.
3. The views.
4. `security/ir.access.csv`.

## Architecture

```text
 Journal items ──► row of the item / its account ──► contact rules
 (posted)            (gec_cit_cell_id)               (_cit_partner_row)
                                                          │
 Invoice lines with a market value ───────────────────────┤
 Credits on taxed accounts (register) ────────────────────┤
 Balances by group (annexes 2, 3) ────────────────────────┤
                                                          ▼
                  Declaration lines (column 2 / column 3: Calculated + Adjustment)
                                                          │
                 Annex amounts (16.1 split, 16.1.3, 25.1, 25.3, 27.4)
                                                          │
                       FORMULAS per column ──► 21 … 29 ──► totals, booking
```

Boxes map to: `rs.cit.declaration` (methods named), `rs.cit.declaration.line` (lines),
`rs.cit.taxed.item` / `rs.cit.recovery` (register), `rs.cit.annex.line` (repeating annex rows).

## File map

| File | Holds |
|---|---|
| `__init__.py`, `models/__init__.py`, `tests/__init__.py` | Imports |
| `__manifest__.py` | Manifest |
| `data/rs.cit.cell.csv` | Part III rows: code, Georgian text, sequence, `kind`, parent, `measure` |
| `data/rs_cit_data.xml` | Seeding call on install and upgrade |
| `models/rs_cit_cell.py` | `rs.cit.cell`: one form row; `kind` (auto/calc/manual) and `measure` |
| `models/rs_cit_declaration.py` | `rs.cit.declaration` and `rs.cit.declaration.line`; constants, `FORMULAS`, every calculation, confirm, correction, booking, checks |
| `models/rs_cit_declaration_xlsx.py` | `action_export_xlsx` and the workbook sheets |
| `models/rs_cit_taxed_item.py` | `rs.cit.taxed.item`, `rs.cit.recovery`, `rs.cit.annex.line` |
| `models/account_account.py` | `gec_cit_cell_id`, `gec_cit_balance_group`, `DEFAULT_CELL_ACCOUNTS`, `DEFAULT_BALANCE_GROUPS`, `_gec_cit_seed_cells` |
| `models/account_chart_template.py` | `_post_load_data` hook |
| `models/account_move_line.py` | Line override `gec_cit_cell_id`, `gec_cit_market_value` |
| `models/res_partner.py` | Contact classification fields, `_gec_cit_preferential`, `_gec_cit_non_resident` |
| `models/res_country.py` | `gec_cit_preferential` |
| `models/res_company.py` | `COMPANY_STATUSES` (part I), `SPECIAL_STATUSES`, special activities, booking settings |
| `models/res_config_settings.py` | Related settings fields |
| `views/rs_cit_cell_views.xml` | Row list and its menu (administrators) |
| `views/rs_cit_declaration_views.xml` | Declaration list, search and form; taxed items list; menus |
| `views/account_views.xml` | Account form fields; entry line and invoice line columns |
| `views/res_partner_views.xml` | Contact group; country list and form field |
| `views/res_config_settings_views.xml` | Settings block |
| `security/ir.access.csv` | Access rows and multi-company rules |
| `tests/test_profit_tax.py` | Instruction examples and flows |

## Recalculate

`action_compute` (also run by `action_confirm`). Each step writes `amount_auto` / `amount3_auto` and
`move_line_ids` through `_auto_vals`. That method puts the value in column 3 when `_cit_status()` is in
`COL3_ONLY`. `_cit_status()` is `special_status` when set, else `company_status`: part I box 6 has only the three
rs.ge choices (`COMPANY_STATUSES`), the other statuses are `SPECIAL_STATUSES`.

1. `_check_draft` refuses confirmed declarations.
2. `_compute_account_rows`:
   - Reads the month's posted items whose line or account has a row.
   - An item with its own `gec_cit_cell_id` always counts there.
   - An item counting through its account goes through `_cit_partner_row`, which returns the final row
     or `False` (the rules in README [Rows and their rules](README.md#rows-and-their-rules)). Loan
     accounts can land on 18.1.4, 18.3 or 18.4.
   - Row 19 skips budget/NBG contacts, keeps charity items aside for `_charity_taxed`, and includes
     the 19.1 items.
   - Row 17.3 adds `_supplier_bill_items`.
   - `measure == 'debit'` rows sum debits only, so the accrual and the payment on one account do not cancel.
   - Row 16.1 stores `dividend_total` from `_dividend_base`. For each payment it follows
     `matched_credit_ids` to the accrual entry and grosses up by the negative-percent or withholding
     tax on that entry's debit line. Unmatched payments count at face value and raise `dividend_unmatched`.
3. `_compute_representation`: row 20 = year-to-date balance − limit − row 20 of `_earlier_confirmed()`.
   The limit is 1% of max(last year's income, expenses) from `_last_year_totals`; in the founding year,
   1% of this year's expenses.
4. `_compute_market_price_rows`: product lines of invoices, bills and receipts with
   `gec_cit_market_value > 0`; status `exempt` → 16.4.x, related non-enterprise → 16.3.x.
5. `_compute_recoveries`:
   - Rebuilds this declaration's `rs.cit.taxed.item` from the items of `RECOVERY_ROWS`.
   - Gathers the items that `_counts_for` this declaration: its own, plus those of the latest confirmed
     version of each earlier month.
   - Allocates the month's credits on the same account and commercial partner, oldest item first, up to
     `_available_for`.
   - Writes `rs.cit.recovery` rows (annex 1.2) and rows 27.1 / 27.2.
6. `_compute_balance_annexes`: annex 2 in March (balances at last year end by `gec_cit_balance_group`);
   annex 3 lines rebuilt (revaluation = items in the company's exchange difference journal).
7. `_compute_formulas`:
   - First `_annex_amounts`: line 16.1 split by status, 16.1.3 from annex 1.6, 25.1 / 25.3 capped by
     the tax on 16.1.1 / 16.1.2, and 27.4 from annex 1.5.
   - Then `FORMULAS` once per column, with 15% for column 2 and `col3_rate` for column 3.

Typing an `amount_adjust` / `amount3_adjust`, a field in `ANNEX_FIELDS`, or an annex line (other than
annex 3) reruns only `_compute_formulas`.

## Confirm, back to draft, correct

- `action_confirm`: recalculates, sets `confirmed`, then `_post_tax_entry`.
  - `_post_tax_entry` runs only with `gec_cit_post_entry`.
  - Amount = `booking_amount` − `booked_amount` of the other confirmed versions of the month.
    `booking_amount` = payable − refund − dividend tax (tax on 16.1 less row 25, per column), because
    the CIT wizard books the dividend tax.
  - The entry is Dr expense / Cr payable, swapped when negative.
- `action_draft`:
  - Refuses a version superseded by a confirmed later one.
  - Refuses when other confirmed declarations hold recoveries on its taxed items.
  - Otherwise reverses `move_id` with `_reverse_moves(cancel=True)`.
- `action_create_correction`:
  - Refuses while the latest version of the month is a draft.
  - Copies the record with `version + 1` and the Part I snapshot; `annex_line_ids` copies the typed annex rows.
  - Copies the adjustments by row code, rebuilds annex 3 and recalculates.
- `_is_latest_confirmed` defines which version counts for "already declared" (rows 19, 20, annex 1.7
  via `_earlier_confirmed`) and for the register.

## Data

- `rs.cit.cell.csv` is not `noupdate`: an upgrade rewrites the row texts, kinds and measures. The
  `UNIQUE(code)` constraint keeps one record per row.
- `_gec_cit_seed_cells` only fills empty values: account rows, balance groups, journal, expense account
  910010 and payable account 331110. It never overwrites a choice. It runs on install/upgrade (data
  file) and when a company loads the `ge` chart.
- No country is marked preferential by data.

## Guards and invariants

| Guard | Where |
|---|---|
| Confirmed declaration: no field changes except `state`, `move_id`, `booked_amount` | `RsCitDeclaration.write` |
| Confirmed declaration: no adjustments, no annex line changes, no recalculation | `RsCitDeclarationLine.write`, `RsCitAnnexLine._check_draft`, `_check_draft` |
| One declaration per company, month, version; one line per row; unique row code | `models.Constraint` on each model |
| `date_from` is always the 1st of the month | `create`, `write` |
| Accounts and lines cannot choose market or register rows | `domain` on both `gec_cit_cell_id` fields |
| Formula order: a row is computed after the rows it uses | order of `FORMULAS` |

## Security

| Model | Group | Rights | Rule domain |
|---|---|---|---|
| `rs.cit.cell` | Internal user / Accounting administrator | read / all | — |
| `rs.cit.declaration`, `rs.cit.declaration.line`, `rs.cit.taxed.item`, `rs.cit.recovery`, `rs.cit.annex.line` | Accounting read-only / Accounting user | read / all | `[('company_id', 'in', company_ids)]` |

**Back to Draft** is limited to `account.group_account_manager` in the view. No `sudo()` is used.

## Integration

- `gec_localization` CIT wizard: the 16.1 gross-up relies on its entry: a debit line carrying the
  withholding tax, and the net credited to the payable account. Changing that entry changes 16.1.
- Accounts are found by `ge_account_*` template xmlids; a renamed xmlid silently drops a default.

## Tests

```bash
odoo-bin -d <db> -u gec_profit_tax_report --test-enable --test-tags /gec_profit_tax_report --stop-after-init
```

`tests/test_profit_tax.py` covers:
- dividend withholding add-back and the enterprise exclusion;
- representation and charity limits (example 4);
- market price (example 2);
- a loan taxed and recovered, with the draft guard;
- the international company (example 7);
- the annex 1 cap;
- a correction posting the difference;
- part IV;
- the confirmed lock.

## Extending safely

- Add a form row in the csv and, if it is a formula, in `FORMULAS` after the rows it uses. Every code
  a formula reads must exist in the csv.
- A new contact rule goes in `_cit_partner_row` and must keep the principle: a row chosen on the line
  always counts.
- A new automatic row writes through `_auto_vals`, so column 3 statuses keep working.
- Anything "already declared this year" reads `_earlier_confirmed`, never all confirmed declarations, or
  corrections double count.
- Do not book the dividend tax here: the CIT wizard does it.

## Known limitations

- Line 23 = (21 − 22) / (1 − rate) is an interpretation not yet confirmed with rs.ge.
- `COL3_RATES['research']` (10%) and putting research companies in `COL3_ONLY` are not confirmed.
- How the rs.ge e-form records the special statuses is not known; they are not exported in part I.
- The register matches returns by account and commercial partner only; a returned amount on another
  account is not seen.
- A correction confirmed after later months were confirmed leaves those months' recoveries pointing at
  the older version's taxed items until they are recalculated.
- No rs.ge upload format: the XLSX is for reading and typing.
- No Georgian translation file yet.
