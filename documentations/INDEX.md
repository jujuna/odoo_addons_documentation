# Documentation Index

> Internal knowledge base for the Odoo 20 project, built from the 20.0 source in `../addons/`, `../enterprise/` and
> `../custom_addons/`. Every fact links to the source line it comes from.
> Odoo 19 versions of every file stay on the `19.0` branch of this repo: `git -C documentations show 19.0:<file>`.

## How to use

- Start with the module's doc before reading code. One file covers one module or one cross-module topic.
- **Status** says how far a file can be trusted on 20.0:
  - **20** (date): checked against the 20.0 source on that date; no Odoo 19 content.
  - **20 + 19 notes** (date): checked against 20.0 on that date, but it still carries Odoo 19 comparisons, and its line
    links may have drifted since the source was pulled.
  - **19**: written for Odoo 19 and not reviewed for 20. Verify before relying on it.
- New and updated docs follow [`doc-template.md`](../.claude/skills/odoo-dev/references/doc-template.md). Add or update the
  row here in the same change.
- Check a doc's source links with `python3 .claude/skills/odoo-dev/scripts/doc_link_check.py documentations/<file>.md`
  (run from the project root). It reports missing files, modules deleted in 20.0, lines past the end of a file, and links
  whose target line no longer holds the named symbol.
- Verified Odoo 19 to 20 code changes live in [`v20-changes.md`](../.claude/skills/odoo-dev/references/v20-changes.md),
  not in these docs.

---

## Accounting

