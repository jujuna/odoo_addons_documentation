# GEO Payroll (`geo_payroll`)

Georgian payroll on top of Odoo 20 Payroll: eight ways to pay an employee, work logs for
overtime, days and piecework, timesheet pay, Georgian income tax and pension, benefits and
salary advances, and payslips that post and pay on the Georgian chart of accounts.

**Who this is for:** payroll managers, managers who approve work, and accountants who post and
pay salaries. Developers: [README_DEV.md](README_DEV.md).

---

## 1. What it does

| Feature | What you get |
|---|---|
| **Pay schemes** | Eight schemes on the employee's contract: Fixed, Hourly, Daily, Per Unit, Fixed + Daily, Fixed + Hourly, Daily + Hourly, Daily + Per Unit |
| **Work logs** | Employees record overtime, worked days or piecework; a manager approves; the next payslip pays them. Approved overtime is also written to the employee's timesheets |
| **Timesheet pay** | Project timesheets can be the hourly base pay or an addition to it; they do not need to be validated |
| **Unit work rates** | A price list for piecework; the price is fixed on each log when it is approved |
| **Georgian taxes** | Income tax 20%, pension 2% + 2% for pension fund members, yearly income-tax exemptions (Tax Code art. 82) |
| **Benefits and advances** | Bonuses, deductions, vendor benefits and salary advances reach the payslip by themselves, with the salary or on a separate payslip |
| **Separate overtime** | Overtime can be paid on its own payslip instead of with the salary |
| **Accounting and payment** | One journal entry per payslip; one button pays the employee, the Pension Agency, the State Treasury and benefit vendors |
| **Safety checks** | The same work is never paid twice, payslips of one contract never overlap, and every paid item stays on a read-only record |

## 2. Quick facts

| | |
|---|---|
| Menus | **Payroll > Work Logs** · **Payroll > Unit Work Rates** (Payroll Administrators) · **Payroll > Benefits & Deductions** · **Payroll > Benefits Pay Run** · **Payroll > Configuration > Salary > Income Tax Exemptions** · **Employees > Work Log Approvals** |
| Added to existing screens | **Work Logs** tab on My Profile and on the employee · Pay Scheme and related fields on the employee's Payroll tab · **Work Items** card and button and **Register Payment** button on the payslip · **Pension Fund Member** on the employee and on the contact · **Work Log** column and **Actions > Waive Payroll Pay** and **Restore Payroll Pay** in the timesheet list |
| Who uses it | Employees (their own work logs), direct managers (approval), Payroll Officers and Administrators (everything else). No new user groups |
| Salary structures | GEO Monthly Salary, GEO Hourly Salary, GEO Daily Salary, GEO Unit Salary; off-cycle: GEO Benefits Pay, GEO Overtime Pay |
| Needs | Payroll and Payroll Accounting (Enterprise), Project and Timesheets, and `gec_localization` (Georgian chart of accounts) |
| Works with | `gec_payroll_bank` (**Pay Salaries** through bank channels), `basis_bank` (sends those payments), `gec_income_tax_report` (rs.ge Form 30 from paid payslips) |

## 3. How it works

```text
Inputs: contract (pay scheme, wages) · working schedule · approved work logs
        · timesheets · benefits and advances
   │
   ▼
Compute payslip ──► Work Items: what this payslip pays, frozen
   │
   ▼
Salary lines: gross, pension, income tax, net
   │
   ▼
Journal entry
   │
   ▼
Register Payment / Pay Salaries
   └──► employee, Pension Agency, State Treasury, vendors
```

The contract's pay scheme decides where base pay comes from. Computing a payslip picks up
every approved work log and timesheet that no payslip has paid yet and lists them under
**Work Items**. Validation refuses a payslip whose lines disagree with its Work Items, so
work is never paid twice and never silently dropped.

## 4. Set it up (once)

1. **Accounts.** Nothing to do on a company with the Georgian chart: the module sets the salary
   accounts and the Salaries journal on install and on every upgrade, and never overwrites
   accounts you changed. On another chart, set the accounts on the salary rules by hand.
   Keep **Batch Payroll Move Lines** off (**Payroll > Configuration > Settings**): each payslip
   needs its own journal entry.
