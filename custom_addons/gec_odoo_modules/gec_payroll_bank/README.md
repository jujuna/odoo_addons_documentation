# Payroll Bank Channels (`gec_payroll_bank`)

Pays a validated payslip run through one or several banks, chosen per employee and per
authority, while the accounting stays Odoo's standard payment register.

**Who this is for:** payroll administrators, accountants, and whoever clicks **Pay Salaries**
each month. Developers and bank-integration authors: [README_DEV.md](README_DEV.md).

---

## What it does

| # | What it does | Why it matters |
|---|---|---|
| 1 | Lets you pick a **bank channel per employee** and **per authority** (pension agency, tax authority, benefit vendors) | Salaries and authority transfers can leave from different banks |
| 2 | Creates the payments through **Odoo's standard payment register**, posts and reconciles them, and marks the payslips **Paid** | Nothing custom touches the ledger |
| 3 | Puts the payments into **sealed payroll batches**, one per bank, purpose and currency | The batch is the envelope a bank module transmits; nobody can quietly add, remove or edit a payment afterwards |
| 4 | Remembers each employee's bank for next month | Less clicking |
| 5 | Runs a **watchdog** every 4 hours that flags batches nobody sent, or that the bank rejected | "Paid" in Odoo is not "money moved"; the watchdog catches the gap |

What it does **not** do: it never talks to a bank. Transmitting a batch is a separate step,
done by a bank module (`basis_bank`, `tbc_bank`, `bog_bank`), by a bank file, or by you in the
bank portal. This module does not know any bank by name.

---

## Quick facts

| Item | Value |
|---|---|
| Technical name | `gec_payroll_bank` |
| Odoo | 20 Enterprise |
| Requires | Payroll Accounting, Batch Payments, `gec_bank` (the channel framework), Georgian localization `gec_localization` |
| Works with | `basis_bank`, `tbc_bank`, `bog_bank` plug into this module; `geo_payroll` ships the account layout it expects |
| Access | **Payroll / Administrator**. Paying also needs accounting rights (**Invoicing** or higher), given separately |
| Setting | Payroll settings (Settings app > Payroll, or **Payroll > Configuration > Settings**), **Accounting** block, **Default Salary Bank** |
| Employee field | **Salary Bank** on the employee form (visible to Payroll Administrators only) |
| Buttons | Payslip form **Pay Salaries**; payslip list **Actions > Pay Salaries**; pay-run kanban card menu **Pay Salaries** and **Payment Batches** |
| Scheduled action | "Payroll: flag batches never confirmed by the bank", every 4 hours |
| License | LGPL-3 |

---

## How it works

```text
Validated payslips (net > 0)
│
▼  Pay Salaries
Pay Salaries wizard — one row per employee, one row per authority, bank on each row
│
▼  Create Payments
Standard payment register — payments posted and reconciled
├──► payslips marked Paid (paid date = payment date)
└──► payroll batches, one per bank + purpose + currency
        ├──► each batch is sent to its bank later (bank module, file, or portal)
        └──► watchdog every 4 h flags batches nobody sent or the bank rejected
```

Everything up to the batches happens in **one click and one database transaction**: if any
check fails, nothing is created, nothing is posted, and no bank is remembered. Everything
after the batches is a separate, later step.

### Paid is not money moved

When you click **Create Payments**, Odoo books the payments against the bank channel's
**Outstanding Payments** account. The payslips turn **Paid** and the salary payables are
settled — but the bank has received nothing yet. The money is proven only when the bank
statement clears the outstanding account. This is standard Odoo outstanding-payment
accounting, applied to payroll.

Example: Beth earns 1,000.00, keeps 784.00, pays 40.00 pension (20.00 employee + 20.00
company share) and 196.00 income tax.