| Topic | File | What it covers | Status |
|---|---|---|---|
| Chart of accounts | [`accounting_coa.md`](accounting_coa.md) | Account types, the `parent_id` tree (no account groups), `compute_sql` fields, company-dependent codes, tags, opening balances, chart template loading, company-level defaults, the category-account cascade, inventory variation closing in core `account`. | 20 (2026-09-24) |
| Taxes | [`taxes.md`](taxes.md) | The `account.tax` engine: computation types, price-included taxes, repartition lines and tax grids, tax groups and totals, fiscal positions, product and company defaults, cash basis, tax closing, reports, sale/purchase/POS flows, FAQ. | 20 + 19 notes (2026-09-22, cleanup started 2026-09-24; sales-order tax recompute corrected 2026-10-02) |
| Taxes quick guide | [`taxes_quick_guide.md`](taxes_quick_guide.md) | Short version for sales order, purchase order, invoice, bill and journal entry lines: how a line gets its taxes (product, our contact default, fiscal position rules), what prod1's Georgian positions do to `18%`, how base/tax/total are computed with worked numbers (included vs excluded, formulas, tax on tax, rounding), how taxes become journal items and tags (prod1 bills), when Odoo re-proposes taxes, why `S00010` shows 0%, troubleshooting order. | 20 (2026-10-02) |
| Tax, account and move constraints | [`odoo_tax_account_constraints.md`](odoo_tax_account_constraints.md) | 158 validations that can block chart loading, tax saving or posting, each with trigger, error text, source line and how to avoid it. | 19 |
| Reporting engine | [`accounting_reports.md`](accounting_reports.md) | Report expression engines and formulas, aggregation bounds, currency consolidation, account hierarchy, report lines and columns, snapshots, Balance Sheet and P&L structures, Trial Balance, Interco Comparison, report options. | 20 + 19 notes (2026-09-22) |
| Tax returns and locking | [`account_returns.md`](account_returns.md) | `account.return`: filing cards per period and type, check templates, `action_validate()` posting the closing entry and advancing the tax lock date, reset rules. No Georgian return type is shipped. | 20 (2026-09-24) |
| Fixed assets | [`account_asset.md`](account_asset.md) | `account.asset` + `account.asset.variant` schedules (statutory, other ledgers, gross increases), 4 methods incl. no depreciation, multi-ledger via `account.journal.group`, depreciation models, bill-to-asset creation, pause/sell/dispose, re-evaluation. | 20 (2026-09-24) |
| Deferred expenses and revenue | [`deferred_expenses_revenue.md`](deferred_expenses_revenue.md) | Settings, eligible lines, date entry, calculation methods with worked amounts, on-validation and grouped generation, reports, tax and budget effects, reset rules, cron, troubleshooting. | 20 (2026-09-24) |
| Deferred revenue walkthrough | [`deferred_revenue.md`](deferred_revenue.md) | Customer-side walkthrough, sign logic, grouped example, reading the report, VAT, revenue budgets, credit notes, common mistakes. | 20 (2026-09-24) |
| Analytic accounting | [`analytic_accounting.md`](analytic_accounting.md) | Plans as columns, the distribution JSON, analytic items created at posting, two-way sync, line splitting, applicability scoring, distribution models, balances, settings and menus. | 20 (2026-09-24) |
| `account.analytic.account` model | [`account_analytic_account.md`](account_analytic_account.md) | One plan per account with a per-plan column, non-stored debit/credit/balance, company and plan changes, duplication, security. | 20 (2026-09-24) |
| Analytic budgets | [`analytic_budget.md`](analytic_budget.md) | Budget states and revisions, the Generate wizard, matching rules, budget types, what consumes a budget, purchase commitments and the over-budget warning, theoretical amount, project progress. | 20 (2026-09-24) |
| Fixed costs guide | [`accounting_fixed_costs_guide.md`](accounting_fixed_costs_guide.md) | Account types, parent accounts, tax repartition and tags, reconciliation, lock dates, year-end, payment terms, journal types, analytic distribution, budgets and their vocabulary, budget vs P&L. | 20 + 19 notes (2026-09-22) |
| Companies vs branches | [`accounting_multicompany_branches.md`](accounting_multicompany_branches.md) | Branches vs separate companies, shared vs separate charts, inter-company rules, consolidation, impact on sales/purchase/inventory/invoicing/expenses/payroll, `ir.access` security, pitfalls, decision framework. | 20 + 19 notes (2026-09-22) |
| Currency exchange and transit | [`currency_exchange_transit.md`](currency_exchange_transit.md) | Rate lookup (a rate applies from the next day; NBG rates therefore one day late), exchange accounts, when payments get exchange entries, worked USD/EUR cases, unreconcile, revaluation. | 20 (2026-09-24) |
| One bank, many currencies | [`bank_journal_multicurrency_setup.md`](bank_journal_multicurrency_setup.md) | Bank accounts carrying name and BIC, one journal per currency, shared-IBAN layout, creation paths (online sync, manual, journal form), currency rules, dropdown search, fixing duplicates. | 20 (2026-09-24) |
| Off-balance sheet | [`off_balance_sheet.md`](off_balance_sheet.md) | Isolation rules (no mixing, no taxes, no reconciliation), where the type can be selected, reports (Trial Balance yes, Balance Sheet no), Georgian 9900xx accounts, scenarios. | 20 (2026-09-24) |
| Equity (cap table, UBO) | [`equity.md`](equity.md) | Transactions, security classes, the cap table SQL view (ownership, voting, dilution), valuations, UBO, portal; not linked to the ledger. | 20 (2026-09-24) |

## Georgian localization, rs.ge and banks