2. **Each employee, Payroll tab:**
   - **Pay Scheme** with the matching **Salary Structure Type** (section 5).
   - The wage the scheme uses: monthly wage, hourly wage or **Daily Wage**.
   - **Pension Fund Member** when the employee pays into the pension fund. The same checkbox is
     on the contact (Sales & Purchase tab, individuals only); the two stay equal.
   - Overtime: **Pay Overtime Work Logs**, and **Overtime Payment**: *With Salary* or
     *Separate Payslip* (section 10).
   - Timesheet schemes: **Payroll Timesheet Projects** (empty means every project of the
     company) and **Timesheet Pay From**, an optional start date so the first payslip does not
     pay old history.
3. **Piecework:** enter the prices in **Payroll > Unit Work Rates** (section 6).
4. **Tax exemptions:** add employees to their category in **Income Tax Exemptions** (section 8.3).
5. **Benefits** (optional): **Payroll > Benefits & Deductions** (section 9).

## 5. Pay schemes

| Pay Scheme | Base pay comes from | Can add | Structure type |
|---|---|---|---|
| Fixed | Monthly wage, prorated by the paid hours of the schedule | Overtime | GEO Monthly Pay |
| Hourly, source *Work Entries* | Paid schedule hours × hourly wage | Overtime | GEO Hourly Pay |
| Hourly, source *Timesheets* | Timesheet hours × hourly wage; the schedule pays nothing | Nothing | GEO Hourly Pay |
| Daily | Approved daily logs × daily wage; the schedule pays nothing | Overtime | GEO Daily Pay |
| Per Unit | Approved unit logs × catalog price; the schedule pays nothing | Overtime | GEO Unit Pay |
| Fixed + Daily | Monthly wage | Daily logs, overtime | GEO Monthly Pay |
| Fixed + Hourly | Monthly wage | Timesheet hours, overtime | GEO Monthly Pay |
| Daily + Hourly | Daily logs | Timesheet hours, overtime | GEO Daily Pay |
| Daily + Per Unit | Daily logs | Unit logs, overtime | GEO Daily Pay |

"Overtime" means approved overtime logs; they are paid only when **Pay Overtime Work Logs** is
on. **Pay Daily Work Logs** and **Pay Timesheet Hours** follow from the scheme and cannot be
set by hand.

Examples with monthly wage 1,600, hourly wage 10, daily wage 80, a 160-hour month:

| Scheme | The month | Gross |
|---|---|---:|
| Fixed | full attendance | 1,600.00 |
| Fixed | 16 hours of unpaid leave | 1,440.00 |
| Hourly from work entries | 152 paid hours | 1,520.00 |
| Hourly from timesheets | 12 timesheet hours on an allowed project | 120.00 |
| Daily | 20 approved full days | 1,600.00 |
| Daily | one half-day log | 40.00 |
| Per Unit | 12.5 m² tiling at 10 + 4 sockets at 3.50 | 139.00 |
| Fixed + Daily | full month + 1 daily log | 1,680.00 |
| Fixed + Hourly | full month + 12 timesheet hours | 1,720.00 |
| Daily + Hourly | 20 daily logs + 10 timesheet hours | 1,700.00 |
| Daily + Per Unit | 1.5 days + 8 m² at 10 + 20 sockets at 3.50 | 270.00 |
| Any scheme | 3 extra hours of overtime at 150% | + 45.00 |

An Hourly-from-Timesheets month without eligible timesheets is a correct zero payslip.
Switching an employee to Hourly from Timesheets shows how many unpaid timesheet lines the
next payslips will pay.

## 6. Work logs

Employees record extra work as work logs, a manager approves them, and the next payslip pays them.

| Type | You enter | Amount | Paid when |
|---|---|---|---|
| Overtime | date, hours, **Rate %** (100, 125, 150 or 200) | hours × hourly wage × rate | **Pay Overtime Work Logs** is on |
| Daily Work | date, days (0 to 1) | days × daily wage | the scheme uses daily logs |
| Unit Work | date, unit rate, quantity | quantity × unit price | the scheme uses unit logs |