| Payslip entry (posted) | Payment entries (Create Payments) | Bank statement (later) |
|---|---|---|
| Dr 720100 Salaries 1,000.00 | Dr 310310 Net Payable 784.00 | Dr 120410 Outstanding 1,020.00 |
| Cr 310310 Net Payable 784.00 | Cr 120410 Outstanding 784.00 | Cr 120110 Bank 1,020.00 |
| Cr 332010 Pension 40.00 | Dr 332010 Pension 40.00 | |
| Cr 331320 Income Tax 196.00 | Cr 120410 Outstanding 40.00 | |
| Dr 740900 Pension expense 20.00 | Dr 331320 Income Tax 196.00 | |
| | Cr 120410 Outstanding 196.00 | |

After **Create Payments** the payslip reads **Paid**, its payables are closed, and the
Outstanding Payments account holds 1,020.00 open. Only the statement proves the money moved.

Consequences:

- Never treat a **Paid** payslip as bank confirmation. Look at the batch and the bank statement.
- The channel's Outstanding Payments account must be a real interim account, not the bank
  account itself. The wizard refuses a channel configured otherwise.
- If a send fails or times out later, the bank module marks the batch and the watchdog raises
  an activity. Do not resend blindly.

---

## Set it up (once)

### A bank channel

A channel is nothing new: it is an **outbound payment method line** on a **bank journal**
(**Accounting > Configuration > Journals**, open the bank journal, **Outgoing Payments** tab).
The wizard reads it as-is. For every channel you will pay payroll from:

| Requirement | Why it is insisted on |
|---|---|
| Bank journal, outbound payment method | Salaries leave a bank |
| An **Outstanding Payments** account on the method line | Without it the payment would post no journal entry at all |
| That account allows **reconciliation** and is **not** a cash or credit-card type account | The statement must be able to clear it |
| That account is **not** the journal's own bank account | Otherwise payments would look bank-confirmed on creation |
| For a bank with an API (Basis, TBC, Bank of Georgia): the company IBAN on the journal | The bank identifies the paying account by it |
| Whatever the bank module itself needs (for example its connection) | Checked through the bank module's own checks |

All channel problems are reported together, before anything is created.

### Trusted recipient accounts

Every recipient (employee or authority) needs a bank account on their contact with **Allow
Out Payments** ticked on the bank account form. An untrusted account blocks the whole run.
This is the single most common first-run error.

A budget recipient is the exception: the State Treasury is paid by treasury code, not into a
bank account. Put the code in the **Treasury Code** field of its contact (Invoicing tab; the
field comes from `gec_localization`). `geo_payroll` ships the State Treasury contact with the
code 101001000 filled in, but as non-updateable data — on a database installed before that,
type the code once by hand.

### Defaults

- **Default Salary Bank** in Payroll settings: proposed for every employee row and every
  authority row. If empty, the wizard proposes the first channel it finds, preferring one a
  bank module can transmit or export.
- **Salary Bank** on each employee: overrides the default for that employee. The wizard can
  fill it for you (see "Remember these banks on the employees" in the step-by-step).

### Payroll accounting that fits

The NET salary rule must credit a **reconcilable payable account** and carry the employee as
partner (the *Employee Move Line* option on the rule). Authority liabilities (pension shares,
income tax, benefit vendors) must sit on reconcilable payable accounts with the right partner.
`geo_payroll` configures exactly this for a Georgian-chart company: NET on `310310`, pension
shares on `332010` with the Pension Agency partner, payroll income tax on the Payable `331320`
with the State Treasury partner (Tax Code art. 154 requires income tax to go with the
salaries), salary expense on `720100`, employer pension on `740900`. A benefit with a
**Vendor** books both its employee and company shares on the vendor's payable account, so the
vendor is paid here too.

The **Anonymize Journal Entries** setting (Payroll settings, **Accounting** block; the
refusal message calls it "Batch Payroll Move Lines") must stay **off**. With shared monthly
entries the salary lines carry no employee, and the wizard refuses to run.

---

## Paying a month, step by step

1. **Confirm** the payslips (state Validated). Draft payroll journal entries are fine: the
   wizard posts them. A slip whose net is zero or negative gets no employee row, but its
   income tax, pension and vendor legs are still paid; a negative-net slip stays Validated
   because the employee owes the difference.