| Topic | File | What it covers | Status |
|---|---|---|---|
| Georgian accounting localization | [`l10n_ge.md`](l10n_ge.md) | Core chart `ge` (accounts, 36 VAT taxes, 4 fiscal positions, VAT Report tags) and our `gec_localization` (extra accounts, 31 taxes incl. 23 withholding, payroll accounts, contact default taxes, Not Taxed, CIT wizard, BIC from IBAN). Tag-to-declaration flow, withholding at payment, three shipped mapping defects, setup checklist. | 20 (2026-09-24) |
| Form 30 withholding declaration | [`gec_income_tax_report.md`](gec_income_tax_report.md) | Annex A from paid payslips, journal entries and vendor bills with a withholding tax (cash basis, part payments by month, In File rows never declared twice), withholding tax proposal from Account Rules, Not Declared lists, annex D cars, annex E self-paying recipients, main part cells 16-69, issue levels, export, design decisions. Tests cover salary and payment rows only. | 20 (2026-11-03) |
| VAT Report (GE) (Georgian) | [`l10n_ge_vat_report.md`](l10n_ge_vat_report.md) | Accountant's guide in plain Georgian: the main rule (the tax on the line decides the declaration line), which actions reach the report (invoice, bill, credit note, advance; not payments), 11 worked cases with debit/credit entries, the full line table with taxes and accounts, the four cases where Odoo picks the wrong tax and the admin fix, four checks (audit, trial balance turnover of the VAT accounts, generic tax report, rs.ge), monthly closing order, limits, test verdict. | 20 (2026-10-02) |
| VAT declaration module (Phase 1) | [`gec_vat_declaration.md`](gec_vat_declaration.md) | The VAT Declaration form for the 5 cell tabs (ა I, ა II, ა III, Part III, III-19⁶): Generate from core's VAT Report, the portal's formulas, computed / proposed / typed cells, Save recomputes, ა III fixed-asset split (column 5 proposed from the "Fixed-asset accounts (VAT declaration)" setting since 2026-11-04), December-only cells, warnings, guards. Built 2026-10-22, commits 4daad73 + 8759c4a (portal-style grid, Georgian). Reverse-charge VAT calculation (annex III-19) for non-VAT-payers: Generate from foreign service bills, cancellation vs correction rules (2026-11-04). Tab 6 (annex ბ III) from uploaded customs PDFs, parsed by text position, optional Documents bridge, added 2026-11-02. Tabs 13 and 14 (petroleum tax invoices, ნსაფ, issued and received) filled by `rs_spec_invoice` at Generate, added 2026-11-07. Drill-down: a search icon beside every number with an Odoo source opens what made it (core Tax Report audit, column 4/5 split, margin, III-19 rows 4/5), padlock tooltips show the portal formula (2026-11-04). Go-live review fixes and corrections booked in the buyer's acceptance month, row 1 net (2026-11-10, e6d09d3 + 440f495). Tabs 10 and 11 (annexes ბ VIII, ბ IX): typed rows, the month filled from the declaration with the typed Portal Number, ბ IX total = Part III cell 10 (2026-11-12). | 2026-11-12 |
| დღგ-ის დეკლარაცია (rs.ge) — accountant guide, complete (Georgian) | [md](gec_vat_declaration_sources.md) · [pdf](pdf/gec_vat_declaration_sources.pdf) | Complete but compact: all 15 notebook tabs (1-8, 10, 11, 13-17) and all 109 cells (32/7/33/24/13), every tab's columns, every annex page's columns, group headers, footer sums, advance sub-grids, the 12 typed Part III cells with meanings, III-19⁶ rows, the 15 typed boxes, warnings, list columns. 3 A4 pages. | 2026-11-12 |
| უკუდაბეგვრის დღგ (rs.ge) — accountant guide, complete (Georgian) | [md](gec_vat_rc_declaration_sources.md) · [pdf](pdf/gec_vat_rc_declaration_sources.pdf) | Complete: form header (title/company/month/type/status/accrued/reduced), both tabs, Part I columns and footer sums, Part II rows 3-9 with the proposed-row mechanism and audit icons, Part III columns and footer sums, Part IV rows, add/open/delete icons, counter, all warnings, list columns. 2 A4 pages. | 2026-11-12 |
| ფორმა 30 — accountant guide, complete (Georgian) | [md](gec_income_tax_report_sources.md) · [pdf](pdf/gec_income_tax_report_sources.pdf) | Complete: header (buttons/status/counters/totals/files), Annex A screen columns + the 14 export columns + 2 controls, Annex D and E columns, every main-part box 16-69 individually with its source and locked/proposed/typed mark (60 rows incl. the info section), Not Declared three lists and their columns, manual-row dialog, explanation workbook, rate matrix pointer, In File rules. 3 A4 pages. | 2026-11-12 |
| rs.ge e-invoice | [`rs_einvoice.md`](rs_einvoice.md) | Sales and purchase flows against rs.ge: statuses and the buttons they unlock, what Check Status triggers, the three Credit Note treatments (correct, cancel and reissue, Odoo-only), cancel of earlier-month or paid invoices, supplier corrections and cancellations, logins per user and company, per-company crons and the dashboard refresh, code layout and offline tests, gotchas. Manual test checklist in `Claude outputs/rs_einvoice_manual_tests.xlsx`; user and developer guides plus `developer_map.html` in the module. Petroleum invoice (ნსაფ) corrections reuse Correct & Reissue through two hooks (2026-11-03). | 20 (2026-09-29; ნსაფ note 2026-11-03) |
| rs.ge e-invoice advances | [`rs_einvoice_down_payments.md`](rs_einvoice_down_payments.md) | Advance invoices and their settlement: net offset vs native rs.ge attach, how the mode is chosen, eligibility, guards, VAT-compliance verdict. | 20 + 19 notes (2026-09-23) |
| rs modules method reference | [`rs_modules_method_reference.md`](rs_modules_method_reference.md) | Per-method reference of `rs_base_methods` + `rs_einvoice`. Written against the old copies (`rs_base`, `gec_rs_invoice`); its paths do not exist in the 20.0 tree. | 19 |
| RS employee registry | [`employee_registry_rs.md`](employee_registry_rs.md) | Employee registry sync with rs.ge: buttons and daily cron, one RS login per legal entity, termination pushes, sync log. | 20 + 19 notes (2026-09-23) |
| rs.ge users, companies and logins | [`rs_multi_company.md`](rs_multi_company.md) | Multi-company analysis of the four rs.ge modules: how a call finds its login today, the A-D cases and ten user/company setups with today/after verdicts, the four design rules (company-dependent credentials, document company, identity check, per-company crons), changes per module with line estimates, cron safety, core-compatibility proof run on a scratch DB, the core account/sale/purchase/stock flows the plan sits on with their company rules, where core keeps external credentials, phases (all four cases A-D approved 2026-09-29: taxpayer id always from the company TIN); appendix classifying all 608 class methods (module-level helpers, field defaults, XML and scripts swept separately); implementation status: phases 1-5 done 2026-09-29 plus the rs_einvoice refactor and the rs.waybill company check, uncommitted, prod1 not upgraded. | 20 (2026-09-29) |
| Basis Bank | [`basis_bank.md`](basis_bank.md) | Transfers and salary/treasury packages with OTP and optional approval, statement import both ways, Paid until the bank confirms then Reconciled (the import reconciles what it confirms), durable send claim, 48-hour check that only flags, journal detection (BIC `CBASGE22` + connection), payroll via `gec_payroll_bank`. | 20 (2026-10-10) |
| Georgian ID card signing | [`id_ge_sign.md`](id_ge_sign.md) | Signing with the Georgian ID card in Odoo Sign: desktop-app hand-off on Sign 20's external-signature flow (no Odoo QES host), PAdES checks, certificate chain required, identity by Tax ID, archived public-link contacts. | 20 (2026-11-12) |
| Georgian translations of industry packages | [`gec_i18n_industries.md`](gec_i18n_industries.md) | How our Georgian reaches the industry packages imported from Apps > Industries: one file per package, links matched to this database's ids, the "Start here!" article re-rendered, demo bookings no longer linked to the Apps screen, POS category paths in the user's language (`gec_i18n_pos_category`), the settings button, and what still needs a manual rename. | 20 (2026-10-21) |