One active daily log per employee and date; overtime on one date may not exceed 24 hours in total.

**Where:** employees use the **Work Logs** tab on My Profile (or their employee card); managers
use **Employees > Work Log Approvals**, which opens on *To Approve* for their direct reports;
payroll uses **Payroll > Work Logs**.

```text
Draft ──Submit──► Submitted ──Approve──► Approved ──► paid by the next payslip
                      │
                      └──Reject──► Rejected ──Submit──► Submitted
```

A manager can also approve a Draft directly. Payroll can reset an approved log to Draft, or
cancel it, while no payslip holds it.

| Action | Employee | Direct manager | Payroll Officer |
|---|---|---|---|
| Create, edit and submit in Draft or Rejected | own logs | reports' logs | anyone's |
| Approve or reject | no | reports' logs | anyone's, including their own |
| Reset or cancel an approved log | no | no | yes, unless a payslip holds it |
| Delete | only Draft, Rejected or Cancelled logs that were never on a payslip | | |

Payroll Assistants (the lowest payroll group) can only read the logs they neither own nor manage.

**Approval fixes the price.** The rate and amount are stored on the log; a later change of
wage, scheme or unit price never reprices an approved log. Approval refuses a log when the
employee has no contract on that date, the scheme has no route for that type (a daily log
needs a daily scheme or Fixed + Daily), the wage or price is zero, or the employee is paid
hourly from attendance (badge hours are already the record) or, for overtime, from timesheets.

The **Work Item status** on a log shows where it stands: *Not in Payslip*, *In Draft Payslip*
or *Paid* (on a validated payslip; not necessarily paid by the bank yet).

**Approved overtime is also a timesheet.** Approving an overtime log writes its hours as a
timesheet line on the log's project, or on the company's **Internal** project when the log
names none, described "Overtime: " plus the log's reason. Project timesheet reports then
include the overtime hours. The line is read-only, shows the log in its **Work Log** column,
disappears when payroll resets or cancels the log, and comes back on re-approval. Payroll
never pays it as timesheet hours: the overtime log pays (section 7). An overtime log can
only name a project that has timesheets enabled. If a Timesheets approver has validated the
line, resetting or cancelling the log needs the Timesheets approver right too, or the line
must first be reset to draft in the Timesheets app.

**Unit Work Rates** (Payroll Administrators) is the piecework price list: name, unit, price per
unit, company. Leave the company empty to share a rate with every company. Everyone can read
it, and an employee filing a unit log sees the price and amount as they type. The unit is a
label only; nothing is converted. Archive a rate to retire it; a rate used by an approved log
cannot be deleted.

## 7. Timesheets in payroll

A timesheet line is paid when all of these hold:

- it is not waived and no other payslip pays it; whether it is validated does not matter;
- it belongs to the contract's company (hours on another company's project are that company's cost);
- its date is inside a contract, on or after **Timesheet Pay From**, and not after the payslip end;
- it is on one of the **Payroll Timesheet Projects**, or the list is empty;
- it has more than 0 and at most 24 hours, and the contract on that date pays timesheets with an
  hourly wage above zero;
- it is not a leave, public-holiday or overtime line (section 6).

Amount = hours × the hourly wage of the contract in force on the work date.

Two things surprise people:

| | Work log | Timesheet |
|---|---|---|
| Price fixed when | the manager approves it | the payslip is validated |
| A wage, project or scheme change while the payslip is a draft | changes nothing | re-prices it |

And: payable hours on one date may not exceed 24, counting hours already paid. Computing the
payslip stops with an error until the extra lines are fixed or deleted.

**Waiving:** when hours must never be paid by payroll (a wrong Hourly-from-Timesheets setup,
for example), a Payroll Administrator selects them in the timesheet list and runs
**Actions > Waive Payroll Pay** with a reason; **Actions > Restore Payroll Pay** undoes it.
Late lines need no waiver: the next regular payslip pays them.

## 8. Georgian taxes

### 8.1 The tax lines

