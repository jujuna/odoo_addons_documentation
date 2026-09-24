# Playbook: Employees, Time Off, Attendance, Payroll, Timesheets

Use this as a research starting point, not a ready-made recommendation. Historical
verification notes below do not certify the current checkout or client database. Re-check
material rules, defaults, calculations and labels before using them. Follow SKILL.md and
the implementation protocol for discovery and decisions.


Decisions to settle with the client, with what Odoo really does for each option. Verified
against Odoo 20 source (2026-09-22). Deeper detail is in `documentations/hr_holidays.md`,
`hr_holidays_accrual_plans.md`, `hr_holidays_time_off_units.md`, `work_entries.md` and
`hr_payroll.md`, which are verified for Odoo 20.

## Odoo 20 changes that mislead anyone who knows older versions

- **Time off types are now "Time Types"** (menu **Time Off > Configuration > Time Types**).
  The same records also define work entry types for payroll.
- **Approval labels changed**: **None** / **By HR Responsible** / **By Time Off Approver** /
  **By HR Responsible and Time Off Approver**. The default is **By HR Responsible**.
- **There is no "Regular vs Accrual" field on allocations anymore.** An allocation is an
  accrual simply because an **Accrual Plan** is set on it.
- **New time types default to Unit = Hours**, not days. Check this on every new type.
- **Work entries are no longer stored records**: no validation step and no "Report to Next
  Month" button. Planning no longer feeds payroll.
- **No Georgian public holiday file** ships with Odoo 20 (20 countries only). Georgian
  holidays must be entered by hand.

## How Odoo thinks

| Idea | In plain words |
|---|---|
| **Time Type** | A kind of absence (annual, sick, unpaid). Holds all the rules: approval, unit, allocation, negative balance |
| **Allocation** | A balance given to an employee for one Time Type ("21 days of annual leave for 2026") |
| **Accrual Plan** | Rules that make an allocation grow over time instead of granting everything at once |
| **Time Off request** | An employee's request. States: **To Approve**, **Second Approval**, **Approved**, **Refused**, **Cancelled** |
| **Working schedule** | Decides which days and hours count as work, and so how many days a leave costs |

## Time Off decisions

**1. Does this type need a balance?** Time Type, **Requires Allocation**.
- On: requests are refused without a valid allocation. Use for quota leave (annual).
- Off: unlimited requests, no balance tracking. Use for sick leave, unpaid leave.
- **Locked** once any leave of that type exists. The fix is to create a new type.
  (`addons/hr_holidays/models/hr_work_entry_type.py`, `check_allocation_requirement_edit_validity`)

**2. Grant once, or earn over time?** On the allocation: no **Accrual Plan**, or choose one
(**Time Off > Configuration > Accrual Plans**).
- Fixed: all days available at once, valid until the **End Date**.
- Accrual: starts at 0, and days are added by a **daily** scheduled job. Example: 1.75
  days/month for 12 months = 21 days. Days appear the day after the accrual date.
- Plan changes apply from the next accrual. Days already earned are not recalculated.

**3. Earn at the start or the end of the period?** Accrual plan, **When the time is
accrued?**: **At the start of the accrual period** / **At the end of the accrual period**
(default: end).
- Example: 2 days/month, employee starts 15 January. At the start: about 1.10 days (2 x
  17/31) available on 15 January. At the end: the same 1.10 days arrive on 1 February.
- **It is based on worked time?** (only with "end"): unpaid absences reduce what is earned.

**4. What happens to unused days?** Accrual plan, **What should happen to the unused
accrued time?** (lost or carried over), and **When should unused accrued time be
reset/carried over?** (**At the start of the year** / **At the allocation date** / **Custom
date**). Per milestone: **Lost (Reset)** / **Carried over**, **How much time can be carried
over** (**Unlimited** / **Up to**), and **Define a carry over validity?**.
- Example: 8 days unused on 1 January, carry over "Up to 5", valid 3 months. 5 days move
  over and 3 are lost; the 5 carried days expire on 1 April if unused.
- Applies only to accrual allocations. Fixed allocations just expire at their End Date.

**5. Can the balance go negative?** Time Type, **Allow Negative** + **Maximum Excess
Amount**.
- Example: 10 days allocated, excess 3. Up to 13 days can be requested, and the 14th is
  refused. The employee still needs some allocation.

**6. Who approves?** Time Type, **Approval** (for requests) and a separate one for
allocation requests (visible with **Allow Employee Requests**).
- **None**: auto-approved. **By HR Responsible and Time Off Approver**: two steps. The
  first approval puts the request in **Second Approval**.
- Trap: the HR Responsible defaults to the user who created the employee. Set it
  deliberately.
- Also: requests created by a Time Off Officer are auto-approved.

**7. Unit and smallest request.** Time Type, **Unit** (**Hours** / **Days**) and **Duration
Type** (**Full Day** / **Half-Day** / **Custom Hours**). These are two separate settings.
- Example: Unit Days + Half-Day lets someone take 0.5 day. Custom Hours allows a 2-hour
  doctor visit.

**8. Working days or calendar days?** Time Type, **Count Days as**: **Working Days** /
**Calendar Days**.
- Example: a one-week leave for a Mon-Thu employee costs 4 days (working) or 7 (calendar).
- **Locked** once leaves of that type exist.

**9. Public holidays and blocked days.** **Time Off > Configuration > Company Holidays** and
**Mandatory Days**. Time Type checkbox **Ignore Public Holidays**.
- Misleading label: checking **Ignore Public Holidays** *counts* holidays as leave days
  (its tooltip: "Public holidays should be counted in the leave duration").
- A holiday added after approval gives the day back automatically and notifies the
  employee.
- On a Mandatory Day, employees can't request leave. Officers still can.

**10. Overtime and undertime.** **Time Off > Configuration > Automatic Rules**: turn extra
hours into paid time, or into a time-off balance (**Allocate %**, **Allocate to**).
- Example: 3 hours over the schedule at 150% into Compensatory = 4.5 hours of
  compensatory balance.

## Attendance and payroll decisions

**11. Pay from the schedule or from check-ins?** Employee **Attendance Based**. The company
default is **Default Tracking** in Employees settings, with Payroll Attendance installed.
- Off: paid hours = schedule minus leaves (salaried office staff).
- On: paid hours = validated check-ins plus time off (hourly, shift, factory).
- Timesheets never feed payroll.

**12. Approve attendances?** Attendances settings, **Attendance Validation**: automatic /
manual / only outside **Validation Tolerance (Hours)**. Only validated attendances count
for payroll.

**13. Leave approved after the payslip is done.** The leave shows a **Payslip State**, and
**Correct related payslips** creates a correction. Set a **Responsible** under
**Deferred Time Off** in Payroll settings. A leave already paid in a validated payslip
can't be deleted.

## Timesheets and billing

**14. How are hours billed?** Service product **Invoicing Policy**: Prepaid/Fixed Price /
Based on Timesheets / Based on Milestones / Based on Delivery (Manual). Timesheets setting
**Invoice**: "All recorded timesheets" / "Validated timesheets only".
- Example: 10 hours at 100/hour on "Based on Timesheets" = 1,000 to invoice. On Fixed
  Price, the hours are only a cost for margin reporting.

## Questions to ask the client

1. Which leave types exist, and which have a yearly quota?
2. Is annual leave given on 1 January, or earned monthly? What about new hires?
3. Carry-over: allowed? How much? Until when?
4. Who approves: manager, HR, or both? Different per type?
5. Days or hours? Half-days allowed?
6. Are working days or calendar days counted (check Georgian labour law per type)?
7. Salaried on schedule, or paid by attendance?