## Inventory and manufacturing

| Topic | File | What it covers | Status |
|---|---|---|---|
| Inventory | [`inventory.md`](inventory.md) | Warehouses and locations, routes and rules, multi-step flows, SO to delivery, reservation and removal, backorders, returns and portal returns, scrap moves, lots, packages, putaway, replenishment, batches and waves, secondary-location pattern, security, settings. | 20 (2026-09-24) |
| Forecasted report | [`inventory_forecast_report.md`](inventory_forecast_report.md) | Header quantities and lead time, the graph view, matching demand to reserved, free and transit stock or receipts, table actions, the availability badge, module extensions. | 20 (2026-09-24) |
| Stock valuation | [`stock_valuation.md`](stock_valuation.md) | Standard/FIFO/AVCO, Anglo-Saxon vs continental, periodic vs perpetual (configured in `account`), COGS, price differences, landed costs, lot valuation, dropship and returns, closing, walkthroughs. | 20 + 19 notes (2026-09-22); journal-entry, Anglo-Saxon and account passages corrected 2026-09-25; menu path fixed 2026-09-28 |
| Transfers and their corrections | [`stock_transfers_corrections.md`](stock_transfers_corrections.md) | How receipts, deliveries and returns link to sales, purchase, valuation and accounting; states and locking; what every correction (unlock and edit, lot/location change, added lines, returns, exchange, cancels, SO/PO edits, backdating, late bills) changes in each app; invoicing and closing consequences; lock-date limits; `rs_waybill` interplay; 39 live scenarios. Receipts and deliveries post no stock entry in 20. | 20 (2026-09-25) |
| Manufacturing and maintenance | [`mrp.md`](mrp.md) | BoMs (kits, batch size, continuous production), MO states, consumption warning, backorders, work orders, planning, procurement MOs, scrap and unbuild, costing, Shop Floor, quality checks, maintenance requests, MTBF/MTTR. | 20 (2026-09-24) |