2. Open the pay run's kanban card menu and click **Pay Salaries**. From a payslip form or a
   payslip list selection the same wizard opens for those payslips only.
3. Check the **Payment Date** and the **Default Bank** in the header. Rows already carry the
   employee's remembered bank or the default.
4. **Employees** tab: change a bank on a row if needed. Totals are shown in the list footer.
5. **Authorities** tab (only when the payslips carry authority amounts): one row per authority
   **and** account, with the default bank. Change it if the agency must be paid from another
   bank.
6. A yellow box lists liability accounts that **cannot** be paid from here (for example
   income tax still on `331310` on a payslip posted before `331320` existed). Those amounts
   stay open on the payslip entry and are settled elsewhere. Expense accounts, such as a
   deduction without a vendor, owe nobody and are never listed.
7. If any chosen bank is **manual** (Odoo only records the payment; you transfer in the
   portal), tick **Record only - I will transfer in the bank portal**. The wizard refuses to
   continue without it.
8. Leave **Remember these banks on the employees** ticked to store each row's bank on the
   employee.
9. Click **Create Payments** and confirm the dialog.
10. Result: the list of created **Payroll Payment Batches** opens, whatever the bank. Send
    each batch from there (bank module), export its file, or transfer manually.

Later, import the bank statement and reconcile the Outstanding Payments account as usual.

---

## Salary payments and authority payments

The wizard creates two kinds of payment on purpose.

| Kind | What it pays | Grouping | Bank chosen by |
|---|---|---|---|
| **Salary** | The NET line of a payslip, to the employee's work contact | One payment per payslip | The employee row |
| **Authority** | Any other open, partnered liability on the payslip entry (pension agency, State Treasury, benefit vendors) | Aggregated across payslips, but **one payment per authority per account** | The authority row |

### One payment per authority and account

| Account | Beth | Aka | Result |
|---|---:|---:|---|
| `332010` Pension, employee share | 20.00 | 15.00 | one payment of 70.00 to the agency |
| `332010` Pension, company share | 20.00 | 15.00 | (same payment) |

Both pension shares sit on one account, so the agency gets one payment. An Odoo payment
settles one account: if an accountant moves a share to a second account, the agency gets a
second payment — correct, not a duplicate.

### Which bank account of the agency is used

If the agency holds one bank account per Georgian bank, the payment goes to the agency's
account **at the bank you pay from** (no interbank transfer). Otherwise the first account by
sequence. An employee's payslip line always pays into the account named on the line itself.

---

## Worked examples

All examples: one company in GEL, everything validated, all recipients trusted.

**A. Two employees, one bank, pension shares.** Beth: NET 784.00, pension 20.00 + 20.00.
Aka: NET 588.00, pension 15.00 + 15.00. Everything routed to Bank A.

| Result | Count | Detail |
|---|---|---|
| Wizard rows | 2 employees (784.00, 588.00), 1 authority (Agency / `332010` 70.00) | Footer totals 1,372.00 and 70.00 |
| Payments | 3 | 784.00 Beth, 588.00 Aka, 70.00 agency |
| Batches | 2 | Bank A / Salary (2 payments, 1,372.00), Bank A / Authority (1 payment, 70.00) |
| Payslips | both **Paid**, paid date = the chosen payment date | |

**B. Same, but Aka's Salary Bank is Bank B and you route the authorities to Bank B.**
3 payments, **3 batches**: A/Salary (Beth), B/Salary (Aka), B/Authority (the agency payment).
Authority rows do not follow employee banks; change them by hand.

**C. One employee, a plain bank without any bank module.** The channel is *manual*: the
wizard demands the **Record only** tick. Result: 1 payment, 1 batch marked *Recorded Only*,
a chatter note "recorded this payroll batch for manual transfer", and the watchdog leaves it
alone. You transfer in the portal.

**D. One employee, Basis Bank channel.** No tick needed. Each payment gets the Basis transfer
type (internal or national, by recipient BIC); the batch is flagged as a salary package; the
batch list opens and you send the batch from its form (**Send to Basis Bank**, then your
digipass OTP). If nobody sends it within 48 hours, the batch creator gets an activity.

