# Payroll

> **Core module:** `hr_payroll` | **Path:** [`enterprise/hr_payroll/`](../enterprise/hr_payroll/)
> **Accounting bridge:** `hr_payroll_account` | **Path:** [`enterprise/hr_payroll_account/`](../enterprise/hr_payroll_account/)
> **Odoo Apps category:** HR / Payroll
> **Verified against Odoo 20 source:** 2026-09-22. Odoo 20 removed the `hr.work.entry` record model and merged `hr_payroll_holidays`, `hr_work_entry_holidays` and several bridges into `hr_payroll` / `hr_work_entry` — see [What Changed in Odoo 20](#what-changed-in-odoo-20) before trusting any v19 knowledge. Public-holiday lifecycle: [`public_holidays_flow.md`](public_holidays_flow.md).

## What It Does

Payroll computes employee payslips by running salary rules against an employee record (`hr.version`), worked days, and salary inputs. The result is a set of payslip lines such as `BASIC`, `GROSS`, `NET`, deductions, reimbursements, and country-specific payroll lines.

Two things gate every payslip and are the source of most real-world blockers:

1. **Worked days** — work entries are no longer records. They are recomputed in memory from the calendar, time off and attendances every time worked-day lines are built ([`_compute_worked_days_line_ids`, hr_payslip.py:2162](../enterprise/hr_payroll/models/hr_payslip.py#L2162)). Nothing is validated or locked, so a late change to the calendar or to a leave silently changes a draft payslip.
2. **Payroll warnings** — `hr.payroll.warning` records are evaluated per payslip into the `issues` JSON field. A `danger` warning raises `error_count`, which blocks confirmation and payment; a warning flagged **Block Payslips** blocks confirmation even when it sits on the employee rather than the slip ([`action_payslip_done`, hr_payslip.py:980](../enterprise/hr_payroll/models/hr_payslip.py#L980)).

The base payroll module does **not** create accounting entries by itself. Journal entries are added by `hr_payroll_account`, and actual bank/payment records are still handled by Accounting's normal payment flow.

---

## Executive Summary

### Main objects

| Object | Model | Role |
|---|---|---|
| Pay Run | `hr.payslip.run` | Batch/container for many payslips in one period. State is computed from its slips and its selected versions. |
| Payslip | `hr.payslip` | Real payroll document for one employee/version/period. |
| Payslip line | `hr.payslip.line` | One computed result of a salary rule (`BASIC`, `NET`, …); source of journal items. |
| Employee Record / Contract Version | `hr.version` | The contract object payroll reads (it replaced `hr.contract` in 19 and is unchanged in 20). Holds wage, structure type, schedule, calendar, contract dates, `payroll_properties`. |
| Work entry values | *(no model)* | Transient dicts (`date`, `duration`, `work_entry_type_id`, `version_id`, …) produced on demand by `hr.version.generate_work_entries()`. **`hr.work.entry` no longer exists** ([hr_version.py:303](../addons/hr_work_entry/models/hr_version.py#L303)). |
| Worked Days | `hr.payslip.worked_days` | Those values aggregated by (work entry type, category options) for the payslip period. |
| Time Rule | `hr.time.rule` | Converts attendance/leave time above or below a threshold into a different work entry type (overtime, undertime, premium pay) — [hr_time_rule.py:111](../addons/hr_work_entry/models/hr_time_rule.py#L111). |
| Structure Type | `hr.payroll.structure.type` | Defines wage type, default schedule, default time type, and default structure. |
| Salary Structure | `hr.payroll.structure` | The salary rules + employee types + payslip report + version property definition. With accounting, also the Salary Journal. |
| Salary Rule | `hr.salary.rule` | One computation step, and — when flagged — the definition of a payslip input. With accounting, can also define debit/credit accounts. |
| Other Inputs | `hr.payslip.input` | Manual/automatic numeric values used by rules, keyed by **salary rule**, not by an input type. |
| Salary Adjustment | `hr.salary.attachment` | Recurring/limited deduction that auto-injects input lines (garnishments, child support, loans). |
| Time Off | `hr.leave` | A leave; `hr_payroll` adds `payslip_state` (normal/done/blocked) and an `issues` field. |
| Payroll Warning | `hr.payroll.warning` | Configurable domain/Python check rendered on the dashboard and/or on employee, version, payslip and time-off records. |
| Journal Entry | `account.move` | Created only by `hr_payroll_account` during confirmation when a Salary Journal exists. Always **draft**. |

### End-to-end flow

```text
Configure structure type / structure / salary rules (+ accounts if accounting)
    |
Start a pay run: pick period + structure (+ employee types)   --> state 00_draft
    |   pre-flight warnings: employees to review / time off to review / no time off
    |
Open the run  -->  _generate_payslips(): one slip per selected version, then compute_sheet()
    |               worked-day lines are rebuilt from freshly generated work-entry VALUES
    |               input lines come from salary attachments + version payroll properties
    |
Validate payslip / pay run (action_payslip_done)
    |   - requires group Payroll / Officer
    |   - blocked by error_count and by any "Block Payslips" warning
    |   - state = validated
    |   - accounting bridge: create DRAFT account.move if the structure has a Salary Journal
    |
Pay (action_payslip_payment_report)  -->  wizard: Manually / CSV / SEPA / Swiss
    |   - Mark as Paid  -> state = paid (+ paid_date), salary attachments recorded
    |   - Download only -> file + paid_date, state stays validated
    |
(accounting path) post the journal entry, then Register Payment + reconcile
    |
state = paid  (only if all move-line residuals are zero)
```

### State vs money — what each step actually does

| Step | Payslip state | Accounting state | Money moved? |
|---|---|---|---|
| Compute | `draft` | none | No |
| Validate | `validated` | optional **draft** `account.move` | No |
| Post journal entry | `validated` | **posted** `account.move` | No |
| Register payment + full reconciliation | `paid` | `account.payment` reconciled | Yes |
| Pay wizard → **Mark as Paid** (any mode, including "Manually") | `paid` | may be none | No |
| Pay wizard → **Download** only (CSV/SEPA/Swiss) | stays `validated`, `paid_date` set | none | bank file only |

> **Important:** the stored `state` is not the whole story. A payslip also has a computed `state_display` that overrides the badge with **Blocked** or **Warning** when it has unresolved issues, and an `error_count` that hard-blocks validation and payment. See [Statuses, Errors & Warnings](#statuses-errors--warnings).

---

## Module Map

Odoo 20 collapsed most of the v19 bridge layer. **Community (`addons/`)** provides the work-entry value engine and time rules; **Enterprise (`enterprise/`)** provides payroll itself and the few remaining bridges.

### Core / required

| Module | Layer | Why |
|---|---|---|
| `hr_work_entry` | community | Generates work-entry **values** from calendars, leaves and attendances; hosts `hr.work.entry.type` and `hr.time.rule`. Depends only on `hr`. |
| `hr_holidays` | community | Owns leave → work-entry-value mapping (`work_entry_type_id` on the leave), and now depends on `hr_work_entry` directly. |
| `hr_holidays_attendance` | community, `auto_install` | Makes attendance-based versions produce their work-entry values from `hr.attendance`. |
| `hr_payroll` | enterprise | The payslip/pay-run/structure/rule engine, salary attachments, payroll warnings, dashboard, declarations, PDF cron, **and** the time-off deferral logic that used to live in `hr_payroll_holidays`. |

`hr_payroll`'s own manifest declares only `mail`, `html_editor` and `hr_holidays_gantt` ([`__manifest__.py`](../enterprise/hr_payroll/__manifest__.py)); `hr_work_entry` arrives through `hr_holidays`.

> **Removed in Odoo 20 — do not look for them:** `hr_work_entry_holidays`, `hr_work_entry_holidays_enterprise`, `hr_work_entry_enterprise`, `hr_work_entry_attendance`, `hr_work_entry_planning`, `hr_payroll_holidays`, `hr_payroll_planning`, `hr_payroll_sale_commission`, `hr_contract_salary_payroll`, `hr_contract_salary_holidays`. Some leave an empty directory with stale `__pycache__` in this checkout; none has a `__manifest__.py`.

### Where worked days come from

There is no `work_entry_source` selection any more. The switch is the boolean `hr.version.attendance_based` ([hr_version.py:10](../addons/hr_attendance/models/hr_version.py#L10)), read through `has_static_work_entries()`:

| `has_static_work_entries()` | Defined in | Source of hours |
|---|---|---|
| `True` (default) | [hr_version.py:297](../addons/hr_work_entry/models/hr_version.py#L297) | the version's working schedule, minus/plus `hr.leave` |
| `False` (`attendance_based`) | [hr_version.py:15](../addons/hr_holidays_attendance/models/hr_version.py#L15) | validated `hr.attendance` records, plus working-time leaves |

On top of either source, `hr.time.rule` records reshape the result (overtime above a threshold, undertime below it, premium pay categories).

### Accounting & payment modules

| Module | What it enables |
|---|---|
| `hr_payroll_account` | Salary journals, salary-rule debit/credit accounts, draft journal-entry creation, batching, register-payment grouping. Now `auto_install` with `hr_payroll` + `accountant`. |
| `hr_payroll_account_iso20022` | SEPA / Swiss ISO20022 bank-file export (`batch_booking`), IBAN and payment-method checks. |
| `project_hr_payroll_account` | A project smart button counting contracts by analytic account. Does **not** change move generation. |

### Input / enrichment integrations

| Module | Injects | Via |
|---|---|---|
| `hr_payroll_attendance` | attendance stat button on the payslip, attendance-discrepancy warning, premium-pay options on attendances, time-rule attendance output | attendance pipeline + `hr.time.rule` |
| `hr_payroll_expense` | one expense input line + reconciled move | `_compute_input_line_ids` override |
| `hr_payroll_fleet` | **nothing** to payslips — `can_be_requested` / `default_car_value` on `fleet.vehicle.model` for the configurator, plus one dashboard warning | [fleet.py](../enterprise/hr_payroll_fleet/models/fleet.py) |
| `spreadsheet_dashboard_hr_payroll` | payroll spreadsheet dashboard | — |

### Configurator & documents

| Module | Role |
|---|---|
| `hr_contract_salary` | Salary-package offer + web configurator that produces the `hr.version` payroll computes against. The benefit model itself (`hr.contract.salary.benefit`) now ships **inside `hr_payroll`** ([hr_contract_salary_benefit.py](../enterprise/hr_payroll/models/hr_contract_salary_benefit.py)). |
| `documents_hr_payroll` | Files payslip/declaration PDFs into Documents; `Send By Email` action. |
| Localization payroll modules (`l10n_*_hr_payroll[_account]`) | Country structures, rules, rate tables (`hr.rule.parameter`), declarations, payment formats, and most of the shipped payroll warnings. |

---

## Pay Run (`hr.payslip.run`)

Source: [`models/hr_payslip_run.py`](../enterprise/hr_payroll/models/hr_payslip_run.py)

A pay run is a batch wrapper around payslips. It does not compute salaries itself. It holds a set of employee **versions** (`version_ids`), creates one payslip per version, and delegates computation/validation/payment to those payslips. **Its state is computed from the versions and the slips — you never write it directly.**

### Core fields

| Field | Purpose |
|---|---|
| `name` | Generated from period, structure and employee types when absent. See `_get_name_for_period()` at [`hr_payslip_run.py:87`](../enterprise/hr_payroll/models/hr_payslip_run.py#L87). |
| `version_ids` | The employee versions in the run. Stored m2m, computed from `_get_valid_versions()` while the run is empty, then kept in sync with the slips ([`:182`](../enterprise/hr_payroll/models/hr_payslip_run.py#L182)). |
| `slip_ids` | One2many to `hr.payslip`; the actual payroll documents. |
| `state` | `store=True compute='_compute_state'` from `version_ids` + `slip_ids.state`. See [`hr_payslip_run.py:216`](../enterprise/hr_payroll/models/hr_payslip_run.py#L216). |
| `date_start`, `date_end` | Period covered. `date_start` continues from the **last closed run** of the same structure and company (its `date_end` + 1 day), falling back to the current period of the structure type's schedule; `date_end` = `date_start` + the schedule timedelta ([`:238`](../enterprise/hr_payroll/models/hr_payslip_run.py#L238), [`:265`](../enterprise/hr_payroll/models/hr_payslip_run.py#L265)). |
| `structure_id` | **Required** salary structure for the batch; its `type_id` is what filters candidate versions. |
| `employee_type_ids` | Optional `hr.employee.type` filter, intersected with the structure's own `employee_type_ids` ([`:151`](../enterprise/hr_payroll/models/hr_payslip_run.py#L151)). |
| `payment_report*` | Generated bank-file metadata. Not an accounting payment. The run also carries `payment_report_format`. |
| `move_id` | (accounting) Set **only in batched mode** — one move per (journal, date) for the whole run ([`hr_payslip.py:118`](../enterprise/hr_payroll_account/models/hr_payslip.py#L118)). |

`schedule_pay` is no longer a field on the run.

### Pay run states

Source: [`_compute_state()`](../enterprise/hr_payroll/models/hr_payslip_run.py#L216) — **five** states in Odoo 20, `00_draft` is new.

| State | Label | Computed when (priority order) |
|---|---|---|
| `00_draft` | Draft | At least one selected version has **no payslip yet** — the run exists but payslips were never generated. |
| `01_ready` | Ready | Every version has a slip and any slip is still `draft`. |
| `02_close` | Done | No draft slips and at least one slip is `validated`. |
| `03_paid` | Paid | No draft/validated slips and at least one slip is `paid`. |
| `04_cancel` | Cancelled | **All** linked payslips are `cancel`. |

> The priority matters twice. Adding an employee to a closed run pushes it back to `00_draft` (a version now has no slip). And **one remaining draft slip keeps the whole run at `01_ready`**, even if every other slip is validated.

### Run-level diagnostic counters

These drive the kanban and the "review issues" workflow:

| Field | Meaning | Source |
|---|---|---|
| `payslips_with_warnings` | **sum of `warning_count`** over the run's slips (not a slip count) | [`hr_payslip_run.py:288`](../enterprise/hr_payroll/models/hr_payslip_run.py#L288) |
| `payslips_with_errors` | **sum of `error_count`** over the run's slips | [`:288`](../enterprise/hr_payroll/models/hr_payslip_run.py#L288) |
| `empty_payslips` | count of slips with no `line_ids`; drives Compute-vs-Validate | [`:294`](../enterprise/hr_payroll/models/hr_payslip_run.py#L294) |
| `employee_count` | distinct employees behind `version_ids` (raw SQL) | [`:199`](../enterprise/hr_payroll/models/hr_payslip_run.py#L199) |
| `action_review_issues` | opens the run's slips pre-filtered to **Has Issues** | [`:571`](../enterprise/hr_payroll/models/hr_payslip_run.py#L571) |

The v19 fields `payslips_with_issues` and `has_error` no longer exist.

### Pay run actions

| UI / method | Effect | Blocking condition |
|---|---|---|
| Open the run (kanban click) | `action_open_payslips()` — if `state == '00_draft'`, calls `_generate_payslips()` first | no version → UserError *"You must have employee records in the payrun to generate payslip(s)."* ([`:588`](../enterprise/hr_payroll/models/hr_payslip_run.py#L588)) |
| Compute | `action_confirm()` → `compute_sheet()` on draft slips | — |
| Re-compute Payslips | `action_re_compute_payslips()` | run not in `00_draft`/`01_ready` → UserError ([`:685`](../enterprise/hr_payroll/models/hr_payslip_run.py#L685)) |
| Validate | `action_validate()` — confirms non-cancel slips that have lines | **non-officers cannot validate a run with any warning or error** → UserError ([`:376`](../enterprise/hr_payroll/models/hr_payslip_run.py#L376)); then inherits every payslip guard |
| Mark as Paid | `action_paid()` → `action_payslip_paid()` | inherits paid guards |
| Mark as Unpaid | `action_unpaid()` | inherits unpaid guards |
| Pay | `action_payment_report()` — opens the payment wizard | see [Payment](#payment-paths-report-and-iso20022) |
| Set to Draft | `action_draft()` — re-drafts slips, clears payment report | any slip `paid` → ValidationError ([`:303`](../enterprise/hr_payroll/models/hr_payslip_run.py#L303)) |
| Correct | `action_correct()` — refunds + corrects every non-refund slip into a **new** "(Correction)" run | run not `02_close`/`03_paid` → UserError ([`:352`](../enterprise/hr_payroll/models/hr_payslip_run.py#L352)) |
| Add Employees | `action_add_employees()` / `action_add_versions()` | hidden once the run is `02_close`/`03_paid`/`04_cancel` |
| Test Print / Send by email | `action_generate_payslips_pdf()` / `…_send_by_email()` | — |
| Work times / Payroll Journal | `action_work_time_report()` / `action_payroll_line_report()` — reports over the **last three** comparable runs ([`:641`](../enterprise/hr_payroll/models/hr_payslip_run.py#L641)) | — |

`_are_payslips_ready()` returns True if any slip is `validated`/`cancel` ([`:622`](../enterprise/hr_payroll/models/hr_payslip_run.py#L622)); the accounting bridge uses it to decide whether to sweep all of a run's slips into one batched move.

### Starting a run: the pre-flight warning dialog

`action_start_payrun_with_warnings(vals)` ([`:517`](../enterprise/hr_payroll/models/hr_payslip_run.py#L517)) resolves the candidate versions, runs `_get_start_payrun_warnings()` ([`:428`](../enterprise/hr_payroll/models/hr_payslip_run.py#L428)) and, if anything fires, returns the client action `hr_payroll.payrun_start_warning` instead of creating the run. Three checks, each with a "review" button:

| Warning | Fires when |
|---|---|
| **Employees to Review** | any candidate version has `review_state` in `2_to_review` / `3_anomaly` |
| **Time Offs to Review** | a leave of a candidate employee is still `confirm`/`validate1`, or is `payslip_state = 'blocked'` |
| **No Time Offs** | schedule-based versions exist but **no** leave at all overlaps the period ("did you forget to record them?") |

`hr_payroll_attendance` adds a fourth check on top of this method ([hr_payslip_run.py:10](../enterprise/hr_payroll_attendance/models/hr_payslip_run.py#L10)).

### How payslip generation picks employee versions

`_get_valid_versions()` ([`:131`](../enterprise/hr_payroll/models/hr_payslip_run.py#L131)) builds a domain ([`_get_valid_versions_domain_payrun`, :151](../enterprise/hr_payroll/models/hr_payslip_run.py#L151)) and feeds it to `hr.employee._get_contracts(date_start, date_end, …)`:

- Domain: same company, an employee set, `active_employee`, `date_version <= date_end`, `structure_type_id == structure.type_id`, and — when set — `employee_type_id in` (run types ∩ structure types).
- `_get_contracts` returns every version of each employee overlapping the period, so **a mid-period version change yields two versions → two payslips** for the same employee.
- `_generate_payslips()` ([`:585`](../enterprise/hr_payroll/models/hr_payslip_run.py#L585)) then creates one slip per version **not already covered**, names them, and runs `compute_sheet()` on the whole batch. Setting `ir.config_parameter` `hr_payroll.payslip_run_creation_no_message` suppresses the per-slip creation chatter message on large runs.

Other run facts verified from source: the run is archivable (`active`, [`:29`](../enterprise/hr_payroll/models/hr_payslip_run.py#L29)); `gross_sum`/`net_sum`/`total_employer_cost` are sums over non-cancelled slips ([`:273`](../enterprise/hr_payroll/models/hr_payslip_run.py#L273), [`:637`](../enterprise/hr_payroll/models/hr_payslip_run.py#L637)); deleting a run is blocked while any slip is not draft/cancel ([`:618`](../enterprise/hr_payroll/models/hr_payslip_run.py#L618)); a daily cron `_cron_generate_payrun_for_employee_types_with_auto_post()` ([`:700`](../enterprise/hr_payroll/models/hr_payslip_run.py#L700)) creates runs automatically for employee types configured to auto-post.

With `hr_payroll_account` installed the kanban Validate button is unchanged — v20 no longer relabels it "Create Draft Entry".

### Pay run vs off-cycle

A payslip belongs to a pay run if `payslip_run_id` is set; if empty, it is an off-cycle payslip using the same computation/validation/accounting/payment logic, simply not grouped. The payslip button [`action_move_to_off_cycle()`](../enterprise/hr_payroll/models/hr_payslip.py#L1337) calls `run.off_cycle_version()` ([`:691`](../enterprise/hr_payroll/models/hr_payslip_run.py#L691)), which removes the version from `version_ids` **and** detaches the slip — removing only `payslip_run_id` would leave the run stuck in `00_draft`.

---

## Payslip (`hr.payslip`)

Source: [`models/hr_payslip.py`](../enterprise/hr_payroll/models/hr_payslip.py)

A payslip is the real payroll computation document for one employee/version/period/structure, plus worked-day lines, input lines, computed salary lines, an optional accounting move, and state + PDF/payment metadata.

### Core fields (selected)

| Field | Purpose |
|---|---|
| `employee_id` | Employee being paid. |
| `version_id` | Employee record/version used for wage/calendar/structure type. Computed from employee + `date_from`. See [`hr_payslip.py:1964`](../enterprise/hr_payroll/models/hr_payslip.py#L1964). |
| `struct_id` | Salary structure whose rules are evaluated. |
| `payroll_config_id` | The dated company payroll configuration (`payroll.config.settings`) in force for the period — new in 20, available to rules as `payroll_config`. |
| `date_from`, `date_to` | Payroll period. `date_to` computed from schedule unless forced by `default_date_to` context. |
| `worked_days_line_ids` / `input_line_ids` / `line_ids` | Worked days, Other Inputs, computed salary lines. |
| `state` | `draft`, `validated`, `paid`, `cancel`. |
| `state_display` | Computed badge: `01_error` (Blocked) / `02_warning` / the real state. See [Statuses](#statuses-errors--warnings). |
| `error_count`, `warning_count`, `issues` | The blocking framework — `error_count > 0` hard-blocks validation and payment. |
| `is_regular` | True when `struct_id == struct_id.type_id.default_struct_id` (the normal monthly run vs an off-cycle structure like a bonus). Gates the leave-deferral logic. [`_compute_is_regular`](../enterprise/hr_payroll/models/hr_payslip.py#L543) |
| `ignore_worked_day_lines` | Set at create from `struct_id.use_worked_day_lines` ([`create`, :254](../enterprise/hr_payroll/models/hr_payslip.py#L254)); when true, no worked-day lines and BASIC falls back to the contract wage. |
| `credit_note` / `is_refund_payslip` / `is_refunded` / `is_corrected` | Refund/correction sub-lifecycle. See [Refund / Correction](#refund--correction--recompute). |
| `origin_payslip_id` / `related_payslip_ids` / `correction_net_delta` | Links a refund/correction chain and the net difference it produces. |
| `edited` | Manual edits made — freezes worked-day amounts and is skipped by full refresh. |
| `queued_for_pdf` | Validated but PDF not yet rendered (awaiting the hourly cron). |
| `has_negative_net_to_report` / `negative_net_to_report` | This slip had NET < 0 at validation; flagged for carry-forward. |
| `is_wrong_version` / `has_wrong_data` / `has_wrong_leaves` / `is_wrong_company_version` / `has_wrong_company_data` | Post-validation drift detectors — all computed **only on `validated`/`paid` slips** ([`:548`–`:594`](../enterprise/hr_payroll/models/hr_payslip.py#L548)). They feed the payroll warnings and the correction wizard. |
| `paid` / `paid_date` | "Made Payment Order?" flag + date; independent of `state`, not proof money moved. |
| `move_id` / `move_state` / `journal_id` / `date` | (accounting) generated entry + its state + salary journal + accounting date. |

### Period logic

Schedule = `version_id.schedule_pay or version_id.structure_type_id.default_schedule_pay` ([`_get_schedule_timedelta`, hr_payslip.py:324](../enterprise/hr_payroll/models/hr_payslip.py#L324)); `date_to = date_from + _get_schedule_timedelta()` ([`_compute_date_to`, :330](../enterprise/hr_payroll/models/hr_payslip.py#L330)). Helpers `_schedule_period_start()` ([`:224`](../enterprise/hr_payroll/models/hr_payslip.py#L224)) and `_schedule_timedelta()` ([`:303`](../enterprise/hr_payroll/models/hr_payslip.py#L303)).

| Schedule | Typical period |
|---|---|
| `monthly` | First-to-last day of month |
| `semi-monthly` | 1st–15th or 15th–end |
| `quarterly` / `semi-annually` / `annually` | Quarter / half-year / year |
| `bi-monthly` | Two calendar months |
| `weekly` / `bi-weekly` / `daily` | Week / two weeks / one day |

The full selection lives on the structure type ([`_get_selection_schedule_pay`, hr_payroll_structure_type.py:13](../enterprise/hr_payroll/models/hr_payroll_structure_type.py#L13)); `hr.version.schedule_pay` reuses it. The pay run derives its period from the structure's schedule instead of carrying its own.

### Computing the sheet

[`compute_sheet()`](../enterprise/hr_payroll/models/hr_payslip.py#L1269): keeps only draft slips, deletes old `line_ids`, flushes, sets `compute_date`, then evaluates the rules **in horizontal layers** — every employee's first slip of the period first, then every second slip, so cumulative/YTD rules see a consistent order when a mid-period version change produced two slips. Refund slips skip rule evaluation entirely and copy the origin's lines negated. Finally it computes worked-day YTD and, for regular slips, flips every non-blocked overlapping leave to `payslip_state = 'done'`.

> **`compute_sheet` does *not* block on `error_count` in Odoo 20** (that guard moved to `action_payslip_done` / `action_payslip_paid` / the payment wizard). It also recomputes **salary lines only**, not worked days/input lines. To fully rebuild use `action_refresh_from_work_entries()` ([`:1326`](../enterprise/hr_payroll/models/hr_payslip.py#L1326)), which wipes worked days + lines and rebuilds — and skips slips with `edited=True`.

### `_get_basic_salary()` in formulas

`payslip.paid_amount` no longer exists. The default BASIC rule is `result = payslip._get_basic_salary()` ([`hr_salary_rule_data.xml:18`](../enterprise/hr_payroll/data/hr_salary_rule_data.xml#L18)), which returns the contract wage under `salary_simulation`, when `ignore_worked_day_lines` is set, or when there are no worked-day lines; otherwise the sum of `worked_days_line_ids.amount` ([`hr_payslip.py:2625`](../enterprise/hr_payroll/models/hr_payslip.py#L2625)).

### Plain-English salary calculation

The payslip amount is driven by **hours**, while **days** are mostly the human-readable rollup shown on the payslip:

1. The employee version/contract has a **Working Hours** calendar, a **Schedule Pay**, and a **Wage Type**.
2. The calendar (or the attendances, for `attendance_based` versions) produces work-entry **values** for the payslip period. Example: Standard 40h/week in June can produce 22 attendance days x 8h = 176h.
3. Worked-day lines group those values by (time type, category options), then show `days = hours / hours_per_day` ([`_get_worked_day_lines_values`, hr_payslip.py:1374](../enterprise/hr_payroll/models/hr_payslip.py#L1374)).
4. Money is computed from hours in `_compute_amount` ([`hr_payslip_worked_days.py:66`](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L66)).

For **Fixed Wage** (`wage_type='monthly'`), Odoo prorates the fixed contract wage over the period's non-extra hours:

```text
hourly rate = contract wage / non-extra worked hours
worked amount = hourly rate * line hours * work entry type rate
```

So a full fixed-wage month stays at the contract wage even if one month has 176 hours and another has 184 hours: Odoo divides by that month's normal hours, then multiplies back by the paid hours. Unpaid or out-of-contract hours reduce the amount because they contribute `amount=0`.

For **Hourly Wage** (`wage_type='hourly'`), Odoo uses `version.hourly_wage` directly:

```text
worked amount = hourly wage * line hours * work entry type rate
```

`Schedule Pay` only chooses the payslip period (monthly, weekly, etc.). `Working Hours` creates the hour quantity. `Wage Type` decides how those hours become money.

State transitions, every blocker, and the badge framework are documented in [Statuses, Errors & Warnings](#statuses-errors--warnings).

---

## Work Entries & Worked Days

**Odoo 20 deleted the `hr.work.entry` model.** A work entry is now a short-lived Python dict produced on demand and thrown away — there is no record, no state machine, no conflict state, no validation, no generation cron, and no regeneration wizard. Everything the v19 doc described here as a blocker is gone.

A work-entry value looks like `{'date', 'duration', 'work_entry_type_id', 'employee_id', 'version_id', 'company_id', …}` and lives only inside one `_compute_worked_days_line_ids()` call.

### Who produces the values

| Step | Method | Source |
|---|---|---|
| Entry point | `hr.version.generate_work_entries(date_start, date_stop)` — **returns a list of vals, creates nothing** | [hr_version.py:303](../addons/hr_work_entry/models/hr_version.py#L303) |
| Per-version worker | `_get_work_entries_values()` → `_get_version_work_entries_values()` | [:277](../addons/hr_work_entry/models/hr_version.py#L277) / [:122](../addons/hr_work_entry/models/hr_version.py#L122) |
| Schedule-based versions | calendar attendance intervals minus `resource.calendar.leaves`, via `_get_attendance_intervals()` | [:72](../addons/hr_work_entry/models/hr_version.py#L72) |
| Attendance-based versions | validated `hr.attendance` records plus working-time leaves | [hr_version.py:35](../addons/hr_holidays_attendance/models/hr_version.py#L35) |
| Post-processing | `_generate_work_entries_postprocess()` — converts datetime spans to `date` + `duration`, splits at local midnight, drops zero-duration, **merges** by `(date, type, employee, version, company)` | [:412](../addons/hr_work_entry/models/hr_version.py#L412) |

**Which time type is used?** For a working interval, the calendar attendance line's own `work_entry_type_id` if set, otherwise the version default (`structure_type_id.default_work_entry_type_id`, else the country type with code `002.00`, else `hr_work_entry.generic_work_entry_type_attendance`) — [`_get_interval_work_entry_type`, :91](../addons/hr_work_entry/models/hr_version.py#L91) and [`_get_default_work_entry_type_id`, :18](../addons/hr_work_entry/models/hr_version.py#L18). For a leave interval, `leave.work_entry_type_id`, falling back to `hr_work_entry.generic_work_entry_type_leave` when the leave type has none ([`_get_interval_leave_work_entry_type`, :44](../addons/hr_work_entry/models/hr_version.py#L44)).

> **Consequence for operations:** there is nothing to "generate" ahead of time and nothing to fix in a work-entry list. If hours look wrong, the cause is the working schedule, the leave, the attendance, or a time rule — fix that and recompute the payslip.

### Time rules (`hr.time.rule`) — the overtime/undertime engine

[hr_time_rule.py:111](../addons/hr_work_entry/models/hr_time_rule.py#L111). A time rule watches a *source* record (`hr.attendance` or `hr.leave`, both mixing in `hr.time.rule.source.mixin`) and, when the worked quantity crosses a threshold, re-types part of that time.

| Field | Meaning |
|---|---|
| `threshold_operator` | `exceed` (overtime) or `less_than` (undertime) |
| `working_hours_mode` | compare against `the daily schedule` / `the weekly schedule` / a flat `per day` / `per week` figure |
| `expected_hours`, `calendar_source`, `resource_calendar_id` | the baseline when the mode is not schedule-driven |
| `condition_work_entry_type_ids` | **required** — only these time types are considered |
| `work_entry_type_id` ("Set Excess to") | the time type the excess/deficit is written as |
| `amount_rate` | salary rate copied onto that output (1.5, 2.0, …) |
| `employee_domain`, `country_id`, `company_id`, `apply_<weekday>`, `apply_on_public_holidays`, `timing_start`/`timing_stop`, `employee_tolerance`/`employer_tolerance` | scoping and tolerance |

Rules run in `sequence` order (lowest wins on overlap). They are triggered from `create`/`write` on the source record ([`_trigger_time_rules`, hr_time_rule_source_mixin.py](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py)) and by two daily crons per source model — `_cron_process_day_undertime_rules()` and `_cron_process_week_time_rules()` ([hr_attendance_data.xml:26](../addons/hr_attendance/data/hr_attendance_data.xml#L26), [hr_holidays/ir_cron_data.xml:36](../addons/hr_holidays/data/ir_cron_data.xml#L36)).

> **Undertime is cron-only for weekly rules.** `_trigger_time_rules_for_affected` deliberately runs weekly rules with `exceed` only, because triggering weekly undertime on every write would create spurious records while a past week is still being entered.

Base data ships one generic rule (*Employee Schedule Rule*: attendance beyond the employee's daily schedule becomes Overtime) plus country rules — [hr_time_rule_data.xml](../addons/hr_work_entry/data/hr_time_rule_data.xml).

### Worked-days rollup and paid/unpaid amounts

`_compute_worked_days_line_ids` ([`hr_payslip.py:2162`](../enterprise/hr_payroll/models/hr_payslip.py#L2162)) generates the values over the period (±1 day) for the slip's version **plus any concurrent version sharing the same contract dates**, then builds lines via `_get_worked_day_lines_values` ([`:1374`](../enterprise/hr_payroll/models/hr_payslip.py#L1374)) from `version.get_work_hours()` ([`hr_version.py:559`](../enterprise/hr_payroll/models/hr_version.py#L559)) — an in-memory sum of `duration` per **(time type, category options)** pair. Hours convert to days via `hours_per_day`, with per-type rounding (`round_days_type`) and a carry onto the largest line. Out-of-contract days get a separate line on the type with code `000.00`, else `hr_work_entry.generic_hr_work_entry_type_out_of_contract` ([`:1462`](../enterprise/hr_payroll/models/hr_payslip.py#L1462)). Refund slips copy the origin's worked days negated. Slips skip this entirely under `salary_simulation`, when `ignore_worked_day_lines` is set, or when the struct has `use_worked_day_lines=False`.

**Worked-day amount** `_compute_amount` ([`hr_payslip_worked_days.py:66`](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L66)):
- Early-returns (amount frozen) if the slip is `edited` or not `draft`; `000.00`/version-less lines are forced to 0 ([`:112`](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L112)).
- **`is_paid` is now purely `work_entry_type_id.amount_rate != 0`** ([`:51`](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L51)). The structure-level `unpaid_work_entry_type_ids` list **no longer exists** — unpaid is a property of the time type, not of the structure.
- Hourly contracts use `version._get_contract_wage()` directly; otherwise hourly rate = `contract_wage / work_time`, where `work_time` is the calendar's own working hours for the period (flexible calendars fall back to the sum of non-`is_extra_hours` worked hours) ([`:92`–`:122`](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L92)).
- `amount = hourly_rate * number_of_hours * work_entry_type.amount_rate` **only if `is_paid`, else 0** ([`:123`](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L123)).

So an **unpaid leave** (`amount_rate = 0`) still shows days/hours on the payslip but contributes `amount=0`; salary rules prorate the monthly wage down because those hours add no paid amount. A **paid leave** carries its hours at the rate scaled by `amount_rate` (e.g. 0.5 for half pay, 2.0 for double time).

Two extra columns worth knowing: `fte` (work-time rate × this line's share of the period's hours, [`:54`](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L54)) and `category_options_ids` — premium-pay categories carried from the source record, which split one time type into several worked-day lines and feed `category_options` in the localdict.

Common examples:

| Time type | What changes salary? |
|---|---|
| Attendance | `amount_rate = 1.0`; full normal hours give the full fixed wage. |
| Out of Contract (`000.00`) | Always amount 0 in `_compute_amount`; used for days outside the contract/version dates. |
| Unpaid leave | `amount_rate = 0` → `is_paid = False` → amount 0. Set the rate on the **time type**. |
| Overtime produced by a time rule | The rule's `amount_rate` is copied onto the output type (1.5, 2.0 …). If that type is `is_extra_hours`, the hours are excluded from the flexible-calendar denominator and added on top. |

### No validation step, and what replaced it

Confirming a payslip no longer validates anything: `action_payslip_done()` ([`:980`](../enterprise/hr_payroll/models/hr_payslip.py#L980)) writes the state, flags negative net, and hands off to the PDF pipeline. There is no `action_draft_linked_entries`, no `_check_undefined_slots`, no immutable-entry guard.

What protects a closed period instead is on the **leave** side: `hr.leave._check_uncovered_by_validated_payslip()` refuses to re-activate or delete a leave already inside a validated/paid regular payslip ([hr_leave.py:370](../enterprise/hr_payroll/models/hr_leave.py#L370)), and `payslip_state = 'blocked'` marks leaves that arrived too late. See [Time Off & Payroll](#time-off--payroll).

---

## Time Off & Payroll

All of this now lives in `hr_payroll` itself — [`models/hr_leave.py`](../enterprise/hr_payroll/models/hr_leave.py). The v19 modules `hr_payroll_holidays`, `hr_work_entry_holidays` and `hr_work_entry_holidays_enterprise` are gone.

### There is no `hr.leave.type` any more

Odoo 20 merged the leave type into the time type. `hr.leave.work_entry_type_id` points straight at an `hr.work.entry.type` ([hr_leave.py:167](../addons/hr_holidays/models/hr_leave.py#L167)), and that record now carries what used to be leave-type configuration: `leave_validation_type`, `requires_allocation`, `request_unit`, `unit_of_measure`, `time_off_selectable`, `support_document`, `allows_negative`. So **the leave's time type and its payroll time type are the same record** — there is no mapping step and no "leave type has no work entry type" failure mode.

Consequences for payroll:
- Whether a leave is paid is `work_entry_type_id.amount_rate` (0 = unpaid, 1 = full, 0.5 = half pay, 2 = double).
- Whether it counts as worked time or absence is `work_entry_type_id.count_as` (`working_time` / `absence`).
- Worked-day lines are keyed by that same type, so the payslip line label is the leave's own name.

When several leaves cover one interval, `_get_interval_leave_work_entry_type` ([hr_version.py:264](../addons/hr_holidays/models/hr_version.py#L264)) picks: a `bypassing_codes` type first (localization-defined, e.g. long-term sick), then global leaves (public holidays), then personal leaves; falling back to `hr_work_entry.generic_work_entry_type_leave`. Public-holiday behaviour is unchanged — see [`public_holidays_flow.md`](public_holidays_flow.md) before changing a holiday around payroll.

### Deferred time off (`payslip_state`)

Handles the case where a leave is approved **after** its payslip is already validated or paid. `payslip_state` lives on `hr.leave` ([hr_leave.py:17](../enterprise/hr_payroll/models/hr_leave.py#L17)):

| `payslip_state` | Label | Meaning |
|---|---|---|
| `normal` | To compute in next payslip | Default; picked up normally. |
| `done` | Computed in current payslip | Already reflected; set by `compute_sheet` for every non-blocked leave the slip covers. |
| `blocked` | **Payslip to be corrected** | The period is already closed by a validated/paid regular slip; the payslip must be corrected. |

**When a leave becomes `blocked`:** `_action_validate()` ([`:247`](../enterprise/hr_payroll/models/hr_leave.py#L247)) sets it when the leave overlaps a `validated`/`paid` **regular** payslip **and** no still-draft slip also covers it. If a draft slip still covers the period the leave stays `normal`, and `_recompute_payslips()` ([`:325`](../enterprise/hr_payroll/models/hr_leave.py#L325)) immediately rebuilds the affected draft slips — `_compute_worked_days_line_ids()` for empty ones, `action_refresh_from_work_entries()` for ones that already have lines.

> **Behaviour change from v19:** blocked leaves are **no longer excluded** from work-entry generation (the old `_get_resource_calendar_leaves` filter is gone), and the label changed from "To defer to next payslip" to "Payslip to be corrected". The fix is now a correction payslip, not a hand-made work entry.

**How it surfaces:** as the shipped payroll warning `hr_payroll.hr_payroll_leaves_to_defer` ("Leaves to defer", level `warning`, displayed on `hr.leave` and the dashboard) rather than as a danger error on the payslip ([hr_payroll_warning_data.xml:577](../enterprise/hr_payroll/data/hr_payroll_warning_data.xml#L577)). `hr.leave.issues` is computed from the `hr.payroll.warning` records whose model is `hr.leave` ([`_compute_issues`, :87](../enterprise/hr_payroll/models/hr_leave.py#L87)). A blocked leave also appears in the pay run's **Time Offs to Review** pre-flight warning.

**Resolution — two paths:**
- **Correct the payslip:** `action_adjust_corresponding_payslip()` ([`:281`](../enterprise/hr_payroll/models/hr_leave.py#L281)) finds the latest validated/paid slip of the same structure type overlapping the leave and opens the Payslip Correction wizard on it. The refund step resets the related blocked leaves back to `normal` ([`_action_refund_payslips`, hr_payslip.py:1181](../enterprise/hr_payroll/models/hr_payslip.py#L1181)).
- **Mark it handled:** completing the **"Leave to Defer"** activity (`hr_payroll.mail_activity_data_hr_leave_to_defer`) writes `payslip_state = 'done'` ([`activity_feedback`, :345](../enterprise/hr_payroll/models/hr_leave.py#L345)). A user-cancelled leave is also forced to `done` ([`:315`](../enterprise/hr_payroll/models/hr_leave.py#L315)).
  > **In 20.0 nothing creates this activity.** The activity type is still shipped ([mail_activity_type_data.xml:12](../enterprise/hr_payroll/data/mail_activity_type_data.xml#L12)) and the feedback handler and the cleanup list still reference it ([`_get_to_clean_activities`, :296](../enterprise/hr_payroll/models/hr_leave.py#L296)), but the v19 `activity_schedule` call that raised it lived in `hr_payroll_holidays/models/hr_leave.py` and died with that module. The only `activity_schedule` left in the payroll leave override is the approval activity ([`:77`](../enterprise/hr_payroll/models/hr_leave.py#L77)). Treat **Correct the payslip** as the only reachable resolution unless someone schedules the activity by hand.

The v19 "Report to Next Month" action (`action_report_to_next_month`) **no longer exists** — it converted next month's draft work entries, which is impossible without work-entry records.

### Guards around a closed period

| Guard | Effect | Source |
|---|---|---|
| `_check_uncovered_by_validated_payslip()` | UserError *"The pay of the month is already validated with this day included…"* when re-activating or deleting a validated leave inside a validated/paid regular slip whose `done_date` is later than the leave's creation | [hr_leave.py:370](../enterprise/hr_payroll/models/hr_leave.py#L370) |
| `_compute_can_back_to_approve` | an approved leave can be sent back to Confirm only when no validated/paid regular slip covers it | [`:232`](../enterprise/hr_payroll/models/hr_leave.py#L232) |
| `_move_validate_leave_to_confirm` | time-off officers only (`AccessError` otherwise), then resets `payslip_state` to `normal` and recomputes draft slips | [`:306`](../enterprise/hr_payroll/models/hr_leave.py#L306) |
| `_process_auto_approve_activities` | a no-validation leave carrying a `danger` payroll warning is **not** auto-approved for non-officers; an approval activity is scheduled on the HR responsible instead | [`:65`](../enterprise/hr_payroll/models/hr_leave.py#L65) |
| `return_time_off_to_normal()` | cancelling a payslip resets that month's blocked leaves to `normal` | [hr_payslip.py:2639](../enterprise/hr_payroll/models/hr_payslip.py#L2639) |

`res.company.deferred_time_off_manager` is still the Payroll setting that designates who handles deferrals ([res_company.py:71](../enterprise/hr_payroll/models/res_company.py#L71), exposed in [res_config_settings.py:16](../enterprise/hr_payroll/models/res_config_settings.py#L16)) — but in 20.0 **nothing reads it**. In v19 it supplied the `user_id` of the "Leave to Defer" activity; with that creation site gone, the field is configurable, visible in Payroll Settings, and orphaned.

### Payroll fields added to the leave

`hr_payroll` also puts `employee_type_id`, `job_id`, `structure_type_id` (all computed from the version in force at `date_from`), a `payslip_count` smart button, and `category_options_ids` — premium-pay categories selectable on the leave and propagated to the underlying `resource.calendar.leaves` record ([`_prepare_resource_leave_vals`, :409](../enterprise/hr_payroll/models/hr_leave.py#L409)), which is what makes a premium show up as its own worked-day line.

---

## Statuses, Errors & Warnings

This is the framework behind "all statuses and all blockers". A payslip is gated by **`error_count`** and by "Block Payslips" warnings, not by `state` alone.

### Two status fields

| Field | Values | Source |
|---|---|---|
| `state` | draft / validated / paid / cancel | [`hr_payslip.py:72`](../enterprise/hr_payroll/models/hr_payslip.py#L72) |
| `state_display` | `01_error` **Blocked** / `02_warning` **Warning** / `03_draft` / `04_validated` "Done" / `05_paid` / `06_cancel` | [`hr_payslip.py:82`](../enterprise/hr_payroll/models/hr_payslip.py#L82) |

`_compute_state_display` precedence ([`:287`](../enterprise/hr_payroll/models/hr_payslip.py#L287)): `error_count` → `01_error`, else `warning_count` **and `state == 'draft'`** → `02_warning`, else the real state. A validated slip therefore never shows the orange badge, only the red one.

### The issues system is now data-driven

The v19 hardcoded `_get_errors_by_slip` / `_get_warnings_by_slip` are gone. Issues come from **`hr.payroll.warning`** records ([`hr_payroll_warning.py`](../enterprise/hr_payroll/models/hr_payroll_warning.py)), which admins can edit and extend from Payroll → Configuration.

| Warning field | Effect |
|---|---|
| `model_id` | One of `hr.employee`, `hr.version`, `hr.payslip`, `hr.leave` ([`_get_allowed_models`, :33](../enterprise/hr_payroll/models/hr_payroll_warning.py#L33)) |
| `warning_type` | `domain` (a domain on that model) or `python` (safe-eval'd `evaluation_code` returning `warning_records` / `warning_details`) |
| `warning_color_class` | `danger` → counts as an **error**; anything else counts as a warning ([`_get_warning_issue`, :583](../enterprise/hr_payroll/models/hr_payroll_warning.py#L583)) |
| `display_on_dashboard` / `display_on_model` | Where it appears; at least one is required ([`:110`](../enterprise/hr_payroll/models/hr_payroll_warning.py#L110)) |
| `block_payslips` | Makes validation refuse, **even for warnings living on the employee rather than the payslip** |
| `visible_to` | `assistant` / `officer` / `admin` — enforced by `ir.access` rows, not by the view |
| `closing_on` + `warning_offset_days` | Computes the warning's due date relative to today / next payslip / contract start-end / end of month-quarter-year / payroll start date |
| `email_alert_days` + `email_message` | Daily cron `_cron_payroll_warning_email_alert()` mails the configured audience ([`:674`](../enterprise/hr_payroll/models/hr_payroll_warning.py#L674)) |
| `snooze_date` | **Snooze** hides the card for 25 days ([`action_snooze`, :140](../enterprise/hr_payroll/models/hr_payroll_warning.py#L140)) |

`hr.payslip._compute_issues` ([`:2080`](../enterprise/hr_payroll/models/hr_payslip.py#L2080)) searches the warnings with `display_on_model` on `hr.payslip` matching the slip's country, evaluates each one **once for the whole recordset**, and fills `issues` (JSON), `error_count` and `warning_count`. Only `draft`/`validated` slips are checked, plus `paid` slips showing post-validation drift ([`_get_payslips_to_compute_issues`, :2068](../enterprise/hr_payroll/models/hr_payslip.py#L2068)). `hr.leave` has the same mechanism on its own `issues` field.

> The compute short-circuits while the registry is still loading unless `hr_payroll_force_compute_issue` is in context — upgrade scripts must pass it.

**Only `danger` issues block.** `_get_error_message` ([`:2139`](../enterprise/hr_payroll/models/hr_payslip.py#L2139)) joins only `danger` issues into the raised message. The form renders `issues` with the `actionable_warnings` widget.

### Shipped payslip warnings (base `hr_payroll`)

Source: [`data/hr_payroll_warning_data.xml`](../enterprise/hr_payroll/data/hr_payroll_warning_data.xml). Only three are `danger`:

| Warning | Level | Fires when |
|---|---|---|
| Payslips Without Running Contract | **danger** | the version's contract dates do not cover the period |
| Wrong Company | **danger** | the slip's company does not match its pay run's |
| Employees Pending Review | **danger** | the employee's `review_state` still needs attention |
| Wrong Employees Data / Wrong Company Data | warning | version or payroll config changed after `done_date` |
| Duplicate Payslips | warning | another non-cancelled slip with the same version/struct/period |
| Payslips With Zero or Negative Net / With Period Mismatch / period does not match payrun | warning | as named |
| Salary Attachment Created / Closed | warning | an adjustment started or ended inside the period |
| Issue Bank Accounts | warning | missing or untrusted employee bank account |
| Time Off Not Validated | warning | a leave overlapping the period is still pending |
| Payslip(s) Before First Pay | warning | the period precedes `company.first_payrun_date` |
| Outdated Payslips / Payslips overdue for payments | warning | dashboard hygiene |

Bridges add their own: **No Journal** (`hr_payroll_account`), **Missing country on employee address** (`hr_payroll_account_iso20022`), **Attendance Discrepancies** (`hr_payroll_attendance`), **Missing Contact Information** (`documents_hr_payroll`), **Drivers Without Running Contract** (`hr_payroll_fleet`). Localizations ship many more, and they are where most `block_payslips` warnings come from.

### Payslip transitions and exactly what gates each

| From → To | Method / button | Blocking conditions (raise) | Source |
|---|---|---|---|
| draft → draft (recompute lines) | `compute_sheet` | **none** — it silently filters to draft slips | [`:1269`](../enterprise/hr_payroll/models/hr_payslip.py#L1269) |
| draft → draft (full refresh) | `action_refresh_from_work_entries` | any slip `state != 'draft'` → UserError; skips `edited=True` slips | [`:1326`](../enterprise/hr_payroll/models/hr_payslip.py#L1326) |
| draft → validated | `action_payslip_done` ("Validate") | not `group_hr_payroll_officer` → ValidationError; any **Block Payslips** warning matching the slip or its employee → ValidationError; any `state=='cancel'` → ValidationError; any `error_count` → ValidationError; archived version → ValidationError; (account) any `state=='paid'` → ValidationError | [`:980`](../enterprise/hr_payroll/models/hr_payslip.py#L980), [`hr_payroll_account/.../hr_payslip.py:34`](../enterprise/hr_payroll_account/models/hr_payslip.py#L34) |
| draft → validated (combined) | `action_validate` | same officer check, computes empty slips first, then `action_payslip_done` | [`:1040`](../enterprise/hr_payroll/models/hr_payslip.py#L1040) |
| validated/paid → paid | `action_payslip_paid` ("Mark as Paid") | any `state not in (validated,paid)` → UserError; any `error_count` → ValidationError | [`:1062`](../enterprise/hr_payroll/models/hr_payslip.py#L1062) |
| paid → validated | `action_payslip_unpaid` ("Mark Unpaid") | any `state != 'paid'` → UserError; forces the run back to `02_close` | [`:1104`](../enterprise/hr_payroll/models/hr_payslip.py#L1104) |
| draft/validated → cancel | `action_payslip_cancel` ("Cancel") | non-manager cancelling a `validated` slip → UserError; resets blocked leaves to `normal`; (account) unlinks/reverses the move first | [`:1055`](../enterprise/hr_payroll/models/hr_payslip.py#L1055), [`hr_payroll_account/.../hr_payslip.py:29`](../enterprise/hr_payroll_account/models/hr_payslip.py#L29) |
| cancel → draft | `action_payslip_draft` ("Set to Draft") | no guard; clears the payment-report fields and `done_date`; **does not touch `move_id`** | [`:843`](../enterprise/hr_payroll/models/hr_payslip.py#L843) |
| (delete) | ORM unlink | any `state not in (draft,cancel)` → UserError; also removes the version from a draft pay run | [`:1242`](../enterprise/hr_payroll/models/hr_payslip.py#L1242), [`:1263`](../enterprise/hr_payroll/models/hr_payslip.py#L1263) |

**Side effects of `action_payslip_done`:** flags negative net (non-`credit_note` slips whose net — or, for a correction of a paid slip, whose `correction_net_delta` — is below zero, [`:1014`](../enterprise/hr_payroll/models/hr_payslip.py#L1014)); PDF queue (context `payslip_generate_pdf` → inline `_generate_pdf` for small batches when the PDF engine is ready, else `_queue_for_send()`, [`:1024`](../enterprise/hr_payroll/models/hr_payslip.py#L1024)). It no longer validates work entries — there are none.

**The `paid` write hook:** writing `state='paid'` triggers salary-attachment payment recording, grouped by rule code ([`write`, :769](../enterprise/hr_payroll/models/hr_payslip.py#L769)). A payment report that only downloads a file never records attachment payments; **Mark as Paid** in the same wizard does.

### Buttons visible per state

**Payslip form header** ([`hr_payslip_views.xml`](../enterprise/hr_payroll/views/hr_payslip_views.xml)):

| Button | Method | Visible when |
|---|---|---|
| Validate | `action_payslip_done` | `draft` AND `line_ids` exist, group **Officer** |
| Compute | `compute_sheet` | `draft` and not `credit_note` (highlighted while there are no lines) |
| Pay | `action_payslip_payment_report` | `state == 'validated'` |
| Correct | `action_adjust_payslip` | `state == 'paid'` and not `credit_note` |
| Mark Unpaid | `action_payslip_unpaid` | `state == 'paid'` |
| Set to Draft | `action_payslip_draft` | `state == 'cancel'` |
| Cancel | `action_payslip_cancel` | `state in (draft, validated)` |
| Print | `action_print_payslip` | any state, once `line_ids` exist |

The payslip **list** view adds Off-Cycle, Validate, Compute, Mark as Paid and Print. With `hr_payroll_account` the header Validate button is re-rendered without the officer group and with a confirmation dialog, and a Journal Entry (Draft/Posted/Canceled) stat button appears ([`hr_payslip_views.xml:20`](../enterprise/hr_payroll_account/views/hr_payslip_views.xml#L20)). **v20 no longer relabels it "Create Draft Entry", and there is no Pay/Register-Payment button on the payslip form.**

**Pay-run kanban** ([`hr_payslip_run_views.xml:40`](../enterprise/hr_payroll/views/hr_payslip_run_views.xml#L40)): Validate (`01_ready`, no empty slips, at least one slip); Test Print (`01_ready`); Compute (`01_ready` + empty slips); Re-compute Payslips (`01_ready`); Mark as Paid / Pay / Set to Draft (`02_close`); Mark as Unpaid (`03_paid`); Correct (`02_close`/`03_paid`); Send by email (`02_close`/`03_paid`, only when the company trigger is `never`); Add Employees (not closed/paid/cancelled); Work times and Payroll Journal always.

### Banner catalog (form alerts)

The v19 hand-written banners were replaced by the single `issues` widget plus the correction wizard.

| Banner | Shows when | Source |
|---|---|---|
| `issues` actionable-warnings list | `issues` non-empty — one row per matching `hr.payroll.warning`, coloured by `warning_color_class` | [`hr_payslip_views.xml`](../enterprise/hr_payroll/views/hr_payslip_views.xml) |
| "Wrong Employees Data" / "Wrong Company Data" / "Employees Pending Review" | the drift detectors below, surfaced as warnings | [`hr_payroll_warning_data.xml:526`](../enterprise/hr_payroll/data/hr_payroll_warning_data.xml#L526) |
| "No Journal" | (account) validated slip whose struct has no `journal_id` | [`hr_payroll_account/data/hr_payroll_warning_data.xml:4`](../enterprise/hr_payroll_account/data/hr_payroll_warning_data.xml#L4) |

**Drift detectors** (all computed only on `validated`/`paid` slips, [`:548`–`:594`](../enterprise/hr_payroll/models/hr_payslip.py#L548)): `is_wrong_version` (the employee's version effective at `date_from` is no longer this slip's), `has_wrong_data` (`version.last_modified_date > done_date`), `has_wrong_leaves` (an overlapping leave was written after `done_date`), `is_wrong_company_version` / `has_wrong_company_data` (the dated `payroll.config.settings` changed). Any of them makes the slip eligible for the **Payslip Correction** wizard ([`_compute_allowed_payslip_ids`, hr_payslip_correction_wizard.py:31](../enterprise/hr_payroll/wizard/hr_payslip_correction_wizard.py#L31)); `keep_wrong_version = True` silences them.

**Negative-net carry-forward:** `action_payslip_done` stores `has_negative_net_to_report` + `negative_net_to_report`. `_negative_net_context()` ([`:2603`](../enterprise/hr_payroll/models/hr_payslip.py#L2603)) aggregates the outstanding amount for the report; `_get_negative_net_rule()` ([`:502`](../enterprise/hr_payroll/models/hr_payslip.py#L502)) resolves the rule the recovery is posted on. The **"Negative Net to Report"** activity type is `hr_payroll.mail_activity_data_hr_payslip_negative_net`.

---

## Refund / Correction / Recompute

The payslip has a refund/correction sub-lifecycle independent of `state`. Odoo 20 removed `correct_sheet()` and routed everything through the **Payslip Correction wizard**.

| Action | Creates | Origin slip effect | Source |
|---|---|---|---|
| `refund_sheet()` / `_action_refund_payslips()` | a credit-note copy (`credit_note=True`, `edited=True`, `is_refund_payslip=True`, `origin_payslip_id` set) with every worked-day, input and salary line **negated**, then immediately **validated** | `is_refunded=True`, chatter note, related blocked leaves reset to `normal` | [`:1181`](../enterprise/hr_payroll/models/hr_payslip.py#L1181) |
| `_action_correct_payslips()` | a fresh draft slip on the **same version and period**, carrying the origin's input lines, then `compute_sheet()` | `is_corrected=True`, chatter note | [`:1211`](../enterprise/hr_payroll/models/hr_payslip.py#L1211) |
| **Correct** button / correction wizard | refund **+** correction, grouped into new "Correction (…)" / "Revert (…)" pay runs per (structure, company) | same | [`hr_payslip_correction_wizard.py:80`](../enterprise/hr_payroll/wizard/hr_payslip_correction_wizard.py#L80) |
| Pay run **Correct** | the same pair for every non-refund slip of the run, into one new `(Correction)` run | same | [`hr_payslip_run.py:352`](../enterprise/hr_payroll/models/hr_payslip_run.py#L352) |

The wizard offers **Correct this payslip only** vs **Correct all affected payslips** — the latter resolving to every validated/paid slip of those employees showing drift and not already refunded/corrected/kept ([`_compute_allowed_payslip_ids`, :31](../enterprise/hr_payroll/wizard/hr_payslip_correction_wizard.py#L31)). It also exposes **Revert only** (`action_revert_payslips`) and **Keep it as is** (`action_keep_wrong_version`).

Correction accounting: `correction_net_delta` = the correction slip's net minus the origin's ([`:495`](../enterprise/hr_payroll/models/hr_payslip.py#L495)); it is that delta — not the full net — that is checked for negative net when the origin was already paid, and paying a correction slip also marks the whole origin chain paid ([`action_payslip_paid`, :1062](../enterprise/hr_payroll/models/hr_payslip.py#L1062)).

The refund copy negates amounts **directly** (not recomputed), so manual edits carry through inverted. `related_payslip_ids`/`origin_payslip_id` drive the **Related Payslips** stat button and `_get_payslip_family()`.

**Custom component warning:** a custom one-time claim cannot simply exclude all correction slips. The refund already reverses the original custom salary line; if the recomputed correction contributes zero, valid custom pay disappears. Use immutable settlement lineage so the correction mirrors the original valid component and only explicit audited adjustments change it. Newly approved late sources belong to the next regular slip, not the correction.

**Compute vs Recompute:** `compute_sheet` re-derives `line_ids` only; `action_refresh_from_work_entries` wipes worked days + lines and rebuilds, but **skips `edited=True` slips**.

### Editing payslip lines in place (the wizard is gone)

`hr.payroll.edit.payslip.lines.wizard` and `hr.payroll.index` no longer exist. In Odoo 20 you edit the salary lines **directly in the list on the payslip**, and `hr.payslip.write()` handles the consequences ([`:694`](../enterprise/hr_payroll/models/hr_payslip.py#L694)):

- Writing `total` on a line without `amount` is rewritten to `amount` (they are equal when qty and rate are untouched).
- Any change to `name`/`amount`/`quantity`/`rate` snapshots the old values, then calls `_recompute_with_forced_lines()` ([`:787`](../enterprise/hr_payroll/models/hr_payslip.py#L787)): rules **before** the lowest edited sequence keep their computed values, the edited values are forced, and every later rule re-evaluates on top under the `force_payslip_line_overrides` context. The slip is then marked `edited=True`.
- `_log_line_manual_changes()` ([`:808`](../enterprise/hr_payroll/models/hr_payslip.py#L808)) posts a chatter diff of every changed field per line.
- Writing `input_line_ids` on a draft slip that already has lines re-runs `compute_sheet()` automatically.
- `hr.payslip.line.manually_modified` marks a line that automatic recomputation must not overwrite.

**The `edited` flag** (set by manual line edits and by refund copies) freezes worked-day `_compute_amount` ([`hr_payslip_worked_days.py:112`](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L112)) and makes `action_refresh_from_work_entries` skip the slip — but **`compute_sheet` ignores it**: clicking Compute on an edited slip regenerates all salary lines from the rules, discarding the manual line edits (only the frozen worked-day amounts survive).

**Wage indexation** is now `hr.payroll.salary.increase` ([`hr_payroll_salary_increase_wizard.py`](../enterprise/hr_payroll/wizard/hr_payroll_salary_increase_wizard.py)): pick employees, an increase date and a rate (full wage or capped, plus an optional extra amount), and it creates new versions — then offers a second step that opens the payslips the increase invalidated so they can be corrected.

---

## Structure Type (`hr.payroll.structure.type`)

Source: [`models/hr_payroll_structure_type.py`](../enterprise/hr_payroll/models/hr_payroll_structure_type.py)

The default payroll configuration attached to an employee version.

| Field | Purpose |
|---|---|
| `default_schedule_pay` | Default payment frequency; the payslip period length derives from it. [`:37`](../enterprise/hr_payroll/models/hr_payroll_structure_type.py#L37) |
| `default_struct_id` | Default salary structure (also what makes a slip `is_regular`). |
| `default_work_entry_type_id` | **Required.** The time type for regular attendance; defaults to the country type with code `002.00`, else `hr_work_entry.generic_work_entry_type_attendance`. Its domain is restricted to `allowed_work_entry_type_ids` (types of the structure type's country, or country-less types). [`:42`](../enterprise/hr_payroll/models/hr_payroll_structure_type.py#L42) |
| `wage_type` | `monthly` fixed or `hourly`. |
| `salary_benefits_ids` | The configurator benefits attached to this type — the model now lives in `hr_payroll`. |

`hr.version` extends employee records with `schedule_pay`, `resource_calendar_id`, `contract_date_start/end`, `wage`, `contract_wage`, `wage_type`, `structure_type_id`, `payroll_properties` and `work_time_rate` ([`hr_version.py` enterprise](../enterprise/hr_payroll/models/hr_version.py)). `work_entry_source` is gone — see [Where worked days come from](#where-worked-days-come-from).

---

## Salary Structure (`hr.payroll.structure`)

Source: [`models/hr_payroll_structure.py`](../enterprise/hr_payroll/models/hr_payroll_structure.py)

The set of rules applied to a payslip, and the definition of its inputs.

| Field | Purpose |
|---|---|
| `type_id` | Links to a structure type. **Required** — it is what matches candidate versions in a pay run. |
| `rule_ids` | Salary rules evaluated. **Many2many** in v20 (a rule can belong to several structures). |
| `employee_type_ids` | Restricts the structure to certain `hr.employee.type`; intersected with the pay run's own filter. |
| `version_properties_definition` | The Properties definition behind `hr.version.payroll_properties` — rebuilt automatically from the structure's input rules ([`_sync_properties_to_definition`, :76](../enterprise/hr_payroll/models/hr_payroll_structure.py#L76)). |
| `report_id` | PDF report template (else default `hr_payroll.action_report_payslip`). |
| `payslip_name` / `hide_basic_on_pdf` | Printed-payslip cosmetics. |
| `use_worked_day_lines` | If false, new slips get `ignore_worked_day_lines=True`: no worked-day lines, and `_get_basic_salary()` falls back to the contract wage. |
| `ytd_computation` | Adds year-to-date values. |
| `journal_id` | (accounting) **Salary Journal** — `company_dependent`. Required in the account view; the first accounting gate. [`hr_payroll_account/.../hr_payroll_structure.py`](../enterprise/hr_payroll_account/models/hr_payroll_structure.py) |

> **Removed in v20:** `unpaid_work_entry_type_ids` (paid/unpaid is `work_entry_type_id.amount_rate` now) and `input_line_type_ids` (inputs are defined by salary rules).

> The journal is **constrained to the company currency** — `_check_journal_id` raises ValidationError if they differ. You also cannot delete a journal linked to a structure ([`account_journal.py`](../enterprise/hr_payroll_account/models/account_journal.py)).

### Country scoping and rule seeding

- `country_id` defaults to the company country ([`hr_payroll_structure.py:48`](../enterprise/hr_payroll/models/hr_payroll_structure.py#L48)) and is **not** cosmetic: a company-less **restriction** row in `security/ir.access.csv` hides structures whose country is not among the logged-in companies' countries — `ir_rule_hr_payroll_structure_multi_company` ([`ir.access.csv`](../enterprise/hr_payroll/security/ir.access.csv)). The same pattern applies to salary rules, rule categories, rule parameters (+values) and payroll warnings. In Odoo 20 these are `ir.access` rows with an empty `group_id`, not `ir.rule` records.
- A **new structure is seeded with copies of the default structure's rules** — `rule_ids` default is `copy_data` of every rule of `hr_payroll.default_structure` ([`_get_default_rule_ids`, :16](../enterprise/hr_payroll/models/hr_payroll_structure.py#L16)). That default set is BASIC / GROSS / DEDUCTION / ATTACH_SALARY / ASSIG_SALARY / CHILD_SUPPORT / REIMBURSEMENT / NET ([`hr_salary_rule_data.xml`](../enterprise/hr_payroll/data/hr_salary_rule_data.xml)).
- The payslip PDF `report_id` domain prefers `l10n_<company country>` reports and falls back to generic `hr_payroll` ones ([`_get_domain_report`, :23](../enterprise/hr_payroll/models/hr_payroll_structure.py#L23)).
- Structure **types** have no country field of their own, but creating/writing one under context `payroll_check_country` validates the country against logged-in companies ([`hr_payroll_structure_type.py:61`](../enterprise/hr_payroll/models/hr_payroll_structure_type.py#L61)).

---

## Salary Rules (`hr.salary.rule`)

Source: [`models/hr_salary_rule.py`](../enterprise/hr_payroll/models/hr_salary_rule.py)

One computation step → one `hr.payslip.line`, updates category totals, and becomes available to later rules. In Odoo 20 a rule can also *be* a payslip input.

| Field | Purpose |
|---|---|
| `sequence` / `code` | Execution order / formula symbol. `code` is unique per structure ([`_check_unique_code_per_struct`, :130](../enterprise/hr_payroll/models/hr_salary_rule.py#L130)). |
| `struct_ids` | **Many2many** — the structures this rule belongs to (was `struct_id` in v19). |
| `category_ids` | **Many2many** of `hr.salary.rule.category` (was the single `category_id`). Every category the rule's total is added to. |
| `round_of_computation` | Rules are evaluated in ascending rounds; use it when a rule depends on a value produced later in sequence. [`:127`](../enterprise/hr_payroll/models/hr_salary_rule.py#L127) |
| `condition_select` | Whether the rule runs: `none` / `property_input` / `domain` / `python` ([`_satisfy_condition`, :264](../enterprise/hr_payroll/models/hr_salary_rule.py#L264)). `domain` is evaluated as `payslip.filtered_domain(...)`. |
| `amount_select` | How the amount is computed: `fix` / `percentage` / `property_input` / `code` ([`_compute_rule`, :230](../enterprise/hr_payroll/models/hr_salary_rule.py#L230)). |
| `input_usage_payslip` | **"Available on Payslip"** — makes the rule selectable as a manual payslip input and as the target of a salary adjustment. |
| `input_usage_employee`, `input_selected_by_default`, `input_default_value`, `input_name`, `input_suffix`, `input_section`, `user_instructions` | The input's presentation: where it can be filled, whether a line is seeded automatically, its default value, label, unit suffix, `hr.salary.rule.section` grouping and help text. |
| `appears_on_payslip` / `appears_on_employee_cost_dashboard` / `display_in_pdf_extra_info` / `hide_amount` | Visibility on the payslip, the employer-cost total and the PDF. |
| `title` / `bold` / `underline` / `italic` / `indented` / `space_above` / `color` | Payslip rendering only. |
| `explanation_template` | f-string rendered into `hr.payslip.line.explanation` ("Calculation Explanation"). |
| `account_debit` / `account_credit` | (accounting) `company_dependent` accounts. |
| `not_computed_in_net` | (accounting) "Excluded from Net" — pulled out of the NET account line. |
| `split_move_lines` | (accounting) one move line per distinct payslip-line name. |
| `employee_move_line` | (accounting) put the employee partner/bank on the line; enables per-bank split. |
| `analytic_distribution` | (accounting) analytic for generated move lines. |

Rules shipped by a module carry `modified_by_user` / `created_by_user` flags and an `action_reset_rule()` that restores the module's XML values ([`:444`](../enterprise/hr_payroll/models/hr_salary_rule.py#L444)).

Each computed rule produces `total = amount * quantity * rate / 100.0` ([`_get_payslip_line_total`, hr_payslip.py:1687](../enterprise/hr_payroll/models/hr_payslip.py#L1687)).

### Localdict (salary-rule Python environment)

[`_get_localdict()`](../enterprise/hr_payroll/models/hr_payslip.py#L1626):

| Variable | Meaning |
|---|---|
| `payslip` / `employee` / `version` / `company` | Current records. |
| `payroll_config` | The dated `payroll.config.settings` record for the period — **new in 20**. |
| `worked_days` | Dict by work-entry-type code, e.g. `worked_days['WORK100']`. |
| `inputs` | Dict by **salary rule code**, e.g. `inputs['DEDUCTION'].amount`. |
| `categories` | Running category totals, rolled up through the `hr.salary.rule.category` parent hierarchy. |
| `category_options` | Hours per premium-pay category option carried by the worked-day lines, ancestors included — **new in 20** ([`_get_category_options_data`, :1583](../enterprise/hr_payroll/models/hr_payslip.py#L1583)). |
| `work_entries` | The raw work-entry **value dicts** for this slip's period and versions — **new in 20**. |
| `rules` / `result_rules` | Running per-rule totals. |
| `same_type_input_lines` | Dict code → input recordset, only for codes with **multiple** input lines (drives the once-per-line rule evaluation). |
| `float_round`, `float_compare`, `relativedelta`, `ceil`, `floor`, `date`, `datetime`, `defaultdict`, `UserError`, `_get_payroll_translation` | Helpers ([`_get_base_local_dict`, :1569](../enterprise/hr_payroll/models/hr_payslip.py#L1569)). |

> `property_inputs` is **gone**. Version property values are materialised into `input_line_ids` before computation, so a property-backed rule reads `inputs['CODE']` like any other. `categories` and `category_options` are `DefaultDictPayroll`, which returns 0 for a missing key; `worked_days` and `inputs` are plain dicts — `worked_days['WORK100']` raises KeyError if the line is absent, use `.get()` or `'CODE' in worked_days`. Date-effective constants are still read through `payslip._rule_parameter('CODE')` ([`:1483`](../enterprise/hr_payroll/models/hr_payslip.py#L1483)).

### Default rule chain

| Rule | Code | Formula |
|---|---|---|
| Basic Salary | `BASIC` | `result = payslip._get_basic_salary()` |
| Taxable Salary | `GROSS` | `result = categories['BASIC'] + categories['ALW']` |
| Deduction / Attachment / Assignment / Child Support | `DEDUCTION`, `ATTACH_SALARY`, `ASSIG_SALARY`, `CHILD_SUPPORT` | run only if `'<CODE>' in inputs`; `result = -inputs['<CODE>'].amount` |
| Reimbursement | `REIMBURSEMENT` | run only if the input exists; `result = inputs['REIMBURSEMENT'].amount` |
| Net Salary | `NET` | `result = categories['BASIC'] + categories['ALW'] + categories['DED']` |

Source: [`data/hr_salary_rule_data.xml`](../enterprise/hr_payroll/data/hr_salary_rule_data.xml). Note that `BASIC` carries **no category** (`category_ids` is emptied) while `GROSS`, `DED` and `NET` rules each carry exactly one.

If a payslip has multiple input lines with the same code, the matching rule is evaluated once per input line (multiple payslip lines), then an aggregator proxy is restored in `inputs[code]` ([`__get_aggregator_hr_payslip_input_model`, :2457](../enterprise/hr_payroll/models/hr_payslip.py#L2457)).

### Salary rule categories

Categories are `hr.salary.rule.category` records such as `BASIC`, `ALW`, `DED`, `GROSS`, and `NET`. They do not come from work entries. They come from the **Categories** m2m on each salary rule.

As rules run, each computed rule total is added to every one of its categories and their parents via `_sum_salary_rule_category()` ([`hr_salary_rule_category.py:81`](../enterprise/hr_payroll/models/hr_salary_rule_category.py#L81)). Later rules read those totals as `categories['CODE']`.

Odoo 20 adds a second job to this model — **premium pay**:

| Field | Meaning |
|---|---|
| `optional_on_work_entry_type_ids` | Makes the category selectable as an *option* on leaves/attendances of those time types (the reverse of `hr.work.entry.type.optional_category_ids`). |
| `is_premium_pay` | Marks the category as a premium-pay family. |
| `premium_amount_per_hour` / `premium_amount_per_day` / `premium_percentage_hourly_rate` | The extra paid on top of the legal rate, summed by `_get_premium_pay_additional_amount()` ([`hr_payslip.py:1600`](../enterprise/hr_payroll/models/hr_payslip.py#L1600)). |

Selecting an option on a leave splits its worked-day line, so the same time type can produce several lines with different premiums.

Example:

```python
result = categories['BASIC'] + categories['ALW']
```

That formula means: take the already-computed Basic category total plus the already-computed Allowance category total. If an allowance rule did not run yet, or has total 0, `categories['ALW']` is 0.

---

## Salary Inputs

Odoo 20 collapsed the two v19 input systems into one. **`hr.payslip.input.type` no longer exists**, and neither do `hr.payslip.payslip_properties` or the localdict's `property_inputs`. An input is now defined by the **salary rule that consumes it**.

### Payslip Input (`hr.payslip.input`)

[`models/hr_payslip_input.py`](../enterprise/hr_payroll/models/hr_payslip_input.py). A value row is `salary_rule_id` + `amount` + optional `name`; `code` is related from the rule. The selectable rules are those of the slip's structure that either read an input natively (`condition_select`/`amount_select` = `property_input`) or opted in with `input_usage_payslip` ([`:31`](../enterprise/hr_payroll/models/hr_payslip_input.py#L31)). Rules read `inputs['CODE'].amount`.

Input-related flags on `hr.salary.rule`:

| Flag | Effect |
|---|---|
| `input_usage_payslip` | "Available on Payslip" — the rule can be filled manually on the payslip and targeted by a salary adjustment. |
| `input_usage_employee` | The rule is exposed as a version-level payroll property, so a value can be set on the employee record. |
| `input_selected_by_default` | An input line is seeded on every new payslip, **even at 0** ([`_compute_input_line_ids`, hr_payslip.py:410](../enterprise/hr_payroll/models/hr_payslip.py#L410)). |
| `input_default_value` | The seeded amount. |
| `input_section` | `hr.salary.rule.section` used to group inputs in the UI; defaults to `hr_payroll.default_salary_rule_section`. |
| `input_suffix`, `input_name`, `user_instructions` | Unit suffix, label and inline help shown next to the value. |

For `amount_select == 'property_input'`, `_compute_rule()` returns `(input.amount, 1.0, 100.0)` and **bypasses** `amount_fix`/`amount_percentage`/`amount_python_compute` entirely; a missing input yields 0 ([`hr_salary_rule.py:239`](../enterprise/hr_payroll/models/hr_salary_rule.py#L239)). For `condition_select == 'property_input'` the rule runs only when the input exists **and is non-zero** ([`:272`](../enterprise/hr_payroll/models/hr_salary_rule.py#L272)).

An input row does **not** change Worked Days and does **not** automatically change Net Salary. It changes the result only if a salary rule in the structure uses that code — which, in v20, is the rule that defines it.

**Multiple inputs, same code:** `_get_localdict` keeps them in `same_type_input_lines`; the matching rule is evaluated once per line (one payslip line each), then `inputs[code]` is restored to an aggregator proxy whose `amount` is the sum ([`__get_aggregator_hr_payslip_input_model`, hr_payslip.py:2457](../enterprise/hr_payroll/models/hr_payslip.py#L2457)).

### Version payroll properties are the employee-level input store

`hr.version.payroll_properties` is a `fields.Properties` whose definition is `structure_id.version_properties_definition` ([`hr_version.py:55`](../enterprise/hr_payroll/models/hr_version.py#L55)), and that definition is regenerated from the structure's input rules ([`_sync_properties_to_definition`, hr_payroll_structure.py:76](../enterprise/hr_payroll/models/hr_payroll_structure.py#L76)) — keyed by **rule code**, grouped under `hr.salary.rule.section` separators.

At payslip compute, `_compute_input_line_ids` materialises those values into real input lines ([`hr_payslip.py:339`](../enterprise/hr_payroll/models/hr_payslip.py#L339)):

- Values are copied only when `version.structure_id == slip.struct_id`.
- A code that already has an input line is **never** re-seeded, so manual edits survive recomputation.
- A zero value produces no line unless the rule is `input_selected_by_default`.
- Helpers `_get_property_input_value` / `_set_property_input_value` translate rule code ↔ property key ([`hr_version.py:429`](../enterprise/hr_payroll/models/hr_version.py#L429)). `_set_property_input_value` writes into `payroll_properties` directly — the salary configurator's `source='rule'` benefits use it.

### Ways input lines are created

| Source | How |
|---|---|
| Manual entry | Payroll user adds rows on the Salary Inputs tab; writing them re-runs `compute_sheet()` on a draft slip that already has lines. |
| Version payroll properties | materialised by `_compute_input_line_ids` as above. |
| Salary Adjustments | `_compute_input_line_ids()` sums open `hr.salary.attachment` records into **one line per salary rule code**. |
| `hr_payroll_expense` | one expense line from linked employee-paid expenses. |
| Localization / custom | module logic, or `_set_input_value(code, value)` ([`hr_payslip.py:509`](../enterprise/hr_payroll/models/hr_payslip.py#L509)). |

`_compute_input_line_ids` depends on `employee_id`, `version_id`, `struct_id`, `date_from`, `date_to`, `version_id.payroll_properties` and `employee_id.salary_attachment_ids` ([`:337`](../enterprise/hr_payroll/models/hr_payslip.py#L337)).

### Salary Adjustments (`hr.salary.attachment`)

Garnishments, child support, loan repayments: recurring or limited deductions that auto-inject input lines. UI label **"Payslip Adjustment"**; `_rec_name` is the free-text `description`.

**Shape of the record** ([`models/hr_salary_attachment.py`](../enterprise/hr_payroll/models/hr_salary_attachment.py)):
- `employee_id` is a plain **Many2one** in v20 (the v19 many2many and its `action_split` are gone).
- `salary_rule_id` replaces `other_input_type_id`: any rule with `input_usage_payslip` belonging to a structure of the employee's structure type ([`:45`](../enterprise/hr_payroll/models/hr_salary_attachment.py#L45)).
- `is_recurring` ("Repeat") replaces the v19 `duration_type`: **recurring** = `amount` is taken every payslip and `remaining_amount` always equals `amount` (so it never exhausts); **non-recurring** = `amount` is the total and `remaining_amount = max(0, amount - paid_amount)` ([`:143`](../enterprise/hr_payroll/models/hr_salary_attachment.py#L143)).
- `amount` (per payslip or total, per above), `paid_amount` (running counter), `date_start`, `date_estimated_end`, `date_end` (stamped when closed), `sequence` (**payment priority** — lower first).
- `beneficiary_bank_account_id` + `allow_out_payment`: the third-party account payment reports pay directly (child support, garnishment).
- `is_seized` is computed from the rule's categories against `_get_seized_categories()` ([`hr_salary_rule_category.py:88`](../enterprise/hr_payroll/models/hr_salary_rule_category.py#L88)).

**Injection into payslips** (`_compute_input_line_ids`): the slip drops every input line whose code is backed by one of the employee's adjustments and rebuilds them from the adjustments that are `1_open`, start on or before `date_to`, and have not ended before `date_from`. One line **per salary rule code**, `amount = sum of remaining_amount` ([`_get_active_amount`, :380](../enterprise/hr_payroll/models/hr_salary_attachment.py#L380)), sign-flipped for credit notes; the line name is the joined descriptions. Manually entered lines on other rules are left untouched.

**Lifecycle (event-driven, no cron):** two states, `1_open` (Running) and `2_close` (Done) ([`:76`](../enterprise/hr_payroll/models/hr_salary_attachment.py#L76)). Creating or writing an adjustment immediately re-runs `compute_sheet()` on the affected **draft** payslips (skipped under `install_mode`, [`:218`](../enterprise/hr_payroll/models/hr_salary_attachment.py#L218)). When a payslip is written to `paid`, the payslip `write` hook groups the slip's attachments by rule code, takes the **computed payslip line totals** (not the input amounts) and calls `record_payment` ([`:325`](../enterprise/hr_payroll/models/hr_salary_attachment.py#L325)), which pays priority group by priority group (`sequence`), prorating inside a group when the amount is short, increments `paid_amount`, posts chatter, and calls `action_close()` the moment `remaining_amount` hits 0. Closing stamps `date_end = today` and re-runs `_compute_issues()` on the attached draft/validated slips.

> **Recurring adjustments never auto-close** — `remaining_amount` always equals `amount`, so there is nothing to exhaust; close them manually. `record_payment` raises **UserError** *"The total amount to pay is higher than the total remaining amount…"* if the payslip line total exceeds what is left across the selected adjustments.

**Constraints:** DB CHECKs enforce `amount > 0`, `remaining_amount >= 0` and `date_start <= date_end` ([`:20`–`:32`](../enterprise/hr_payroll/models/hr_salary_attachment.py#L20)). An advisory "similar adjustment found" warning compares open adjustments with the same employee/rule/amount/dates ([`:157`](../enterprise/hr_payroll/models/hr_salary_attachment.py#L157)), and `salary_rule_warning` flags a rule that will not actually consume the value.

**Bulk entry:** `hr.salary.attachment.generate.multi.wizard` ([`wizard/hr_salary_attachment_generate_multi_wizard.py`](../enterprise/hr_payroll/wizard/hr_salary_attachment_generate_multi_wizard.py)) creates the same adjustment for several employees at once — the v20 replacement for the multi-employee record.

**Employee-side visibility:** the employee form exposes `salary_attachment_ids` and the monthly running total, gated to `hr_payroll.group_hr_payroll_user` ([`hr_employee.py`](../enterprise/hr_payroll/models/hr_employee.py)).

---

## Accounting Integration (`hr_payroll_account`)

Source: [`enterprise/hr_payroll_account/`](../enterprise/hr_payroll_account/). `auto_install` with `hr_payroll` + `accountant`.

This module translates computed payslip lines into account move lines at validation. It does not change the computation engine.

### When the journal entry is created — and why it stays draft

`action_payslip_done` (override) calls `_action_create_account_move` for slips with a `journal_id` ([`hr_payslip.py:34`](../enterprise/hr_payroll_account/models/hr_payslip.py#L34)). **The move is created but never posted** — there is no `action_post` anywhere in this module; the final step is `self.env['account.move'].sudo().create(values)` ([`_create_account_move`, :305](../enterprise/hr_payroll_account/models/hr_payslip.py#L305)). The accountant must post it.

> **UI change in Odoo 20:** the confirmation button is labelled **Validate** with or without accounting. The v19 "Create Draft Entry" label is gone ([`hr_payslip_views.xml:21`](../enterprise/hr_payroll_account/views/hr_payslip_views.xml#L21)). The label never proved salary-rule accounts were configured anyway; the move can still have an empty **Journal Items** tab if the rules have no debit/credit accounts.

**Gate conditions** ([`_get_account_move_vals`, :45](../enterprise/hr_payroll_account/models/hr_payslip.py#L45)): a slip gets a move only if it has `struct_id.journal_id` **and** either `state == 'validated'` with **no existing `move_id`**, or `state == 'draft'` while the company has `batch_payroll_move_lines` on. A structure with no journal silently produces no move (and raises the **No Journal** payroll warning). When called from a slip in a run where `_are_payslips_ready()`, the method pulls in the whole batch's slips.

### Batching (`company.batch_payroll_move_lines`)

| Mode | Grouping | Result |
|---|---|---|
| Batched (`True`) | `{journal_id: {date: slips}}` ([`:65`](../enterprise/hr_payroll_account/models/hr_payslip.py#L65)) | **one move per (journal, date) group** for all slips; lines with the same name/account/analytic/tags merged; **no per-employee partner/bank** (anonymized). The **run** gets `move_id` ([`:118`](../enterprise/hr_payroll_account/models/hr_payslip.py#L118)). |
| Per-slip (`False`, default) | list of single-slip groups ([`:71`](../enterprise/hr_payroll_account/models/hr_payslip.py#L71)) | **one move per payslip**; employee partner/bank applied. |

The date key is `slip.date or fields.Date.end_of(slip.date_to, 'month')`. The move `ref` is the month formatted `"%B %Y"`. After creation, the resolved `date` is written back onto the slips ([`:114`](../enterprise/hr_payroll_account/models/hr_payslip.py#L114)).

`slip.date` ("Accounting Date") is itself computed in v20 ([`_compute_date`, :20](../enterprise/hr_payroll_account/models/hr_payslip.py#L20)): `create_date` for a refund slip, `done_date` for a correction slip, otherwise the **end of `date_to`'s month**. It stays editable while the slip is draft.

### Which payslip lines become journal items

`_prepare_slip_lines` ([`:164`](../enterprise/hr_payroll_account/models/hr_payslip.py#L164)) iterates **every** payslip line (the v19 "only lines with a category" filter is gone — rules now have a category *many2many* and may legitimately have none):
1. `amount = line.total`.
2. **NET special-casing:** when `line.code == 'NET'`, the absolute totals of every rule flagged `not_computed_in_net` are removed from NET, toward zero ([`get_accounting_amount`, :177](../enterprise/hr_payroll_account/models/hr_payslip.py#L177)). A rule marked **Excluded from Net** must carry its own debit/credit accounts to land in the move — otherwise its value disappears entirely.
3. Lines whose adjusted amount is zero (to Payroll precision) are skipped.
4. A debit item only if the rule has `account_debit`; a credit item only if it has `account_credit`. A rule with no accounts contributes nothing — hence sparse/empty moves when accounts are unset.

**Storno (credit notes):** if `company.account_storno` AND the slip is a `credit_note`, debit/credit signs are flipped (negative on the original side) instead of mirrored ([`get_debit_credit`, :195](../enterprise/hr_payroll_account/models/hr_payslip.py#L195)). `account_storno` is a company field, on by default for storno-mandatory countries and optional for AT/CH/DE/IT.

### Line merging vs splitting

`merge_amounts = batch_payroll_move_lines or not rule.employee_move_line`. Merging is driven by a `line_index` keyed on **(name, account, analytic distribution)**; inside a key, a candidate merges only when the signs are compatible and the tax tags match ([`_check_debit_credit_tags`, :283](../enterprise/hr_payroll_account/models/hr_payslip.py#L283)). If a merge cancels a line to zero it is dropped from the index. `split_move_lines` ("Split on names") sets the line name to `line.name` instead of `salary_rule_id.name`; since the name is part of the key, enabling it yields one line per distinct payslip-line name.

### Employee partner + per-bank split (`_prepare_line_values`)

[`:123`](../enterprise/hr_payroll_account/models/hr_payslip.py#L123): if **not batched** and the rule has `employee_move_line`, `partner_id = employee.work_contact_id`; otherwise `line.partner_id`. The employee appears on lines only when batching is off (the point of "anonymize" in the setting). If additionally `employee.has_multiple_bank_accounts`, the line is **exploded into one line per bank account** — including the beneficiary accounts of the slip's salary adjustments — via `_compute_salary_allocations()`, each tagged with `employee_bank_account_id` ([`account_move_line.py`](../enterprise/hr_payroll_account/models/account_move_line.py)), the field the register wizard keys on for one-payment-per-bank.

### Analytic distribution

Every line sets `analytic_distribution = rule.analytic_distribution or version.analytic_distribution` — the rule wins, else the version's. Differing analytics force separate move lines (analytic distribution is part of the merge key).

### Rounding adjustment line

After summing debit/credit across the group's lines, if they differ at Payroll precision a single balancing line is injected by `_prepare_adjust_line` ([`:260`](../enterprise/hr_payroll_account/models/hr_payslip.py#L260)): named "Adjustment Entry", no partner, on `journal_id.default_account_id`. **If that account is empty it raises UserError** *"The Expense Journal … has not properly configured the default Account!"*. It reuses an existing adjustment line if one is already present in the group. This absorbs rounding drift (e.g. multi-bank percentage allocations).

### Accounting date & multi-company/currency

`journal_id`, `account_debit`, `account_credit` are all `company_dependent`, and grouping is by journal id, so **cross-company slips never share a move**. Move lines set only `debit`/`credit` (never `currency_id`/`amount_currency`) — always company currency.

### Move lifecycle on cancel / set-to-draft (the part users get blocked by)

`action_payslip_cancel` (override) grabs `move_id`, calls `moves.sudo()._unlink_or_reverse()` **before** super ([`:29`](../enterprise/hr_payroll_account/models/hr_payslip.py#L29)). `_unlink_or_reverse` ([`addons/account/models/account_move.py`](../addons/account/models/account_move.py)) routes each move:

| Bucket | Condition | Move outcome |
|---|---|---|
| **Unlink** | `_can_be_unlinked()` and not audit-protected | reset to draft then `unlink()` — **deleted**, `move_id` cleared |
| **Cancel** | unlinkable but audit-trail protected | `button_cancel()` — kept as cancelled for audit |
| **Reverse** | not unlinkable (hash / lock date / caba) | `_reverse_moves(cancel=True)` — reversing entry created, original kept |

**Net behaviour:** a draft never-posted move is deleted; a posted move on a hashed journal is reversed; a plain posted move with no hash/lock is still reset-to-draft and deleted.

> **Set-to-Draft does NOT touch the move.** There is no `action_payslip_draft` override in `hr_payroll_account`. So re-drafting keeps `move_id`, and re-validating will **not** create a second move (the create gate skips slips that already have one). To actually drop the move, **cancel** the slip.

---

## Payment Paths, Report, and ISO20022

### One wizard, two buttons — and they are not equivalent

`action_payslip_payment_report()` (payslip) and `action_payment_report()` (run) both open **`hr.payroll.payment.report.wizard`** ([`wizard/hr_payroll_payment_report_wizard.py`](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py)). The wizard has two exits:

| Exit | Writes `paid_date`? | Writes `state='paid'`? | Produces a file? | Source |
|---|---|---|---|---|
| **Mark as Paid** (`mark_as_paid`) | yes (`effective_date`) | **yes** — calls `action_payslip_paid()` | only if the mode is not "Manually" | [`:162`](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L162) |
| **Download** (`download_report`) | no | no | yes (returns an `ir.actions.act_url`) | [`:172`](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L172) |

This is the biggest v20 change on this page: in v19 the payment report could only stamp `paid_date`. Now **Mark as Paid lives in the same wizard**, so it also records salary-attachment payments (the `state='paid'` write hook) — and the default mode is **`manual`**, i.e. no file at all.

Two other flags matter:
- `include_unpaid` + `unpaid_payslips` let one run's payment sweep in other validated, still-unpaid slips of the same employees ([`:43`](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L43)); when set, **those** slips are the ones marked paid.
- `generate_payment_report()` refuses outright if any selected slip has `error_count` ([`:150`](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L150)), and `_perform_checks()` requires at least one slip that is `validated` **and** has `net_wage > 0` ([`:127`](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L127)).

The third path — **Register Payment** through Accounting — still exists but has **no payroll button in v20**. `hr_payroll_account` only keeps the two wizard hooks (`_get_line_batch_key`, `_reconcile_payments`); `action_register_payment` on the payslip was removed, and the only shipped caller of the `hr_payroll_payment_register` context is `l10n_au_hr_payroll_account`. Generic databases now pay through the payment-report wizard, or from Accounting on the journal entry itself.

### Payment report fields

Bank-file metadata on **both** payslip and run (the run additionally has `payment_report_format`, filled with the *label* of the export format):

| Field | Payslip | Run | Cleared by |
|---|---|---|---|
| `payment_report` (Binary) / `payment_report_filename` / `payment_report_date` | yes | yes | set-to-draft |
| `payment_report_format` | **no** | yes | set-to-draft |

There is no `payment_report_state`. `_write_file()` ([`:105`](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L105)) names the run's copy "Payment Report - `<run>`" and each payslip's copy "Payment Report - `<period>` - `<legal name>`".

### Export formats

`export_format` is extended by `_get_export_format_selection`. Base ships **Manually** (the default) and **CSV**; `hr_payroll_account_iso20022` adds **SEPA** (its own default) and **Swiss ISO20022**:

| Value | Label | Added by | File |
|---|---|---|---|
| `manual` | Manually | base `hr_payroll` | none |
| `csv` | CSV | base `hr_payroll` | `.csv` |
| `sepa` | SEPA | iso20022 | `.xml` |
| `iso20022_ch` | Swiss ISO20022 | iso20022 | `.xml` |

Which one the wizard opens on is decided by the run: `iso20022_ch` for a CH company, `sepa` for a EUR company, otherwise the base default ([`hr_payslip_run.py:7`](../enterprise/hr_payroll_account_iso20022/models/hr_payslip_run.py#L7)).

The **CSV** writer ([`_create_csv_binary`, :55](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L55)) emits one row **per bank account** (employee accounts *and* salary-adjustment beneficiary accounts), amounts taken from `_compute_salary_allocations()`, with columns *Sequence, Payment Date, Report Date, Payment Period, Employee name, Bank account, BIC, Amount to pay*. Rows for the same account across several payslips are merged and their periods widened.

### SEPA / ISO20022

`_create_sepa_binary` ([`hr_payroll_account_iso20022/wizard/hr_payroll_payment_report_wizard.py:38`](../enterprise/hr_payroll_account_iso20022/wizard/hr_payroll_payment_report_wizard.py#L38)) builds one payment dict per bank account from the same allocations, then calls `journal.create_iso20022_credit_transfer(..., payment_method_line=…, batch_booking=True)`. `batch_booking=True` means the bank posts **one consolidated debit** while each employee still receives an individual credit.

New in v20: the wizard requires a **`payment_method_line_id`** (an outbound `sepa_ct` / `iso20022_ch` method on the chosen bank journal) and a **`sepa_priority`** of Standard / High / **SCT (Instant Credit Transfer)**; `iso20022_priority` is `HIGH` for anything but Standard. For `pain.001.001.09` the wizard stamps a per-slip `iso20022_uetr` UUID.

`_perform_checks()` overrides ([`:97`](../enterprise/hr_payroll_account_iso20022/wizard/hr_payroll_payment_report_wizard.py#L97)) add: payment date not in the past; every employee has a work contact **with a name**; the journal's bank account is an IBAN; a payment method line exists.

> This file export creates and reconciles **nothing**. Use Accounting's own Register Payment on the posted journal entry if you need reconciled `account.payment` records.

### Register Payment grouping & reconciliation (when a localization wires it up)

`_get_line_batch_key()` override ([`account_payment_register.py:11`](../enterprise/hr_payroll_account/wizard/account_payment_register.py#L11)): if a line carries `employee_bank_account_id` → that bank becomes `partner_bank_id` (one payment per employee bank); else, with `payment_consider_partner` in context, fall back to the partner's first bank by sequence.

`_reconcile_payments()` ([`:24`](../enterprise/hr_payroll_account/wizard/account_payment_register.py#L24), only under the `hr_payroll_payment_register` context) posts a chatter link, then writes `state='paid'` + `paid_date` **only if every move-line residual is zero**:

| Situation | Result |
|---|---|
| Partial payment (amount < net) | stays **`validated`**; payment exists, partially reconciled |
| Multi-bank, only one account paid | stays `validated` until **all** payable lines reconcile |
| Full payment | becomes `paid` |
| Currency rounding leaves a sub-cent residual | stays `validated` |

> The chatter "Payment done at …" is posted **regardless** of the residual test. Undoing a `paid` via `action_payslip_unpaid()` flips the slip back to `validated` but does **not** un-reconcile the `account.payment`.

**Salary allocation split** `_compute_salary_allocations()` ([`hr_payslip.py:2514`](../enterprise/hr_payroll/models/hr_payslip.py#L2514)) is what both the CSV and the SEPA writer call. It allocates, in order: adjustment beneficiary accounts first (paid from the computed deduction line totals, so child support goes straight to the beneficiary); then, if the employee has a single account, the whole remainder to `primary_bank_account_id`; otherwise fixed-amount accounts, then percentage accounts with the **last** one absorbing the rounding remainder. It raises **ValidationError** *"Allocated amounts surpass the net salary"* / *"…are less than the net salary"* when they do not reconcile. For a correction slip it allocates `correction_net_delta`, not the full net. `safe_compute_salary_allocations()` ([`:2582`](../enterprise/hr_payroll/models/hr_payslip.py#L2582)) is the UI-facing wrapper that returns the error as data instead of raising.

---

## Input Integrations

Only two bridges still feed a payslip in Odoo 20: attendance (through the work-entry values and time rules) and expense (through `input_line_ids`). `hr_payroll_planning` and `hr_payroll_sale_commission` were removed.

### `hr_payroll_attendance`

Depends on `hr_attendance_gantt`, `hr_holidays_attendance` and `hr_payroll`; `auto_install`.

The real injection happens in community `hr_holidays_attendance`: for a version with `attendance_based = True`, `_get_version_work_entries_values()` reads **validated** `hr.attendance` records (`check_out` set, `state = 'validated'`) plus working-time leaves and turns them into work-entry values ([hr_version.py:35](../addons/hr_holidays_attendance/models/hr_version.py#L35)). Overtime is no longer a separate `hr.attendance.overtime` pipeline — it is produced by `hr.time.rule` (see [Time rules](#time-rules-hrtimerule--the-overtimeundertime-engine)).

What the enterprise bridge adds ([enterprise/hr_payroll_attendance](../enterprise/hr_payroll_attendance/)):

| Addition | Effect |
|---|---|
| `hr.attendance.category_options_ids` | premium-pay categories selectable on an attendance, propagated into the worked-day line |
| `hr.attendance.payslip_id` + **Payslip** button | links an attendance to the slip covering it |
| `hr.payslip.attendance_count` / `attendance_based` | Attendances stat button on the payslip |
| `hr.time.rule._get_output_attendance_vals()` | how a rule's excess/deficit is written back as an attendance |
| Warning **Attendance Discrepancies** | dashboard/record warning on `hr.employee` ([data/hr_payroll_attendance_warning_data.xml](../enterprise/hr_payroll_attendance/data/hr_payroll_attendance_warning_data.xml)) |
| `_get_start_payrun_warnings()` override | a fourth pre-flight check when starting a pay run |

**Blockers/edge cases:** an attendance with no `check_out` produces nothing; an attendance that is not `validated` produces nothing; changing an attendance re-triggers the time rules on write, which can silently change a *draft* payslip's overtime.

### `hr_payroll_expense`

Depends on `hr_expense` + `hr_payroll_account`; `auto_install`. Rewritten in v20 around **products and salary rules** instead of a hardcoded `EXPENSES` input type.

- An expense product carries `salary_rule_ids` ([product_template.py](../enterprise/hr_payroll_expense/models/product_template.py)) — salary rules with `condition_select = 'property_input'` and `input_usage_payslip`. A constraint refuses more than one rule per structure and refuses any rule whose `account_debit` is not of type **`liability_payable`**.
- Candidate expenses are `state in ('approved', 'posted')`, **`payment_mode = 'payslip_account'`** (renamed from `own_account`), `refund_in_payslip = True`, `payslip_id = False` ([`_get_employee_expenses_to_refund_in_payslip`, hr_payslip.py:67](../enterprise/hr_payroll_expense/models/hr_payslip.py#L67)).
- They are linked to a draft slip at create and at set-to-draft ([`_link_expenses_to_payslip`, :75](../enterprise/hr_payroll_expense/models/hr_payslip.py#L75) — payroll users only, `AccessError` otherwise), and summed **per resolved salary rule** into input lines by `_update_expense_input_line_ids()` ([`:95`](../enterprise/hr_payroll_expense/models/hr_payslip.py#L95)). Rules that lost their expenses are reset to 0 rather than left stale.
- Cancelling the slip unlinks the expenses so they can go on the next one; removing the input line detaches the expense ([`_update_expenses`, :130](../enterprise/hr_payroll_expense/models/hr_payslip.py#L130)).
- When the payslip move posts, `account.move._post()` reconciles the expense move's payable line against the rule's payable line, **skipping silently** when the reconcile wizard reports a required write-off or forced partial ([account_move.py:10](../enterprise/hr_payroll_expense/models/account_move.py#L10)).

**Blockers:** reporting a non-approved/posted or non-payslip-mode expense → UserError *"Only approved and posted expenses with payslip reimbursement can be reported in the next payslip."* ([hr_expense.py:91](../enterprise/hr_payroll_expense/models/hr_expense.py#L91)); a product with no salary rule for the employee's structure → UserError *"Please add a Salary Rule belonging to Expense Product …"* ([`:103`](../enterprise/hr_payroll_expense/models/hr_expense.py#L103)); removing an expense from a validated slip, or adding one without payroll rights → UserError ([`:143`](../enterprise/hr_payroll_expense/models/hr_expense.py#L143), [`:258`](../enterprise/hr_payroll_expense/models/hr_expense.py#L258)).

### `hr_payroll_fleet`

**Injects nothing into payslips.** In v20 it adds two fields to `fleet.vehicle.model` — `can_be_requested` (company-dependent) and `default_car_value` — used by the salary configurator, and ships **one** dashboard warning: *Drivers Without Running Contract* ([data/hr_payroll_warning_data.xml](../enterprise/hr_payroll_fleet/data/hr_payroll_warning_data.xml)). The v19 second warning ("Employees With Multiple Company Cars") is gone. Company-car benefit-in-kind is implemented in **country localizations** (e.g. Belgian payroll), not this generic bridge.

---

## Contract Salary Configurator → Payroll

How an offer/salary-package produces the `hr.version` payroll consumes (the handoff only, not the recruitment funnel). `hr_contract_salary_payroll` and `hr_contract_salary_holidays` were folded away in v20: the benefit model and the payroll-side version fields now live in **`hr_payroll`**, and `hr_contract_salary` depends on `hr_payroll` directly.

### The version, not the offer, is what payroll reads

`hr.contract.salary.offer` is a staging record; payroll never reads it. The offer becomes a version two ways:
1. **Simulation** (preview numbers): `hr.version._generate_salary_simulation_payslip()` ([hr_version.py:218](../enterprise/hr_contract_salary/models/hr_version.py#L218)) creates a payslip under the `salary_simulation` context, fabricates a single worked-day line from the calendar (no leaves), and optionally re-scales the calendar for a part-time simulation. Nothing is persisted for payroll.
2. **Real signature**: `create_new_version` ([main.py:663](../enterprise/hr_contract_salary/controllers/main.py#L663)) persists a version with `active=False`; `_update_version_on_signature` ([main.py:52](../enterprise/hr_contract_salary/controllers/main.py#L52)) flips it `active=True` once **every** signatory has signed (`nb_wait == 0`), archiving the employee's previous version — nudging `date_version` by a day first when the two collide.

So a `half_signed` offer leaves an inactive version that payroll ignores; only `active=True` (driven by the sign request, not the `state` field) matters.

### The numbers and which one payroll uses

| Field | Meaning | Defined |
|---|---|---|
| `final_yearly_costs` | total yearly employer budget (the configurator slider) — **now on `hr.version` in `hr_payroll`** | [hr_version.py:74](../enterprise/hr_payroll/models/hr_version.py#L74) |
| `hr.contract.salary.offer.final_yearly_costs` | the offer's own stored budget, computed back from the version's gross | [hr_contract_salary_offer.py:83](../enterprise/hr_contract_salary/models/hr_contract_salary_offer.py#L83) |
| `wage` | monthly gross stored on the version — **what payroll computes against** by default | base `hr.version` |
| `holidays` | "Extra Time Off" days sacrificed from the wage | [hr_version.py:71](../enterprise/hr_payroll/models/hr_version.py#L71) |

> **Removed in v20:** `wage_with_holidays` and `wage_on_signature` no longer exist anywhere in the tree. The v19 trap where a Belgian payslip silently read a stale `wage_on_signature` is gone — `_get_contract_wage_field()` now returns `hourly_wage` for hourly contracts ([hr_version.py:540](../enterprise/hr_payroll/models/hr_version.py#L540)), and the BE override only chooses between the flexi and the normal wage field ([l10n_be_hr_payroll/hr_version.py:2057](../enterprise/l10n_be_hr_payroll/models/hr_version.py#L2057)).

The conversion between budget and gross runs through `_get_wage_from_yearly_costs()` / `_get_employer_costs_from_gross()` on the version, called from the offer's compute ([hr_contract_salary_offer.py:213](../enterprise/hr_contract_salary/models/hr_contract_salary_offer.py#L213)).

### Benefits → version fields or payslip inputs

`hr.contract.salary.benefit` now lives in `hr_payroll` ([models/hr_contract_salary_benefit.py](../enterprise/hr_payroll/models/hr_contract_salary_benefit.py)) and is seeded from [`data/hr_contract_salary_benefits_data.xml`](../enterprise/hr_payroll/data/hr_contract_salary_benefits_data.xml). Its `source` maps a choice either to a real version field (`source='field'`, via `res_field_id`) or to a **salary rule** (`source='rule'`, via `salary_rule_id`), in which case the chosen value is written into `version.payroll_properties` under the rule's code and materialised as a payslip input at compute time.

> **Gotcha:** `_set_property_input_value` writes into `payroll_properties` keyed by rule **code** ([hr_version.py:436](../enterprise/hr_payroll/models/hr_version.py#L436)). If a benefit value "won't stick", check that the rule is part of the version's structure — `_compute_input_line_ids` only copies property values when `version.structure_id == slip.struct_id`. Also: `get_values_from_contract_template` copies only a whitelist, which `hr_payroll` extends with `payroll_properties` and `hourly_wage` ([`_get_whitelist_fields_from_template`, hr_version.py:639](../enterprise/hr_payroll/models/hr_version.py#L639)); other custom fields used by salary rules are **not** inherited from the template.

### Offer states (informational for payroll)

`open` (In Progress) → `half_signed` (Partially Signed) → `full_signed` (Fully Signed), plus `expired` / `refused` / `cancelled` ([hr_contract_salary_offer.py:65](../enterprise/hr_contract_salary/models/hr_contract_salary_offer.py#L65)). Activation is driven off the sign-request counters, not the state: employee-signed-only (`nb_closed == 1`, `nb_wait > 0`) → `half_signed`, version still inactive; all signers done (`nb_wait == 0`) → `full_signed`, version `active=True`, prior version archived.

### Extra holidays

`hr_contract_salary_holidays` is gone. `version.holidays` still reduces the wage through the configurator's cost maths, but **this module no longer creates the matching `hr.leave.allocation`** — the v19 `hr_contract_timeoff_auto_allocation` company setting does not exist in the v20 tree. If your process relies on an allocation being created at countersignature, verify it in your localization or create it yourself.

---

## Scheduled Actions, Async PDF, and Documents

### Crons

| XML id | Name | Method | Cadence | What it does |
|---|---|---|---|---|
| `hr_payroll.ir_cron_update_payroll_data` | Payroll: Update data | `hr.payslip._update_payroll_data()` | weekly (day 20) | Reloads static data from `_get_data_files_to_update()`. Base returns `[]`; localizations override it to reload salary rules/tables. |
| `hr_payroll.ir_cron_generate_payslip_pdfs` | Payroll: Generate pdfs | `hr.payslip._cron_generate_pdf()` | hourly | Renders queued payslip + declaration PDFs in batches of 30; self-retriggers. |
| `hr_payroll.ir_cron_send_payroll_warning_email_alert` | Payroll: Warning Email Alert | `hr.payroll.warning._cron_payroll_warning_email_alert()` | daily | Emails the warnings whose `email_alert_days` has elapsed. **New in 20.** |
| `hr_payroll.ir_cron_generate_payrun_for_employee_types_with_auto_post` | Payroll: Generate payrun for employee types with auto post | `hr.payslip.run._cron_generate_payrun_for_employee_types_with_auto_post()` | daily | Creates pay runs automatically for employee types configured to auto-post. **New in 20.** |
| `hr_attendance` / `hr_holidays` day & week time-rule crons | — | `_cron_process_day_undertime_rules()` / `_cron_process_week_time_rules()` | daily | Apply undertime and weekly time rules that the write-time trigger deliberately skips. |

Source: [`data/ir_cron_data.xml`](../enterprise/hr_payroll/data/ir_cron_data.xml). **The work-entry generation cron is gone** (there are no work-entry records to generate), and there is no salary-attachment cron — adjustments close on payment.

### Asynchronous payslip PDF generation

PDFs are **not** generated synchronously on validation. `action_payslip_done` ([`hr_payslip.py:1024`](../enterprise/hr_payroll/models/hr_payslip.py#L1024)) only acts when `payslip_generate_pdf` is in context (the Validate buttons put it there):

- `payslip_generate_pdf_direct`, or a batch of ≤ 5 slips whose company trigger is `on_confirmed` and whose PDF engine is installed → inline `_generate_pdf()` (blocking).
- otherwise, for each company whose `payslip_generate_and_send_trigger` is `on_confirmed` → `_queue_for_send()` ([`:959`](../enterprise/hr_payroll/models/hr_payslip.py#L959)), which sets `queued_for_pdf=True` and `_trigger()`s the hourly cron.
- `action_payslip_paid` does the same for companies whose trigger is `on_paid`.

`_cron_generate_pdf` ([`:2429`](../enterprise/hr_payroll/models/hr_payslip.py#L2429)) processes the first 30 queued `validated`/`paid` slips, clears the flag, then does declarations, self-retriggering. `_generate_pdf` ([`:885`](../enterprise/hr_payroll/models/hr_payslip.py#L885)) groups slips by report (`struct_id.report_id` else default), renders in the **employee's language**, stores an attachment, registers it as the main attachment, and **only then** sends the payslip email. Under `is_test_print` (the pay run's **Test Print** button) it stops after attaching and sends nothing.

The company setting `payslip_generate_and_send_trigger` (`never` / `on_confirmed` / `on_paid`) is what decides all of this ([res_company.py:62](../enterprise/hr_payroll/models/res_company.py#L62)). With `never`, the pay run shows an explicit **Send by email** button instead.

> `queued_for_pdf=True` means validated but PDF not yet rendered. A stalled/disabled cron means **no PDF and no employee email** until it runs.

### Documents bridge (`documents_hr_payroll`)

Depends on `documents_hr` + `hr_payroll`. It hooks `_pdf_post_create()` ([hr_payslip.py:78](../enterprise/documents_hr_payroll/models/hr_payslip.py#L78)) — the hook `_generate_pdf` calls right after creating the attachments — to file them into Documents, and overrides `_check_send_payslip_mail()` so the payslip email is only sent when a document was actually created ([`:105`](../enterprise/documents_hr_payroll/models/hr_payslip.py#L105)). Document folder, members and access rights come from `_get_document_folder()` / `_get_document_members()` / `_get_document_vals_access_rights()`.

It also extends `_cron_generate_pdf` with a declaration-posting stage, adds the **Send by Email** wizard (`payslip.send.mail`) and a declaration-overwrite wizard, and ships the *Missing Contact Information* payroll warning. `action_resend_payslips` refuses if a slip is not validated/paid or an employee has no email. Declarations advance `draft → pdf_to_generate → pdf_generated → pdf_to_post → pdf_posted`.

---

## Changing Salary and Version Dates

The relevant version for a payslip is the one active at `date_from` (`slip.version_id = employee._get_version(date_from)`, [`hr_payslip.py:1964`](../enterprise/hr_payroll/models/hr_payslip.py#L1964)).

| Change | Effect |
|---|---|
| Edit wage on the current version | Recomputed draft slips use the new wage; validated slips raise the **Wrong Employees Data** warning (`has_wrong_data`). |
| New version dated first day of the period | New wage applies cleanly. |
| New version mid-period, same contract dates | `_compute_worked_days_line_ids` pulls in the **concurrent** version too, so one payslip carries worked-day lines for both spans. |
| New contract mid-period | `_get_contracts` returns both versions, so the pay run produces **two payslips** for that employee. |

> When a validated slip's source version changed afterwards, use **Correct** (the Payslip Correction wizard) or **Keep it as is** (`keep_wrong_version`). The dedicated **Salary Increase** wizard does both in one pass: it creates the new versions and then offers to correct every payslip the increase invalidated ([`hr_payroll_salary_increase_wizard.py`](../enterprise/hr_payroll/wizard/hr_payroll_salary_increase_wizard.py)). Recommended practice: make raises effective on the first day of a pay period.

---

## Configuration & Debug Checklists

### Accounting configuration

1. Install `hr_payroll_account` (it is `auto_install` with `accountant`).
2. Set the **Salary Journal** on the structure (`struct_id.journal_id`) — in company currency.
3. Configure rule debit/credit accounts: expense/debit for costs; payable/credit on `NET`; deduction/reimbursement as needed. Mark the `NET` credit account **reconcilable**.
4. Set the salary journal's **default account** (absorbs the rounding adjustment line).
5. Compute slips; verify `line_ids` are not empty and `error_count` is 0.
6. Validate; open the move and verify meaningful lines; **post it** in Accounting.
7. Pay through the payment wizard (Mark as Paid), or register the payment from Accounting and reconcile.

> **Empty journal-entry gotcha:** salary computation lines and journal items are different things. If a payslip has computed salary lines but the related salary rules have no Debit/Credit accounts, Odoo still creates the draft `account.move` header, but `_prepare_slip_lines()` creates no journal items for those rules. The result is a draft journal entry with an empty **Journal Items** tab. Configure the salary-rule accounts, then cancel and re-validate the slip.

### Debug checklist (what to inspect, in order)

1. **Run period and structure** — `date_start`/`date_end`/`structure_id`/`employee_type_ids`; the run's `state` (`00_draft` means payslips were never generated).
2. **Issues first** — `error_count`/`warning_count`/`issues`/`state_display`. A red **Blocked** badge means a danger warning is blocking; resolve it before anything else. Check Payroll → Configuration → Payroll Warnings for anything with **Block Payslips**.
3. **Worked days** — types, hours, days, `amount_rate` on the time type (this is what makes a line unpaid), `is_extra_hours`, `category_options_ids`, the `000.00` out-of-contract line, the `edited` flag (frozen amounts). There are no work-entry records to inspect: read the working schedule, the leaves and the attendances instead.
4. **Time off** — any overlapping leave still pending, or `payslip_state = 'blocked'` (→ the *Leaves to defer* warning, resolved by a correction payslip).
5. **Time rules** — an unexpected overtime/undertime line means an `hr.time.rule` matched. Check `condition_work_entry_type_ids`, `employee_domain`, thresholds and `sequence`.
6. **Version** — `version_id` vs `employee._get_version(date_from)`; `wage_type`, `wage`, `hourly_wage`, `schedule_pay`, `resource_calendar_id`, `attendance_based`; the drift detectors (`is_wrong_version`, `has_wrong_data`, `has_wrong_leaves`).
7. **Inputs** — expected codes present; the rule that defines each input has `input_usage_payslip`; salary adjustments open and in range; expense injections.
8. **Salary lines** — rule codes, sequence, `round_of_computation`, categories, totals; whether the rule ran and whether its categories feed later formulas. `hr.payslip.line.explanation` shows the rendered explanation template.
9. **Accounting** — `struct_id.journal_id`; rule accounts; `move_id`/`move_state`; rounding adjustment.
10. **Payment** — move posted; `NET` credit account reconcilable; employee bank trusted; all residuals zero.

---

## Rule Parameters (`hr.rule.parameter`) — date-versioned constants

Two models: the header (`name`, `code`, `country_id`, `description`) and dated values `hr.rule.parameter.value` ([hr_rule_parameter.py](../enterprise/hr_payroll/models/hr_rule_parameter.py) / [hr_rule_parameter_value.py](../enterprise/hr_payroll/models/hr_rule_parameter_value.py) — the value model was split into its own file in v20). A value is any `safe_eval`-able Python literal (number, dict, table) with a `date_from`; lookup returns the latest value whose `date_from <= date`. Rules call `payslip._rule_parameter('CODE')` — the reference date defaults to **`payslip.date_to`** ([hr_payslip.py:1483](../enterprise/hr_payroll/models/hr_payslip.py#L1483)). This is the right home for legal constants that change per year (minimum wage, caps, tax tables) instead of hardcoding them in rule code.

Lookup mechanics ([`_get_parameter_from_code`, :38](../enterprise/hr_payroll/models/hr_rule_parameter.py#L38)): a `search(limit=1)` on `hr.rule.parameter.value` ordered `date_from desc`, evaluated, and cached with `@api.ormcache('code', 'date', 'frozenset(self.env.companies.ids)')` ([`:50`](../enterprise/hr_payroll/models/hr_rule_parameter.py#L50)); the result is `deepcopy`'d so a rule cannot mutate the cache. Values are validated as parseable Python at save time, and `(parameter, date_from)` is unique — creating a duplicate **replaces** the existing value ([hr_rule_parameter_value.py:40](../enterprise/hr_payroll/models/hr_rule_parameter_value.py#L40)).

Gotchas: no value at the date → UserError *"No rule parameter with code … was found for <date>"*; `code` is enforced unique **across countries** by a partial unique index on active records ([`:33`](../enterprise/hr_payroll/models/hr_rule_parameter.py#L33)) and the search has no country clause — but the company-less `ir.access` restriction hides parameters/values whose country isn't among the user's companies' countries, so a wrong-country lookup fails with the not-found UserError rather than returning the other country's value (this is why company ids are in the cache key). Any create/write of a value calls `self.env.transaction.invalidate_ormcache()` — the v20 replacement for `registry.clear_cache()` — so don't script mass edits on a busy server. Every value change is tracked on the parameter's chatter.

## Payroll properties (the version-level input store)

This is the section that in v19 described a *parallel* input system. In Odoo 20 it is simply **where employee-level input values are stored**, and it feeds the ordinary `hr.payslip.input` rows:

- The **structure** holds one Properties definition, `version_properties_definition`, rebuilt from its own input rules ([hr_payroll_structure.py:76](../enterprise/hr_payroll/models/hr_payroll_structure.py#L76)) and grouped under `hr.salary.rule.section` separators.
- The **version** stores values in `payroll_properties`, whose definition follows `structure_id.version_properties_definition` ([hr_version.py:55](../enterprise/hr_payroll/models/hr_version.py#L55)). `hr.employee.payroll_properties` is the related field.
- Property keys are the **salary rule `code`** (v19 used `str(rule.id)`).
- A rule participates by setting `condition_select`/`amount_select` to `property_input`, or `input_usage_employee` / `input_selected_by_default`.
- `hr.payslip.payslip_properties` and the localdict's `property_inputs` are **gone**: values are materialised into `input_line_ids` at compute time, so rules read `inputs['CODE']`.

Gotchas: values are copied only when `version.structure_id == slip.struct_id`, so an off-cycle structure sees none of them; an existing input line is never overwritten by a property value, so a manual edit sticks; `_set_property_input_value` silently does nothing useful if the rule is not part of the version's structure.

## Headcount snapshots (`hr.payroll.headcount`)

Manual, stateless report: pick a date range → `action_populate()` creates one line per employee with a contract overlapping the range (most recent in-range version), showing the wage and every distinct working rate the employee had in range ([hr_payroll_headcount.py:53](../enterprise/hr_payroll/models/hr_payroll_headcount.py#L53)). Repopulating wipes lines. No cron, no lifecycle. `hr_contract_salary` extends the line with `final_yearly_costs` ([hr_payroll_headcount.py](../enterprise/hr_contract_salary/models/hr_payroll_headcount.py)).

## Declarations framework (`hr.payroll.declaration.mixin`)

Abstract scaffolding for yearly per-employee declaration sheets (year selector, employee lines, batch PDF). Lines are generic pointers (`res_model` + `res_id`) with a PDF lifecycle driven by the **same cron as payslip PDFs**. In bare `hr_payroll` it is dormant — every concrete sheet is l10n (BE 281.x, IN, KE, CH, HK); `documents_hr_payroll` adds post-to-Documents states and an overwrite wizard. Relevant to us only as the sanctioned pattern if we ever build Georgian yearly employee declarations.

## Payroll warnings are configurable records

See [The issues system is now data-driven](#the-issues-system-is-now-data-driven). `hr.payroll.warning` replaced `hr.payroll.dashboard.warning`: same "admins can add custom company checks" idea, but a warning can now also render **on the record** (employee, version, payslip, time off), block validation, carry a due date and an email alert, and be snoozed. A broken warning no longer kills the panel — it is serialized as its own error card ([`_serialize_error_card`, hr_payroll_warning.py:653](../enterprise/hr_payroll/models/hr_payroll_warning.py#L653)). `hr.payroll.note` (the dashboard sticky notes) was removed.

## YTD (year-to-date) mechanics

Opt-in **per structure** (`ytd_computation`); the company sets the reset anchor (`ytd_reset_day` / `ytd_reset_month`, Feb 29 rejected). `_get_last_ytd_payslips()` ([hr_payslip.py:1704](../enterprise/hr_payroll/models/hr_payslip.py#L1704)) finds, per employee and structure, the latest payslip since the reset date; each line's `ytd` is that line's previous ytd plus this line's total. The reference date is `_get_ytd_reference_date()` (default `date_to`) and the SQL pre-filter field `_get_ytd_date_field()` — both overridable by localizations that pay on a different date. Worked-days lines get the same treatment during `compute_sheet` (`_compute_worked_days_ytd`).

## Payslip line math & styling

Lines are dumb storage: `total = amount × quantity × rate / 100` computed at generation via the overridable hook `_get_payslip_line_total` ([hr_payslip.py:1687](../enterprise/hr_payroll/models/hr_payslip.py#L1687)). Per `amount_select`: fix → `(amount_fix, eval(quantity), 100)`; percentage → `(eval(base), eval(quantity), pct)`; `property_input` → `(input.amount, 1, 100)`; code → `(result, result_qty, result_rate)`. The rule's `title`/`bold`/`italic`/`underline`/`indented`/`space_above`/`color` flags exist purely for payslip rendering via `get_payslip_styling_dict` ([hr_payslip_line.py:99](../enterprise/hr_payroll/models/hr_payslip_line.py#L99)). New in v20: `hr.payslip.line.explanation` (rendered from the rule's `explanation_template`), `employer_cost`, and `manually_modified`.

## Version-side payroll extension facts (beyond wage types)

- `schedule_pay` is computed from `structure_type_id.default_schedule_pay`, stored and editable.
- `work_time_rate` = version hours_per_week ÷ company calendar hours_per_week; it is what `hr.payslip.worked_days.fte` multiplies.
- "Occupations": `_get_occupation_dates` stitches consecutive versions with the same contract type + work-time rate, tolerating small gaps — the seniority primitive l10n logic builds on — a gap of 4 days or more breaks the occupation ([hr_version.py:475](../enterprise/hr_payroll/models/hr_version.py#L475)).
- `_get_fields_that_recompute_payslip()` returns `['wage', 'hourly_wage', 'payroll_properties']` ([hr_version.py:613](../enterprise/hr_payroll/models/hr_version.py#L613)); writing one of those on a version recomputes the affected draft payslips.
- `_preprocess_work_hours_data()` is the documented hook `hr_payroll_attendance` uses to adjust the hours dict before worked-day lines are built.

## Settings reference (`res.config.settings`)

[`models/res_config_settings.py`](../enterprise/hr_payroll/models/res_config_settings.py): `module_hr_payroll_account_iso20022` (SEPA export), the two YTD reset fields (with a two-fields-at-once write workaround for the company constraint), `payslip_generate_and_send_trigger`, `deferred_time_off_manager`, `first_payrun_date` and `payroll_closing_date`. `batch_payroll_move_lines` lives in `hr_payroll_account`.

Separately, `payroll.config.settings` ([models/payroll_config_settings.py](../enterprise/hr_payroll/models/payroll_config_settings.py)) is a **dated, versioned company payroll configuration** — new in Odoo 20. Each record covers a period (`date_version` → computed `date_start`/`date_end`), branches inherit from a parent company's config, and a payslip stores the one in force via `payroll_config_id`. Changing it after a payslip was validated raises the *Wrong Company Data* warning. Localizations put their company-level payroll constants on this model instead of on `res.company`, so they become history-aware. The **Set Schedule** wizard ([wizard/hr_payroll_set_schedule_wizard.py](../enterprise/hr_payroll/wizard/hr_payroll_set_schedule_wizard.py)) is the onboarding step that sets `first_payrun_date`, `payroll_closing_date` and the company calendar.

---

## What Changed in Odoo 20

Only material changes; each verified against the v20 source.

- **`hr.work.entry` was deleted.** Work entries are transient value dicts returned by `hr.version.generate_work_entries()` — no records, no state machine, no conflicts, no "undefined slots", no generation cron, no regeneration wizard, no validation on confirm — [hr_version.py:303](../addons/hr_work_entry/models/hr_version.py#L303).
- **New `hr.time.rule`** replaces the attendance-overtime pipeline: threshold rules that re-type excess/deficit time on attendances and leaves, driven from write hooks and two daily crons — [hr_time_rule.py:111](../addons/hr_work_entry/models/hr_time_rule.py#L111).
- **`hr.leave.type` is gone**; a leave points straight at an `hr.work.entry.type`, which now carries validation type, allocation and unit configuration — [hr_leave.py:167](../addons/hr_holidays/models/hr_leave.py#L167).
- **`work_entry_source` is gone.** The only switch is the boolean `attendance_based`, read through `has_static_work_entries()` — [hr_version.py:15](../addons/hr_holidays_attendance/models/hr_version.py#L15).
- **Modules removed:** `hr_payroll_holidays`, `hr_work_entry_holidays(_enterprise)`, `hr_work_entry_enterprise`, `hr_work_entry_attendance`, `hr_work_entry_planning`, `hr_payroll_planning`, `hr_payroll_sale_commission`, `hr_contract_salary_payroll`, `hr_contract_salary_holidays`. Their live code moved into `hr_payroll`, `hr_holidays` and `hr_work_entry` — [hr_payroll/__manifest__.py](../enterprise/hr_payroll/__manifest__.py).
- **Warnings are data.** `hr.payroll.dashboard.warning` → `hr.payroll.warning`, which also renders on employee/version/payslip/time-off records, can **block validation**, carries a due date, email alert and snooze; the hardcoded `_get_errors_by_slip` / `_get_warnings_by_slip` are gone — [hr_payroll_warning.py](../enterprise/hr_payroll/models/hr_payroll_warning.py).
- **New pay run state `00_draft`** (versions selected, payslips not generated) and a pre-flight warning dialog before the run is even created — [hr_payslip_run.py:216](../enterprise/hr_payroll/models/hr_payslip_run.py#L216), [`:428`](../enterprise/hr_payroll/models/hr_payslip_run.py#L428).
- **Validation is group-gated.** `action_payslip_done` requires `hr_payroll.group_hr_payroll_officer` — a new middle group between Assistant and Administrator — and `compute_sheet` no longer blocks on `error_count` — [hr_payslip.py:980](../enterprise/hr_payroll/models/hr_payslip.py#L980), [hr_payroll_security.xml:18](../enterprise/hr_payroll/security/hr_payroll_security.xml#L18).
- **`hr.payslip.input.type` was deleted.** An input is defined by the salary rule that consumes it (`input_usage_payslip` and friends); `hr.salary.rule.category_id` became `category_ids` and `struct_id` became `struct_ids` — [hr_payslip_input.py:22](../enterprise/hr_payroll/models/hr_payslip_input.py#L22), [hr_salary_rule.py:27](../enterprise/hr_payroll/models/hr_salary_rule.py#L27).
- **Unpaid is a property of the time type.** `hr.payroll.structure.unpaid_work_entry_type_ids` is gone; `is_paid = work_entry_type_id.amount_rate != 0` — [hr_payslip_worked_days.py:51](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L51).
- **The payment wizard can mark slips paid.** `mark_as_paid()` writes `state='paid'` (default export mode is now "Manually"), while `action_register_payment` was removed from the payslip — [hr_payroll_payment_report_wizard.py:162](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L162).
- **Security rebuilt**: `security/ir.access.csv` replaces `ir.model.access.csv` + the `ir.rule` records; country and company restrictions are now rows with an empty `group_id` — [ir.access.csv](../enterprise/hr_payroll/security/ir.access.csv).

---

## Appendix A — Blockers Catalog

Every user-facing `UserError`/`ValidationError` in the payroll flow, with trigger and resolution. The whole v19 "work entries" block is gone — there is no work-entry record to conflict, validate or regenerate.

### Payslip & pay run

| Exception & message | Trigger | Source |
|---|---|---|
| ValidationError "You do not have sufficient permissions to validate payslips." | validating without `group_hr_payroll_officer` | [hr_payslip.py:981](../enterprise/hr_payroll/models/hr_payslip.py#L981) |
| ValidationError = list of blocking warning names | a `hr.payroll.warning` with **Block Payslips** matches the slip or its employee | [hr_payslip.py:984](../enterprise/hr_payroll/models/hr_payslip.py#L984) |
| ValidationError = bullet list of danger issues | validating or paying with `error_count > 0` | [hr_payslip.py:1004](../enterprise/hr_payroll/models/hr_payslip.py#L1004), [`:1065`](../enterprise/hr_payroll/models/hr_payslip.py#L1065) |
| ValidationError "You can't confirm cancelled payslips." | validating a `cancel` slip | [hr_payslip.py:1002](../enterprise/hr_payroll/models/hr_payslip.py#L1002) |
| ValidationError "You can't validate a payslip linked to an archived version." | the slip's version is archived | [hr_payslip.py:1006](../enterprise/hr_payroll/models/hr_payslip.py#L1006) |
| ValidationError "Payslip 'Date From' must be earlier than 'Date To'." | bad dates | [hr_payslip.py:684](../enterprise/hr_payroll/models/hr_payslip.py#L684) |
| UserError "Cannot mark payslip as paid if not confirmed." | mark paid when not validated/paid | [hr_payslip.py:1063](../enterprise/hr_payroll/models/hr_payslip.py#L1063) |
| UserError "You cannot cancel the payment if the payslip has not been paid." | mark unpaid when not paid | [hr_payslip.py:1105](../enterprise/hr_payroll/models/hr_payslip.py#L1105) |
| UserError "Cannot cancel a payslip that is validated." | non-manager cancels a validated slip | [hr_payslip.py:1056](../enterprise/hr_payroll/models/hr_payslip.py#L1056) |
| UserError "The payslips should be in Draft or Waiting state." | Recompute Whole Sheet on a non-draft slip | [hr_payslip.py:1329](../enterprise/hr_payroll/models/hr_payslip.py#L1329) |
| UserError "Only draft and cancelled payslips can be deleted…" | deleting a validated/paid slip | [hr_payslip.py:1243](../enterprise/hr_payroll/models/hr_payslip.py#L1243) |
| UserError "The selected payslips should be linked to the same batch" | payment report across >1 pay run | [hr_payslip.py:1080](../enterprise/hr_payroll/models/hr_payslip.py#L1080) |
| ValidationError "Allocated amounts surpass / are less than the net salary." | bank-split allocations ≠ net | [hr_payslip.py:2561](../enterprise/hr_payroll/models/hr_payslip.py#L2561) |
| UserError "You do not have sufficient permissions to validate a Pay Run with warnings or errors." | non-officer validates a run that has any warning or error | [hr_payslip_run.py:376](../enterprise/hr_payroll/models/hr_payslip_run.py#L376) |
| ValidationError "…cannot reset a pay run to draft if some of the payslips have already been paid." | run set-to-draft with a paid slip | [hr_payslip_run.py:304](../enterprise/hr_payroll/models/hr_payslip_run.py#L304) |
| UserError "You must have employee records in the payrun to generate payslip(s)." | generating with no version selected | [hr_payslip_run.py:588](../enterprise/hr_payroll/models/hr_payslip_run.py#L588) |
| UserError "You can only correct a validated or paid pay run." | Correct on a run that is not `02_close`/`03_paid` | [hr_payslip_run.py:355](../enterprise/hr_payroll/models/hr_payslip_run.py#L355) |
| UserError "You can only re-compute payslips in a pay run that is in draft or ready state." | Re-compute on a closed run | [hr_payslip_run.py:687](../enterprise/hr_payroll/models/hr_payslip_run.py#L687) |
| UserError "You can't delete a pay run with payslips if they are not draft or cancelled." | deleting a run with live slips | [hr_payslip_run.py:619](../enterprise/hr_payroll/models/hr_payslip_run.py#L619) |
| ValidationError "There is no valid payslip (validated and net wage > 0)…" | payment wizard, no eligible slip | [hr_payroll_payment_report_wizard.py:137](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L137) |

### Time off

| Exception & message | Trigger | Resolution | Source |
|---|---|---|---|
| UserError "The pay of the month is already validated with this day included…" | re-activating or deleting a leave inside a validated/paid regular payslip | correct the payslip instead of editing the leave | [hr_leave.py:387](../enterprise/hr_payroll/models/hr_leave.py#L387) |
| AccessError "Access allowed only for time-off officers." | non-officer sends an approved leave back to Confirm | ask a time-off officer | [hr_leave.py:308](../enterprise/hr_payroll/models/hr_leave.py#L308) |
| `can_back_to_approve` False on an approved leave | a validated/paid regular payslip already covers it | correct/cancel that payslip first | [hr_leave.py:232](../enterprise/hr_payroll/models/hr_leave.py#L232) |
| *Leaves to defer* warning (not an exception) | `payslip_state = 'blocked'` | **Correct** the covering payslip (the "Leave to Defer" activity still closes it, but nothing schedules it in 20.0) | [hr_payroll_warning_data.xml:577](../enterprise/hr_payroll/data/hr_payroll_warning_data.xml#L577) |

### Salary adjustments

| Exception & message | Trigger | Source |
|---|---|---|
| UserError "The total amount to pay is higher than the total remaining amount of the selected payslip adjustments." | the computed deduction line exceeds what is left on the adjustments | [hr_salary_attachment.py:378](../enterprise/hr_payroll/models/hr_salary_attachment.py#L378) |
| UserError "You cannot delete a payslip adjustment that is linked to a payslip!" | deleting a used adjustment | [hr_salary_attachment.py:307](../enterprise/hr_payroll/models/hr_salary_attachment.py#L307) |

### Accounting & payment

| Exception & message | Trigger | Source |
|---|---|---|
| ValidationError "You can't create a journal entry for a paid payslip." | validating a slip already `paid` | [hr_payroll_account/.../hr_payslip.py:40](../enterprise/hr_payroll_account/models/hr_payslip.py#L40) |
| UserError "The Expense Journal … has not properly configured the default Account!" | rounding adjustment needed but journal has no default account | [hr_payroll_account/.../hr_payslip.py:263](../enterprise/hr_payroll_account/models/hr_payslip.py#L263) |
| ValidationError "…journal must be in the same currency as the company" | salary journal currency ≠ company | [hr_payroll_account/.../hr_payroll_structure.py](../enterprise/hr_payroll_account/models/hr_payroll_structure.py) |
| UserError "You cannot delete the journal linked to a Salary Structure" | delete a journal used by a structure | [hr_payroll_account/.../account_journal.py](../enterprise/hr_payroll_account/models/account_journal.py) |
| ValidationError "The payment date cannot be in the past." | SEPA/Swiss export with a past `effective_date` | [iso20022 wizard:101](../enterprise/hr_payroll_account_iso20022/wizard/hr_payroll_payment_report_wizard.py#L101) |
| UserError "Some employees (…) don't have a work contact." / "…don't have a valid name on the work contact." | SEPA export, missing employee work contact | [iso20022 wizard:104](../enterprise/hr_payroll_account_iso20022/wizard/hr_payroll_payment_report_wizard.py#L104) |
| UserError "The journal '…' requires a proper IBAN account to pay via SEPA." | bank journal account not IBAN | [iso20022 wizard:111](../enterprise/hr_payroll_account_iso20022/wizard/hr_payroll_payment_report_wizard.py#L111) |
| UserError "No payment method found. Check the outgoing payment methods linked to the journal '…'." | no `sepa_ct` / `iso20022_ch` method line | [iso20022 wizard:116](../enterprise/hr_payroll_account_iso20022/wizard/hr_payroll_payment_report_wizard.py#L116) |

### Integrations

| Exception & message | Trigger | Source |
|---|---|---|
| UserError "Only approved and posted expenses with payslip reimbursement can be reported in the next payslip." | reporting a non-eligible expense | [hr_payroll_expense/.../hr_expense.py:91](../enterprise/hr_payroll_expense/models/hr_expense.py#L91) |
| UserError "Please add a Salary Rule belonging to Expense Product '…' to report its expenses in the next payslip" | the expense product has no salary rule for the employee's structure | [hr_payroll_expense/.../hr_expense.py:103](../enterprise/hr_payroll_expense/models/hr_expense.py#L103) |
| UserError (remove from payslip) | removing an expense from a validated/paid slip | [hr_payroll_expense/.../hr_expense.py:143](../enterprise/hr_payroll_expense/models/hr_expense.py#L143) |
| AccessError "You don't have the access rights to link an expense to a payslip…" | non-payroll user triggers the link | [hr_payroll_expense/.../hr_payslip.py:80](../enterprise/hr_payroll_expense/models/hr_payslip.py#L80) |
| ValidationError "The salary rules linked to a product must have a debit account of type 'Liability Payable'." | expense product wired to a rule without a payable debit account | [product_template.py:33](../enterprise/hr_payroll_expense/models/product_template.py#L33) |

---

## Appendix B — Status Reference

Every state across the payroll-relevant models.

### `hr.payslip.state` & `state_display`

| State | Meaning | Gated by | Source |
|---|---|---|---|
| `draft` | editable; lines/worked-days/inputs recompute | default; from cancel via Set-to-Draft | [hr_payslip.py:72](../enterprise/hr_payroll/models/hr_payslip.py#L72) |
| `validated` | confirmed; draft move created when a Salary Journal exists | `action_payslip_done`: officer group, no blocking warning, no cancel slip, no `error_count`, version active | [`:980`](../enterprise/hr_payroll/models/hr_payslip.py#L980) |
| `paid` | salary attachments recorded; `paid_date` set | `action_payslip_paid` (validated/paid, no `error_count`); the payment wizard's **Mark as Paid**; or register-payment when all residuals are zero | [`:1062`](../enterprise/hr_payroll/models/hr_payslip.py#L1062) |
| `cancel` | move unlinked/reversed; blocked leaves reset to `normal` | `action_payslip_cancel`: managers only if validated | [`:1055`](../enterprise/hr_payroll/models/hr_payslip.py#L1055) |
| `state_display = 02_warning` | orange **Warning** badge | `warning_count > 0`, `error_count == 0`, **and `state == 'draft'`** | [`:287`](../enterprise/hr_payroll/models/hr_payslip.py#L287) |
| `state_display = 01_error` | red **Blocked** badge; validation and payment raise | `error_count > 0` | [`:287`](../enterprise/hr_payroll/models/hr_payslip.py#L287) |

### `hr.payslip.run.state` (computed)

`00_draft` (Draft — a selected version has no payslip) / `01_ready` (Ready) / `02_close` (Done) / `03_paid` (Paid) / `04_cancel` (Cancelled) — see [Pay run states](#pay-run-states).

### `hr.leave.payslip_state`

| State | Label | Meaning | Source |
|---|---|---|---|
| `normal` | To compute in next payslip | default; picked up normally | [hr_leave.py:17](../enterprise/hr_payroll/models/hr_leave.py#L17) |
| `blocked` | **Payslip to be corrected** | the period is closed by a validated/paid regular slip; raises the *Leaves to defer* warning | [`:247`](../enterprise/hr_payroll/models/hr_leave.py#L247) |
| `done` | Computed in current payslip | set by `compute_sheet` for covered leaves, by the "Leave to Defer" activity feedback, and on user cancellation | [`:345`](../enterprise/hr_payroll/models/hr_leave.py#L345) |

### `account.move` (payslip `move_id`)

| State | Meaning | Source |
|---|---|---|
| `draft` | created on validation; never auto-posted | [hr_payroll_account/.../hr_payslip.py:305](../enterprise/hr_payroll_account/models/hr_payslip.py#L305) |
| `posted` | accountant posted it; required before any Register Payment | [addons/account](../addons/account/models/account_move.py) |
| deleted / cancel / reversed | on payslip cancel, routed by `_unlink_or_reverse` | [account_move.py](../addons/account/models/account_move.py) |

### Other states

- `hr.salary.attachment`: `1_open` (Running) / `2_close` (Done) — auto-closes when `remaining_amount` hits 0; recurring adjustments never do ([hr_salary_attachment.py:76](../enterprise/hr_payroll/models/hr_salary_attachment.py#L76)).
- `hr.payroll.employee.declaration`: `draft → pdf_to_generate → pdf_generated → pdf_to_post → pdf_posted` (last two via the Documents bridge).
- `hr.contract.salary.offer`: `open / half_signed / full_signed / expired / refused / cancelled` — only `active=True` on the version reaches payroll.
- `hr.version.attendance_based`: False (schedule-driven) / True (attendance-driven) — decides where worked days come from. **There is no `work_entry_source` selection any more.**
- `hr.attendance`: only `validated` attendances with a `check_out` produce work-entry values.
- `hr.expense`: only `approved`/`posted` expenses with `payment_mode = 'payslip_account'` and `refund_in_payslip` are eligible.

---

## Appendix C — Common Symptoms → Cause

| Symptom | Cause | Source |
|---|---|---|
| Fixed-wage salary still equals the monthly wage even when days/hours differ by month | the fixed wage is divided by that period's scheduled hours, then multiplied back by the paid hours | [hr_payslip_worked_days.py:122](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L122) |
| Hourly employee salary changes directly with hours | hourly wage uses `version._get_contract_wage() * hours * amount_rate` | [hr_payslip_worked_days.py:119](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L119) |
| A Bonus/Salary Input row does not change the Attendance amount | inputs only affect the salary rule that defines them; worked days are separate | [hr_salary_rule.py:234](../enterprise/hr_payroll/models/hr_salary_rule.py#L234) |
| Hours missing for a day and there is no work entry to inspect | there are no work-entry records in v20 — check the working schedule, the leave, or the attendance's `state`/`check_out` | [hr_version.py:122](../addons/hr_work_entry/models/hr_version.py#L122) |
| A payslip changed by itself after someone edited an attendance or a leave | write hooks re-trigger the time rules and `_recompute_payslips()` on draft slips | [hr_time_rule_source_mixin.py](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py), [hr_leave.py:325](../enterprise/hr_payroll/models/hr_leave.py#L325) |
| Unexpected Overtime/Undertime worked-day line | an `hr.time.rule` matched the employee and time type | [hr_time_rule.py:111](../addons/hr_work_entry/models/hr_time_rule.py#L111) |
| Unpaid leave shows days but contributes 0 | the time type's `amount_rate` is 0 → `is_paid = False` | [hr_payslip_worked_days.py:51](../enterprise/hr_payroll/models/hr_payslip_worked_days.py#L51) |
| A leave type "named Unpaid" still pays | the name is irrelevant; set `amount_rate = 0` on the **time type** (there is no structure-level unpaid list any more) | [hr_work_entry_type.py:43](../addons/hr_work_entry/models/hr_work_entry_type.py#L43) |
| "You do not have sufficient permissions to validate payslips" | the user lacks the new **Officer** group | [hr_payroll_security.xml:18](../enterprise/hr_payroll/security/hr_payroll_security.xml#L18) |
| Validation refused with a warning name, though the payslip shows no error | a `hr.payroll.warning` with **Block Payslips** matched the *employee*, not the slip | [hr_payslip.py:984](../enterprise/hr_payroll/models/hr_payslip.py#L984) |
| Pay run stuck at `00_draft` after removing a payslip | the version is still in `version_ids` with no slip; use **Off-Cycle** (which unlinks both) rather than clearing `payslip_run_id` | [hr_payslip_run.py:216](../enterprise/hr_payroll/models/hr_payslip_run.py#L216) |
| Pay run stuck at `01_ready` after validating several slips | one slip is still `draft`; draft has priority in `_compute_state` | [hr_payslip_run.py:216](../enterprise/hr_payroll/models/hr_payslip_run.py#L216) |
| Validated slip's journal entry is Draft (never posted) | no `action_post` in the validation path; posting is manual | [hr_payroll_account/.../hr_payslip.py:114](../enterprise/hr_payroll_account/models/hr_payslip.py#L114) |
| No journal entry though accounting is installed | the structure has no `journal_id` (silently skipped + *No Journal* warning) | [hr_payroll_account/.../hr_payslip.py:45](../enterprise/hr_payroll_account/models/hr_payslip.py#L45) |
| Journal entry exists but Journal Items are empty | the salary rules have no Debit/Credit accounts, so `_prepare_slip_lines()` adds no lines | [hr_payroll_account/.../hr_payslip.py:164](../enterprise/hr_payroll_account/models/hr_payslip.py#L164) |
| Re-validating a re-drafted slip makes no new move | Set-to-Draft doesn't clear `move_id`; the create gate skips slips with a move | [hr_payroll_account/.../hr_payslip.py:45](../enterprise/hr_payroll_account/models/hr_payslip.py#L45) |
| Cancelling a slip sometimes deletes, sometimes reverses the move | `_unlink_or_reverse` buckets by hash/lock/audit-trail | [account_move.py](../addons/account/models/account_move.py) |
| "Excluded from Net" rule's amount vanishes from the entry | removed from NET; if it has no own accounts it posts nowhere | [hr_payroll_account/.../hr_payslip.py:177](../enterprise/hr_payroll_account/models/hr_payslip.py#L177) |
| There is no **Pay**/Register Payment button on the payslip form | `action_register_payment` was removed in v20; pay via the payment wizard or from Accounting | [hr_payslip_views.xml](../enterprise/hr_payroll_account/views/hr_payslip_views.xml) |
| Slip shows a Payment Date but state is Validated | the wizard's **Download** exit writes the file only; **Mark as Paid** is the exit that sets the state | [hr_payroll_payment_report_wizard.py:172](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L172) |
| Salary attachments not recorded although a payment file was produced | recording fires only on the `state='paid'` write | [hr_payslip.py:769](../enterprise/hr_payroll/models/hr_payslip.py#L769) |
| Validated slip has no PDF / employee got no email | PDF is async; `queued_for_pdf` awaits the hourly cron, and the company trigger may be `never` | [hr_payslip.py:1024](../enterprise/hr_payroll/models/hr_payslip.py#L1024) |
| A refund or zero-delta correction produces no PDF and no email | `_check_generate_payslip_pdf` / `_check_send_payslip_mail` skip them | [hr_payslip.py:873](../enterprise/hr_payroll/models/hr_payslip.py#L873) |
| Extra holidays reduced the wage but no leave allocation appeared | `hr_contract_salary_holidays` no longer exists — nothing creates the allocation | see [Extra holidays](#extra-holidays) |

---

## Key Methods Map

### Work-entry values & time rules

| Method | Source |
|---|---|
| `generate_work_entries()` (returns vals, creates nothing) | [hr_version.py:303](../addons/hr_work_entry/models/hr_version.py#L303) |
| `_get_version_work_entries_values()` / `_generate_work_entries_postprocess()` | [:122](../addons/hr_work_entry/models/hr_version.py#L122) / [:412](../addons/hr_work_entry/models/hr_version.py#L412) |
| `has_static_work_entries()` (schedule vs attendance) | [:297](../addons/hr_work_entry/models/hr_version.py#L297) / [hr_holidays_attendance/hr_version.py:15](../addons/hr_holidays_attendance/models/hr_version.py#L15) |
| `_trigger_time_rules()` / `_process_time_rules_for()` | [hr_time_rule_source_mixin.py](../addons/hr_work_entry/models/hr_time_rule_source_mixin.py) |
| `get_work_hours()` / `_get_work_hours()` | [hr_version.py:559](../enterprise/hr_payroll/models/hr_version.py#L559) / [:580](../enterprise/hr_payroll/models/hr_version.py#L580) |

### Payslip

| Method | Source |
|---|---|
| `compute_sheet()` / `action_refresh_from_work_entries()` | [hr_payslip.py:1269](../enterprise/hr_payroll/models/hr_payslip.py#L1269) / [:1326](../enterprise/hr_payroll/models/hr_payslip.py#L1326) |
| `_compute_worked_days_line_ids()` / `_compute_input_line_ids()` | [:2162](../enterprise/hr_payroll/models/hr_payslip.py#L2162) / [:339](../enterprise/hr_payroll/models/hr_payslip.py#L339) |
| `_get_worked_day_lines()` / `_get_worked_day_lines_values()` | [:1422](../enterprise/hr_payroll/models/hr_payslip.py#L1422) / [:1374](../enterprise/hr_payroll/models/hr_payslip.py#L1374) |
| `_get_localdict()` / `_get_payslip_lines()` | [:1626](../enterprise/hr_payroll/models/hr_payslip.py#L1626) / [:1744](../enterprise/hr_payroll/models/hr_payslip.py#L1744) |
| `_compute_issues()` / `_get_error_message()` / `_compute_state_display()` | [:2080](../enterprise/hr_payroll/models/hr_payslip.py#L2080) / [:2139](../enterprise/hr_payroll/models/hr_payslip.py#L2139) / [:287](../enterprise/hr_payroll/models/hr_payslip.py#L287) |
| `action_payslip_done / validate / paid / unpaid / cancel / draft` | [:980](../enterprise/hr_payroll/models/hr_payslip.py#L980) / [:1040](../enterprise/hr_payroll/models/hr_payslip.py#L1040) / [:1062](../enterprise/hr_payroll/models/hr_payslip.py#L1062) / [:1104](../enterprise/hr_payroll/models/hr_payslip.py#L1104) / [:1055](../enterprise/hr_payroll/models/hr_payslip.py#L1055) / [:843](../enterprise/hr_payroll/models/hr_payslip.py#L843) |
| `_action_refund_payslips()` / `_action_correct_payslips()` / `action_adjust_payslip()` | [:1181](../enterprise/hr_payroll/models/hr_payslip.py#L1181) / [:1211](../enterprise/hr_payroll/models/hr_payslip.py#L1211) / [:1120](../enterprise/hr_payroll/models/hr_payslip.py#L1120) |
| `_recompute_with_forced_lines()` / `_log_line_manual_changes()` | [:787](../enterprise/hr_payroll/models/hr_payslip.py#L787) / [:808](../enterprise/hr_payroll/models/hr_payslip.py#L808) |
| `_compute_salary_allocations()` / `_cron_generate_pdf()` / `_generate_pdf()` | [:2514](../enterprise/hr_payroll/models/hr_payslip.py#L2514) / [:2429](../enterprise/hr_payroll/models/hr_payslip.py#L2429) / [:885](../enterprise/hr_payroll/models/hr_payslip.py#L885) |

### Pay run

| Method | Source |
|---|---|
| `_compute_state()` / `_generate_payslips()` | [hr_payslip_run.py:216](../enterprise/hr_payroll/models/hr_payslip_run.py#L216) / [:585](../enterprise/hr_payroll/models/hr_payslip_run.py#L585) |
| `_get_valid_versions()` / `_get_valid_versions_domain_payrun()` | [:131](../enterprise/hr_payroll/models/hr_payslip_run.py#L131) / [:151](../enterprise/hr_payroll/models/hr_payslip_run.py#L151) |
| `_get_start_payrun_warnings()` / `action_start_payrun_with_warnings()` | [:428](../enterprise/hr_payroll/models/hr_payslip_run.py#L428) / [:517](../enterprise/hr_payroll/models/hr_payslip_run.py#L517) |
| `action_validate()` / `action_correct()` / `_are_payslips_ready()` | [:376](../enterprise/hr_payroll/models/hr_payslip_run.py#L376) / [:352](../enterprise/hr_payroll/models/hr_payslip_run.py#L352) / [:622](../enterprise/hr_payroll/models/hr_payslip_run.py#L622) |

### Warnings & time off

| Method | Source |
|---|---|
| `_get_warning_domain_records()` / `_get_warning_python_records()` / `_get_warning_issue()` | [hr_payroll_warning.py:508](../enterprise/hr_payroll/models/hr_payroll_warning.py#L508) / [:542](../enterprise/hr_payroll/models/hr_payroll_warning.py#L542) / [:583](../enterprise/hr_payroll/models/hr_payroll_warning.py#L583) |
| `get_payroll_dashboard_warning_cards()` / `_cron_payroll_warning_email_alert()` | [:618](../enterprise/hr_payroll/models/hr_payroll_warning.py#L618) / [:674](../enterprise/hr_payroll/models/hr_payroll_warning.py#L674) |
| `hr.leave._action_validate()` / `_recompute_payslips()` / `_check_uncovered_by_validated_payslip()` | [hr_leave.py:247](../enterprise/hr_payroll/models/hr_leave.py#L247) / [:325](../enterprise/hr_payroll/models/hr_leave.py#L325) / [:370](../enterprise/hr_payroll/models/hr_leave.py#L370) |

### Accounting & payment

| Method | Source |
|---|---|
| `action_payslip_done()` / `action_payslip_cancel()` overrides | [hr_payroll_account/.../hr_payslip.py:34](../enterprise/hr_payroll_account/models/hr_payslip.py#L34) / [:29](../enterprise/hr_payroll_account/models/hr_payslip.py#L29) |
| `_get_account_move_vals()` / `_action_create_account_move()` / `_create_account_move()` | [:45](../enterprise/hr_payroll_account/models/hr_payslip.py#L45) / [:114](../enterprise/hr_payroll_account/models/hr_payslip.py#L114) / [:305](../enterprise/hr_payroll_account/models/hr_payslip.py#L305) |
| `_prepare_slip_lines()` / `_prepare_line_values()` / `_prepare_adjust_line()` | [:164](../enterprise/hr_payroll_account/models/hr_payslip.py#L164) / [:123](../enterprise/hr_payroll_account/models/hr_payslip.py#L123) / [:260](../enterprise/hr_payroll_account/models/hr_payslip.py#L260) |
| `mark_as_paid()` / `download_report()` / `generate_payment_report()` | [hr_payroll_payment_report_wizard.py:162](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L162) / [:172](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L172) / [:144](../enterprise/hr_payroll/wizard/hr_payroll_payment_report_wizard.py#L144) |
| `_get_line_batch_key()` / `_reconcile_payments()` | [account_payment_register.py:11](../enterprise/hr_payroll_account/wizard/account_payment_register.py#L11) / [:24](../enterprise/hr_payroll_account/wizard/account_payment_register.py#L24) |

---

## Related Docs

- [`INDEX.md`](INDEX.md)