## HR, time off and attendance

| Topic | File | What it covers | Status |
|---|---|---|---|
| Employees and versions | [`hr_employee_versions.md`](hr_employee_versions.md) | Employee as a timeline of `hr.version`: version in force, contract dates, templates, calendar and timezone on the version, departure, the payroll "Version update" dialog. | 20 + 19 notes (2026-09-22, dialog 2026-09-24) |
| HR access rights | [`hr_access_rights.md`](hr_access_rights.md) | Who sees what: `ir.access` layers, the six different managers, what a plain user reaches, officer vs administrator, payroll access levels, a diagnosis ladder. | 20 + 19 notes (2026-09-22) |
| Time off | [`hr_holidays.md`](hr_holidays.md) | Leaves, allocations, approvals, time-off types as work entry types, public holiday loading, payroll interaction, crons, security. | 20 + 19 notes (2026-09-22, cleanup started 2026-09-24) |
| Accrual plans | [`hr_holidays_accrual_plans.md`](hr_holidays_accrual_plans.md) | Plans and milestones, the accrual engine, carry-over (and when it wipes the balance), backdating, caps, batch allocation. | 20 + 19 notes (2026-09-22) |
| Time off units | [`hr_holidays_time_off_units.md`](hr_holidays_time_off_units.md) | Unit of measure vs request unit, per-request durations, hours-to-days conversion. | 20 + 19 notes (2026-09-22) |
| Public holidays | [`public_holidays_flow.md`](public_holidays_flow.md) | Manual entry, loader wizard and cron (no Georgian data), leave re-evaluation, time rules, timesheets, payslip hours and pricing, the GROSS trap, overtime on holidays, Georgian checklist, the country-only time type trap. | 20 (2026-09-24) |
| Resource calendars | [`resource_calendars.md`](resource_calendars.md) | Fixed / Variable / Undefined calendars, flexible hours, `hours_per_day`, half days, calendar leaves, timezone on the version, the interval engine and who calls it. | 20 (2026-09-24) |
| Attendance and payroll | [`attendance_work_entry.md`](attendance_work_entry.md) | Clock records, validation modes, time rules and crons, attendance-based vs schedule-based pay, payroll warnings, settings, Georgian overtime recipe, access. | 20 (2026-09-24) |
| Work entries and time rules | [`work_entries.md`](work_entries.md) | Work entries as values computed at payslip time, `hr.time.rule` reclassifying attendances and leaves, work entry types, payslip consumption, security. | 20 + 19 notes (2026-09-22) |
| Timesheets, validation and locks | [`timesheets.md`](timesheets.md) | Timesheet lines as analytic lines, creation paths incl. the Timesheets Assistant, validation and locks, costs, payroll use. | 20 + 19 notes (2026-09-22) |
| Timesheets and analytic lines | [`hr_timesheet.md`](hr_timesheet.md) | Timesheet costing, the analytic profitability classification, project reporting. | 20 + 19 notes (2026-09-22) |
| Appraisals | [`hr_appraisal.md`](hr_appraisal.md) | States, creation paths, sharing, the Done lock, bulk actions. | 20 + 19 notes (2026-09-22) |
| Job positions | [`hr_job_positions.md`](hr_job_positions.md) | Job department vs employee department, duplicate names, recruitment links. | 20 + 19 notes (2026-09-22) |
| Recruitment sourcing | [`hr_recruitment_sourcing.md`](hr_recruitment_sourcing.md) | Source, medium and campaign on applicants, tracker URLs. | 20 + 19 notes (2026-09-22) |
| Alta HR customization | [`hr_customization.md`](hr_customization.md) | Offer Accept/Reject on locked terms, contract and trial expiry cron, team-leader access to versions, payslips and attendances, timesheet change history, welcome mail. | 20 (2026-11-07) |

