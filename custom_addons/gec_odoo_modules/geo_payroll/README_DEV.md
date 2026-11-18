# GEO Payroll (`geo_payroll`) — Developer guide

For developers changing the module. How it is used: [README.md](README.md). What the module
is for, its cases with real numbers and its flows: open [developer_map.html](developer_map.html) in a
browser. Design decisions and their history: [documentations/geo_payroll.md](../../../documentations/geo_payroll.md)
and the plans next to it.

---

## 1. Purpose and facts

The module extends Odoo 20 Payroll with pay schemes on `hr.version`, a work-log model, a
settlement ledger that turns approved work and timesheets into salary lines, a
piecework price list, benefit and advance programs injected as payslip inputs, Georgian tax
rules with art. 82 exemptions, an account configurator for the `ge` chart, and its own payslip
payment.

| Item | Value |
|---|---|
| Depends | `hr_payroll` (payslips, rules, versions) · `hr_payroll_account` (rule accounts, journal entries, `_configure_payroll_account`) · `project` (timesheet projects) · `timesheet_grid` (the Timesheets app the lines come from; validation is not a pay condition) · `uom` (unit rates) · `gec_localization` (the `l10n_ge` chart and payroll account settings, account 331320, the State Treasury's `gec_treasury_code`) |
| New models | `hr.employee.work.log`, `hr.payroll.component.settlement`, `hr.payroll.unit.rate`, `hr.payroll.benefit`, `hr.payroll.benefit.line`, `hr.payroll.tax.exemption`; wizards `gec.payroll.timesheet.waiver`, `hr.payroll.benefit.assign`, `hr.payroll.benefit.payrun` |
| Extended models | `hr.version`, `hr.employee`, `hr.employee.public`, `res.users`, `res.partner`, `hr.payroll.structure.type`, `hr.payslip`, `hr.payslip.run`, `hr.payslip.input`, `hr.payslip.worked_days`, `account.analytic.line`, `account.payment.register`, `account.chart.template` |
| Hooks, crons, controllers | None. Install and upgrade logic runs through `<function>` records in the data files |
| Migrations | None: data changes are solved in code with fill-only-if-empty passes |

What the data files load, in manifest order:

1. `res_partner_data.xml`: the Pension Agency and the State Treasury (no company).
2. `res_partner_bank_data.xml`: the agency's ten bank accounts, one per Georgian bank, so
   `gec_payroll_bank` can pay it at the paying journal's own bank.
3. `payroll_structure_data.xml`: four structure types and structures (`noupdate`), the base
   rules (updated on every upgrade), then `_gec_set_missing_default_struct` and the account
   configurator.
4. `payroll_benefit_data.xml`: the Benefits type and structure, the `ADV` (Salary Advance) and
   `BIK` (Benefit in Kind) categories, benefit rules shared by the four base structures and the Benefits
   structure's own, then the configurator again, because on a fresh install the first call ran before these rules existed.
5. `payroll_overtime_data.xml`: the Overtime type and structure, six rules, the configurator a
   third time.
6. `payroll_tax_exemption_data.xml`: eight exemption categories (`noupdate`).
7. The views, then `security/ir.access.csv` last.

## 2. Architecture

```text
                   hr.version
     pay scheme, wages, flags: the route of every source
                        │
       ┌────────────────┼──────────────────┐
       ▼                ▼                  ▼
   work logs        timesheets       benefit programs
 (price frozen     (validated or    (bonus, deduction,
  at approval)      not, waivable)      advance)
       │                │                  │
       └───────┬────────┘                  │
               ▼                           ▼
       settlement ledger             payslip inputs
          (claims)                         │
               │                           │
               └─────────────┬─────────────┘
                             ▼
                       salary rules ◄── tax exemptions
                             │
                             ▼
                       journal entry
                             │
                             ▼
              Register Payment / Pay Salaries
```

Names in the code: work logs `hr.employee.work.log` (prices from `hr.payroll.unit.rate`),
timesheets `account.analytic.line`, benefit programs `hr.payroll.benefit` and
`hr.payroll.benefit.line`, settlement ledger `hr.payroll.component.settlement`, payslip inputs
`hr.payslip.input`, tax exemptions `hr.payroll.tax.exemption`, accounts
`_gec_configure_payroll_account_ge`, payment `action_register_payment`.

The contract version decides the route of every source. At compute, work logs and timesheets
become settlement rows (claims) and benefits become payslip inputs; the salary rules read the
ledger totals through payslip helpers, so a salary line can always be traced to the rows it
pays. An approved overtime log also writes a mirror timesheet line (`work_log_id`), which every
pay route ignores. Accounting is configured once per company and the payment is the module's own.

## 3. File map

| File | What it holds |
|---|---|
| [`__manifest__.py`](__manifest__.py) | Depends, data load order, and the plain-text `description` that keeps Odoo from rendering README.md as reStructuredText |
| **models/** | |
| [`hr_version.py`](models/hr_version.py) | Pay-scheme fields and normalization, the scheme/wage-type/structure constraint, routing-change and stranding guards, timesheet eligibility, wage helpers, draft refresh |
| [`hr_employee.py`](models/hr_employee.py), [`hr_employee_public.py`](models/hr_employee_public.py), [`res_users.py`](models/res_users.py) | Mirrors of the version fields, `pension_fund_member`, `work_log_ids` for self-service |
| [`res_partner.py`](models/res_partner.py) | `pension_fund_member` on the contact, kept equal to the employee's |
| [`hr_employee_work_log.py`](models/hr_employee_work_log.py) | Work logs: fields, constraints, workflow, approval checks, snapshots, the overtime timesheet mirror |
| [`hr_payroll_unit_rate.py`](models/hr_payroll_unit_rate.py) | Piecework price list |
| [`hr_payroll_component_settlement.py`](models/hr_payroll_component_settlement.py) | The settlement ledger |
| [`hr_payslip.py`](models/hr_payslip.py) | Payslip lifecycle: create, compute, structure alignment, contract guards, grouped validation, cancel and reset |
| [`hr_payslip_settlement.py`](models/hr_payslip_settlement.py) | Claiming, stale release, claim guards, component totals, line tooltips, Work Items card and button |
| [`hr_payslip_tax.py`](models/hr_payslip_tax.py) | Art. 82 allowance per person, PIT taxable base and tooltips, exemption re-check |
| [`hr_payslip_benefit.py`](models/hr_payslip_benefit.py) | Benefit and advance inputs, consumption stamps, advance repayment shares |
| [`hr_payslip_correction.py`](models/hr_payslip_correction.py) | Refund and correction chain checks |
| [`hr_payslip_account.py`](models/hr_payslip_account.py) | Vendor split, batch-entry guard, journal-entry release, Register Payment |
| [`hr_payslip_run.py`](models/hr_payslip_run.py) | Overtime pay runs, run reset and delete |
| [`hr_payslip_worked_days.py`](models/hr_payslip_worked_days.py) | Zero worked-day money on daily, unit and timesheet-mode slips |
| [`hr_payslip_input.py`](models/hr_payslip_input.py) | `benefit_line_id` on inputs |
| [`hr_payroll_structure_type.py`](models/hr_payroll_structure_type.py) | Wage types `daily` and `unit`, default-structure repair, off-cycle constraint |
| [`hr_salary_rule.py`](models/hr_salary_rule.py) | Data hook archiving the pre-shared-rule copies on upgrade |
| [`hr_payroll_benefit.py`](models/hr_payroll_benefit.py) | Benefit programs and lines, eligibility, the three benefit wizards |
| [`hr_payroll_tax_exemption.py`](models/hr_payroll_tax_exemption.py) | Exemption categories |
| [`account_analytic_line.py`](models/account_analytic_line.py), [`gec_payroll_timesheet_waiver.py`](models/gec_payroll_timesheet_waiver.py) | Timesheet guards, the `work_log_id` mirror link and its locks, waiver stamps, the waive wizard and the restore action |
| [`account_chart_template.py`](models/account_chart_template.py) | The `ge` account configurator, benefit and overtime account fill, salary-journal default account |
| [`res_company.py`](models/res_company.py) | Keeps Odoo's own Georgian payroll (`l10n_ge_hr_payroll`) out of the modules a new Georgian company installs |
| [`account_payment_register.py`](models/account_payment_register.py) | Outstanding-account check on payslip payments, paid flip when the net settles |
| [`resource_calendar_leaves.py`](models/resource_calendar_leaves.py), [`res_partner.py`](models/res_partner.py) | Deletes company public holidays typed for another country than their company (left over from a country change; the type's country restriction makes them unreadable and payslip computation raises AccessError). Runs once per database at install or upgrade (`data/public_holiday_repair_data.xml`) and after every change of a company's country, on the company or on its contact |
| [`tools.py`](models/tools.py) | `gec_lock_for_update`: row locks that turn v20's `LockError` into a "try again" message |
| **data/** | Structures and rules (`payroll_structure_data.xml`, `payroll_benefit_data.xml`, `payroll_overtime_data.xml`), exemption categories, partners and bank accounts (section 1), the foreign public holiday repair (`public_holiday_repair_data.xml`) |
| **views/** | Payroll fields on employee and contract template (`hr_version_views.xml`), contact pension flag (`res_partner_views.xml`), work logs, payslip Work Items, waiver, unit rates, benefits, exemptions |
| **security/** | `ir.access.csv` (section 11) |
| **tests/** | `common.py` fixture and one file per area (section 13) |
| **i18n/** | `ka_GE.po` |
| [`developer_map.html`](developer_map.html) | Developer map: purpose, scenarios, flows, built by the odoo-developer-map skill |
| [`CODE_REVIEW.md`](CODE_REVIEW.md) | Open review findings |

## 4. Routing: `hr.version`

Odoo 20 has no `hr.contract`: an employee is a timeline of `hr.version` records, a version is a
contract when `contract_date_start` is set, and `employee._get_version(date)` returns the one
in force. The module treats each version as a pay-routing slice.

Fields added (all `groups='hr_payroll.group_hr_payroll_user'`): `pay_scheme`, `daily_wage`,
`worklog_ot_enabled`, `overtime_pay_mode` (`with_salary` / `separate`),
`worklog_daily_enabled` and `timesheet_extra_enabled` (stored computes of the scheme),
`hourly_source` (`work_entry` / `timesheet`),
`timesheet_pay_project_ids`, `timesheet_pay_start_date`. `wage_type` gains `daily` and `unit`
on `hr.version` and `hr.payroll.structure.type`.

| `pay_scheme` | `wage_type` | Work logs pay as | Timesheets pay as |
|---|---|---|---|
| `fixed` | monthly | overtime → `worklog_ot` | — |
| `hourly` | hourly | overtime → `worklog_ot` (work-entry source only) | `timesheet_basic` (timesheet source) |
| `daily` | daily | daily → `daily_basic`; overtime | — |
| `unit` | unit | unit → `unit_basic`; overtime | — |
| `fixed_daily` | monthly | daily → `worklog_daily`; overtime | — |
| `fixed_hourly` | monthly | overtime | `timesheet_extra` |
| `daily_hourly` | daily | daily → `daily_basic`; overtime | `timesheet_extra` |
| `daily_unit` | daily | daily → `daily_basic`; unit → `unit_extra`; overtime | — |

Overtime always needs `worklog_ot_enabled`. Component to rule code: `_GEC_COMPONENT_RULE_CODE`
in `hr_payslip_settlement.py` (`worklog_ot` → `WORKLOG_OT`, and so on).

- `create` / `write` normalize: `wage_type` from `pay_scheme`, `hourly_source = work_entry`
  unless the scheme is pure hourly.
- `_check_pay_scheme_wage_type`: timesheet mode needs a positive `hourly_wage` and no overtime
  logs. Scheme and wage type cannot diverge in the UI (`wage_type` is derived from the scheme and
  read-only once a scheme is set); a structure type of another wage type, and the rule content
  of the default structure, are caught on the payslip at Validate (the blocking warnings of
  `_gec_schedule_base_slips` and `_gec_timesheet_base_slips`, and `_gec_check_lines_match_settlements`),
  not on the contract.
- `_gec_check_routing_change`: a change of `pay_scheme`, `hourly_source` or
  `overtime_pay_mode` is refused once the version has validated or paid payslips or finalized
  settlements, and when it would strand payable timesheets (`_gec_raise_strandable`,
  draft-claimed lines included). Narrowing the projects or moving the cutoff forward is checked
  the same way. The sanctioned path is a new dated version.
- `_onchange_gec_timesheet_mode_preview` (version and employee form) calls
  `_gec_timesheet_mode_warning`: how many unclaimed lines the next payslips will pay.
  An empty project list or cutoff counts everything, exactly like `_gec_timesheet_line_eligible`.
- `_get_fields_that_recompute_payslip` adds the scheme fields; `_recompute_payslips` calls core
  (regular drafts) and adds the unedited overtime drafts core skips. The realignment of unedited
  regular drafts to the default structure (`_gec_prepare_reset_to_draft`, keeping a hand-set end
  date) runs inside our `action_refresh_from_work_entries` override.
- Wage helpers: `_get_contract_wage_field` returns `daily_wage` for daily; `_get_contract_wage`
  and `_get_normalized_wage` are 0 for unit; the daily normalized wage is
  `daily_wage / hours_per_day`.
- `hr.employee` mirrors the version fields (`related`, `inherited=True`: writes go to the
  current version).
- `pension_fund_member` is a plain employee field (`hr.group_hr_user`), not versioned, mirrored
  on `res.partner`. `_gec_sync_pension` and `res.partner.write` keep both sides equal across
  `work_contact_id`: the written side wins, a new work contact takes the employee's value, a
  relink takes the new contact's value. The partner-to-employee write carries the context key
  `gec_pension_sync` to stop the ping-pong; cross-model writes use sudo because HR users lack
  partner rights and accountants lack HR rights. Salary rules read `employee.pension_fund_member`.

## 5. Structures and salary rules

Structure types GEO Monthly / Hourly / Daily / Unit Pay (`noupdate`) with structures GEO
Monthly / Hourly / Daily / Unit Salary (`use_worked_day_lines=True`). The off-cycle types GEO
Benefits and GEO Overtime have **no default structure** (`_check_benefits_type_stays_off_cycle`)
and their structures GEO Benefits Pay and GEO Overtime Pay have `use_worked_day_lines=False`,
so a BASIC rule there would pay the full wage. Rules attach by `struct_id` and are updated on
every upgrade. The four base structures share one rule set (the `rule_geo_monthly_*` records); the old
hourly, daily and unit copies are noupdate and archived by the data function `_gec_archive_rule_copies`
(an upgrade must never rewrite them: their codes would collide with the shared rules); they stay for the payslip lines that reference them.
Before `-u` on another database check `SELECT count(*) FROM ir_model_data WHERE module='geo_payroll' AND model='hr.salary.rule' AND noupdate`:
core flags a rule noupdate once a user edits a critical field, and such a monthly rule would keep one structure while its copy is archived.

Base rules (shared by the four base structures):

| Seq | Code | Category | Amount |
|---|---|---|---|
| 1 | `BASIC` | none; sets `categories['BASIC']` itself | `_get_basic_salary()`; 0 on a unit-wage slip or when `gec_uses_timesheet_hourly_base()` |
| 2-4 | `DAILY_BASIC`, `TIMESHEET_BASIC`, `UNIT_BASIC` | BASIC | `gec_component_line_vals(code)` when `gec_component_total(code)` is not zero |
| 25-28 | `WORKLOG_OT`, `WORKLOG_DAILY`, `TIMESHEET_EXTRA`, `UNIT_EXTRA` | ALW | same |
| 28 | `ADVANCE_PAY` | ADV | the advance net of 2% and 20% on `gec_advance_taxable_gross`; `employee_move_line` |
| 29 | `ADVANCE` | ALW | `-inputs['ADVANCE'].amount` (reduces gross before tax) |
| 30 | `BONUS` | ALW | `inputs['BONUS'].amount` |
| 31-33 | `ADV_PEE_PRE`, `ADV_PIT_PRE`, `ADV_PER_PRE` | COMP | prepaid pension and tax slices, rounded |
| 34 | `BENEFIT_KIND` | BIK (parent ALW) | `inputs['BENEFIT_KIND'].amount` |
| 35 | `TERMINATION` | ALW | `inputs['TERMINATION'].amount` (typed payslip input) |
| 100 | `GROSS` | GROSS | `BASIC + ALW` |
| 120 | `PENSION_EE` | DED | members: `-GROSS × 0.02` (the company share paid to a vendor is in the base, accountant 2026-11-12); partner Pension Agency |
| 140 | `PIT` | DED | `taxable = gec_pit_taxable_gross(GROSS, -PENSION_EE, ADV_PEE_PRE)`; `-taxable × 0.20`: the withheld pension comes off first, in full, then the allowance left (while allowance is left an advance pay-out joins with its pension); partner State Treasury |
| 160 | `PENSION_ER` | COMP | members: `GROSS × 0.02` |
| 170 | `BENEFIT_DED` | DED | `-inputs['BENEFIT_DED'].amount` |
| 171-174 | `REPAY_NET`, `REPAY_PEE`, `REPAY_PIT`, `REPAY_PER` | COMP | close the prepaid legs, one share per installment (`gec_advance_repay_share`) |
| 175 | `BENEFIT_KIND_DED` | DED | `-inputs['BENEFIT_KIND'].amount`: the company share leaves net, it is paid to the vendor |
| 200 | `NET` | NET | `BASIC + ALW + DED + ADV`; `employee_move_line` |

GEO Benefits Pay: `BONUS`, `ADVANCE_PAY`, `ADV_*_PRE`, `GROSS`, `PENSION_EE`, `PIT`,
`PENSION_ER`, `NET`. GEO Overtime Pay: `WORKLOG_OT`, `GROSS`, `PENSION_EE`, `PIT`, `PENSION_ER`,
`NET` (net without ADV).

Engine facts this relies on:

- A Python condition is truth-tested, so a zero component makes no line. `result_qty` becomes
  the line quantity; line total = amount × quantity × rate / 100, unrounded.
- Odoo 20 has no input types: an input points to a salary rule and uses its code. `BONUS`,
  `BENEFIT_DED`, `ADVANCE` and `ADVANCE_PAY` carry `input_usage_payslip=True`, and benefit
  injection creates each input on the structure's rule with that code.
- Core pre-fills `categories['BASIC']` from attendance worked days only; the BASIC rules
  overwrite it so paid leave counts. When a line is edited, `_get_localdict` gives the category
  the forced BASIC line's total, so an edited Basic Salary reaches GROSS, PIT and NET.
- Rates are dated `hr.rule.parameter` values (`data/hr_rule_parameter_data.xml`): `gec_ge_pit_rate` (20) and
  `gec_ge_pension_rates` (`{'employee': 2, 'employer': 2}`), read with `payslip._rule_parameter()` at the slip's
  end date. A law change is a new dated value, shipped in that XML (the parameter's Reset button deletes values
  added in the UI); never edit a value already used by validated slips. GROSS, PIT, pension and NET do
  not round; advance rules round to 2 decimals; settlements round per source line.

## 6. Compute: from sources to salary lines

`hr.payslip.compute_sheet` (a user's Compute Sheet, or the pay run) runs, in order:

1. `_gec_align_draft_base_structures`: unedited regular drafts move to their version's default
   structure.
2. An edited payslip that holds live claims is refused.
3. `_gec_release_stale_claims` releases every claim `_gec_settlement_still_valid` rejects: the
   slip left the claim scope, the source is outside the window or not approved, the structure
   does not pay the component, or the amount changed. Reason "Payslip recomputed".
   Timesheet claims are re-priced this way; work-log claims never are, because the snapshot is
   authoritative.
4. `_gec_claim_work_logs`: approved, unclaimed logs dated in the window. Locks them
   (`gec_lock_for_update`), re-reads them, checks that the structure has the rule of the frozen
   component and that the frozen currency is the company's, then writes one settlement from the
   snapshot (quantity, UoM, rate, amount, `source_version_id` = approval version).
5. `_gec_claim_timesheets`: unwaived, unclaimed lines with a project (validated or not, never an
   overtime mirror), dated up to the window end and payable under
   `version._gec_timesheet_line_eligible`.
   `_gec_check_timesheet_day_caps` raises above 24 hours a date, claimed hours included. Amount =
   hours × the work-date version's hourly wage, rounded.
6. `_gec_check_claims`, then core's `compute_sheet`, where the rules read `gec_component_total`,
   `gec_component_line_vals` and `gec_pit_taxable_gross`.

**Claim scope and window.** `_gec_in_claim_scope`: draft, not a credit note, no origin, with a
version, and on the version's default structure or GEO Overtime Pay; `_gec_can_claim` also
requires an unedited slip. `_gec_claim_window` ends at `date_to` (regular slips: also at the
contract end) and starts only when an earlier contract of the employee overlaps the period (then
at this contract's start). Otherwise it has no lower bound: that is how late work carries
forward. One window spans every version of the contract.

**The ledger** (`hr.payroll.component.settlement`): the source (`work_log_id` or
`timesheet_line_id`), `payslip_id` and `payslip_ref`, `employee_id`, `company_id`,
`currency_id`, `component_code`, `source_version_id`, `date`, `quantity`, `uom_id`, `rate`,
`amount`, `active_claim`, `release_reason`, `released_at`. Partial unique indexes allow one live
claim per work log and one per timesheet line. `write` and `unlink` always raise and
`_allow_sudo_commands = False`; release goes only through `_release` / `_write_release`, with
the reasons "Payslip recomputed", "Payslip cancelled", "Payslip deleted" and "Pay run deleted".

**Lines and tooltips.**

- `gec_component_total(code)` sums the live claims of the correction-chain root (negative on
  credit notes). `gec_component_line_vals` returns `(total / quantity, quantity)`, or
  `(total, 1)`, so quantity × amount reproduces the ledger total exactly.
- `_recompute_with_forced_lines`: when a user edits a line, work-item lines are forced as
  total × 1, so blended unit amounts stay exact, and forced lines keep their tooltips (the engine
  would show "Explanation couldn't be computed").
- Tooltips use `explanation_template = "{explanation}"`, filled by `gec_component_explanation`,
  `gec_pit_explanation` and `gec_net_explanation`; amounts are rounded half-up by `_gec_money`.
- `hr.payslip.worked_days._compute_amount` pays nothing on daily, unit and timesheet-mode slips,
  and `_gec_schedule_base_slips` (a blocking warning) flags a non-zero BASIC there.

**Benefit inputs** (`hr_payslip_benefit.py`). `_compute_input_line_ids` calls
`_benefit_input_commands`, which rebuilds benefit inputs idempotently on unedited drafts that are
not credit notes: with-salary lines on regular slips, separate lines on the Benefits structure,
and only when the structure has the matching rule. `_benefit_eligible_lines` decides eligibility
and blocks double carry. Corrections get the chain root's benefit inputs once, at creation
(`_benefit_mirror_root_inputs`; `_gec_drop_copied_benefit_inputs` drops the copies core makes), and
later recomputes leave the correction's inputs alone. A benefit change under a computed draft
recomputes its lines too (`_benefit_refresh`), and `_benefit_check_inputs_match_lines` refuses to
validate a draft whose benefit inputs no longer match its lines. A program locks its vendor, and an
advance its terms, once a payslip with its inputs is validated (`locked`). GEO Overtime Pay gets no inputs
at all, salary attachments included. `action_refresh_from_work_entries` recomputes inputs before
lines, so a reopened slip pays a changed benefit at its current amount and never pays a
once-benefit that another slip took meanwhile.

## 7. Validation, cancel and reset

`action_payslip_done` runs, in this order:

1. `_gec_check_one_entry_per_payslip`: batch journal entries refused for Georgian companies.
2. `_gec_check_correction_chains` (a refund needs an origin; a correction needs a validated refund).
3. `_gec_check_no_overlap` (locks the employee).
4. `_gec_check_claims`. Unclaimed work items, a shortened fixed-wage period, a mixed pay route,
   schedule-based base pay on a daily or unit slip and a non-standard timesheet-paid slip are not
   raises: blocking `hr.payroll.warning` cards (data/hr_payroll_warning_data.xml) list the slips on
   the dashboard through `_gec_unclaimed_slips`, `_gec_short_fixed_period_slips`,
   `_gec_mixed_pay_route_slips`, `_gec_schedule_base_slips` and `_gec_timesheet_base_slips`, and
   core refuses Validate while a card names the slip.
5. `_gec_check_lines_match_settlements` and `_benefit_check_inputs_match_lines`.
6. `_gec_check_overtime_payslips`.
7. Lock every employee record of the persons (`_gec_exemption_persons`), then for each group of
   `_gec_validation_groups`: `_gec_check_current_exemption_tax` on each slip, core validation for
   the group (journal entries), `_benefit_record_consumption`.

Slips of one person with the same start date go to consecutive groups: the exemption re-check
counts a same-date sibling only once it is validated, so checking all slips first and calling
core once would let both spend the same allowance. `lock_for_update` uses SKIP LOCKED, so a
concurrent run gets the `gec_lock_for_update` retry message; employees are locked with
`allow_referencing=True`, so timesheets and attendance can still be saved meanwhile.

| Guard | Rule |
|---|---|
| Correction chains | No standalone credit note; the origin is validated or paid; descendants keep employee, company and period; validated corrections never outnumber validated refunds that exactly negate every `(rule, code)` total of the origin |
| Full schedule period | A regular monthly slip covers `date_from` plus the schedule period |
| No overlap | No other live regular slip on the same contract (`_get_version_lookup_key`) overlaps the period |
| One pay route | The versions one slip pays share structure type and timesheet mode |
| Claims intact, nothing unclaimed | Live claims match their sources; every approved payable log and payable timesheet in the window is claimed |
| Daily and unit base | Worked-day base and BASIC are zero |
| Timesheet base | Unedited, default structure, BASIC-category `TIMESHEET_BASIC`, zero work-entry base |
| Lines match settlements | Each component line equals the root's live settlement total |
| Overtime slip | Only the six overtime rules, no inputs, at least one live claim |

Cancel, reset and delete:

- `action_payslip_cancel`: `_gec_check_not_paid`, `_benefit_check_no_live_installments` (a pay-out
  slip whose installment is already validated must be corrected, not cancelled),
  `_gec_check_correction_balance_after_removal`, `_gec_release_journal_entries`, core, release the
  claims ("Payslip cancelled"), `_benefit_release_consumption`.
- `action_payslip_paid`: drops the family members named in context `gec_paid_cascade_skip_ids`
  (`_gec_mark_settled_paid` lists those whose NET line is still open), so core's cascade from a
  paid correction never marks a refund with an open residual as Paid.
- `action_payslip_draft`: `_gec_check_not_paid`, release the entries of validated and cancelled
  slips, realign cancelled regular slips (`_gec_prepare_reset_to_draft`), then core, whose
  refresh recomputes inputs and lines.
- `_gec_release_journal_entries` does what core's Cancel does (`_unlink_or_reverse`) and then
  clears `move_id`. Without that, core's reset keeps the entry and core's Cancel keeps a reversed
  one linked, validation skips a slip that still has `move_id`, and the reopened slip books
  nothing. An entry already reversed or cancelled is only unlinked.
- `_gec_check_not_paid` exists because core's list actions Cancel and Set to Draft reach any
  state, and a cancelled paid slip would free its claims to be paid again.
- `hr.payslip.run.action_draft` realigns and releases the same way. Deleting a run or a slip
  releases its claims first (`_gec_release_run_settlements`, `_gec_release_settlements`).

Corrections are core (`_action_refund_payslips`, `_action_correct_payslips`); Odoo 20 validates
the refund on creation, so the origin must be validated first. Component totals come from the
chain root.

Edited slips cannot claim, cannot recompute while they hold claims, are skipped by the stale
release, and are refused at validation when new eligible work appears. The exemption re-check
replays the lines the user edited (`manually_modified`), so only a changed allowance refuses them.

Pay runs: core `action_validate` validates all slips in one transaction and also passes the
run's slips that were validated on their own; `_gec_check_claims` checks drafts only, so those do
not block the run. Overtime runs: `_get_valid_versions` offers, per employee, the version of the
latest approved unpaid separate-overtime log; `_generate_payslips` creates overtime slips for the
run's versions and drops those that claimed nothing (core calls it whenever a draft run opens,
so it does not raise).

## 8. Taxes (`hr_payslip_tax.py`)

- `_gec_exemption_persons`: every employee record sharing the `identification_id` in any company
  (sudo, archived included), or the slips' own employees when they have no personal number.
- `_gec_exemption_remaining`: `None` without an active category. Limit = the highest
  `yearly_limit`; consumed = GROSS + PENSION_EE (negative) - ADV_PEE_PRE of the person's earlier original
  slips of the calendar year (Benefits and Overtime included; not cancelled, not credit notes,
  no origin; an earlier `date_from`, or the same `date_from` and validated) plus their
  `ADVANCE_PAY` inputs.
- `gec_pit_taxable_gross(gross, pension, advance_pension)`: `gross - pension` without a category or allowance (the old
  one-argument call still returns `gross`); otherwise `max(0, gross + own ADVANCE_PAY inputs - pension - advance_pension - remaining)`.
- `gec_advance_taxable_gross`: inside an allowance an advance pay-out prepays no tax; its gross is
  part of the monthly PIT line.
- `gec_advance_repay_share` (`hr_payslip_benefit.py`): each installment closes its share of what
  the pay-out slip actually prepaid (not today's pension flag); the last installment closes the
  rest; a slip repaying several advances gets one share per advance, split by pay-out amounts.
- `_gec_check_current_exemption_tax`: at validation, recomputes PIT with the rule engine and
  refuses a stale amount.

Numeric anchors from the tests: member 1,000 → -20 / -196 / +20 / 784; non-member → -200 / 800;
daily 80, member → 62.72; 500 allowance left on 1,000 → PIT -96 with PENSION_EE -20 (arithmetic only, no test pins it).

## 9. Accounting and payment

GEO Monthly carries `sequence` 5, so the pay-run default prefers it to core's "Georgia: Regular Pay" when both are installed
(fresh installs only, the record is `noupdate`).

`_gec_configure_payroll_account_ge(companies)` runs when a company loads the `ge` chart (called by
our `_load_payroll_accounts` override) and from the data files (`_gec_configure_ge_payroll_accounts`) for every
`ge` company on install and upgrade:

| Rules | Debit field | Credit field |
|---|---|---|
| `BASIC`, `DAILY_BASIC`, `TIMESHEET_BASIC`, `UNIT_BASIC`, `WORKLOG_DAILY`, `TIMESHEET_EXTRA`, `UNIT_EXTRA` | 720100 | |
| `WORKLOG_OT` (monthly and the separate overtime payslip) | 720200 | |
| `BONUS`, `BENEFIT_KIND` | 720110 | |
| `TERMINATION` | 720700 | |
| `PENSION_EE` | 332010 (negative total → credit) | |
| `PIT` | 331320 (negative total → credit) | |
| `PENSION_ER` | 721000 | 332010 |
| `BENEFIT_DED`, `BENEFIT_KIND_DED` | 720900 (negative → credit; the vendor part is moved, below) | |
| `ADVANCE_PAY` | 150310 | |
| `ADV_PEE_PRE` / `ADV_PIT_PRE` / `ADV_PER_PRE` | 332011 / 331311 / 332011 | 332010 / 331320 / 332010 |
| `REPAY_NET` / `REPAY_PEE` / `REPAY_PIT` | | 150310 / 332011 / 331311 |
| `REPAY_PER` | 721000 | 332011 |
| `NET` | | 310310, employee partner (`employee_move_line`) |

- Accounts are `l10n_ge` template xmlids resolved per company and passed as `account_refs` to
  `_configure_payroll_account` (precedent: `l10n_au_hr_payroll_account`).
- How core books a rule line: the debit-field account gets the total as debit when positive and
  as credit when negative; the credit field mirrors it. That is why deductions sit on the debit
  field.
- Ownership: core's configurator runs only for a company where no base rule has an account; after
  it every mapped rule that has neither account is filled
  (`_gec_fill_missing_rule_accounts`), in every `ge` company, on install and upgrade. An account set
  by an accountant is never overwritten, and a rule emptied on purpose is filled again at the next
  upgrade. `_gec_fill_salary_journal_default_account` gives the salary
  journals 720100 as default account where empty: core's `_prepare_adjust_line` books a
  payslip's rounding cent there and raises without one.
- Vendor split (`_prepare_slip_lines`, after core): core merges the per-input `BENEFIT_DED` lines
  into one journal line; the override sums the slip's inputs per
  `benefit_line_id.benefit_id.partner_id` and writes one line per vendor on its payable account
  (label `<rule> - <vendor>`), leaving the rest on 720900. It finds the line by the rule name, so
  "Split on names" or a rule without an account makes it refuse the entry.

Payment:

- `action_register_payment` (Odoo 20 dropped core's): opens the payment wizard on the slip's open
  lines on reconcilable payroll accounts (`asset_receivable`, `liability_payable`, and
  `liability_current` with the context key `hr_payroll_payment_register`), grouped per partner: employee
  (310310), Pension Agency (332010), State Treasury (331320), each vendor. It refuses paid slips,
  unposted entries, untrusted employee bank accounts, a missing or non-reconcilable net line and
  partner-less lines (naming the rule). One slip at a time (`ensure_one`): a Pension Agency or
  Treasury payment grouped across slips makes core's `_reconcile_payments` crash.
- `account.payment.register._create_payments` (context flag `gec_payslip_register_payment`)
  refuses a payment method without an Outstanding Payments account: such a payment posts no
  entry and settles nothing.
- `account.payment.register._reconcile_payments`: with that context key, flips
  validated slips to `paid` (`paid_date` = payment date) once every net-account line is settled;
  core needs every line.
- `gec_payroll_bank` overrides other wizard methods (`_get_line_batch_key`, `_create_payments`)
  without conflict; the treasury transfer type and code are set there, not here.

## 10. Work logs, timesheets and benefits

**Work logs** (`hr.employee.work.log`, with chatter, `_allow_sudo_commands = False`):

- Snapshots written at approval (payroll group, read-only, not copied): `version_id`,
  `rate_snapshot`, `amount_snapshot`, `component_code_snapshot`, `currency_id_snapshot`,
  `unit_uom_snapshot_id`, `approved_by_id`, `approved_at`. `settlement_state` is computed:
  `unclaimed`, `claimed`, `paid`.
- Constraints: one active daily log per employee and date (partial unique index with its own
  message); fields of the other log types are cleared on create and write
  (`_gec_clear_other_type_fields`); at most 24 overtime hours a date across active
  logs, logs saved together included (`_check_overtime_daily_cap`).
- `create` forces draft and drops forged states and snapshots. `action_submit`: owner or payroll
  officer. `action_approve`: direct manager or payroll officer; runs `_gec_approval_component`
  (contract on the date, attendance or timesheet double pay, pay route) and
  `_gec_approval_rate`, then freezes the snapshots under sudo. `action_reject` needs a reason.
  `action_reset_to_draft` and `action_cancel` are blocked while a live claim exists. `write`
  refuses state, snapshot and `user_id` changes and freezes approved logs. Delete: draft,
  rejected or cancelled logs without settlement history (`_unlink_except_processed`).
- Authority checks (`_ensure_owner`, `_ensure_approver`, officer-only cancel and reset) use
  `group_hr_payroll_officer`, because in Odoo 20 `group_hr_payroll_user` is the lowest payroll
  group.
- Overtime mirror: `action_approve` ends with `_gec_create_timesheets`, one `account.analytic.line`
  per approved overtime log from `_gec_timesheet_vals` (the log's project, else its task's
  project, else the company's `internal_project_id`; with none of them `action_approve`
  refuses the log), named
  "Overtime: <reason>", created under sudo in the log's company because the approver may lack
  timesheet rights. `action_reset_to_draft` and `action_cancel` call `_gec_unlink_timesheets`
  first: the link is cleared, then the lines are deleted (the `project_timesheet_holidays`
  pattern). The work-log views offer only `allow_timesheets` projects on overtime logs.

**Unit rates** (`hr.payroll.unit.rate`): `uom_id` is a label only, `price_per_unit` must be
positive, an empty `company_id` shares the rate. `_onchange_company_id` sets the currency from
the chosen company, so a rate made for another company does not keep the creator's currency and
fail at approval.

**Timesheets** (`account.analytic.line`): `gec_settlement_ids`, the waiver stamps
(`gec_payroll_waived_at`, `gec_payroll_waived_by_id`, `gec_payroll_waive_reason`) and the mirror
link `work_log_id`. While a line is claimed or waived, its identity fields (`unit_amount`,
`employee_id`, `date`, `project_id`, `task_id`, `company_id`) are locked and it cannot be
deleted; `validated` is never read: validation is a Timesheets-app step. The stamps change only
through `_gec_waive_payroll_pay` and `action_gec_restore_payroll_pay`; the waiver wizard
pre-fills `_gec_waivable_payroll_lines` and re-checks under lock. A mirror (`work_log_id` set)
is read-only in the timesheet views (`_is_readonly`), refuses non-sudo writes
(`_check_can_write`) and deletion (`_gec_unlink_work_log_lines`), and never passes
`_gec_timesheet_line_eligible`; every timesheet search of the module excludes it in the domain.

**Benefits** (`hr_payroll_benefit.py`): a program (`company_amount`, `employee_amount`,
`recurrence`, `pay_mode`, `advance`, `payslip_count`, period, optional vendor `partner_id`) with
one line per employee. Creating, changing or deleting one re-marks the employees' unedited
drafts; a program or line that was paid cannot be deleted. `_in_period`: one-time lines carry
forward until paid, monthly lines need window overlap, advances run until repaid.
`_benefit_eligible_lines` blocks double carry (once: another live slip carries it; monthly:
overlap or same month; one live pay-out; repayments start the month after the pay-out and stop
at `payslip_count`). `_advance_carrier_inputs` counts only regular salary slips, so overtime
slips never take an installment. Installment = remaining / slips left; the last one takes the
rounding. `hr.payroll.benefit.payrun.action_generate` builds a Benefits run on GEO Benefits Pay
for separate-mode lines, deletes slips that got no benefit input and opens the payslip list filtered on the run
(never `run.action_open_payslips()`: on a draft run it generates a payslip for every eligible contract of the company).

## 11. Security

| Model | Group | Rights |
|---|---|---|
| `hr.employee.work.log` | Internal user | read own and direct reports' logs; create, write and delete own logs in draft or rejected; managers create and write reports' logs in draft or submitted |
| `hr.employee.work.log` | Payroll Officer / Payroll Assistant | all / read |
| `hr.payroll.component.settlement` | payroll users | read, create and release (`write()` refuses everything but `_write_release`; no delete) |
| `hr.payroll.unit.rate` | Internal user / Payroll Administrator | read / all |
| `hr.payroll.benefit`, `hr.payroll.benefit.line`, benefit wizards | payroll users | all (like core's salary attachments) |
| `hr.payroll.tax.exemption` | payroll users / Payroll Administrator | read / all (a limit applies in every company) |
| `gec.payroll.timesheet.waiver` | Payroll Administrator | all |

Company restriction rows cover work logs, settlements, benefits and benefit lines; unit rates
also allow `company_id = False`. Scheme fields, snapshots, settlement fields and the timesheet
`gec_*` fields carry the payroll-user group; `pension_fund_member` carries `hr.group_hr_user`.
Self-service: `hr.employee.public.work_log_ids` and `res.users.work_log_ids` (`user_writeable=True`)
let employees file logs from My Profile; nested creates run under the user's own rules.

`sudo()` serves two purposes. Reads: checks that must see records the user may not (other
payslips of the contract, versions, timesheets, benefit inputs, the person's other
employee records). Writes the user's own rights do not reach: work-log workflow and snapshots
(after `_ensure_owner` / `_ensure_approver`), the overtime mirror lines (created and deleted by
the work-log workflow), waiver stamps (Payroll Administrator actions), the pension flag on the
other side, journal-entry releases and benefit re-marking.

Sudo policy, one line per family. Settlements use none: payroll users have read, create and release rows.
- `hr.version` and `hr.employee`: private fields (wage, pay scheme, personal number) payroll assistants may not read.
- The person's employee records in other companies: the yearly exemption is pooled per person.
- `account.move`: payroll users post and release salary entries without accounting rights.
- Work logs: their record domains hide other employees' logs from the payroll user who computes.
- Timesheets: only approvers read all lines, while Compute claims them for every employee.
- Benefit lines: a payslip compute reads and stamps lines of benefits the user may not open.

## 12. Integration

| Module | Relies on |
|---|---|
| `gec_income_tax_report` | Depends on this module; reads `paid_date`, the lines `GROSS`, `PIT`, `PENSION_EE`, `ADV_PIT_PRE`, `ADV_PEE_PRE`, the `ADVANCE_PAY` inputs and `pension_fund_member`; its tests use `GeoPayrollCase`. Renaming any of them breaks it |
| `gec_payroll_bank` | No dependency. Finds the net by the structure's NET credit account with the employee partner; pays 332010, 331320 and vendor payables as authority payments; uses the agency's ten bank accounts for same-bank matching |
| `basis_bank` | No dependency; its legacy salary send also finds the net by account |
| `gec_localization` | The `l10n_ge` chart and account settings; the configurator runs only for `chart_template == 'ge'` |
| `hr_customization` (Alta) | Declares the same `pension_fund_member` on `hr.employee`; compatible, but the field belongs to whichever module loads last |

## 13. Tests

```bash
./odoo-bin -d <test-db> -i geo_payroll --test-tags /geo_payroll --stop-after-init
```

`tests/common.py` (`GeoPayrollCase`) builds a Georgian company, a payroll-manager user, the four
structures, a square-metre UoM, allowed and excluded projects, and helpers: `_make_employee`
(contract 2025-01-01 to 2027-12-31, wage 1,600, hourly 10, daily 80), `_make_work_log`,
`_approve_log`, `_make_timesheet`, `_make_payslip` (January 2026), `_make_correction_pair`,
`_make_settlement`, `_line_total`.

| File | Covers |
|---|---|
| `test_tax_rules.py` | PIT and pension math, the journal entry, configurator skip, salary-journal default account (skips without a Georgian chart) |
| `test_tax_exemption.py` | Under the limit, crossing month, highest category, bonuses, advances inside the allowance, two same-date slips of one person |
| `test_payroll_schemes.py` | Every scheme, overtime on every scheme |
| `test_payslip_lifecycle.py` | Claim scope, idempotency, carry-forward, frozen components, cancel and reopen, guards, version refresh |
| `test_payrun.py` | Run compute, validate and reset; a paid run cannot reset |
| `test_hr_version.py` | Normalization, the scheme matrix, constraints, mirrors, templates, wage helpers |
| `test_version_segmentation.py`, `test_version_split.py` | Mid-period versions on one full-period slip, clipped slips refused, carry-forward |
| `test_correction_chain.py` | Refund and correction balance |
| `test_edited_slip_claims.py` | Edited-slip guards |
| `test_line_quantity.py` | Quantities and blended amounts, line edits, refunds |
| `test_work_log.py`, `test_unit_work.py` | Work logs and unit rates |
| `test_settlement.py` | The ledger |
| `test_timesheet.py`, `test_timesheet_hourly_base.py` | Timesheet pay, the waiver, timesheet mode |
| `test_benefits.py` | Benefits, deductions, advances and repayments |
| `test_payment_flow.py` | Register Payment and Pay Salaries, vendor split, batch entries refused, paid slips locked, reset re-books |
| `test_pension_sync.py` | The pension flag kept equal on employee and contact |
| `test_known_limitations.py` | Green tests that pin current limitations |
| `test_security.py` | Self-service, manager and officer authority, assistant read-only, field groups, company rules |

Odoo has no xfail (`@unittest.expectedFailure` counts as a failure), so known limitations are
pinned with green tests. Every test runs post-install: v20 tags untagged classes `post_install`.

## 14. Extending safely

- A new pay component needs a `component_code` value on the settlement, an entry in
  `_GEC_COMPONENT_RULE_CODE`, a routing branch on the version and the work log, and a rule in
  the shared set: carry-forward across scheme switches depends on every base structure having every component rule.
- Never write settlements directly; go through claim and release. Never reprice a work-log
  snapshot.
- Keep the off-cycle types without a default structure, and never add a BASIC rule to GEO
  Benefits Pay or GEO Overtime Pay.
- Keep `PIT` self-contained: it must not read `categories['DED']`.
- Company-dependent accounts never go into data XML: extend the configurator mapping, and
  remember it only touches unconfigured companies. Move an existing mapping with a
  fill-only-if-empty pass, not a migration script.
- Keep the rule codes and the `pension_fund_member` field name: `gec_income_tax_report` reads them.
- A new guard on `action_payslip_done` runs before core and gets a test; pay-run validation is
  all or nothing.
- Keep `_allow_sudo_commands = False` on the ledger and work logs, and the ledger's `write` and
  `unlink` raising.
- A new timesheet search excludes `work_log_id` lines in its domain and never filters on
  `validated`: the mirror must not pay, and validation is not a pay condition.
- Keep payroll income tax on the payable 331320: an income-tax line on a `liability_current`
  account cannot be paid by Pay Salaries.
- Keep "Split on names" off on `BENEFIT_DED` and `BENEFIT_KIND_DED`: the vendor split finds their
  journal line by the rule name.

## 15. Known limitations

1. No cross-source check: a daily log and a timesheet on the same day both pay; overtime logs
   are not reconciled with attendance or planning overtime.
2. Abandoned drafts keep their claims and count as live in the overlap and coverage checks.
3. Carry-forward has no lower bound unless an earlier contract overlaps.
4. Pay-run validation is one transaction.
5. `settlement_state = paid` means "on a validated or paid slip", not bank-paid.
6. Exemption limits combine by maximum; earlier-month drafts consume the allowance.
7. `pension_fund_member` is not versioned (advance repayments follow the pay-out slip, not the flag).
8. No state pension share.
9. `UNIT_EXTRA` and `ADVANCE_PAY` share sequence 28 (harmless).
10. An empty `timesheet_pay_project_ids` means every project of the employee's own company. The
    picker is limited to that company plus company-less projects (a field-level domain that
    `inherited=True` carries to the employee form); the contract-template form has an invisible
    `company_id` for that domain.
11. The timesheet lock message says "claimed by a draft payslip" while the check covers any live
    claim.
12. Unit rates: per company or shared; no conversion, no per-employee or per-project rate, no
    quantity ceiling.
13. A validated overtime mirror blocks its log's reset and cancel for users outside
    `hr_timesheet.group_hr_timesheet_approver`: core's `_check_can_write` and `_unlink_if_manager`
    in `timesheet_grid` check the real user even under sudo, exactly as for time-off lines.
14. The 24 h/day cap counts payable timesheet hours only; an overtime mirror on the same date is
    not added to them.

## 16. Upgrading an existing database

Upgrades never overwrite accounts an accountant set (section 9), so some fixes need a manual step:

- If the `PIT` and `ADV_PIT_PRE` rules still book to 331310, set them to 331320, and give the
  State Treasury contact the Treasury Code 101001000.
- The data does not ship a `GE_PUBLIC_HOLIDAY` time type. On a database that still has one, an
  upgrade deletes it only when its external id is not `noupdate` (hr_payroll's weekly "Payroll:
  Update data" cron clears the flag); otherwise archive it by hand.
- Overtime logs approved before the mirror existed have no timesheet line; nothing backfills
  them. Reset and re-approve a log if it needs one.
- Unvalidated timesheet lines of employees on a timesheet scheme become payable at the next
  compute; check for stray draft lines before the first pay run after the upgrade.
- Accounts changed on 2026-11-12: bonus and the company share paid to a vendor book on 720110,
  overtime on 720200, employer pension on 721000. The first upgrade after that date moves a rule once, only where it
  still holds the old default (720100 or 740900): `_gec_move_rule_accounts`, flag
  `geo_payroll.payroll_accounts_20261112`. A refund or correction of a payslip posted before the
  upgrade reverses on the new accounts. The method can be deleted once every database is upgraded.
- Odoo's own Georgian payroll: every upgrade runs `_gec_retire_core_ge_structure`. A contract on
  Odoo's type moves to our type of the same wage type only when our structures pay it the same way:
  no payslip on any structure of Odoo's type, a gross wage (not Odoo's net-salary basis), no Odoo tax
  privilege, a company on the standard tax regime, and no contract allowance. Every other contract
  stays on Odoo's type until someone sets it up by hand (enter our income-tax exemption, turn the net
  wage into gross, add the allowance as a benefit) and clears the Odoo setting; the next upgrade then
  moves it. While a contract is left, Odoo's type is put after ours, so a new contract takes ours by
  default; once none is left, Odoo's type and structure are archived. Uninstall
  `l10n_ge_hr_payroll` by hand where it is installed.
  Odoo keeps the pension choice on the contract (**Funded Pension**), we keep it on the employee: an
  employee whose current contract moves and says Participant gets **Pension Fund Member** switched on;
  an older contract version never changes it. Participant is Odoo's default, so check the moved
  employees once. The retire tests run only on a database where Odoo's Georgian payroll is installed;
  elsewhere they skip.