| Line on the payslip | Amount | Applies to |
|---|---|---|
| **Pension Employee Contribution** | -2% of gross | pension fund members |
| **Income Tax** | -20% of (gross - employee pension) | everyone; less during an exemption (8.3) |
| **Pension Company Contribution** | 2% of gross, paid by the company, not part of net | pension fund members |
| **Net Salary** | gross - pension - income tax - deductions | everyone |

A vendor benefit's company share (section 9) counts in gross for income tax but not for pension.

**Pension Fund Member** is not dated: changing it changes every payslip computed afterwards,
including recomputed drafts of earlier months. Set it before the first payslip.

### 8.2 Examples

| Wage 1,000, full month | Non-member | Member |
|---|---:|---:|
| Basic Salary | 1,000.00 | 1,000.00 |
| Pension Employee Contribution | | -20.00 |
| Income Tax | -200.00 | -196.00 |
| **Net Salary** | **800.00** | **784.00** |
| Pension Company Contribution (company cost) | | 20.00 |

A member's net is 78.4% of gross and costs the company 102%; a non-member's net is 80%.
Daily scheme, member, one approved day at 80: pension -1.60, income tax -15.68, net 62.72.

### 8.3 Income-tax exemptions (art. 82)

**Payroll > Configuration > Salary > Income Tax Exemptions** holds eight categories with a
yearly limit: 6,000 GEL (persons with disabilities, peacekeeping-operation injuries, permanent
highland residents) or 3,000 GEL (war veterans, single mothers, adopters in the first year,
foster parents, holders of the "Georgian Mother" title). Payroll Administrators assign
employees and edit the categories; other payroll users only read them, because a limit applies
in every company.

- Income tax is 0 while the employee's **income of the calendar year after pension** stays under the limit; the
  month that crosses it taxes only the excess; after that, the normal 20%.
- Several categories: the **highest** limit applies. Limits do not add up.
- The employee pension comes off first, in full; the allowance covers only the income left after it.
- All gross income counts: salary, bonuses, separate benefits, separate overtime and salary
  advance pay-outs.
- Earlier payslips of the year use the allowance first, drafts of earlier months included. The
  same person's employee records in other companies (same personal number) share one
  allowance, and a category set on one record applies to all of them.

Single mother (3,000), member, wage 1,000 every month:

| Month | Used before | Left | Taxable | Pension | Income Tax | Net |
|---|---:|---:|---:|---:|---:|---:|
| Jan | 0 | 3,000 | 0 | -20.00 | 0.00 | 980.00 |
| Feb | 980 | 2,020 | 0 | -20.00 | 0.00 | 980.00 |
| Mar | 1,960 | 1,040 | 0 | -20.00 | 0.00 | 980.00 |
| Apr | 2,940 | 60 | 920 | -20.00 | -184.00 | 796.00 |
| May | 3,920 | 0 | 980 | -20.00 | -196.00 | 784.00 |

The allowance is used up by income after pension: a member's 1,000 wage uses 980 of it. With 500
of the allowance left on a 1,000 wage: pension -20.00 first, base 1,000 - 20 - 500 = 480, income
tax -96.00, net 884.00.

## 9. Benefits, deductions and salary advances

In **Payroll > Benefits & Deductions** a program has a **company amount** (paid to the
employee, taxed like a bonus), an **employee amount** (deducted from net, after tax), an
optional **Vendor**, a recurrence (*One Time* or *Monthly*), a period and a pay mode: *With
Salary* (on the regular payslip) or *Separate Payment* (on its own payslip). **Add Employees**
creates one line per employee; a line can override the amounts and dates.

| Kind | On the payslip |
|---|---|
| Company amount | **Bonus**: added to gross; pension and income tax apply |
| Employee amount | **Benefit Deduction**: taken from net after tax (With Salary only) |
| Benefit with a **Vendor** | Both amounts are owed to the vendor and paid to it. The company share shows as **Benefit in Kind (Company Share)**: in gross, so income tax and pension apply as to salary, and taken back out of net as **Company Share Paid to Vendor** |
| Salary advance | **Salary Advance Pay-Out (Net)** now, then **Salary Advance Repayment** on the following payslips |
| Payment at the end of employment | On the payslip press **Add Inputs**, choose **Termination Payment** and type the amount. It is added to gross; pension and income tax apply |