## Payroll

| Topic | File | What it covers | Status |
|---|---|---|---|
| Payroll core | [`hr_payroll.md`](hr_payroll.md) | Payslips and pay runs: states and blockers, warnings, worked days, salary rules and inputs, refunds and corrections, accounting and payment, integrations, crons, symptom-to-cause appendix. | 20 + 19 notes (2026-09-22) |
| Payroll accounting | [`hr_payroll_account.md`](hr_payroll_account.md) | Payslip to journal entry: validation, move construction and line merging, batch mode, entry preview, warnings. | 20 + 19 notes (2026-09-22) |
| Paying payslips | [`payroll_payment_flow.md`](payroll_payment_flow.md) | Stock Pay and Mark as Paid, payment register rules, our net-payable layout on `l10n_ge`, Pay Salaries batches with Basis Bank, `geo_payroll` Register Payment, checklist. | 20 (2026-10-10) |
| Wage types | [`payroll_wage_types.md`](payroll_wage_types.md) | Fixed and hourly pricing (wage over the calendar's hours in the period), where worked time comes from, scheme matrix, the daily-rate pattern, combinations, `geo_payroll` schemes. | 20 (2026-09-24) |
| Georgian payroll (`geo_payroll`) | [`geo_payroll.md`](geo_payroll.md) | Pay schemes, work logs, Georgian income tax and pension, benefits, register payment, payslip header, troubleshooting. Updated for 20 section by section by the payroll sessions; section 13 (multi-version slip refresh, Add Payslip to Pay Run) 2026-10-31. | partly 20 |

## Point of Sale

| Topic | File | What it covers | Status |
|---|---|---|---|
| Wolt marketplace orders (`pos_platform_order_wolt`) | [`pos_platform_order_wolt.md`](pos_platform_order_wolt.md) | Wolt as a `pos_platform_order` provider: provider and store setup, Connect to Wolt (SSIO), signed webhook, accept / reject / food ready / delivered, payment and session close, preorders, the 5-minute cron (queued orders, unpaid orders, item pushes, token keep-alive), menu sync, venue actions. | 20 (2026-10-31) |
| Wolt Drive couriers (`pos_wolt_drive`) | [`pos_wolt_drive.md`](pos_wolt_drive.md) | Book a Wolt courier for a paid POS order: settings and webhook registration, quote (price, ETA), booking and retries, cancel before pickup, signed status events, relink of a rolled-back booking. | 20 (2026-10-31) |

## Platform

| Topic | File | What it covers | Status |
|---|---|---|---|
| Mail | [`mail_configuration.md`](mail_configuration.md) | Alias domains, outgoing servers and From resolution, personal servers, the queue, incoming servers, routing, aliases, bounces and blacklist, notifications, system parameters, troubleshooting. | 20 (2026-09-24) |
| Microsoft Entra ID login | [`azure_entra_sso.md`](azure_entra_sso.md) | Entra ID through `auth_oauth` (implicit flow): provider values, the authorization header parameter, user linking, sign-up default, error meanings, session timeouts, LDAP alternative. | 20 (2026-09-24) |
| Signify e-signature | [`signify.md`](signify.md) | Send a record's PDF/DOC for signing by email, SMS or link (basic, SMS code, Georgian ID card/stamp, remote ID, pad), send order with share last, 15-minute status polling, signed copy to the linked record, evidence on the document, chatter "Send with Signify" button for PDFs, protected sync fields. | 20 (built 2026-10-29, on prod1 since 2026-10-31; review fixes 2026-11-06) |
| Signify - Documents | [`signify_documents.md`](signify_documents.md) | Auto-installed bridge: signed files and evidence reports filed in a per-company Documents folder (documents.mixin, same attachment), "Send with Signify" embedded action on PDF/Word documents. | 20 (built 2026-11-06) |
| AI | [`ai_module.md`](ai_module.md) | Odoo AI through IAP (no own API keys): agents, skills, tools, async sessions, AI server actions and fields, RAG with pgvector, the `ai_mcp` server, module map. | 20 (2026-09-24) |
| Dashboards | [`board_dashboard.md`](board_dashboard.md) | My Dashboard boards and spreadsheet dashboards: pinning, layouts, shipping a board, sections, publication, sample data, editing, access, share links. | 20 (2026-09-24) |

## Plans, tests and reference material

Plans, handoffs, work logs, manual test guides, the certification exam, the accounting data-loading tutorial, VAT
research notes and the Georgian legal texts live in [`../dev_notes/`](../dev_notes/INDEX.md), outside this folder.

## Module READMEs

Each custom module keeps a user guide (`README.md`) and a developer guide (`README_DEV.md`) in its own folder. These were not
part of the 2026-09-24 review; some still mention Odoo 19 (noted below).

| Module | User guide | Developer guide |
|---|---|---|
| `gec_localization` | [`README.md`](../custom_addons/gec_odoo_modules/gec_localization/README.md) | [`README_DEV.md`](../custom_addons/gec_odoo_modules/gec_localization/README_DEV.md), wiring map [`developer_map.html`](../custom_addons/gec_odoo_modules/gec_localization/developer_map.html) |
| `geo_payroll` | [`README.md`](../custom_addons/gec_odoo_modules/geo_payroll/README.md) | [`README_DEV.md`](../custom_addons/gec_odoo_modules/geo_payroll/README_DEV.md) |
| `gec_payroll_bank` | [`README.md`](../custom_addons/gec_odoo_modules/gec_payroll_bank/README.md) (still says 19.0) | [`README_DEV.md`](../custom_addons/gec_odoo_modules/gec_payroll_bank/README_DEV.md) |
| `basis_bank` | [`README.md`](../custom_addons/gec_odoo_modules/basis_bank/README.md) | [`README_DEV.md`](../custom_addons/gec_odoo_modules/basis_bank/README_DEV.md), backlog [`KNOWN_ISSUES.md`](../custom_addons/gec_odoo_modules/basis_bank/KNOWN_ISSUES.md), wiring map [`developer_map.html`](../custom_addons/gec_odoo_modules/basis_bank/developer_map.html) |
| `gec_income_tax_report` | [`README.md`](../custom_addons/gec_odoo_modules/gec_income_tax_report/README.md) | [`README_DEV.md`](../custom_addons/gec_odoo_modules/gec_income_tax_report/README_DEV.md), wiring map [`developer_map.html`](../custom_addons/gec_odoo_modules/gec_income_tax_report/developer_map.html) |

## Files outside this folder

| File | What it is |
|---|---|
| [`../basisbank_api.md`](../basisbank_api.md) | Basis Bank API reference (the bank's spec; not tied to an Odoo version). |
| [`../eapi_rs.md`](../eapi_rs.md) | rs.ge e-invoice REST API specification (Georgian). |
| [`../sashemosavlo_deklaraciebi_sruli_cnobari.md`](../sashemosavlo_deklaraciebi_sruli_cnobari.md) | Income declarations domain reference (Georgian). |
| [`../rs_einvoice_method_reference.md`](../rs_einvoice_method_reference.md), [`../rs_einvoice_method_reference_2026-06-08.md`](../rs_einvoice_method_reference_2026-06-08.md) | Odoo 19 method references of the old `gec_rs_invoice` copy of `rs_einvoice`; not maintained. |