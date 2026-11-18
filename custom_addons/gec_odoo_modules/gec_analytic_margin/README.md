# Analytic Margin & Cost Allocation — User Guide

Module `gec_analytic_margin` · Odoo 20 Enterprise · version 20.0.1.21.0

This module shows what each project, product line and customer **really earns
after shared costs**, what each activity costs per unit (Activity-Based
Costing, ABC), and how the company compares with a software-vendor benchmark.

It works on top of Odoo's own analytic accounting. Invoices, bills, payroll
entries and timesheets are booked as usual; the module classifies them, spreads
shared costs onto the things that used them, and reports the result.

> Developers: technical notes are in [README_DEV.md](README_DEV.md).

---

## Contents

1. [Before you start](#1-before-you-start)
2. [Where everything is](#2-where-everything-is)
3. [Setting up, step by step](#3-setting-up-step-by-step)
4. [The monthly routine](#4-the-monthly-routine)
5. [Reading the reports](#5-reading-the-reports)
6. [What the figures mean](#6-what-the-figures-mean)
7. [When a figure looks wrong](#7-when-a-figure-looks-wrong)
8. [Limits to know](#8-limits-to-know)

---

## 1. Before you start

**Apps needed:** Accounting (with Accounting Reports), Budget, Project and
Timesheets. Employees are used for headcount and FTE.

**Access rights**

| Who | Needs | Can do |
|---|---|---|
| Readers (managers, controllers) | *Analytic Accounting* | Open the Dashboard and every report |
| Cost accountant | The setting *Activity-Based Costing* turned on | Configure activities, rules, components; run allocations |

**Turn the module on:** Accounting ▸ Configuration ▸ Settings ▸ *Analytics*
section:

- **Activity-Based Costing** — tick it. This shows the configuration menus and
  allocation runs.
- **P&L Presentation** — choose per company:
  - *By nature* — costs read by what was bought: Personnel, Overhead,
    Depreciation.
  - *By function* — Personnel and Overhead regrouped by what they were for:
    Cost of Sales, R&D, Sales & Marketing, G&A. Software companies and the
    benchmark use this one.
- **Monthly Allocation** — leave *Off* until the setup is checked (see
  [section 4](#4-the-monthly-routine)).

---

## 2. Where everything is

**Reports** — Accounting ▸ Reporting ▸ Activity-Based Costing

| Menu | What it is for |
|---|---|
| Dashboard | The company at a glance, against the benchmark |
| Margin Statement | The P&L per project, product, partner or activity, down to the invoice |
| Margin Analysis | Free pivot / list / graph over every amount |
| Activity Rates | What one unit of each activity cost, run by run |
| Planned vs Actual | Planned driver units against what was measured |
| Revenue Forecasts | Each month's revenue forecast, frozen on the 1st, against the actual |
| Allocation Runs | The monthly allocation: preview, generate, reset |

**Configuration** — Accounting ▸ Configuration ▸ Activity-Based Costing

| Menu | What it is for |
|---|---|
| Setup Health Check | Lists setup mistakes before a run shows them |
| Activities | The work being costed and how it is counted |
| Allocation Rules | Which cost pool goes where, by which driver |
| Margin Components | The P&L lines, with their classification rules inside |
| Revenue Streams | Kinds of revenue: licenses, maintenance, subscriptions, services |
| Margin Levels | The subtotals: Contribution Margin, Gross Margin, EBITDA, EBIT |

**Fields the module adds to existing screens**

| Screen | Field(s) |
|---|---|
| Analytic Account | Function, Revenue Stream, Headcount |
| Analytic Plan | Margin Statement Reading (Products / Departments) |
| GL Account | Margin Component, Revenue Stream |
| Project | P&L Function; tab **Margin Forecast** (incl. Planned / Actual Go-Live, Built From Template) |
| Department | P&L Function |
| Project Tag | Counts as Rework |
| Timesheet / analytic item | Activity |
| Budget line | GL Account |

---

## 3. Setting up, step by step

Do the steps in this order. Each one ends with a check, so a mistake is found
at that step and not later in the reports.

### Step 1 — Analytic plans and accounts

The module reads **analytic items** only. A cost or revenue with no analytic
distribution appears in no report.

1. Accounting ▸ Configuration ▸ Analytic Plans. A typical setup:
   - **Project** plan — one account per customer project (Odoo creates them
     with projects).
   - **Cost Centre** plan — Delivery, Engineering, Sales, Administration…
   - **Product Line** plan (optional) — your product or service lines.
2. On a plan, set **Margin Statement Reading** to *Products* or *Departments*
   to get that plan as its own reading of the Margin Statement.
3. Make sure bills, payroll entries and invoices carry an analytic
   distribution. Analytic Distribution Models fill it automatically.

✔ Check: Margin Analysis, filter *Actual*, group by plan. Every plan you expect
has amounts.

### Step 2 — Margin components (the P&L lines)

The module ships with: Revenue, Other Income, Direct Cost, Personnel, Overhead,
Depreciation & Amortisation, Finance, Income Tax, Excluded, and the four
function lines Cost of Sales, R&D, Sales & Marketing, G&A.

Each GL account gets one component:

1. Open Margin Components ▸ a component ▸ tab **Classification Rules**. A rule
   matches accounts by **Account Type** and/or **Code Prefix** (e.g. `741`).
   Rules are tried in order; the first match wins.
2. The shipped rules use the account type only: *Income* → Revenue,
   *Cost of Revenue* → Direct Cost, *Depreciation* → Depreciation, plain
   *Expense* → Overhead. Add prefix rules for your chart, above all for
   payroll (→ Personnel) and income tax, or salaries land in Overhead.
3. Press **Apply Rules**.
4. An account can be forced by hand: GL Account ▸ **Margin Component**. A hand
   value always beats the rules.

Two flags on a component matter:

- **Allocatable** — an allocation rule may move this cost. On for Personnel,
  Overhead, Depreciation; off for Finance and Income Tax.
- **Regroup by Function** — in a *by function* company, this cost is moved to
  the function line its cost centre or activity names. On for Personnel and
  Overhead.

✔ Check: the GL Account list shows *Component (effective)* for every P&L
account. Accounts with none land on the *Unclassified* line.

### Step 3 — Margin levels (the subtotals)

Margin Levels lists the subtotals and the components each one adds up:

```
Contribution Margin   Revenue + Direct Cost
Gross Margin          + Personnel           (by function: + Cost of Sales)
EBITDA                + Overhead            (by function: + R&D, S&M, G&A)
EBIT                  + Depreciation
```

Rename, add or remove levels as you need. Finance, Tax and Excluded are in no
level, so they never enter a margin.

⚠ A module upgrade resets the shipped levels. Note your changes.

### Step 4 — Functions (by-function companies only)

Tell the module what each cost was **for**. Set the function on:

| Where | Field | Example |
|---|---|---|
| Cost centre analytic account | Function | Delivery → Cost of Sales; Sales → Sales & Marketing; Administration → G&A |
| Project | P&L Function | An internal product project → R&D |
| Activity | Function | Implementation hours → Cost of Sales |
| Department | P&L Function | Engineering → R&D; Delivery → Cost of Sales (used for headcount and utilization) |

When more than one is set, the order used is: project → activity → cost
centre.

A project with a P&L Function is treated as an **internal project**: shown as
spend, not as a profit centre.

✔ Check: Setup Health Check lists *cost without a function*.

### Step 5 — Revenue streams

Revenue Streams ships with Licenses, Maintenance & Support, Subscriptions and
Professional Services. On each:

- **Recurring** — revenue that renews without a new sale (maintenance,
  subscriptions).
- **Standard Product** — revenue from the product as it is, sold to many
  customers (licenses, maintenance, subscriptions), not custom work.

Then say which revenue is which:

- on an **income GL account** ▸ Revenue Stream, when each account carries one
  kind of revenue; or
- on an **analytic account** (a product line or project) ▸ Revenue Stream,
  when one income account carries several kinds. The analytic stream wins.

✔ Check: Health Check lists *revenue without a stream*. Revenue with no stream
counts as one-off and non-product.

### Step 6 — Activities (ABC)

An activity is a piece of repeated work whose cost you want per unit:
consulting hours, invoices issued, tickets solved.

1. Activities ▸ New.
2. **What It Measures** — pick a template (*Timesheet hours per project*,
   *Completed tasks per project*, *Vendor bill lines per cost object*,
   *Customer invoice lines per cost object*). It fills the technical fields.
3. **Driver Unit** — what one unit is: `hour`, `invoice line`, `ticket`.
4. **Rate Basis**
   - *Actual* — pool ÷ what was measured. Simple, but a quiet month makes each
     unit expensive.
   - *Standard* — a fixed **Standard Rate** per unit. Differences show as rate
     variance.
5. **Practical Capacity** — the units the team can deliver per period at a
   normal rhythm. When set, only the used share of the pool is charged out;
   the rest shows as **idle capacity**. Leave 0 to charge out the whole pool.
6. **Value** — Value-added / Business-required / Non-value-added. Used on the
   dashboard to split the pool.
7. Optional: **Weight by Employee Cost** (an architect's hour costs more than a
   junior's); **Only Records Tagged With This Activity** when several
   activities count the same timesheets.
8. Press **Preview Quantities**. It shows what the activity measures this
   year, per cost object. Nothing measured = wrong filter, path or company.

✔ Check: Preview shows quantities on the projects you expect.

### Step 7 — Allocation rules

A rule takes a cost pool and spreads it onto cost objects.

| Group | Field | Meaning |
|---|---|---|
| Allocate from | Source Plan, Source Accounts | Where the cost sits now (e.g. Cost Centre ▸ Delivery). Empty accounts = all of the plan |
| | Source GL Accounts or Source Component | Which cost (e.g. Personnel) |
| Allocate onto | Target Plan, Target Accounts | Where it goes (e.g. Project plan). Empty = every account, so new projects are included automatically |
| | Only Untagged Cost | Keep on: cost already on a project is not moved again |
| Driver | Driver | *Revenue share, Direct cost share, Headcount share, Equal split, Manual percentages, Activity (ABC)* |
| | Share of Pool (%) | ABC: the share of the pool this activity takes |
| | Stage 1 Basis | ABC: *Declared* (typed) or *Measured* (from timesheets tagged with the activity) |
| | Step | Order in a cascade: step 2 pools include what step 1 delivered |

For ABC, create **one rule per activity** over the same pool, e.g.
Delivery Personnel → Consulting hours 80%, Invoicing 20%.

*Headcount share* reads **Headcount** on the target analytic accounts.
*Manual percentages* must total 100%.

### Step 8 — Budgets

Accounting ▸ Accounting ▸ Analytic Budget. Budget lines per analytic account,
with the module's **GL Account** field on each line so the amount reaches the
right P&L line. Budgets feed the Budget and Variance columns, the budget cards
and the four-quarter outlook.

### Step 9 — Projects (margin at completion)

Project ▸ tab **Margin Forecast**:

| Field | Fill with |
|---|---|
| Contract Value | What the customer pays for the whole project. Empty = the project's revenue budget |
| Allocated Time (Timesheets) | Total hours planned; hours to go = allocated − logged |
| Remaining Other Cost | Cost still to come that is not hours: subcontractors, licences, travel |
| Hourly Cost Override | Cost of one remaining hour. Empty = the latest rate of the hours activity |
| Planned Go-Live / Actual Go-Live | When the customer is due to start using the system, and when it did |
| Built From Template | Filled in automatically when the project is created from a project template |
| End Date (project's own field) | The planned end, compared with the forecast end |

The tab then shows revenue and cost to date, overhead to come, estimate to
complete, forecast margin, **Forecast Status** (On track / Eroding / Loss),
backlog, percent complete, unbilled work, cash collected and cash margin, and
the **Forecast End Date** (hours to go at the pace of the last 8 weeks) with
the days late against the planned end.

**Milestones:** turn on Milestones in the project's settings and give each a
deadline; mark it reached when it is. Milestones on time are measured from
these, so no extra field is needed.

### Step 10 — Rework tag (optional)

Project ▸ Configuration ▸ Tags ▸ tick **Counts as Rework** on a tag such as
"Rework" or "Bug fix". Hours on tasks with that tag feed the Rework card.

### Step 11 — Run the Health Check

Accounting ▸ Configuration ▸ Activity-Based Costing ▸ **Setup Health Check**.
Choose a period. Findings are graded *Wrong*, *Suspicious*, *Worth knowing*;
**Go to it** opens the record to fix. Press **Check Again** until nothing is
*Wrong*.

---

## 4. The monthly routine

1. **Post everything** for the month: invoices, bills, payroll, depreciation.
2. **Timesheets complete** — the dashboard's *Timesheet coverage* should be
   90% or more.
3. **Allocation run** — Reporting ▸ Activity-Based Costing ▸ Allocation Runs ▸
   New, set the period:
   - **Preview** — a dry run: what each rule would move, nothing written.
     **Generate It** from there, or close.
   - **Generate Allocation** — writes the allocated items and the activity
     rates.
   - **Recompute** — after a correction in the month; rebuilds from scratch.
   - **Delete Allocation** — removes everything the run wrote.
4. **Check** — company Net is the same before and after the run. Allocation
   moves cost; it never changes the total.
5. **Read** the Dashboard and the Margin Statement.

Allocation never touches journal entries. It writes analytic items only: a
*contra* line taking cost off the source and *target* lines putting it on the
cost objects. They sum to zero.

**Automatic runs:** Settings ▸ **Monthly Allocation**:

- *Prepare a draft run* — creates the run; you review and press Generate.
- *Prepare and generate it* — fully automatic.
- **A Period Is Closed When** — *Accounting lock date* (recommended) or a
  number of **Days After Month End**.

---

## 5. Reading the reports

### Dashboard

Reporting ▸ Activity-Based Costing ▸ **Dashboard**.

**Top bar:** period (This Month, Last Month, This Quarter, This Year, Last Year,
Custom), analytic plan, and **Print / PDF**. The company comes from Odoo's
company switcher. Choose **Whole company** in the plan list to count every
amount once. Your filter choices are remembered in your browser.

Every figure is compared with the previous period of the same length (green or
red pill). A coloured top edge and gauge show the benchmark: red below the base
range, amber in the base range, green in the strong range.

**Click a card** to open its *proof*: the formula, the same formula with this
period's numbers, the parts it adds up (click a part to open its records), the
benchmark, and what can make the figure wrong. Clicking a bar, chart point or
table row opens the records behind it.

| Tab | What you find |
|---|---|
| **Overview** | Revenue, Gross margin, EBITDA margin, Recurring revenue, Net revenue retention, Revenue per FTE, Backlog, Projects at risk; P&L ladder; last 12 months; *Needs attention* warnings |
| **Revenue & Customers** | Revenue and Net vs budget; Product revenue; Next four quarters outlook; retention (NRR, GRR, customers lost / won) and the retention bridge; revenue mix and margin by stream; customer concentration; most and least profitable cost objects |
| **People** | FTE; revenue, gross profit and recurring revenue per FTE; revenue vs FTE growth; utilization (all and delivery staff); timesheet coverage; product share; bespoke engineering; rework; R&D per active customer; headcount by function; revenue per FTE by stream |
| **Projects & Cash** | *Delivery:* milestones on time, go-live slippage, projects finishing late, projects built from a template; projects at completion; forecast end dates. *Cash:* backlog, unbilled work, billed ahead, cash-negative projects; backlog, billing and cash per project; days sales outstanding, cash conversion, lowest cash in the next 13 weeks, forecast accuracy; the 13-week cash forecast chart; internal projects |
| **Activity Costing** | Cost pool, charged, not charged, idle capacity, rate variance, capacity used; charts per activity and by value; activity table |

Figures marked *company-wide* (productivity, concentration, cash) ignore the
plan filter.

When the selected companies use different currencies, the dashboard converts
every amount to the active company's currency at the rate of its own date, and
says so under *Needs attention*.

### Margin Statement

Reporting ▸ Activity-Based Costing ▸ **Margin Statement**. The P&L in Odoo's
accounting-report screen.

- **Rows:** section → cost object → P&L line → GL account → invoice, bill or
  activity. Click a row to unfold.
- **Columns:** Revenue, Expense, Net, Margin %, Budget, Variance. Use the
  comparison filter for previous periods.
- **By… dropdown:** By Analytic Plans, By Projects, By Partner, By Activity,
  and By Products / By Department when a plan is marked for it. The picker
  next to it limits the report to chosen sections.
- **Before Allocation** — cost as booked, before any run moved it.
- **Ladder First** — P&L lines first, cost objects inside each: the company's
  own P&L.
- Export to PDF or Excel with the usual report buttons.

### Margin Analysis

Reporting ▸ Activity-Based Costing ▸ **Margin Analysis**. Pivot, list and
graph over every amount. Group by plan, account, component, stream, partner,
activity, month.

⚠ An amount tagged on several plans appears once per plan. For a company total
tick the filter **Count Each Amount Once**.

### Activity Rates

One row per activity and run: rate per unit, units, pool, charged, not charged,
idle capacity, rate variance, capacity used. Use it to watch the cost of an
hour or an invoice month by month.

### Planned vs Actual

Planned driver units per activity and cost object against what was measured,
with the variance and its cost. Create the plan with **Plan from Actuals** on
an activity, then edit. Filters *Over Plan* / *Under Plan*.

---

## 6. What the figures mean

Revenue is positive and cost negative, so every margin is a plain sum.

**Profit and loss**

| Term | What the module counts |
|---|---|
| Revenue | Actual amounts on *Money in* components |
| Contribution margin | Revenue + Direct Cost |
| Gross margin | + Personnel (by nature) or + Cost of Sales (by function) |
| EBITDA | Operating profit before depreciation: everything above Depreciation |
| EBIT | EBITDA + Depreciation & Amortisation |
| Net | Every amount except Excluded |
| Margin % | Amount ÷ revenue of the same cost object |

**ABC**

| Term | What the module counts |
|---|---|
| Cost pool | Actual cost on the rule's source accounts for the period |
| Rate per unit | Actual: pool ÷ practical capacity (÷ units measured when no capacity is set); Standard: the standard rate |
| Charged | Units used × rate, put on cost objects |
| Not charged | Pool − charged; stays on the cost centre |
| Idle capacity | (capacity − units used) × rate: the cost of unused capacity |
| Rate variance | Not charged − idle capacity: the activity cost more than planned |
| Capacity used | Units measured ÷ practical capacity |

**Revenue and customers**

| Term | What the module counts |
|---|---|
| Recurring revenue % | Revenue on recurring streams ÷ revenue |
| Product revenue % | Revenue on standard-product streams ÷ revenue |
| NRR | Revenue now from customers who had revenue a year earlier ÷ their revenue then (recurring revenue when there is any) |
| GRR | The same with growth left out; never above 100% |
| Concentration | Largest customer's and top 10's share of revenue; contacts count as their company |

**People**

| Term | What the module counts |
|---|---|
| FTE | Days employed ÷ days in period × schedule rate, summed over employees |
| Revenue per FTE | Annualised revenue ÷ FTE |
| Utilization | Customer-project hours ÷ hours the working schedules offered |
| Delivery utilization | The same for Cost of Sales departments only |
| Timesheet coverage | Hours logged ÷ hours available |
| Product share | Hours on R&D projects ÷ all project hours |
| Bespoke engineering | R&D staff hours on customer projects ÷ their project hours |
| Rework | Hours on rework-tagged tasks ÷ customer-project hours |
| R&D per active customer | Annualised R&D cost ÷ customers with revenue |

**Projects**

| Term | What the module counts |
|---|---|
| Backlog | Contract value − revenue invoiced, not below zero |
| Overhead to come | Backlog × overhead allocated so far ÷ revenue so far |
| Estimate to complete | Hours to go × hourly cost + remaining other cost + overhead to come |
| Forecast margin | Contract value − cost to date − estimate to complete |
| Eroding | Forecast margin % more than 5 points below the budgeted margin % |
| Percent complete | Cost to date ÷ forecast cost (cost-to-cost) |
| Unbilled work | Contract value × percent complete − revenue invoiced; negative = billed ahead |
| Cash margin | Cash collected − cost to date; negative = the company finances the project |
| Outlook coverage | Backlog ÷ planned revenue of the next four quarters (budget, else run rate) |
| Milestones on time | Milestones reached by their deadline ÷ milestones whose deadline is in the period |
| Go-live slippage | Projects live after the planned go-live, or still not live past it ÷ go-lives planned in the period |
| Forecast end date | Today + hours to go ÷ hours logged per week over the last 8 weeks |
| Built from a template | Customer projects created from a project template ÷ all customer projects |

**Cash** (company-wide)

| Term | What the module counts |
|---|---|
| Days sales outstanding (DSO) | Receivables open at period end ÷ invoiced in the period × days |
| Cash conversion | Operating cash ÷ EBITDA; operating cash = bank movements not from loans, capital or fixed assets, plus payments registered but not yet on a bank statement |
| 13-week cash forecast | Cash today + customer invoices on their due dates − vendor bills on theirs − other costs (payroll, accruals) at their last-13-week average |
| Forecast accuracy | Average of \|actual − forecast\| ÷ actual over the last closed months; the forecast is frozen on the 1st (budget, else 3-month run rate) |

---

## 7. When a figure looks wrong

| You see | Likely cause | Fix |
|---|---|---|
| An amount on *Unclassified* | GL account matches no classification rule | Add a rule or set Margin Component on the account, press Apply Rules |
| *Uncovered cost* warning | Allocatable cost no rule reaches | Add or widen an allocation rule |
| Margins all too good | Shared cost not allocated yet | Run the month's allocation |
| Personnel is empty, salaries sit in Overhead | Payroll accounts are plain *Expense* | Prefix rule to Personnel, Apply Rules |
| An activity charges nothing | Its counting finds no records | Preview Quantities; check filter, date field, company |
| Company total too high in Margin Analysis | Amounts counted once per plan | Filter *Count Each Amount Once* |
| Utilization / FTE figures low | Missing timesheets or employees without contracts | Check *Timesheet coverage*; employees need a contract start date and a working schedule |
| Recurring % is 0 | No streams set | Step 5 |
| Function lines empty | Company still *By nature*, or no functions set | Settings ▸ P&L Presentation; Step 4 |
| Project shows *No forecast* | No contract value and no revenue budget | Fill Contract Value |
| NRR far above 100% | The company had little revenue a year earlier | Compare a period with a full year before it |
| Rework card blank | No tag has *Counts as Rework* | Step 10 |
| Milestone / go-live cards missing | No milestone deadline or planned go-live in the period | Step 9 |
| Cash conversion strange or missing | Bank statements not imported; payroll paid outside Odoo | Import bank statements; book salary payments from the bank journal |
| Forecast accuracy marked * | Months before the module recorded forecasts, rebuilt afterwards | Wait for months recorded on their 1st |
| Net changed after a run | Should never happen | Delete Allocation, report it to support |

---

## 8. Limits to know

- **Cost centres keep their gross cost after allocation.** Allocated lines
  keep the source cost-centre tag, so the Cost Centre reading shows what each
  centre spent, not what it has left.
- **A run is counted whole.** A quarterly run shown against one month is not
  prorated.
- **Overhead to come is an estimate** at the past overhead-to-revenue ratio; a
  project with no revenue yet gets none.
- **Only the dashboard converts currencies.** The Margin Statement and Margin
  Analysis add amounts as booked.
- **Timesheets carry no GL account.** Decide whether labour cost comes from
  payroll or from timesheets; using both counts it twice.
- **Budget where you commit spend.** If personnel is budgeted on a department
  and allocation moves it to projects, compare with *Before Allocation* ticked.
- **Keep using Odoo's Budget report** for budget monitoring (committed purchase
  orders, achieved %); use this module for margin and GL-level variance.
- **The cash forecast assumes on-time payment.** Every invoice and bill is
  expected on its due date; late payers make it optimistic.
- **Reconstructed forecasts** (months before installation) use only data dated
  before the month, but that data may have been corrected since.
- **Multi-company:** rules, runs and activities belong to one company. An
  activity created in the wrong company measures nothing; Preview Quantities
  shows it at once.