Examples:

- Bonus 500, member, wage 1,600: gross 2,100.00, pension -42.00, income tax -411.60, net 1,646.40.
- Deduction 80 a month, non-member, wage 1,600: income tax -320.00 (unchanged), deduction
  -80.00, net 1,200.00.
- Fitpass with a vendor (company 20, employee 80), member, wage 3,000: gross 3,020.00, pension
  -60.40, income tax -591.92, deductions -80.00 and -20.00, net 2,267.68. Fitpass receives one
  payment of 100.00.

**Separate Payment** benefits are paid through **Payroll > Benefits Pay Run**, which creates
Benefits Payslips on GEO Benefits Pay next to the month's salary and opens their list. They carry only bonuses and
advance pay-outs, taxed normally. Deductions and repayments always ride the salary payslip
(alone they would be a negative payment).

**Salary advances** are paid in two steps:

1. The pay-out payslip pays the advance net of tax: 2,000 to a member → 2,000 - 40 pension -
   392 income tax = 1,568.00. The tax and pension are booked as prepaid.
2. The next salary payslips pay the full salary and deduct one installment each (1,000 a month
   for two installments), which closes the prepaid amounts. The last installment takes any
   rounding. The advance total is the amount on the employee's line; a line saved with 0 pays nothing.

Deleting a repayment payslip re-opens its installment. Two advances repaid in the same months
each get their own installment. An advance paid while an exemption allowance is left prepays
no tax; its tax is part of that month's income tax line.

## 10. Overtime on a separate payslip

1. On the employee's Payroll tab: turn on **Pay Overtime Work Logs**, set the hourly wage and
   choose **Overtime Payment** = *Separate Payslip*.
2. Approve overtime logs as usual (hours × hourly wage × rate, fixed at approval).
3. **Payroll > Payslips > Pay Runs > New**: choose the structure **GEO Overtime Pay** and the
   period, select the employees (only those with approved unpaid separate overtime appear) and
   generate. Each employee gets one overtime payslip with all approved, unpaid overtime dated on
   or before the period end; the period start is not a filter, so overtime left over from earlier
   months is paid on this run too.
4. Check **Work Items**, then validate and pay as usual; **Pay Salaries** works too.

Keep the employee's normal salary structure type: GEO Overtime Pay is chosen on the pay run
only. Each approved log keeps the payment route of the contract it was approved under. An
overtime payslip holds only overtime, gross, pension, income tax and net: no base salary,
benefits, deductions or advance installments.

Overtime shares the income-tax exemption with salary and benefits. If a salary payslip and an
overtime payslip were both computed before either was validated, validate one, then recompute
and check the other (validation refuses the stale one).

Example: 10 hours at hourly wage 10 and 150% → gross 150.00. Member: pension -3.00, income tax
-29.40, net 117.60. Non-member: income tax -30.00, net 120.00. Member with only 100 of
exemption left: base 150 - 3 - 100 = 47, income tax -9.40, net 137.60.

## 11. The monthly payroll, step by step

1. **Approve** the month's work logs. Timesheets need no validation for payroll.
2. **Payroll > Payslips > Pay Runs > New**, one run per salary structure (monthly, hourly,
   daily and per-unit employees need a run each). **Generate Payslips** makes one payslip per
   contract. A month has up to six runs, in this order: Monthly, Hourly, Daily, Unit, Benefits
   (Payroll > Benefits Pay Run) and Overtime (a run on the GEO Overtime Pay structure).
