# Odoo basics: the mental model to teach

Use this for "what is X", "explain X", "teach me X", and whenever an answer would otherwise
assume knowledge the user does not have yet. Everything here is in business language. The
file paths are research aids; include concise evidence only when useful or requested.
These teaching examples need verification for the target environment before use.

## The ten ideas that make Odoo click

1. **One database, many apps, one set of records.** Every app (Sales, Inventory,
   Accounting, HR...) works on the same shared records. A **Contact** is the same record
   whether Sales calls it a customer, Purchase a vendor, or HR an employee's home address.
   That is why duplicate contacts hurt everywhere at once.
2. **Apps connect themselves.** Some combinations of apps install connecting modules
   automatically (details in dependency-analysis.md). Resulting behavior also depends on
   the product, route and other settings; not every order creates a delivery.
3. **A document has a life cycle.** Most records show a **status bar** at the top of the
   form (Quotation, Sales Order...). Buttons move the document forward, and a step often
   creates the next document. Odoo rarely deletes: it cancels and keeps the trail.
4. **The chain of documents.** Sales: a **Quotation** becomes a **Sales Order** when
   confirmed; the order creates a **Delivery**; invoicing the order creates a **Customer
   Invoice**; payment and reconciliation settle it according to the payment setup. Purchase: a **Request for Quotation** is
   confirmed into a **Purchase Order**; it creates a **Receipt**; the supplier's invoice is
   entered as a **Vendor Bill**; then payment. Every document keeps links to the ones before
   and after it (the **smart buttons** at the top of the form). Teach the chain first: most
   questions are about one link in it.
5. **Everything financial ends in a journal entry.** Invoices, bills, payments and stock
   valuation each post an entry in a **Journal** (a book of entries: Customer Invoices,
   Vendor Bills, Bank, Miscellaneous). Reports are built from these entries, so the accounts
   on products, taxes and journals must be right before the first document is posted.
6. **Configuration lives in three places.** (a) **Settings**, per app, with three kinds of
   switch: a feature switch, a switch that installs a module, and a per-company value.
   (b) The **Configuration** menu inside each app: types, stages, teams, rules, templates.
   (c) The master records themselves: a product's invoicing policy, a contact's payment
   terms. "Where do I set X" usually means finding which of the three.
7. **Who sees what.** Each user gets a level per app on their user form, tab **Access
   Rights** (for example **Purchase: User** or **Administrator**). Some groups include other groups; verify their actual relationships. Menus, buttons and fields can be limited to a level, and record rules limit
   which records someone sees (own team, own company). The "I don't see it" checklist is in
   ui-lookup.md.
8. **Companies.** One database can hold several legal entities. Most settings, journals and
   documents belong to one company; users switch with the company selector at the top right.
   Decide the company structure before creating any data.
9. **The chatter is the history.** On documents that support chatter: messages, emails sent,
   field changes with who and when, and **activities** (to-dos with a deadline). Odoo sends
   many emails automatically; the client should know which ones before go-live.
10. **Odoo has an opinion.** Standard flows encode a way of working. Bending them costs
    money at every upgrade. The consultant's first job is to fit the client to the standard
    where the difference does not matter, and only then to change Odoo where it does.

## Vocabulary: business word to Odoo word

Labels verified against Odoo 20 source (2026-09-23). Give the Odoo word in bold when the
user will meet it on screen.

| Business word | Odoo 20 word | Note |
|---|---|---|
| Customer, supplier, company, person | **Contact** | One record; "customer" and "vendor" are only its role on a document |
| Offer, proposal | **Quotation** | Becomes a **Sales Order** on **Confirm** |
| Supplier order | **Purchase Order** | Starts as **RFQ** (request for quotation) |
| Delivery note, goods receipt | **Delivery Orders** / **Receipts** | Both are transfers in Inventory |
| Sales invoice | **Customer Invoice** | Menu **Accounting > Customers** |
| Supplier invoice | **Vendor Bill** | Menu **Accounting > Vendors** |
| Credit note, refund | **Customer Credit Note** / **Vendor Credit Note** | Shown as **Credit Note** on the document |
| Cost center, project for reporting | **Analytic Account** | Needs the **Analytic Accounting** setting |
| Ledger, book | **Journal** | Every entry belongs to one |
| Leave, vacation | **Time Off** | The app and the request |
| Leave type | **Time Type** | Renamed in Odoo 20 |
| Leave balance, entitlement | **Allocation** | Per employee and time type |
| Earned monthly | **Accrual Plan** | Set on the allocation |
| Employment contract | The employee record, **Contract** dates, **Effective Date** | Odoo 20 has no separate contract document: wage, schedule and dates are dated versions of the employee record |
| Salary slip | **Payslip** | Payroll app, Enterprise |
| Product, service, item | **Product**, type **Goods** / **Service** / **Combo** | Goods can additionally be tracked in stock |
| Warehouse process step | **Route** and operation type | Receipts and deliveries in 1, 2 or 3 steps |
| Approval chain | **Purchase Order Approval** (setting) or the **Approvals** app | Check the rule and connecting modules; the app alone does not prove enforcement |
| Custom field without code | **Studio** | Enterprise |
| Reminder, task on a document | **Activity** | In the chatter |

## How to teach a topic ("teach me X")

Give one manageable lesson, not a reference page. Choose the useful parts below:

1. **What it is for**, in two sentences, from the business side.
2. **The story**: one concrete client, the documents in order, who clicks what, what Odoo
   creates. Real numbers and dates.
3. **The relevant decisions** the client must make in this area, with the options and what each
   changes (from the playbook if one exists).
4. **What surprises people** coming from other systems or from older Odoo versions.
5. **Try it**: a small exercise in a test database, with starting data and expected results.
6. **Odoo ideas to remember**: two or three terms from the vocabulary table, one line each.
7. **Where to go next**: the neighboring topic in the learning path below.

Keep each part short. If the topic is big (Accounting, Inventory), split it: "Today the
document chain; next time valuation." Verify material behavior and labels before the lesson. Ask an occasional practical
understanding question, then adapt the next explanation to the answer. Do not force a quiz
or repeat definitions the user already understands.

## Learning path for a new implementation consultant

Offer this as a possible path, adapted to the person’s current assignment. Start with a
useful end-to-end process; do not require a service implementer to study warehouses first.

| Step | Topic | Why now |
|---|---|---|
| 1 | Contacts, Products, Users and access, the Settings pages | Everything else uses these records |
| 2 | Sales chain: quotation to payment | The clearest example of the document life cycle |
| 3 | Purchase and Inventory chain, receipt steps, valuation basics | Mirrors sales; introduces stock and cost |
| 4 | Accounting: journals, entries, taxes, lock dates, closing | Where every flow ends |
| 5 | Employees, Time Off, working schedules | Introduces HR rules and scheduled jobs |
| 6 | Projects, timesheets, billing services | Connects sales to work delivered |
| 7 | CRM and Helpdesk | Front of the sales chain, and after-sales |
| 8 | Multi-company, Studio, automation rules | Only once the standard flows are clear |

## Explaining an Odoo term the first time

Pattern: **term** (plain explanation in 5-10 words). Examples:
- **journal entry** (the accounting record behind a document)
- **analytic account** (a cost center or project used for reporting)
- **work entry** (a day or hour of an employee's time, as payroll sees it)
- **route** (the path goods take through the warehouse)
- **fiscal position** (a rule that swaps taxes and accounts for a customer type)
- **scheduled job** (work Odoo runs automatically at a configured time)

Never write a paragraph a newcomer cannot read without asking what a word means.