**D2. One employee, TBC or Bank of Georgia channel.** No tick needed. The payment gets the
bank's transfer type from the recipient's IBAN; send the batch with **Send to TBC** or **Send
to BOG**. A recipient IBAN that is not Georgian is refused before anything is created.

**E. Income tax and benefit vendors on the payslip.** The `331320` income tax line becomes a
State Treasury row. A Fitpass benefit (company 20.00, employee 80.00) becomes one Fitpass row
of 100.00 and one payment of 100.00. With Basis Bank or TBC the treasury payment is sent as a
treasury transfer using the contact's Treasury Code; Bank of Georgia sends no treasury
transfers, so route the State Treasury row to another bank. Vendors are paid like the agency,
into their account at the paying bank or by national transfer.

**F. Two people pay the same run at once.** The second one gets "These salary lines are being
paid right now by someone else" or "These payroll amounts changed while you were working".
Nothing is created twice.

---

## When Odoo refuses

Everything is all-or-nothing: one failure, nothing created, draft entries not posted,
remembered banks not saved.

| Message starts with | Why | What to do |
|---|---|---|
| "Only confirmed payslips can be paid" | A slip is not Validated | Confirm the slip |
| "Every selected payslip must have a draft or posted journal entry" | The slip has no entry, or it was cancelled | Recompute / validate the slip |
| "Select payslips from a single company" | The selection crosses companies | Pay per company |
| "Shared payroll journal entries are enabled" | **Anonymize Journal Entries** is on | Turn the setting off |
| "These employees have no work contact" | An employee contact is missing | Set the employee's work contact |
| "The work contact of these employees is a child of another contact" | A child contact would pay the parent's bank account | Set the employee bank account on the NET line |
| "The NET salary rule has no credit account" | The structure's NET rule is incomplete | Configure the salary structure |
| "These NET salary lines do not match the employee's current work contact" | Partner or account of the NET line is wrong | Recompute the entry or fix the account |
| "These open amounts are owed to somebody but cannot be routed by this flow" | An open, reconcilable, partnered liability this flow cannot carry | Give the rule a partner and a payable account, or settle it elsewhere |
| "Every employee and authority needs a bank." / "Choose a bank for:" | A row has no bank | Pick a bank on every row |
| "… has no Outstanding Payments account" / "must allow reconciliation" / "is a bank/cash account" / "is the journal's own account" | The channel is misconfigured | Fix the journal's outgoing payment method |
| "belongs to another company than the payslips" | The channel is from another company | Use the payslips' company channel |
| "must pay payroll in the company's currency" | Journal or lines are foreign-currency | Use a company-currency journal |
| "These recipients have no bank account" / "These bank accounts are not trusted for outgoing payments" | Recipient account missing or untrusted | Add the account, tick **Allow Out Payments** |
| "One of the chosen banks only records the payment in Odoo and transmits nothing" | A manual bank without the tick | Tick **Record only** |
| "These payroll amounts changed while you were working" / "Partially paid payroll lines are not supported" / "These salary lines were paid while you were working" | The payslips changed or were paid since the wizard opened | Reopen the wizard |
| "The payment register did not settle these payslips, so nothing was created" | A slip is not fully settled after the payments | Accounting configuration; ask the developer |
| "These authority amounts were not settled" | An authority liability stayed open | Accounting configuration; ask the developer |

---

## Payroll batches: the sealed envelope

A payroll batch shows a **Payroll** group on the batch form: **Payroll Purpose** (Salary /
Authority), **Payroll Channel**, **Pay Run**, and **Recorded Only** when applicable. The
batch list gains a **Payroll Purpose** column.

| You can | You cannot |
|---|---|
| Send it through the bank module, or export its file for a file bank | Add or remove payments |
| Read it, follow its chatter, complete activities | Change its journal, date, channel, purpose or pay run |
| Keep it as the record of what went to the bank | Delete it while it holds payments |

The standard batch **Validate** action stays available for file-based banks (it generates the
bank file). API banks (Basis, TBC, Bank of Georgia) use their own send screen instead.

