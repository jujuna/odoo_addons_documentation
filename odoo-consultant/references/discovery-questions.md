# Discovery questions

Use these as a question bank, not a questionnaire. Follow
[implementation-protocol.md](implementation-protocol.md): use known facts, select the
1–3 missing details most likely to change the design (at most 4 per round), and explain
why they matter. Wait on essential unknowns; continue when the brief is sufficient.

Ask about the business in familiar words. Environment facts such as the client's version,
edition, hosting and installed apps may need clarification too. Look up Odoo capabilities
yourself. Keep confirmed answers, assumptions and open questions in the working snapshot.

## Every client

- How many companies / branches? Separate legal entities or one company?
- Which currencies? Which country's taxes?
- What system do they use today, and what data must move to Odoo?
- Who are the users by role, and how many?
- What are the 3 biggest problems they want Odoo to solve?
- Who approves what today? (approval chains drive the whole design)
- Go-live date, and any hard deadline (year start, tax period, payroll month)?

## Accounting (ask with the accountant)

- Chart of accounts: Georgian standard, their own, or a group chart?
- VAT payer? Which VAT regime and declaration frequency?
- Bank accounts and currencies; do they want bank statement import/sync?
- Cost centers / projects / departments for reporting (analytic accounting)?
- Fixed assets, deferred revenue/expenses?
- Opening balances: from which date, at what detail (per invoice or totals)?
- Month-end close: who does what, what reports must come out?

## Sales / CRM

- How does a sale start: lead, quote, walk-in, online?
- Price lists, discounts, and who can give discounts?
- Invoicing: on order, on delivery, on milestones, recurring?
- Down payments or prepayments?
- Commission or sales team targets?

## Purchase / Inventory

- Purchase approval: by amount? by who?
- Warehouses and locations; one or several?
- Products tracked by lot/serial number? Expiry dates?
- Stock valuation needed in accounting (perpetual)? Costing method?
- Delivery steps: 1 step, or pick/pack/ship?
- Waybills (RS.ge) required for deliveries?

## HR / Time Off / Payroll

- Working schedules: one for all, or several (shifts, part-time)?
- Time off types: annual, sick, unpaid, others? Which need approval, and by whom?
- How is annual leave earned: fixed amount per year, or earned monthly (accrual)?
- Carry-over to next year: yes/no, limit, expiry?
- Can employees go negative on leave balance?
- Public holidays: which calendar, per company?
- Payroll in Odoo or outside? Which allowances, deductions, benefits?
- Attendance or timesheets needed? For payroll, projects, or both?

## Projects / Services

- Fixed price, time & material, or milestones?
- Timesheets: who logs, how often, and are they billed?
- Project profitability reporting needed?

## Closing each topic

Summarize the agreed flow briefly when it helps. Ask for confirmation only if a material
interpretation or decision remains uncertain. Do not reopen questions already answered.
