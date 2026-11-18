# GEO Payroll — Simple and Complete User Guide

This guide explains how `geo_payroll` decides what to pay, what every contract field means, and
how work logs, timesheets, payslips, pay runs, waivers, cancellations, refunds, and corrections
move through the system.

> **Current scope:** the module calculates gross wage and custom payroll components. It does not
> yet provide complete Georgian income tax, pension, accounting, or production sign-off.

> **Odoo 20 (2026-09-23):** sections 13, the line-edit paragraph, the payment paragraph, the Work
> Entry Source row, the troubleshooting rows and (2026-09-24) the payslip header paragraph in
> section 10 describe the Odoo 20 port. Other sections were
> written for Odoo 19 and are not re-verified yet. In Odoo 20 a full month means the working
> schedule's hours (January 2026: 22 days / 176 hours), not 20 days / 160 hours: Odoo 20 prorates a
> monthly wage against the schedule, not against the payslip's own worked-day hours.

The examples use these rates:

- Monthly Wage: **1,600 GEL**
- Hourly Wage: **10 GEL**
- Daily Wage: **80 GEL**
- Full month: **20 days / 160 hours**

---

> **Payroll and Form 30, checked 2026-10-13** (Opus bug-hunter on prod1 data; details in
> [form30_entry_redesign_plan.md](../dev_notes/plans/form30_entry_redesign_plan.md) section 4.4 "Salaries"): September Form 30 tax 6,287.95
> equals the 331320 credits and pension matches; advances, repayments and exempt relief are right. Paths that go wrong:
> - **S1** a net-pay payment rejected or never sent: core Mark Unpaid keeps the Payment Date, so a slip paid again next month
>   is declared twice (Pay Salaries) or stays in the old month (Register Payment). Fix planned (Form 30 step 1: Mark Unpaid
>   clears the date, a new payment's date wins).
> - **S2** net pay settled straight from a bank statement: the slip never becomes Paid and is never declared.
> - **S3** zero net with income tax above zero: no NET line, never Paid, never declared.
> - **S4** net paid in two parts in two months: all in the last month (the tax law wants each part in its own month).
> - **Corrections:** a correction slip is computed in full; Form 30 reports origin + correction (1,000 + 1,100 = 2,100).
> - **Accounts vs the accountant's table:** payroll posts income tax on **331320** (table: 331310, which is not payable, so
>   Pay Salaries would refuse every slip); keep 331320. Since 2026-11-12 the defaults follow the table: bonus and the company
>   share paid to a vendor on **720110**, overtime logs on **720200**, employer pension on **721000**, a typed **Termination
>   Payment** input on **720700**; base pay and the other extra-pay lines stay on 720100. The account fill writes only empty values, so an upgrade moves a rule once, and only
>   where it still holds the old default (720100 or 740900); an account an accountant chose stays
>   (`_gec_move_rule_accounts`, [account_chart_template.py](../custom_addons/gec_odoo_modules/geo_payroll/models/account_chart_template.py)).
>   A refund or correction of a payslip posted before that upgrade reverses on the new accounts.
> - **Pension on a benefit paid to a vendor:** since 2026-11-12 the company share is in the pension base, like salary
>   (accountant's answer); wage 1,000 + company share 100, member: pension 22.00 each side, income tax 215.60, net 762.40.
> - **Odoo's own Georgian payroll (`l10n_ge_hr_payroll`):** it books income tax on 331310, which Pay Salaries cannot pay.
>   geo_payroll keeps it out of a new Georgian company's module list and, on every upgrade, moves a contract to our type of
>   the same wage type only when our structures pay it the same way: never paid on any structure of Odoo's type, gross wage
>   (not Odoo's net-salary basis), no Odoo tax privilege, company on the standard tax regime, no contract allowance. The rest
>   stay on Odoo's type until set up by hand; meanwhile Odoo's type is put after ours, so a new contract takes ours by
>   default. Odoo's type and structure are archived once no contract is left on it. An
>   employee whose current contract moves and says pension **Participant** gets our **Pension Fund Member** switched on
>   (Participant is Odoo's default: check the moved employees once); an older contract version never changes it. The first
>   Payroll install on a Georgian database still installs Odoo's module: uninstall it by hand.

## 1. The three records that can affect pay

These names are similar, but they are different records:

| Record | Plain meaning | Typical use in this module |
|---|---|---|
| **Work Entry** | Odoo payroll calendar hours generated from Working Schedule, Attendances, or Planning | Fixed base and Hourly-from-Work-Entries base; leave and public-holiday payroll behavior |
| **Work Log** | A custom record submitted and approved by an employee, manager, or payroll user | Daily pay, unit (piecework) pay, and overtime pay |
| **Timesheet** | Project/task hours recorded in Odoo Timesheets | Hourly base from Timesheets, or an hourly addition on combined schemes |

The employee's **Pay Scheme** first decides the base calculation. Some schemes then add an extra
component. **Pay Overtime Work Logs** is a separate optional addition where allowed.

---

## 2. Choose the Pay Scheme first

There are eight Pay Scheme choices, but Hourly has two possible sources. This creates nine practical
calculation cases.

| Pay Scheme and source | Base pay | Scheme addition | Work-entry money | Leave / holiday money |
|---|---|---|---|---|
| **Fixed** | Monthly wage through Odoo `BASIC` | None | Yes | Follows the work-entry type and its paid rate |
| **Hourly — Work Entries** | Paid work-entry hours × Hourly Wage | None | Yes | Follows the work-entry type and its paid rate |
| **Hourly — Timesheets** | Eligible validated timesheet hours × Hourly Wage | None | **No** | **No** — only eligible timesheets pay |
| **Daily** | Approved Daily Work logs × Daily Wage | None | No | No log means no Daily pay |
| **Per Unit** | Approved Unit Work logs × frozen catalog price | None | No | No log means no Unit pay |
| **Fixed + Daily** | Fixed monthly base | Approved Daily Work logs × Daily Wage | Yes for the fixed base | Follows the fixed base work entries |
| **Fixed + Hourly** | Fixed monthly base | Eligible validated timesheets × Hourly Wage | Yes for the fixed base | Follows the fixed base work entries |
| **Daily + Hourly** | Approved Daily Work logs × Daily Wage | Eligible validated timesheets × Hourly Wage | No | No Daily log means no Daily base pay |
| **Daily + Per Unit** | Approved Daily Work logs × Daily Wage | Approved Unit Work logs × frozen catalog price | No | No Daily log means no Daily base pay |

### The most important Hourly rule

For the pure **Hourly** scheme, **Hourly Source** is the real choice:

- **Work Entries:** keep standard Odoo hourly pay. The normal Odoo **Work Entry Source** can still
  be Working Schedule, Attendances, or Planning.
- **Timesheets:** pay only eligible validated project timesheets. Work entries still exist for
  calendars, leave management, and conflict checks, but every work-entry amount is forced to zero.
  Paid leave, public holidays, Daily Work logs, and Overtime Work logs also pay zero or are blocked.

There is no fallback. If an Hourly-from-Timesheets employee has no eligible timesheet hours, a zero
payslip is correct.

---

## 3. Contract fields in plain language

The payroll fields live on the effective employee contract version (`hr.version`). Fields visible
on the employee are related views of that current version; historical versions keep their own
values.

### Fields a payroll user chooses

| Screen label | Technical field | What it determines |
|---|---|---|
| **Pay Scheme** | `pay_scheme` | The main route: Fixed, Hourly, Daily, Fixed + Daily, Fixed + Hourly, or Daily + Hourly |
| **Salary Structure Type** | `structure_type_id` | Must match the scheme's wage type: GEO Monthly, GEO Hourly, or GEO Daily |
| **Wage** | `wage` | Monthly amount used by Fixed, Fixed + Daily, and Fixed + Hourly |
| **Hourly Wage** | `hourly_wage` | Hourly base, timesheet rate, and/or overtime rate, depending on the scheme |
| **Daily Wage** | `daily_wage` | Daily base or Fixed + Daily addition |
| **Tracked by Attendance** | Odoo `attendance_based` (Odoo 20, from `hr_attendance`; replaces v19 `work_entry_source`) | Whether work entries come from badge attendances instead of the Working Schedule. An hourly employee tracked by attendance cannot get work logs approved |
| **Pay Overtime Work Logs** | `worklog_ot_enabled` | Allows approved work logs whose **Type is Overtime** to pay `hours × Hourly Wage × Rate %` |
| **Hourly Source** | `hourly_source` | Only for pure Hourly: regular pay comes from Work Entries or Timesheets |
| **Payroll Timesheet Projects** | `timesheet_pay_project_ids` | Project allow-list. Timesheets on other projects never pay |
| **Timesheet Pay From** | `timesheet_pay_start_date` | Earliest timesheet date allowed into payroll; prevents the first payslip from sweeping old history |

### Fields the scheme determines automatically

| Screen label | Technical field | Why it may look false or be hidden |
|---|---|---|
| **Wage Type** | `wage_type` | Derived from Pay Scheme. It is hidden on the employee form because users should choose Pay Scheme, not maintain two conflicting selectors |
| **Pay Daily Work Logs** | `worklog_daily_enabled` | True only for **Fixed + Daily**, where Daily Work logs are an addition to a fixed base. It is not the switch for the pure Daily scheme |
| **Pay Timesheet Hours** | `timesheet_extra_enabled` | True only for **Fixed + Hourly** and **Daily + Hourly**, where timesheets are an addition. It is not the switch for Hourly-from-Timesheets base pay |
| **Daily Source** | `daily_source` | Fixed internally to Approved Work Logs. Working Schedule is reserved but currently rejected |

### Why “Pay Daily Work Logs” can be false

This field means **pay Daily Work logs as an extra component**.

- **Daily:** the Daily Work log is already the base, so this extra flag is false.
- **Fixed + Daily:** the fixed wage is the base and Daily Work logs are extra, so the flag is true.
- All other schemes: Daily Work logs have no route and cannot be approved for pay.

### Why “Pay Timesheet Hours” can be false

This field means **pay timesheets as an extra component**.

- **Fixed + Hourly / Daily + Hourly:** timesheets are extra, so the flag is true.
- **Hourly + Hourly Source = Timesheets:** timesheets are the base, not an extra, so the flag is
  correctly false. The **Hourly Source** field activates this route.
- Fixed, Hourly-from-Work-Entries, Daily, and Fixed + Daily: timesheets do not pay.

### What “Pay Overtime Work Logs” means

This checkbox affects only a Work Log with **Type = Overtime**. It never enables Daily Work logs.

```text
Overtime amount = Hours × Hourly Wage × Rate %
```

Example: `3 hours × 10 GEL × 150% = 45 GEL`.

It can be used with any scheme except these two cases:

1. Pure Hourly paid from **Attendances**: attendance/badge hours are already the payroll record, so
   all custom work logs are blocked to prevent duplicate payment.
2. Pure Hourly paid from **Timesheets**: the policy is “timesheets only,” so the overtime checkbox
   is hidden, cannot be enabled, and Overtime Work logs cannot be approved.

For other routes, the module does not fully reconcile custom overtime with attendance/planning
overtime or with project timesheets. Payroll must enforce its chosen overlap policy.

---

## 4. Why fields appear, disappear, or become read-only

The view conditions only control what users see. They do not calculate salary by themselves; the
model validations and salary rules enforce the actual calculation.

| View rule | Easy explanation |
|---|---|
| `worklog_ot_enabled` is invisible for Hourly + Timesheets | Timesheets are the only payable record, so custom overtime is not allowed |
| `worklog_daily_enabled` is read-only and hidden on the employee | Pay Scheme computes it; only Fixed + Daily sets it true |
| `timesheet_extra_enabled` is read-only and hidden on the employee | Pay Scheme computes it; only Fixed + Hourly and Daily + Hourly set it true |
| `hourly_source` is invisible unless Pay Scheme = Hourly | Only pure Hourly can choose between Work Entries and Timesheets |
| `daily_source` is always invisible | Daily is currently always paid from Approved Work Logs |
| Payroll Timesheet Projects and Timesheet Pay From appear for a timesheet-extra scheme | Fixed + Hourly and Daily + Hourly require timesheet routing data |
| The same two fields appear for Hourly + Timesheets | Pure Hourly needs them when timesheets are its base |
| Daily Wage appears for a Daily wage type or Fixed + Daily | Those are the only routes that price Daily Work logs |
| “Hourly Rate (Overtime / Timesheet)” appears on a non-hourly scheme only when needed | Fixed/Daily schemes need Hourly Wage only if overtime or a timesheet addition uses it |

The supplied XML therefore means:

```xml
<field name="worklog_ot_enabled"
       invisible="pay_scheme == 'hourly' and hourly_source == 'timesheet'"/>
<field name="worklog_daily_enabled" readonly="1" invisible="1"/>
<field name="timesheet_extra_enabled" readonly="1" invisible="1"/>
<field name="hourly_source" invisible="pay_scheme != 'hourly'"/>
<field name="daily_source" invisible="1"/>
<field name="timesheet_pay_project_ids"
       invisible="not timesheet_extra_enabled and (pay_scheme != 'hourly' or hourly_source != 'timesheet')"/>
<field name="timesheet_pay_start_date"
       invisible="not timesheet_extra_enabled and (pay_scheme != 'hourly' or hourly_source != 'timesheet')"/>
```

On contract templates, the two computed flags are visible but read-only. On the employee payroll
form they are hidden because the chosen Pay Scheme already communicates the same information.

---

## 5. Required setup for every calculation case

| Case | Required values | Salary lines expected |
|---|---|---|
| Fixed | GEO Monthly structure type, Monthly Wage, valid work entries | `BASIC` |
| Hourly — Work Entries | GEO Hourly structure type, Hourly Wage, Hourly Source = Work Entries, Odoo Work Entry Source | `BASIC` |
| Hourly — Timesheets | GEO Hourly structure type, positive Hourly Wage, Hourly Source = Timesheets, at least one payroll project, Pay From date | `TIMESHEET_BASIC`; `BASIC` must be zero |
| Daily | GEO Daily structure type, positive Daily Wage, approved Daily Work logs | `DAILY_BASIC`; `BASIC` must be zero |
| Fixed + Daily | GEO Monthly structure type, Monthly Wage, positive Daily Wage, approved Daily Work logs for additions | `BASIC` + `WORKLOG_DAILY` |
| Fixed + Hourly | GEO Monthly structure type, Monthly Wage, positive Hourly Wage, payroll projects, Pay From date, validated timesheets | `BASIC` + `TIMESHEET_EXTRA` |
| Daily + Hourly | GEO Daily structure type, positive Daily Wage, approved Daily Work logs, positive Hourly Wage, payroll projects, Pay From date, validated timesheets | `DAILY_BASIC` + `TIMESHEET_EXTRA` |
| Per Unit | GEO Unit structure type, active Unit Work Rates, approved Unit Work logs | `UNIT_BASIC`; `BASIC` must be zero |
| Daily + Per Unit | GEO Daily structure type, positive Daily Wage, approved Daily Work logs, active Unit Work Rates, approved Unit Work logs | `DAILY_BASIC` + `UNIT_EXTRA` |

For timesheet-extra schemes, the code requires a Pay From date. Always select at least one payroll
project as well; an empty project allow-list leaves every timesheet ineligible.

The structure type must match the Pay Scheme:

| Pay Scheme | Required Wage Type / Structure Type |
|---|---|
| Fixed, Fixed + Daily, Fixed + Hourly | Monthly / GEO Monthly Pay |
| Hourly | Hourly / GEO Hourly Pay |
| Daily, Daily + Hourly, Daily + Per Unit | Daily / GEO Daily Pay |
| Per Unit | Unit / GEO Unit Pay |

Save Pay Scheme and its matching Salary Structure Type together. The derived Wage Type follows the
scheme automatically.

---

## 6. Calculation examples

### Fixed

```text
Base = paid work-entry hours × monthly hourly equivalent × work-entry-type rate
```

- Full 160-hour month: **1,600 GEL**.
- If 16 hours exist as unpaid leave, 144 hours pay: normally **1,440 GEL**.
- If Attendances or Planning creates only 120 hours, Odoo may shrink the denominator as well and
  still pay the full **1,600 GEL**. Use Working Schedule unless another fixed-wage proration policy
  has been designed and tested.

### Hourly from Work Entries

```text
Base = paid work-entry hours × Hourly Wage × work-entry-type rate
```

- 160 hours × 10 = **1,600 GEL**.
- 152 hours × 10 = **1,520 GEL**.
- An unpaid work-entry type pays zero.

### Hourly from Timesheets

```text
Base = eligible validated timesheet hours × Hourly Wage of the version active on the work date
```

- 12 timesheet hours × 10 = **120 GEL**.
- The schedule may still show 160 work-entry hours, but those work entries pay **0 GEL**.
- Approved paid leave without a project timesheet pays **0 GEL**.
- Public holiday without a project timesheet pays **0 GEL**.
- No eligible timesheets means a correct **0 GEL base payslip**.
- An ordinary allowed-project timesheet entered on a holiday can still pay at the normal 100% hourly
  rate. This module does not add a holiday premium.

### Daily

```text
Base = approved Daily Work units × Daily Wage frozen at approval
```

- 20 full-day logs × 80 = **1,600 GEL**.
- One half-day log: 0.5 × 80 = **40 GEL**.
- No approved Daily Work log for a date means no Daily pay for that date, including leave and public
  holidays.

### Fixed + Daily

```text
Gross before other rules = Fixed base + approved Daily Work additions
```

Example: `1,600 + (1 day × 80) = 1,680 GEL`.

### Fixed + Hourly

```text
Gross before other rules = Fixed base + eligible timesheet hours × Hourly Wage
```

Example: `1,600 + (12 hours × 10) = 1,720 GEL`.

### Daily + Hourly

```text
Gross before other rules = approved Daily Work base + eligible timesheet addition
```

Example: `(20 days × 80) + (10 hours × 10) = 1,700 GEL`.

### Per Unit

```text
Base = approved Unit Work quantity × price per unit frozen at approval
```

- 12.5 m² of tile laying at 10 GEL/m² = **125 GEL**.
- Schedule/work-entry rows may exist for calendars and conflict checks, but they pay **0 GEL**;
  leave and public holidays also pay nothing.
- Multiple Unit logs per day (different rooms, different work types) are normal and all pay.
- No approved Unit log means a correct **0 GEL payslip**.

### Daily + Per Unit

```text
Gross before other rules = approved Daily Work base + approved Unit Work additions
```

Example: `(1 day × 80) + (8 m² × 10) = 160 GEL`. A Daily log and Unit logs on the same date both
pay — that is the scheme's intent (a day rate plus piecework output), not a defect.

The module currently allows a Daily Work log and project timesheets on the same date. They represent
different configured components, but there is no full cross-source overlap check.

---

## 7. Work Log flow

### What a Work Log can represent

| Work Log Type | Fields used | Formula | Where it can pay |
|---|---|---|---|
| **Daily Work** | Date and Days (`0 < Days ≤ 1`) | Days × Daily Wage | `DAILY_BASIC` for Daily/Daily + Hourly; `WORKLOG_DAILY` for Fixed + Daily |
| **Overtime** | Date, Hours (`0 < Hours ≤ 24`), and Rate % | Hours × Hourly Wage × Rate % | `WORKLOG_OT` when Pay Overtime Work Logs is enabled and the route is allowed |
| **Unit Work** | Date, Unit Rate item, and Quantity (`> 0`, any decimal, no cap) | Quantity × Price per Unit frozen at approval | `UNIT_BASIC` for Per Unit; `UNIT_EXTRA` for Daily + Per Unit |

Only one active Daily Work log can exist for an employee/date. Multiple Overtime logs can exist, but
their active total cannot exceed 24 hours for that employee/date. Multiple Unit Work logs per
employee/date/item are allowed — there is no quantity ceiling; the approver is the volume control.

### Unit Work Rates catalog

**Payroll → Unit Work Rates** (Payroll Managers only) defines the piecework price list: a name
("Tile laying"), a unit of measure, and a price per unit. Every internal user can read the catalog —
they must pick an item when filing a Unit log, and the form shows them the current price and the
computed amount live. The UoM is a label only: no unit conversion exists anywhere.

The catalog is **global** — one price list shared by all companies. A Unit log can only be approved
when the rate's currency equals the employee company's currency; there is no automatic conversion.

Approval is the freezing point: it stamps the price, amount, currency, component, and **UoM** onto
the log. Editing a rate's price or UoM afterwards changes only future approvals — approved logs,
their payslip lines, and their settlements never move, and the log form keeps showing the frozen
values (also on a log that was approved and later cancelled: its snapshots are audit history). Archive a rate to retire it (approval of drafts pointing to it is refused); a rate that was
ever used in an approved log cannot be deleted.

### Where users work with Work Logs

- Employee: **My Profile → Work Logs**, or the employee directory card → **New Work Log**.
- Direct manager: **Employees → Work Log Approvals** for direct reports.
- Payroll user: **Payroll → Work Logs**.

### Status flow

```text
Draft → Submitted → Approved → Claimed by a draft payslip → Validated/Paid
  ↑        ↓
Reset    Rejected

Payroll can also Cancel a log that is not actively claimed.
```

### Approval checks

At approval the module checks:

- the work date is not in the future;
- the employee has an effective contract version on that date;
- the contract version enables the matching Daily, Unit, or Overtime route;
- the quantity is valid and the rate is positive;
- for Unit logs: the rate item is not archived and its currency matches the employee company;
- attendance-based Hourly is not being duplicated by a custom work log;
- Hourly-from-Timesheets is not being duplicated by Overtime Work logs.

Approval freezes the source contract version, component, currency, rate, amount, the UoM for Unit
logs, approver, and time. A later wage, scheme, or catalog change does not reprice that approved
Work Log.

An employee cannot approve their own log. Their direct manager can approve/reject it. Payroll users
can approve and can reset approved/cancelled logs.

An approved Work Log with an active payslip claim cannot be reset or cancelled. First cancel,
delete, or recompute the draft payslip so the claim is released. Work Logs with settlement history
cannot be deleted, even after the active claim is released.

---

## 8. Timesheet payroll flow

### Configure the employee

Timesheets need:

1. A route that pays timesheets:
   - Hourly + Hourly Source = Timesheets for base pay; or
   - Fixed + Hourly / Daily + Hourly for extra pay.
2. A positive Hourly Wage on the work-date contract version.
3. At least one **Payroll Timesheet Project**.
4. A **Timesheet Pay From** date.

When Hourly-from-Timesheets is first enabled, the form may warn that existing validated lines on
the selected projects and after the cutoff will become payable. This is only a preview. The server
still applies the full eligibility rules when computing payroll.

### Create and validate the Timesheet

The normal Timesheets process creates the line. Payroll only considers a line when it is validated.
Validation does not freeze a payroll amount; the line is priced when a draft payslip claims it.

### Eligibility checklist

A timesheet pays only when all of these are true:

- validated;
- belongs to the payslip employee and company;
- date is inside an effective contract version and not after the payslip end date;
- project is in Payroll Timesheet Projects;
- date is on or after Timesheet Pay From;
- hours are positive and not more than 24 on the line;
- total payable timesheet hours for the employee/date, including existing active claims, do not
  exceed 24;
- work-date contract version has a timesheet-paying route and positive Hourly Wage;
- it is not a holiday/global-leave/generated Work Log analytic line;
- it is not waived;
- another payslip has not already claimed it.

The price is always taken from the contract version active on the timesheet date:

```text
Timesheet amount = Hours × work-date Hourly Wage
```

### Claiming and carry-forward

Computing a normal, unedited, draft payslip with the employee's default structure creates an active
settlement claim. That claim freezes the quantity, rate, amount, source version, currency, component,
and destination payslip.

There is no lower payslip-date boundary. A January item validated too late can be carried forward to
a later regular payslip, while still using January's contract version and rate. This also works after
a correctly dated scheme change because the custom salary rules exist on all GEO structures.

Late payment therefore follows the **source date**, not the destination slip's current scheme:

- a January Hourly-from-Timesheets line carried into a February Fixed slip remains
  `TIMESHEET_BASIC`;
- the February slip can contain its own Fixed `BASIC` plus the January carried-forward
  `TIMESHEET_BASIC`.

---

## 9. Waive Timesheet Pay

### Purpose

Waiving is an audited way to say:

> “These validated timesheets must never be paid by payroll.”

Its main use is correcting a wrong Hourly-from-Timesheets setup. Without a waiver, switching that
contract version away from Timesheets could silently strand validated unpaid hours. The module
therefore blocks the routing change until the lines are paid, preserved by a dated version, or
explicitly waived.

Do **not** waive merely because a timesheet will be paid late. Carry-forward already handles
late valid lines. A waiver means intentional abandonment of payroll pay.

### Entry point

The action lives directly on the timesheet. There is no standalone menu or contract-version picker.
A Payroll Manager selects timesheets and runs the action from the **Actions** menu of the timesheet
list or form. The Timesheets app opens in grid view by default; switch to **List** to multi-select.

Both actions and the restore method are Payroll-Manager-only, enforced by the action binding and
re-checked in the code.

### Waiving

1. In the timesheet **List**, select the lines to waive.
2. **Actions → Waive Payroll Pay**.
3. The dialog pre-fills **Timesheets to Waive** with the waivable subset of the selection and asks
   for a required business **Reason**.
4. Click **Waive Pay**.

A line is waivable only if it is validated, unclaimed, not already waived, and currently
payroll-payable under its own work-date contract version
([`_gec_waivable_payroll_lines`](../custom_addons/gec_odoo_modules/geo_payroll/models/account_analytic_line.py)).
Non-waivable lines in the selection are silently dropped from the pre-fill. The dialog locks and
re-checks every line at confirmation, rejecting any that became claimed, unvalidated, already waived,
or no longer payroll-payable in the meantime.

If a line is claimed by a draft payslip, it is not waivable. Cancel or delete that draft payslip
first to release the claim, then waive.

### What waiver changes

Each waived timesheet receives:

- Payroll Pay Waived On;
- Payroll Pay Waived By;
- Payroll Waive Reason.

A waived line:

- is excluded from all future payroll claiming;
- no longer blocks the Hourly Source/project/cutoff change;
- cannot have its identity, hours, date, employee, project, company, or validation changed;
- cannot be deleted.

Direct writes through imports, RPC, server actions, or normal forms cannot forge or clear these
fields. The waiver stamps are visible on the timesheet form (a payroll-only group) and as an
optional **Pay Waived** column in the timesheet list.

### Restoring payroll eligibility

**Actions → Restore Payroll Pay** on the selected timesheet(s) clears all three waiver stamps
together in one click (Payroll Manager only). Restoring removes the waiver only. The line becomes
payable again only if its work-date contract version still has a valid timesheet-paying route,
project, cutoff, and rate. Restore records no separate reason; only database/audit logging identifies
the restore operation.

---

## 10. Payslip flow

### Recommended normal flow

1. Confirm the employee has the correct effective contract version, Pay Scheme, matching Salary
   Structure Type, rates, and source fields.
2. Generate/check Odoo Work Entries and resolve conflicts. Even Timesheets-only and Daily schemes
   still use Odoo's calendar machinery and conflict checks.
3. Approve all payable Work Logs.
4. Validate all payable Timesheets.
5. Create the normal draft payslip or generate the pay run.
6. Compute the payslip.
7. Open the **Work Items** smart button to inspect every claimed Work Log/Timesheet, source date,
   component, source version, quantity, rate, amount, and active status.
8. Review worked days, salary lines, gross, and net.
9. Validate the payslip, then complete payment through Odoo's normal flow.

### What the payslip header tells the accountant (Odoo 20, 2026-09-24)

Odoo 20 puts two summary cards at the top of the payslip
([hr_payslip_views.xml:95](../enterprise/hr_payroll/views/hr_payslip_views.xml#L95)). The module
leaves them as Odoo built them, so read them knowing what they count:

| Card | What Odoo counts | What that means on GEO slips |
|---|---|---|
| **Worked days** | paid worked-day lines, i.e. the working schedule ([hr_payslip.py:792](../enterprise/hr_payroll/models/hr_payslip.py#L792)) | right for Fixed and Hourly-from-Work-Entries; on Daily, Per Unit and Hourly-from-Timesheets it still shows the full schedule (22 days / 176 h) although those days pay 0 |
| **Wage** | the `BASIC` line only ([hr_payslip.py:714](../enterprise/hr_payroll/models/hr_payslip.py#L714)) | shows 0.00 on Daily, Per Unit and Hourly-from-Timesheets (their base is `DAILY_BASIC` / `UNIT_BASIC` / `TIMESHEET_BASIC`); on Fixed + additions it shows the fixed part only |
| Net under Wage | the `NET` line | includes an advance pay-out: gec20_prod1 slip 1 shows Wage 3,000 and Net 10,686 because 9,800 of the net is the advance |

The module adds a third card, **Work Items**, before them: the amount and quantities of the logs and
timesheets this payslip pays, for example `1,265.00` and `15.00 days Daily Work (Basic) · 5.00 h
Overtime`. It reads the payslip's own live claims, the same records as the **Work Items** button and
the work-item salary lines, so the three always agree. It is hidden when there is nothing (Fixed-only
slips, refunds and corrections, which hold no claims of their own). After a manual line edit the card
still shows the claims, while the edited line shows the manual amount.

The **Work Items** button opens the claims grouped by component with quantity and amount totals, the
project and task of each timesheet or work log, the frozen rate and the priced-by version. Released
claims sit behind the *Released* filter, for the audit trail.

**Line explanations.** Odoo 20 shows an info icon on a salary line when the rule has an
`explanation_template` ([hr_payslip.py:2476](../enterprise/hr_payroll/models/hr_payslip.py#L2476),
Belgian payroll uses the same mechanism). The module fills it on three kinds of lines:

| Line | Example text (demo slips, test DB) |
|---|---|
| Work-item lines (`DAILY_BASIC`, `TIMESHEET_BASIC`, `UNIT_BASIC`, `WORKLOG_*`, `*_EXTRA`) | "15 approved Daily Work logs (01/01/2026 - 01/21/2026): 15.00 days × 80.00 = 1,200.00"; overtime adds the Rate %: "2.00 h × 10.00 × 100% + 3.00 h × 10.00 × 150% = 65.00"; timesheets add "Projects: Office Renovation 30.50 h, Warehouse Build 12.00 h"; unit work lists each work type with its unit and price |
| `PIT` | "Taxable income = gross 3,000.00 + advance pay-out 10,000.00 - employee pension 260.00 - tax exemption left 3,000.00 = 9,740.00. Income tax = 20% × 9,740.00 = 1,948.00." |
| `NET` | "Net = gross 3,000.00 - deductions 2,020.00 + advance pay-out 9,800.00 = 10,780.00." |

The text is built from the same numbers the rule used, rounded half-up like the line totals. Only
payslips computed after the module upgrade carry it; validated and paid slips keep the lines they
were validated with. When a line is edited by hand, the edited line loses its explanation and every
other line keeps its own
([`_recompute_with_forced_lines`](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payslip.py)).

### What compute does

For a normal, unedited draft payslip on the version's default structure, compute:

- keeps still-valid claims;
- releases stale claims with a reason;
- claims newly eligible Work Logs and Timesheets;
- creates salary lines from active settlement totals.

Refunds, corrections, manually edited slips, and special/off-cycle structures do not create new
source claims.

**Manually edited payslips (since 19.0.1.7.0):** editing lines through the Edit Payslip Lines
wizard keeps the slip's existing claims — they are the audit link for the work-item pay the
lines still contain. Because an edited slip can never claim again, two operations are guarded:

- **Compute is refused** while an edited slip holds active claims. Recomputing would discard the
  manual lines and release every claim with no way to claim them back — the work logs and
  timesheets would silently stay unpaid (the version-coverage rule prevents a second regular
  slip for the same slice). Cancel the payslip instead: cancellation releases its claims for a
  new standard payslip. Validating the edited slip as-is stays possible.
- **Validation is refused** when eligible approved work logs or payable validated timesheets in
  the slip's window are not claimed. For an unedited slip the fix is to compute again; an edited
  slip cannot claim, so the error says to cancel it and create a standard slip (or waive the
  timesheets). Before 19.0.1.7.0 edited slips skipped this check entirely, so an edited slip
  could validate while eligible work items stayed unpaid forever.

Both automated recompute paths (`action_refresh_from_work_entries`, version-change
`_recompute_payslips`) already excluded edited slips, so these guards only fire on direct user
actions.

### What confirmation checks

Confirmation refuses inconsistent payroll, including:

- an active source claim that no longer matches the source/version/rate/amount;
- a custom salary line that does not equal its active settlement total;
- an eligible approved Work Log or validated Timesheet that should have been claimed but was
  skipped — including on manually edited slips, which cannot claim and must be cancelled and
  replaced instead (since 19.0.1.7.0);
- Daily `BASIC` that was not zeroed;
- Hourly-from-Timesheets work-entry `BASIC` or worked-day money that was not zeroed;
- an Hourly-from-Timesheets slip that is edited, on the wrong structure, or missing the required
  `TIMESHEET_BASIC` behavior.

A zero Hourly-from-Timesheets payslip is allowed only when there are genuinely no eligible
timesheets.

### Salary line codes

| Code | Meaning | Category |
|---|---|---|
| `BASIC` | Standard Odoo Fixed/Hourly work-entry base; zero for Hourly-from-Timesheets and hard zero on the Unit structure | BASIC |
| `DAILY_BASIC` | Daily base from approved Daily Work logs | BASIC |
| `TIMESHEET_BASIC` | Hourly base from validated timesheets | BASIC |
| `UNIT_BASIC` | Per Unit base from approved Unit Work logs | BASIC |
| `WORKLOG_OT` | Overtime Work Log addition | ALW |
| `WORKLOG_DAILY` | Fixed + Daily Work Log addition | ALW |
| `TIMESHEET_EXTRA` | Fixed + Hourly or Daily + Hourly timesheet addition | ALW |
| `UNIT_EXTRA` | Daily + Per Unit unit-work addition | ALW |
| `GROSS` | BASIC category + ALW category | GROSS |
| `PENSION_EE` | −2% × GROSS, only when `employee.pension_fund_member` | DED |
| `PIT` | −20% × (GROSS + DED so far) — pension-reduced base for members, full gross for non-members | DED |
| `PENSION_ER` | +2% × GROSS, members only — company cost, outside NET | COMP |
| `NET` | BASIC + ALW + DED | NET |

**Quantity column on Salary Computation lines (since 19.0.1.6.0):** the seven work-item rules
set `result_qty` to the claimed settlement quantity (hours for timesheets/overtime, day units
for daily work, units for piecework) and `result` to the per-unit amount via
`payslip.gec_component_line_vals(code)`
([hr_payslip.py](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payslip.py)). The
line total stays settlement-exact by construction: the engine multiplies the *unrounded* unit
amount back by the quantity, so `_gec_check_lines_match_settlements` always holds — even when
per-settlement rounding makes `quantity x displayed rate` differ by a cent from the total
(the displayed unit amount is the effective blended rate, 2 decimals). A component whose
claimed quantity is zero falls back to quantity 1.00 with the full total as amount. Before
19.0.1.6.0 every line showed quantity 1.00/rate 100% (rules set only `result`; Odoo defaults).
The authoritative per-item quantities and rates remain on the **Work Items** smart button
(settlement ledger) and the **Worked Days** tab. `BASIC`, `GROSS`, and the tax lines still show
quantity 1.00 — they are aggregates, not per-unit pay.

One interaction is guarded: Odoo 20 edits payslip lines directly on the payslip, and after an
edit it re-forces the other lines from their stored cent-rounded amount x 2-decimal quantity,
which would corrupt blended per-unit amounts (139.00 at 16.5 units re-derives as 138.93). The
module therefore forces work-item lines as `total x 1` on every edit
([`_recompute_with_forced_lines`](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payslip.py)),
so untouched lines stay equal to their settlements; after an edit the payslip line shows quantity
1.00 again, which is expected — edited slips are outside the claiming pipeline anyway.

**Georgian tax layer SHIPPED 19.0.1.4.0 (2026-07-15):** PIT 20% + funded-pension 2%+2% as the
three rules above (sequences 120/140/160, between GROSS at 100 and NET at 200), on all four
structures. NET = 0.784 × GROSS for a pension member, 0.80 × GROSS for a non-member. The
participation flag `pension_fund_member` (Boolean, `hr.group_hr_user`, tracked) **moved from
`hr_customization` to this module** ([hr_employee.py](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_employee.py));
`hr_customization` now depends on `geo_payroll`, and its salary-offer question keeps filling the
flag (its data record resolves the field by model+name search, not by module). Payroll users can
read the flag inside rule conditions because `hr_payroll.group_hr_payroll_user` implies
`hr.group_hr_user`. **19.0.1.32.0 (2026-09-03):** the same flag exists on `res.partner`
([res_partner.py](../custom_addons/gec_odoo_modules/geo_payroll/models/res_partner.py), Sales & Purchase tab, individuals);
employee and work contact are kept equal by `create`/`write` overrides on both models (context key `gec_pension_sync`
prevents loops, sudo bridges HR and accounting rights; a first work contact takes the employee's value, a relink to another
person takes that person's value, and a partner write spreads to every employee sharing the contact); salary rules
still read `employee.pension_fund_member`. The state pension share is never booked. Rule formulas are linear, so native
refund/correction slips negate the tax lines symmetrically.

**Income-tax exemption categories (19.0.1.24.0, 2026-08-28):** the statutory art. 82 categories
live in `hr.payroll.tax.exemption` (Payroll → Configuration → Salary → Income Tax Exemptions):
8 seeded `noupdate="1"` records (შშმ 6000, სამშვიდობო 6000, მაღალმთიანი 6000, ომის მონაწილე /
მარტოხელა დედა / შვილად ამყვანი / მინდობით აღმზრდელი / „ქართველი დედა" 3000) — HR edits, adds,
deletes and batch-assigns employees via the many2many; no new access group (payroll-user ACL,
manager-gated Configuration menu). While an assigned employee's cumulative calendar-year income
after the employee pension (GROSS − PENSION_EE, plus advance pay-outs net of their pension) is under
the yearly limit (several categories → the max limit wins), PIT is 0; the crossing month taxes only
the excess; afterwards the normal 20%. **Pension first (accountant, 2026-11-11):** the full employee
pension comes off the income-tax base before the allowance, e.g. member, 1,000 wage, 500 allowance
left: (1,000 − 20 − 500) × 20% = 96.00 (until 2026-11-11 the rule subtracted 2% of the taxed part
only, 98.00, and used the allowance up by GROSS); the PIT rules read the withheld `PENSION_EE` line
and the advance's `ADV_PEE_PRE` line. The PIT rules call
`payslip.gec_pit_taxable_gross(categories['GROSS'], pension, advance_pension)`, which returns the base after pension and allowance
([hr_payslip.py](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payslip.py)): earlier
live payslips of the year consume the allowance first (same-date siblings only once validated),
the current slip takes the remainder — bonuses and separate-slip benefits count automatically
because they flow through GROSS. Pension 2%+2% is NOT exempt (stays on full gross). **Advances (19.0.1.28.0–.29.0, accountant rule "sum salary + bonuses + advance, one 3320 line of
20% × the excess"):** the pay-out gross counts toward the limit, and **while the employee still
has allowance left, the whole slip folds into ONE monthly Income Tax line** — taxable = salary
GROSS + advance gross − their employee pension − remaining allowance (slip 66 example, member:
14,370 − 287.40 − 6,000 = 8,082.60 → one Cr 3320 of 1,616.52; before 2026-11-11 it was
(8,370 − 2%-slice) × 20% = 1,640.52). Nothing is prepaid on such a slip (`ADV_PIT_PRE`
= 0, `1730` holds A − 2%A), and the repayment closings self-adapt because `REPAY_PIT`
(`payslip.gec_advance_repay_pit`) mirrors the pay-out's ACTUAL prepaid amount — here zero, so
installments close only `1730`/`1731`/`1732`. Once the allowance is exhausted (or the employee
has no category), advances use the standard full-rate prepaid mechanics (1733/3320 pair, closed
proportionally), so `1733` always ends at exactly zero. Pensions stay full-rate on
everything. Remaining boundaries: refunds and corrections are not counted, the year is the
calendar year of `date_from`, and two advance pay-outs on one slip share the same remaining
allowance (each sees the full remainder — rare, accepted). 7 tests in
[test_tax_exemption.py](../custom_addons/gec_odoo_modules/geo_payroll/tests/test_tax_exemption.py).

### Accounting: debit/credit accounts and tax grids (wired since 19.0.1.4.0)

**Verified 2026-07-15 from source and from two live/test DBs
(`codex_geo_payroll_tests`, `gec_modules_hr`):** none of the 40 rule records across the 4 GEO
structures (Monthly/Hourly/Daily/Unit × BASIC/DAILY_BASIC/TIMESHEET_BASIC/UNIT_BASIC/WORKLOG_OT/
WORKLOG_DAILY/TIMESHEET_EXTRA/UNIT_EXTRA/GROSS/NET) set `account_debit`, `account_credit`,
`debit_tag_ids`, or `credit_tag_ids` in either database — confirmed both from the source data file
([`payroll_structure_data.xml`](../custom_addons/gec_odoo_modules/geo_payroll/data/payroll_structure_data.xml),
which never sets them) and by querying `hr_salary_rule` directly. As of 19.0.1.4.0 the count is 52
records (the 12 new `PENSION_EE`/`PIT`/`PENSION_ER` rules ship equally accountless — company-
dependent accounts cannot go in data XML). Validating one of these payslips today, in any company,
produces no journal entry for the rule's own amount.

**Two different gaps, don't conflate them:**

1. ~~`geo_payroll`'s manifest did not declare the Enterprise `hr_payroll_account` bridge~~ —
   **closed 19.0.1.4.0**: `hr_payroll_account` is now a hard dependency (see
   [`hr_payroll_account.md`](hr_payroll_account.md)), so the accounting fields exist on every
   install, and `codex_geo_payroll_tests` will pull the accounting stack in on its next upgrade.
2. In `gec_modules_hr`, `hr_payroll_account` **is** installed (installed independently of
   `geo_payroll`'s manifest) and `journal_id` is already set to journal `16` ("SLR — Salaries") on
   the GEO Monthly/Hourly/Daily structures for the San Francisco company. The **GEO Unit Salary**
   structure has no journal at all — a payslip on that structure gets the "Account Journal not
   configured on Structure" dashboard warning and silently skips move creation. Rule-level
   `account_debit`/`account_credit` were still never filled in on any of the 40 records, in either
   company — the journal is present but empty of account mappings.

**Do not assume `gec_localization`'s chart of accounts (the `account.account-ge.csv` "ge"
template) is what's loaded.** None of the companies in `gec_modules_hr` use
`chart_template = 'ge'` — they're on stock Odoo `generic_coa` or `us` templates instead, so
Georgian-specific codes like `7410`/`3130` were never created there. Verify per company with
`SELECT chart_template FROM res_company` before naming an account code.

For reference, the pattern every `l10n_*_hr_payroll_account` localization uses (verified against
[`l10n_ae_hr_payroll_account/models/account_chart_template.py`](../enterprise/l10n_ae_hr_payroll_account/models/account_chart_template.py)):
most earning rules set only `account_debit`, the NET rule sets only `account_credit`, and the two
sides cancel out globally across the move. **`geo_payroll` deviated from this between 2026-07-15
and 2026-08-05 (Georgian gross-payable bookkeeping) and returned to the stock layout in
19.0.1.8.0** — the transit pattern broke both payment flows; full analysis in
[payroll_payment_flow.md](payroll_payment_flow.md). Stock
example verified against `gec_modules_hr`'s actual `generic_coa` company:

| Rule code(s) | Category | Account (San Francisco co., `generic_coa`) | Side |
|---|---|---|---|
| `BASIC`, `DAILY_BASIC`, `TIMESHEET_BASIC`, `UNIT_BASIC`, `WORKLOG_OT`, `WORKLOG_DAILY`, `TIMESHEET_EXTRA`, `UNIT_EXTRA` | BASIC / ALW | `630000` Salary Expenses | debit only |
| `GROSS` | GROSS | none — pure subtotal, not booked independently in any stock localization | — |
| `NET` | NET | `230000` Salary Payable, with `employee_move_line=True` so the employee lands as journal-item partner and per-bank-account splitting works | credit only |

The `us`-template company in the same DB uses `611000` "Salaries & Wages" instead of `630000` for
the expense side, with the same `230000` code for the payable side — confirming this is
per-company, not a fixed constant to hardcode once.

**SHIPPED mapping for a company on the frozen `gec_localization` "ge" chart** (stock net-payable
layout since 19.0.1.8.0, 2026-08-05;
[`account.account-ge.csv`](../custom_addons/gec_odoo_modules/gec_localization/data/template/account.account-ge.csv)).
The 2026-07-15 gross-payable transit pattern is **retired**: routing gross through reconcilable
`3130` made the Pay button and the Basis Bank send sweep the transit and pension-interim lines
into junk payments (5 per pension member) and permanently blocked the automatic `paid` state —
mechanics in [payroll_payment_flow.md](payroll_payment_flow.md):

| Rule code(s) | Debit Account **field** | Credit Account **field** | Actual booking |
|---|---|---|---|
| `BASIC`, `DAILY_BASIC`, `TIMESHEET_BASIC`, `UNIT_BASIC`, `WORKLOG_OT`, `WORKLOG_DAILY`, `TIMESHEET_EXTRA`, `UNIT_EXTRA` | `7410` Wages and Salaries | — | Dr `7410` at the earned amount |
| `GROSS` | — | — | nothing (pure subtotal) |
| `PENSION_EE` | `3182` Pension Interim (Employee's Share) | — | negative total flips: Cr `3182` |
| `PIT` | `3320` Income Tax Payable (accountant decision 2026-07-15 — direct to payable, the `3325` interim stays unused by payroll) | — | Cr `3320` |
| `PENSION_ER` | `7490` Other Tax Expense (accountant decision 2026-07-15; the dedicated `7411` Pension Contribution Expense stays unused) | `3181` Pension Interim (Company's Share) | Dr `7490` / Cr `3181` |
| `NET` | — | `3130` Wages Payable (reconcilable; accountant rejected `3160` 2026-08-05) | Cr `3130` at net, employee work contact as partner |

**Consequences of this layout:** the payslip entry records the net as a *debt* on `3130`; the Pay
button clears it against the bank journal chosen **at payment time** — salary rules never name a
bank account. Odoo 20 removed the core payslip Register Payment action; the module rebuilds it
(button **Register Payment** on a validated payslip with a posted entry). The payment scope is "NET
plus partnered authority legs": `action_register_payment` passes every open payable-type line on a
**reconcilable** account that carries a partner (Odoo 20 keeps a residual on every line, so the
reconcile flag now does the filtering the v19 residual did; a
partner-less payable raises, naming the misconfigured rule), so one run yields one NET payment per
employee plus one aggregated Pension Agency payment per interim account (`3181`/`3182`, both rules
ship `partner_pension_agency`) and one aggregated State Treasury payment for PIT (`3320`,
`reconcile=True` since 19.0.1.12.0, rules ship `partner_state_treasury`). The slip flips to `paid`
when its NET lines reach zero residual
([account_payment_register.py](../custom_addons/gec_odoo_modules/geo_payroll/models/account_payment_register.py))
— open withholding legs no longer block the flip. Full mechanics in
[payroll_payment_flow.md](payroll_payment_flow.md). `7120`/`7140`/`7115`
production-wage alternatives exist in the CoA — route cost
splits through analytic distribution, not by forking rules.

Because `account_debit`/`account_credit` are company-dependent, they can't be baked into
`payroll_structure_data.xml` as record fields. Since 19.0.1.4.0 the
`_configure_payroll_account_ge` chart-template hook lives **inside `geo_payroll` itself** (the
user rejected a separate bridge module; cost accepted: `hr_payroll_account` + the Enterprise
accounting stack now install everywhere `geo_payroll` does, including the bare test DB, where
move creation is silently skipped because no structure has a journal there).

Tax-layer rules (SHIPPED 19.0.1.4.0 — 12 new rule records, 3 per structure). Company-dependent
accounts cannot ship as plain XML fields, so 19.0.1.4.0 also **auto-configures them in code**:
`geo_payroll` now depends on `hr_payroll_account` directly (user decision 2026-07-15 — no separate
bridge module) and ships
[`account_chart_template.py`](../custom_addons/gec_odoo_modules/geo_payroll/models/account_chart_template.py)
with `_configure_payroll_account_ge(companies)` (fires automatically when a company loads the
`ge` chart) plus a no-arg wrapper `_gec_configure_ge_payroll_accounts` invoked by a `<function>`
tag at the end of the data file. **Core's configurator runs only for a never-configured company**
(no account on any base rule). **Since 2026-11-11** every mapped rule that has neither a debit nor a
credit account is then filled, in every `ge` company, on install and upgrade
(`_gec_fill_missing_rule_accounts`): a rule shipped later gets
its accounts, an account set by an accountant is never overwritten, and a rule emptied on purpose is
filled again at the next upgrade. For a virgin `ge`-chart company
it writes the SHIPPED table above plus `journal_id` = the per-company SLR "Salaries" journal on
all 4 GEO structures; non-ge companies are always a no-op. `employee_move_line=True` ships on the
4 NET rules in the data file and is load-bearing since 19.0.1.8.0 — it stamps the employee work
contact on the `3130` net line, which the payment wizard batches per employee (and splits per
bank account). Validated against the Tax Code 2026-07-15. **Field-level truth, verified from
[hr_payslip.py:209](../enterprise/hr_payroll_account/models/hr_payslip.py#L209) and the stock UAE
precedent ([account_chart_template.py:107](../enterprise/l10n_ae_hr_payroll_account/models/account_chart_template.py#L107),
[hr_salary_rule_regular_pay_data.xml:462](../enterprise/l10n_ae_hr_payroll/data/hr_salary_rule_regular_pay_data.xml#L462)):
a rule with a negative total and an account in the *Debit Account* field books that amount as a
CREDIT (the engine flips sides on negative totals: `debit = amount if amount > 0 else 0; credit =
-amount if amount < 0 else 0`). Stock l10n therefore puts the liability account of employee-share
deductions in the DEBIT field (UAE `SIEC`: DED, `result = -(gross*0.05)`, mapping sets only
`debit='201021'` the liability), and gives the company-share rule (COMP, positive) both fields.**

| Rule | Category | Formula (sign matters) |
|---|---|---|
| `PENSION_EE` | DED | `-(0.02 × gross)`, participants only |
| `PIT` | DED | `-(0.20 × (gross − employee pension))` — **self-contained since 19.0.1.5.0**: the formula derives the pension exclusion itself (`pension = 2% × GROSS if member else 0`) and never reads `categories['DED']`, so future loan/advance/garnishment deductions cannot shrink the tax base (Codex P1 fix) |
| `PENSION_ER` | **COMP** (stock category, outside `NET = BASIC+ALW+DED`) | `+(0.02 × gross)` |

Their accounts are in the SHIPPED table above: on the negative DED rules the *liability* sits in
the **Debit** field alone (sign-flip books it as a credit; since 19.0.1.8.0 the Credit field stays
empty — no `3130` transit leg) — putting the liability in the Credit field instead books it
backwards and silently dumps
the imbalance into the journal's Adjustment Entry line, no error raised. Grids also follow the
**field**, not the booked side
([hr_payslip.py:162](../enterprise/hr_payroll_account/models/hr_payslip.py#L162): `debit_tag_ids`
apply when the line's account equals `account_debit`). Optionally set the rule's third-party
`partner_id` (Pension Agency on both pension rules, RS on `PIT`) so the liability journal items
carry the creditor as partner.

Balanced example, 1000.00 GEL gross, participant (net-payable layout): Dr `7410` 1000.00;
Cr `3182` 20.00; Cr `3320` 196.00; Dr `7490` 20.00 / Cr `3181` 20.00; Cr `3130` 784.00 (partner =
employee). Debits = credits = 1020.00, zero
adjustment. NET = 0.784 × GROSS for a participant, 0.80 × GROSS for a non-participant. Getting
the order wrong (PIT on full gross) overstates PIT by 0.4% of gross. Tax-law anchors:

- **PIT base excludes the employee's funded-pension contribution**, and the employer's 2% is not
  employee income at all (Tax Code Art. 101(3) — state-mandated pension contributions by employer
  and state are not employment income). The 2%+2%+state split and the state's sliding share
  (2%/1%/0% by income bracket) come from the Law on Funded Pensions (2018), not the Tax Code; the
  state share never touches employer books — no rule, no account.
- **Rules must be conditional on participation** (mandatory for citizens under 40 at the 2018
  start, opt-out was possible for 40+, non-covered foreigners exist) — a per-employee flag, not a
  structure-level constant.
- **Timing accounts:** withholding legally crystallizes at salary *payment* (Tax Code Art. 154 —
  tax agent withholds at source and files/pays by the 15th of the month *following the payment*),
  while the payslip books at accrual. The CoA offers a `3325` Salary Income Tax **Interim** account
  for that gap, but **the accountant decided 2026-07-15 to book PIT directly to `3320` Income Tax
  Payable** (no interim step; `3325` stays unused by payroll). Pension shares still accrue on the
  `3181`/`3182` interims and settle via `3180` on the Pension Agency transfer, which happens in
  step with the monthly income-declaration deadline (exact statutory timing to be confirmed with
  the accountant). `3183` (individual's share) is not needed for standard employee payroll.
- **Agent liability:** if PIT is not withheld, the employer owes the unwithheld amount itself plus
  penalties (Art. 154); late declaration = 5%/10% of tax due, interest 0.05%/day.

**Grids stay empty even after the tax layer exists**, for a declaration-side reason too: the
monthly withholding declaration on rs.ge is per-employee detail (განაცემთა ინფორმაცია) generated
from payroll-register data — it is never computed from GL tax-grid totals, so an `account.report`
with grids is the wrong tool for it; a per-employee export from payslip lines would be the right
shape if it's ever automated.

**Tax grids are further out, and this part of the analysis does hold across both databases.**
`debit_tag_ids`/`credit_tag_ids` stamp `account.account.tag` values used by tax-report grids onto
the journal item — but `gec_l10n_ge_tax`'s only report,
[`account_tax_report_data.xml`](../addons/l10n_ge/data/account_tax_report_data.xml),
is VAT-only (confirmed by grep: no `salary`/`wage`/`pension`/`payroll` tags exist anywhere in
`gec_l10n_ge_tax`). The PIT/pension **rules** now exist (19.0.1.4.0), but a Georgian salary-tax
report (equivalent to DGV but for PIT/pension declarations) still does not — grids would need
their own `account.report` + tags before `debit_tag_ids`/`credit_tag_ids` had anywhere to point,
and the rs.ge declaration is per-employee detail anyway (see above). The frozen `gec_localization`
CoA already has the accounts the rules book to on a `ge`-chart company — `3320` Income Tax
Payable for PIT withheld (accountant's choice; the `3325` interim exists but is unused),
`3180`/`3181`/`3182`/`3183` for the pension split.

---

## 11. Settlement ledger: why “Work Items” exists

Every claimed Work Log or Timesheet creates an immutable
`hr.payroll.component.settlement` record. It is the audit link between the source record and the
payslip.

It records:

- source Work Log or Timesheet;
- employee, company, and work date;
- component code;
- contract version that priced it;
- quantity, rate, currency, and amount;
- destination payslip;
- whether the claim is active;
- release reason and time when released.

One source can have only one active claim. Database locks and a partial unique index protect this
rule during concurrent calculations. Settlement rows are read-only in the UI.

---

### Public holidays after a company country change

Odoo types each company holiday with the public-holiday Time Type of the company's country when the holiday is created,
and never retypes it. A company switched from the United States to Georgia keeps a year of US holidays typed with the US
type, which the global country restriction on `hr.work.entry.type`
([ir.access.csv:4](../addons/hr_work_entry/security/ir.access.csv#L4)) hides from Georgian users, so computing a payslip
raises an AccessError. geo_payroll deletes company holidays whose Time Type belongs to another country than their company
([resource_calendar_leaves.py](../custom_addons/gec_odoo_modules/geo_payroll/models/resource_calendar_leaves.py)) on
install or, on an existing database, at the first upgrade (once per database, flag
`geo_payroll.foreign_public_holidays_removed`), and right after a company's country changes, on the company form or on its
contact ([res_partner.py](../custom_addons/gec_odoo_modules/geo_payroll/models/res_partner.py)). Later upgrades delete
nothing. Odoo 20 ships no Georgian holiday dates, so the Georgian holidays are entered by hand.

## 12. Changing Pay Scheme, sources, projects, or cutoff

### Safest rule

Create a **new dated contract version** from the effective change date. Do not rewrite historical
routing in place.

New versions inherit payroll source/configuration values. Unsupported combinations are normalized:
Timesheets as Hourly Source is allowed only on the pure Hourly scheme, and Daily Source is always
Approved Work Logs.

### Changes the module blocks

An in-place routing change is blocked when the version already has:

- a validated or paid payslip; or
- an active carried-forward settlement priced by that version whose destination payslip is
  validated or paid.

This prevents already-paid Work Entry periods from later becoming Timesheet-payable, and prevents
paid Timesheet periods from silently losing their route.

For an Hourly-from-Timesheets version, the module also blocks:

- leaving Timesheets mode while validated payable lines are unclaimed;
- leaving Timesheets mode while such lines are claimed by a draft payslip, because recompute would
  release and strand them;
- removing allowed projects when validated payable lines on those projects would be stranded;
- moving Timesheet Pay From forward when earlier validated payable lines would be stranded.

Resolve those lines by one of these methods:

1. Keep the old slice and create a new dated version for the future change.
2. Pay the valid lines.
3. If they must never pay, release any draft claim, then select the lines in the timesheet list and
   run **Actions → Waive Payroll Pay** (see [section 9](#9-waive-timesheet-pay)).

Unvalidated draft timesheets do not block a routing change. After a change they follow the route
active when they are eventually validated/claimed.

Additive routes (Fixed + Hourly and Daily + Hourly) are intentionally outside this strand guard.
Changing those schemes can release draft claims and leave validated extras unclaimed. Review these
lines manually before changing an additive scheme.

### Wage edits

Wage changes are not routing changes:

- an approved Work Log keeps its approval-time frozen rate;
- an unclaimed Timesheet uses the current Hourly Wage of its work-date version;
- a Timesheet claimed by a recomputed draft can release and reprice;
- a validated/paid settlement keeps its frozen amount.

---

## 13. Pay runs and mid-period contract versions

Odoo 20 pays every version of one **contract** (versions with the same contract start and end
dates) on **one** full-period payslip. Each worked-day line carries its own version and is priced
by that version's wage. The module follows this model.

Example: Monthly Wage changes from 1,600 to 2,000 on January 16 (a new version, same contract).

- January gets **one** payslip. Its worked days hold 88 hours on the old version and 88 hours on
  the new one, so it pays 800 + 1,000 = 1,800.
- Work Logs and Timesheets of both versions are claimed by that one payslip. Each keeps the price
  of its own work date (a log's approval-time rate, a timesheet's work-date version rate).

Important rules:

- One regular payslip per contract and period. A second regular payslip for any version of the
  same contract is blocked at validation, because it would pay the later days twice.
- A change of **salary structure type** (for example Fixed to Daily) or of **timesheet-based hourly
  pay** in the middle of a period needs a **new contract** starting on the change date. Validation
  blocks a payslip whose contract versions differ on these. A new version that starts on the first
  day of a pay period is fine.
- A new contract gets its own payslip: the earlier contract's payslip claims work up to its end
  date, the new contract's payslip claims work from its start date.
- Do not shorten a fixed-wage payslip to the version dates. The module blocks this because a
  shortened slip pays the full monthly wage for a partial period.
- Older carried-forward Work Logs/Timesheets are claimed by the payslip of the contract that covers
  their date, and retain their source-date component/rate.
- Changing the later version (for example its wage to 2,400) refreshes the shared draft payslip,
  although the payslip's main version is the earlier one: January then pays 800 + 1,200 = 2,000.
  The payslip keeps its own version's default structure and a hand-set end date. Before 2026-10-31
  only payslips whose main version changed were refreshed
  ([hr_version.py:453](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_version.py#L453)).
- **Add Payslip to Pay Run**, the action on the warning "The pay run ... is missing this employee",
  adds the employee's payslip to the open run (Odoo offers only runs of the employee's own structure
  type or without a structure, so never an overtime run). Before 2026-10-31 it raised a
  `TypeError` ([hr_payslip_run.py:36](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payslip_run.py#L36)).

Resetting a pay run refreshes only safe regular draft/base slips. Deleting a pay run releases its
children's active claims first, unless correction lineage blocks deletion.

---

## 14. Recompute, cancel, delete, refund, and correction

| Operation | Result for custom Work Items |
|---|---|
| Recompute an eligible draft | Keep valid claims, release stale claims, claim new eligible items |
| Cancel a payslip | Release its active claims when lifecycle rules allow cancellation |
| Reset a cancelled regular base slip to Draft | Align default structure and recompute |
| Delete a draft/cancelled payslip | Release active claims before deletion |
| Delete a pay run | Release child claims before deletion, if no correction lineage blocks it |
| Refund | Copy and negate the original salary lines using standard Odoo behavior |
| Correction | Read custom component totals from the root original payslip |

### Correction-chain rules

**Guard removals round 2 (2026-08-19, user decision — "less restrictions"):** six more geo_payroll
guards deleted: work-log self-approval block, future-date approval block, both required
'Timesheet Pay From' cutoffs (payslips now sweep historical validated timesheets — carry-forward
applies), required timesheet-project allowlist for pure timesheet mode (empty = ALL projects pay,
now consistent with additive schemes), the structure-alignment check
(`_gec_check_version_structure_alignment`), and the missing-version-slice raise in
`_gec_check_version_coverage` (a slice without a payslip validates fine and stays unpaid; the
**duplicate-slice and overlap raises remain** — those are double-pay protection). Matching tests
removed/rewritten in test_hr_version / test_work_log / test_version_split.

**Upstream separator crash guard (2026-08-19):** enterprise `_get_localdict` does `int(key)` on every
stored payroll-properties key ([hr_payslip.py:2133](../enterprise/hr_payroll/models/hr_payslip.py#L2133));
Salary-Input rules with a Section store a `separator_N` key on the contract/payslip, so any Compute
Sheet after saving such inputs crashed with `ValueError: invalid literal for int()`. geo_payroll now
strips separator entries at write time (`gec_strip_property_separators` in hr_version.py, hooked into
version create/write and payslip create/write) — sections still display (they live in the structure
definition), they just never reach stored values. Existing poisoned rows in hr3 were SQL-cleaned.

Correction history is dismantled leaf-first:

- **REMOVED 2026-08-19 (user decision):** the live-descendants ordering guard
  (`_gec_check_no_live_descendants` + the run-reset twin) AND the payslip-level delete guard are
  gone — an origin payslip CAN now be cancelled, reset, or deleted while corrections referencing
  it exist. `origin_payslip_id` is `set null`, so deleting an origin orphans its corrections'
  lineage (their frozen lines survive; component totals read from the origin become 0 on any
  recompute). The pay-run delete guard is gone too (same date) — the ONLY remaining chain
  protection is the correction-balance check on cancel/run-reset.
- A validated positive correction must have one validated refund that exactly reverses the origin's
  salary lines. One refund cannot authorize two positive corrections.
- A refund may exist without a correction, but its cancellation cannot leave a validated positive
  correction without its balancing refund.

These rules keep the root settlements available while refunds/corrections still depend on them.

---

## 15. Quick troubleshooting

| Symptom | What to check |
|---|---|
| “Pay Daily Work Logs” is false on Daily | Correct: Daily logs are the base. The flag represents only the Fixed + Daily addition |
| “Pay Timesheet Hours” is false on Hourly + Timesheets | Correct: Timesheets are the base. The flag represents only combined-scheme additions |
| Overtime cannot be approved | Checkbox, positive Hourly Wage, contract date, Work Log Type = Overtime, and not Hourly-from-Attendance/Timesheets |
| Daily Work cannot be approved | Scheme must be Daily, Daily + Hourly, Daily + Per Unit, or Fixed + Daily; set positive Daily Wage |
| Unit Work cannot be approved | Scheme must be Per Unit or Daily + Per Unit; the rate item must be active and in the employee company's currency |
| Unit log paid the old price | Correct: approval froze the price; catalog edits affect only future approvals |
| Ledger shows a different unit than the catalog | Correct: the UoM was frozen at approval; the catalog UoM changed later |
| Timesheet did not pay | Validation, employee/company, allowed project (since 19.0.1.5.0 an **empty** list on additive schemes = **all projects pay**; pure Hourly-from-Timesheets still requires an explicit list), cutoff, contract date, positive rate/hours, 24h cap, waiver, existing claim |
| Hourly-from-Timesheets payslip is zero | Correct if no eligible line exists; otherwise check the default structure/rule, edits, and Work Items |
| Fixed employee received full wage despite missing hours | Missing hours may be absent rather than recorded as unpaid work entries; check Work Entry Source and denominator behavior |
| Compute says more than 24 hours | Correct/invalidate excess timesheets for the employee/date |
| Old item appeared on a later payslip | Carry-forward is intentional and uses the source-date version/rate |
| Cannot change Hourly Source | Finalized history exists, or validated lines would be stranded; create a dated version, pay, or waive |
| Cannot waive a line | It is claimed, unvalidated, already waived, or not payroll-payable under its work-date version (wrong project/cutoff/rate/mode) |
| Waive/Restore not in Actions menu | Not a Payroll Manager, or you are in grid view — switch to the timesheet List |
| Cannot reset/cancel a Work Log | A payslip actively claims it; release/recompute that payslip first |
| Approved Work Log / Timesheet not on the payslip after Compute | The payslip is marked edited (chatter: "manually edited by …"); edited slips never claim. Cancel → Set to Draft keeps the mark (Odoo 20 never clears `edited`), so cancel it and create a new payslip for the period |
| Cannot validate a payslip | Resolve stale claims, salary-line mismatch, source-zeroing errors, a second payslip on the same contract, or mixed pay routes inside one contract |
| “… already has a regular payslip for the same contract …” | Odoo 20 pays all versions of a contract on one payslip; cancel the duplicate |
| “… covers contract versions with different salary structure types …” | Start a new contract on the change date instead of a new version |
| “Does not cover its full pay schedule period” | A fixed-wage slip was shortened; use one full-period payslip per contract |
| Payslip/pay-run cancel-reset-delete blocked by corrections | No longer happens — all lineage guards removed 2026-08-19; only the correction-balance check remains |

---

## 16. Known limits before production

The current module still has boundaries that payroll/UAT must account for:

- PIT 20% + funded-pension 2%+2% and the journal mapping are implemented since 19.0.1.4.0/1.5.0,
  but with accepted limits: the `pension_fund_member` flag is **not effective-dated** (recomputing
  an old slip after a membership change reprices history with today's status — decided-accepted
  2026-07-15), pension members' slips emit extra junk payments and never auto-flip to `paid`
  until the accountant unchecks reconcile on `3181`/`3182` (pending 2026-08-05), and the Employer
  Cost dashboard number is under review with the
  accountant (it sums NET + employer pension instead of gross + employer pension). No salary
  declaration export exists.
- Ordinary client-project timesheets can overlap paid/unpaid leave.
- Daily Work, Unit Work, Timesheets, custom Overtime, and native attendance/planning overtime are
  not fully cross-reconciled, except the explicit Hourly-from-Attendance and
  Hourly-from-Timesheets blocks. On Daily + Per Unit, same-day daily and unit pay is by design.
- The Unit Work Rate catalog is global with one price per work type; multi-currency groups are
  protected only by the approval-time currency-match refusal, and per-employee or per-project
  rates do not exist.
- Unit quantities have no upper bound; the approver is the only volume control.
- A privileged direct `validated=True` timesheet write can bypass normal timer/future-date checks;
  payroll does not re-run every Timesheets application validation.
- A claim may remain after changing a draft payslip to another structure that contains the same
  component rule; avoid structure changes on claimed drafts and recompute/review Work Items.
- Work Log currency is frozen, but its company follows the employee. A later company transfer can
  leave an old-currency approved log unpaid.
- Restoring a waiver is a one-click **Actions → Restore Payroll Pay** item but records no separate restore reason.
- Additive timesheet routes do not use the Hourly-base strand guard by policy.
- Automated tests exist, but a real two-worker concurrency race and browser/timer end-to-end harness
  are still missing.
- Managers can create and approve a direct report's payable Work Log; stricter separation of duties
  may be required.

Do not market or deploy this as complete Georgian payroll until these items are accepted, fixed where
required, and tested with real payroll data.

---

## Code reference

- [`hr_version.py`](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_version.py) — schemes,
  fields, constraints, inheritance, and routing guards
- [`hr_version_views.xml`](../custom_addons/gec_odoo_modules/geo_payroll/views/hr_version_views.xml) —
  field visibility/read-only rules
- [`hr_employee_work_log.py`](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_employee_work_log.py) —
  Work Log workflow and frozen pricing
- [`hr_payroll_unit_rate.py`](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payroll_unit_rate.py) —
  global Unit Work Rate catalog
- [`gec_payroll_timesheet_waiver.py`](../custom_addons/gec_odoo_modules/geo_payroll/models/gec_payroll_timesheet_waiver.py) —
  waiver wizard
- [`account_analytic_line.py`](../custom_addons/gec_odoo_modules/geo_payroll/models/account_analytic_line.py) —
  timesheet claim/waiver protection and restore method
- [`hr_payslip.py`](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payslip.py) — claiming,
  carry-forward, calculations, and confirmation guards
- [`hr_payslip_run.py`](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payslip_run.py) — pay-run
  version slicing
- [`hr_payroll_component_settlement.py`](../custom_addons/gec_odoo_modules/geo_payroll/models/hr_payroll_component_settlement.py) — immutable Work Item ledger
- [`payroll_structure_data.xml`](../custom_addons/gec_odoo_modules/geo_payroll/data/payroll_structure_data.xml) — GEO salary structures and rules

Design history and technical decisions: [geo_payroll_implementation_plan.md](../dev_notes/plans/geo_payroll_implementation_plan.md).