**A salary the bank rejected** is paid again with Odoo's own steps: on the payment, **Reset
to Draft** and **Cancel** (the bank module allows it once the transfer is *Failed*); on the
payslip, **Mark Unpaid**; then **Pay Salaries** for that payslip. The rejected payment stays
in its batch as history.

---

## The watchdog

Every 4 hours the scheduled action looks at every payroll batch that was not acknowledged as
*Recorded Only*, asks the bank module where the batch stands, and reacts:

| Bank module says | Meaning | What the watchdog does |
|---|---|---|
| **prepared** | created, waiting for approval, or not sent yet (TBC and Bank of Georgia: **Pending**, **Awaiting Approval**, **Approved**; Bank of Georgia also **Awaiting Confirmation**) | After 48 hours from creation: a to-do activity for the batch creator + chatter note "still not been sent to the bank" |
| **pending** | a send is in progress, or the bank holds a document nobody signed yet (Basis Bank sending; Bank of Georgia **Created at Bank**) | Same 48-hour rule |
| **transmitted** | bank received it, final result pending | Recorded, no activity |
| **confirmed** | bank confirmed execution | Recorded, no activity |
| **partial** | some payments succeeded, others failed | **Immediate** activity: check with the bank before reversing or resending |
| **failed** | bank rejected the whole batch | Immediate activity |
| **uncertain** | Odoo cannot tell whether the bank got it (timeout), or a TBC or Bank of Georgia payment is still **Sending** or **Unknown** when the watchdog looks | Immediate activity: resynchronise first, never resend blindly |

One activity per state change; the same state is not reported twice. A batch that goes from
transmitted to failed later is flagged again. In short: `prepared → pending → transmitted →
confirmed`, with `failed`, `partial` and `uncertain` as immediate-activity side exits.

---

## Stock "Pay" button versus "Pay Salaries"

| | Stock payslip **Pay** | **Pay Salaries** (this module) |
|---|---|---|
| Bank | One journal for the whole run | Per employee and per authority |
| Authorities | Swept in with everything open | Separate authority payments, aggregated |
| Batches | None | Sealed payroll batches per bank and purpose |
| Bank module metadata (transfer type, salary package flag) | No | Yes, through hooks |
| Watchdog | No | Yes |
| Concurrency protection | Yes (this module adds it to both) | Yes |
| Paid date | Today | The payment date you chose |

The stock button is still there. Decide operationally whether your team uses only
**Pay Salaries** for API or file banks.

---

## What each module adds

| Module | Effect on you |
|---|---|
| `hr_payroll_account` | Provides the payslip entry and the Paid logic the wizard reuses. Its **Anonymize Journal Entries** setting must be off |
| `account_batch_payment` | Provides batches. File banks (SEPA and similar) register there and are classified as *file* channels automatically |
| `gec_bank` | Defines the channel itself: what counts as a channel, its configuration checks, the recipient-account rule, and the hook contract the bank modules implement. For TBC and Bank of Georgia it also holds the shared **Bank State** of each payment, from which the batch's handoff state is read |
| `gec_localization` | Fills the bank (BIC) from Georgian IBANs and adds the **Treasury Code** field on contacts |
| `basis_bank` | Turns a Basis journal into an *api* channel; adds its own checks (connection, GEL, BIC, memo); sets transfer type and the salary-package flag; reports batch state to the watchdog. You send with **Send to Basis Bank** and your digipass OTP |
| `tbc_bank` | Turns a TBC journal into an *api* channel; checks the connection, a 9-digit Treasury Code and Georgian IBANs; sends income tax as a treasury transfer; reports batch state to the watchdog. You send with **Send to TBC**, then **Approve TBC Transfers** |
| `bog_bank` | Turns a Bank of Georgia journal into an *api* channel; checks the connection and that recipients have a Georgian IBAN with a bank code; refuses State Treasury rows; reports batch state to the watchdog. You send with **Send to BOG** or **Send One by One** |
| `geo_payroll` | Not a dependency. It books NET on `310310` with the employee partner and pension on `332010` with the Pension Agency partner — exactly what this wizard needs — and ships the agency's bank accounts per Georgian bank so same-bank matching works |