3. **Compute.** Each payslip picks up the approved logs and timesheets not yet paid,
   including older ones approved late (they keep their own date's price), and the benefits due.
4. **Check** each payslip:
   - the **Work Items** card in the header: what logs and timesheets pay, for example
     1,265.00 with *15.00 days Daily Work (Basic) · 5.00 h Overtime*. On Daily, Per Unit and
     Hourly-from-Timesheets payslips read this card: Odoo's *Wage* and *Worked days* cards count
     only the schedule and show 0.00 and 22 days there;
   - the **Work Items** button: every paid log and timesheet with its date, project, quantity,
     rate and amount (read-only);
   - the info icon on a salary line: which records it pays, and how income tax and net were
     reached.
5. **Validate** the run. One failing payslip stops the whole run and nothing is posted: fix the
   payslip the message names and validate again (section 13).
6. **Pay** with **Register Payment** on each payslip, or **Pay Salaries** with `gec_payroll_bank`
   (section 14). A payslip turns **Paid** when its net is settled.

The lines you will see on a payslip:

| Code | Line | |
|---|---|---|
| BASIC | Basic Salary | monthly or schedule pay |
| DAILY_BASIC, TIMESHEET_BASIC, UNIT_BASIC | Daily Work (from Logs), Timesheet Hours (Basic), Unit Work (from Logs) | base pay of the Daily, Hourly-from-Timesheets and Per Unit schemes |
| WORKLOG_OT, WORKLOG_DAILY, TIMESHEET_EXTRA, UNIT_EXTRA | Overtime Work Logs, Daily Work Logs, Timesheet Hours, Unit Work Logs | additions (section 5) |
| BONUS, BENEFIT_KIND, BENEFIT_DED, BENEFIT_KIND_DED | Bonus, Benefit in Kind (Company Share), Benefit Deduction, Company Share Paid to Vendor | section 9 |
| ADVANCE_PAY, ADVANCE | Salary Advance Pay-Out (Net), Salary Advance Repayment | section 9 |
| GROSS | Gross | |
| PENSION_EE, PIT, PENSION_ER | Pension Employee Contribution, Income Tax, Pension Company Contribution | section 8 |
| NET | Net Salary | |

Advance payslips also show "Prepaid …" and "… from Prepaid" lines: they move the tax and
pension paid in advance and do not change net.

## 12. Changing a payslip or a contract

| Action | What happens |
|---|---|
| Cancel a payslip | Its work items go back to *Not in Payslip*, one-time benefits are released, and its journal entry is deleted (or reversed in a locked period) |
| Reset a cancelled payslip to draft | It is recomputed with today's amounts and picks its work items up again |
| **Set to Draft** on a validated payslip (list **Actions**) | Its journal entry is deleted or reversed; validating again books the new amounts |
| Reset a pay run to draft | Its unedited payslips are refreshed and their journal entries removed. A paid run cannot be reset |
| Delete a draft or cancelled payslip, or a pay run | Its work items are released first |
| A **Paid** payslip | Cannot be cancelled or reset: use **Correct**, or **Mark Unpaid** first if the payment was reversed |
| **Correct** | Standard Odoo refund and correction; the correction reads the original payslip's work items. The refund of a validated correction cannot be cancelled on its own |
| Edit a salary line | The lines after it follow (an edited Basic Salary changes gross, tax and net). The payslip keeps its work items but cannot pick up new ones after an edit: if new work appears, cancel it and create a new one |

**A raise in the middle of a month:** Odoo 20 pays both contract versions on one full-month
payslip, each day at its own version's wage. Wage 1,600 until 15 January and 2,000 from 16
January → January pays 800 + 1,000 = 1,800.00. Do not shorten the payslip to the version
dates. A change of structure type (Fixed to Daily, for example) or of timesheet pay in the
middle of a month needs a **new contract** from the change date.

## 13. When Odoo refuses

| Message starts with | When | What to do |
|---|---|---|
| "Work items not in the payslip" (a dashboard warning that blocks Validate) | Validate | Compute the payslip again |
| "… pays work items that changed after being claimed" / "… does not match its settlements" | Validate | Compute the payslip again |
| "… already has a regular payslip for the same contract overlapping this period" | Validate | Delete or cancel the other payslip (forgotten drafts count) |
| "Fixed-wage payslip shorter than its period" (a dashboard warning that blocks Validate) | Validate | Keep the standard monthly dates (section 12) |
| "… covers contract versions with different salary structure types or timesheet-based hourly pay" | Validate | Start a new contract from the change date |
| "… still contains schedule-based BASIC pay" | Validate | Compute again; do not edit worked days on Daily or Per Unit payslips |
| "The income-tax exemption used by … has changed" | Validate | Compute, check, then validate (section 8.3) |
| "Correction payslip … has no matching validated refund" | Validate | Use **Correct** on the original payslip |
| "Georgian payroll posts one journal entry per payslip" | Validate | Turn off **Batch Payroll Move Lines** in the Payroll settings |
| "… payable timesheet hours on …, over the 24h/day limit" | Compute | Fix or delete the extra timesheet lines |
| "These payslips are already paid" | Cancel or reset | Use **Correct**, or **Mark Unpaid** first |
| "The benefit inputs of … changed after its last computation" | Validate | A benefit or advance changed after the last Compute: compute the payslip again |
| "… paid out an advance whose installments are already validated" | Cancel | Use **Correct** on the pay-out payslip; cancelling it would re-issue the advance |
| "… already paid on validated payslips: the vendor and the advance terms cannot change" | Saving a benefit | Archive the program and create a new one with the new vendor or terms |
| "The advance of … was already paid out; its amount cannot change" | Saving a benefit line | Same: a paid-out advance keeps its total |
| "Payment method … has no Outstanding Payments account" | Register Payment | Set an Outstanding Payments account on the journal's payment method (journal > Outgoing Payments) |
| "These payable salary lines have no partner" | Register Payment | Set the partner on the salary rule the message names |
| "The pay routing of … cannot change in place" / "… would become permanently unpayable after this change" | Saving the contract | Create a new dated contract version, pay the lines first, or waive them |
| "… has no pay route for … work logs" / "… is hourly-paid from attendance" | Approving a work log | See section 6: the scheme must pay that kind of log |

## 14. Accounting and payment

One journal entry per payslip in the **Salaries** journal, dated at the end of the payslip's
month. Member, gross 1,000:

| Account | Partner | Debit | Credit | From |
|---|---|---:|---:|---|
| 720100 Salaries & Wages | | 1,000.00 | | Basic Salary |
| 721000 Pension & Post-Employment Contributions | Pension Agency | 20.00 | | Pension Company Contribution |
| 332010 Pension Contribution Accrued | Pension Agency | | 20.00 | Pension Company Contribution |
| 332010 Pension Contribution Accrued | Pension Agency | | 20.00 | Pension Employee Contribution |
| 331320 Employee PIT Transit | State Treasury | | 196.00 | Income Tax |
| 310310 Salaries Payable | the employee | | 784.00 | Net Salary |
| **Total** | | **1,020.00** | **1,020.00** | |

Other lines: bonuses and the company share paid to a vendor debit 720110 (Allowances & Bonuses); overtime
debits 720200 (Overtime & Commissions); a termination payment debits 720700; benefit deductions credit 720900 (Personnel Cost Others),
except the part owed to a vendor, which goes to the vendor's payable account (normally 310110);
advance pay-outs debit 150310 Payroll Advances, with prepaid pension on 332011 and prepaid tax
on 331311, closed by the repayments. A rounding cent (prorated wages leave one) goes to 720100.

**Register Payment** (a validated payslip with a posted entry) pays every open amount of the
payslip: the net to the employee, both pension shares to the Pension Agency in one payment,
income tax to the State Treasury, and one payment per benefit vendor. It pays one payslip at a
time, and the journal's payment method needs an **Outstanding Payments** account.

```text
Validated payslip: net 784 · pension 20 + 20 · income tax 196
   │  Register Payment / Pay Salaries
   ├──► 784 to the employee (310310) ──► payslip turns Paid
   ├──► 40 to the Pension Agency (332010)
   └──► 196 to the State Treasury (331320)
```

To pay many employees through bank channels, use **Pay Salaries** (`gec_payroll_bank`);
`basis_bank` sends the batches to Basis Bank. Pay Salaries also sends income tax as a treasury
transfer with the State Treasury's code, which Register Payment does not.

## 15. Rules to remember

| Rule | Why |
|---|---|
| Set **Pay Scheme** and **Salary Structure Type** together | Saving refuses a mismatch |
| Daily and per-unit pay come only from approved logs | No log, no pay; leave and holidays pay nothing on these schemes |
| Hourly from Timesheets pays only timesheets | Schedule, leave, holidays and overtime logs pay nothing; a zero month is correct |
| Timesheets are paid whether or not they are validated | Validation stays a Timesheets-app step; payroll pays every eligible line |
| Approve before computing, compute before validating | Approved work the payslip has not picked up blocks validation |
| Change pay routing with a new dated contract version | In-place changes are refused once a version has validated payslips |
| One regular payslip per contract, for the full period | Odoo 20 pays every version of a contract on one payslip |
| Validate a pay run only when every payslip is ready | One failure rolls the whole run back |
| Keep income tax on 331320, not 331310 | Income tax on 331310 cannot be paid from payroll |
| Keep **Batch Payroll Move Lines** off | Payment needs one journal entry per payslip |
| Keep "Split on names" off on the Benefit Deduction and Company Share Paid to Vendor rules | The vendor split finds their journal line by the rule name |
| Never add a Basic Salary rule to GEO Benefits Pay or GEO Overtime Pay, or a default structure to their types | They would stop being off-cycle payslips |

## 16. Common questions

**"Pay Daily Work Logs" is off for my Daily employee.** Correct: on daily schemes the daily log
is the base pay. The flag means "daily logs on top of a monthly wage" (Fixed + Daily).

**An Hourly-from-Timesheets payslip is zero.** Correct when no eligible timesheet exists. Check:
project list, **Timesheet Pay From**, contract dates, hourly wage, the 24-hour limit, waivers,
and whether another payslip already pays them. Validation is not a condition.

**A daily log cannot be approved.** The scheme must use daily logs (Daily, Daily + Hourly, Daily
+ Per Unit or Fixed + Daily), with a daily wage above zero and a contract on that date.

**Overtime cannot be approved.** **Pay Overtime Work Logs** must be on, with an hourly wage above
zero and a contract on that date. Employees paid hourly from attendance or from timesheets
cannot have overtime logs.

**Income tax is 19.6% of gross, not 20%.** For a pension fund member, income tax is 20% of gross
after the 2% pension: 20% × 98% = 19.6%.

**Two employees in the same category: one pays income tax, one does not.** Their gross of the
year differs, or an earlier draft used one employee's allowance.

**Why one payment to the Pension Agency for both shares?** Both shares sit on the same account
(332010) with the same partner.

## 17. Known limitations

| Limitation | What to do |
|---|---|
| Nothing cross-checks a daily log and a timesheet on the same day, or overtime logs and attendance or planning overtime | The approver checks it |
| **Pension Fund Member** is not dated | Set it before the first payslip |
| Exemption categories use the highest limit; drafts use the allowance | Validate months in order |
| Abandoned drafts keep their work items | Delete or cancel them |
| Late work has no oldest date | Old approved work lands on the next regular payslip |
| Unit rates: one price per work type, per company or shared; no per-employee or per-project price, no quantity limit | |
| The state's pension share is not modelled; one income tax rate for every employee | A new legal rate: Payroll > Configuration > Rule Parameters |
| Daily pay from the working schedule is not available | Daily pay comes from approved logs |
| Restoring a waiver records no reason | |
| A validated overtime timesheet blocks Reset to Draft and Cancel of its log for users without the Timesheets approver right | Ask a Timesheets approver to reset the line to draft, or to reset the log |
| Overtime logs approved before this feature existed have no timesheet line | Reset and re-approve the log if it needs one |
| A Payroll Officer can approve their own work log | Separation of duties is a process rule |
| Pay run validation is all or nothing | One bad payslip blocks the run |

## 18. Glossary

| Term | Meaning |
|---|---|
| Contract version | The dated part of an employee's contract that holds the pay scheme and wages; a raise creates a new version |
| Pay scheme | Where base pay comes from and what can be added |
| Work log | Overtime, daily work or unit work recorded by an employee and approved by a manager |
| Work Item | One log or timesheet paid by one payslip, with its frozen quantity, rate and amount |
| Regular payslip | The monthly payslip on the contract's own structure; with overtime payslips, the only kind that picks up logs and timesheets |
| Off-cycle payslip | A Benefits or Overtime payslip, paid apart from the salary |
| Waiver | A decision that timesheets must never be paid by payroll |
| Art. 82 exemption | A yearly amount of gross income free of income tax, for the categories the law lists |