---

## Rules to remember

- **Paid is not money moved.** The payslip turns Paid when the payment is created; the bank
  proves it later. Check batches and statements, not the payslip state.
- **A payroll batch is sealed.** Its payments, routing and date cannot be changed; delete it
  only after cancelling its payments (see the batch section).
- **The wizard refuses a channel whose Outstanding Payments account is wrong.** Cash-type
  accounts, non-reconcilable accounts and the journal's own account all block the run.
- **Authorities are aggregated, salaries are not.** One payment per authority and account
  across the whole run; one payment per payslip for employees.
- **The default bank fills only empty rows.** Change rows directly or use multi-edit.
- **Nothing is created unless everything checks.** One failed check rolls back postings,
  payments, paid state and remembered banks.

---

## Common questions

**The payslips are Paid but the bank shows nothing.**
Correct until the batch is sent and the statement imported. Open the pay run's **Payment
Batches** and check each batch. The watchdog flags a batch nobody sends within 48 hours.

**The pension agency has two payments in one batch. Duplicate?**
No. Two liability accounts, two payments — one per account.

**I changed the Default Bank in the header but the rows kept their banks.**
Rows are filled when the wizard opens; the header only fills rows that are still empty.
Change rows directly, or use the list's multi-edit.

**Why is there no Pay Salaries button on the pay run form?**
The run-level entry point is the kanban card menu (next to *Mark as Paid*). From the run
form, use the payslip list selection instead.

**Why does the agency's payment go to a different IBAN than the one at the top of its bank
list?**
The wizard prefers the agency's account at the bank you pay from. Sequence decides only when
there is no same-bank account.

**Can I pay in USD or pay a partial amount?**
No. Company currency only, full settlement only. Partial or foreign-currency payroll must be
designed explicitly.

**A pension account line blocks the run with "cannot be routed".**
The line is reconcilable but has no partner, or sits on an account type the payment register
does not accept for third parties. Give the salary rule a partner and a payable-type account,
or make the account non-reconcilable if it is settled elsewhere.

**Who receives the watchdog activity?**
The user who created the batch (the one who clicked Create Payments).

**Can I delete a wrong batch?**
Not while it contains payments: it is the record of what was sent to the bank. Cancel the
payments that should not go out (**Reset to Draft**, then **Cancel** — refused while a
payment is at the bank), mark their payslips unpaid, and pay them again with **Pay Salaries**.

**Does Remember these banks also remember the authority bank?**
No. Only employee rows are remembered; authority rows always start from the Default Bank.

---

## Known limitations

| Limitation | Note |
|---|---|
| Company currency only, single company per run | By design |
| Full settlement only; partially paid payroll lines are refused | By design |
| Only recipients with an ordinary bank account or a Treasury Code; partner-less or non-reconcilable liabilities are excluded | Taxes other than payroll income tax belong to their own flows |
| Authority routing is not remembered | No field exists for it |
| Header Default Bank does not re-route already filled rows | Use row edit or multi-edit |
| The watchdog scans every unacknowledged payroll batch on each run, without an age cut-off | Cost grows with history |
| The stock Pay button remains available without routing or batches | Team rule needed |

---

## Glossary

| Term | Meaning here |
|---|---|
| Channel | An outbound payment method line on a bank journal, used as "the bank we pay from" |
| Channel kind | `api` (a bank module transmits), `file` (Odoo generates a bank file), `manual` (you transfer in the portal) |
| Salary payment | Payment of a payslip's NET line to the employee |
| Authority payment | Payment of another partnered liability on the payslip entry (pension agency, treasury, vendors) |
| Payroll batch | A sealed group of payments for one channel, purpose and currency |
| Handoff state | The bank module's answer about a batch: prepared, pending, transmitted, confirmed, partial, failed, uncertain |
| Outstanding Payments account | Interim account between "payment created" and "seen on the bank statement" |
| Trusted account | A partner bank account with **Allow Out Payments** ticked |
