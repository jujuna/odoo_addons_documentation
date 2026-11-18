# Basis Bank Integration (`basis_bank`)

Sends outgoing payments from Odoo to Basis Bank with a Digipass one-time password (OTP),
imports the bank statement back, and keeps each payment open until the statement proves the
money left the account.

**Who this is for:** accountants, treasury and payroll staff who pay through Basis Bank, the
people who approve those payments, and the administrator who sets the module up.
Developers: read [README_DEV.md](README_DEV.md).

---

## 1. What it does

| Feature | What you get |
|---|---|
| Send from Odoo | Pay a vendor, the State Treasury, a foreign beneficiary or a salary run from the payment or batch form: **Send to Basis Bank**, then type the OTP |
| One OTP for many payments | A batch goes to the bank as one package or one multi-transfer request |
| Approval before sending | In *Approve in Odoo first* mode a named approver clicks **Approve** before anyone can send |
| Statement import | **Import Statement** brings the Basis account statement into the bank journal; a daily automatic import can be switched on |
| Proof before Reconciled | A sent payment stays *Paid* until the statement shows the debit; the import then matches that statement line with it and it becomes *Reconciled* |
| Safe recovery | A send with an unclear outcome is marked *Unknown*; **Resync from Bank** reads the bank report instead of sending again |
| 48-hour check | A sent payment that the bank report never shows is flagged for review after 48 hours, with an activity; its journal entry is not touched |
| Audit trail | Every call to the bank is logged, with passwords, OTPs and session tickets masked |

The module books nothing of its own. Standard Odoo posts the payment and creates the
statement lines; the module transmits the payment and records the bank's answer in its own
field, **Basis Bank State**.

---

## 2. Quick facts

| Item | Value |
|---|---|
| Menus | **Basis Bank > Operations**: Batches, Payments, Batches Awaiting Approval, Import Statement. **Basis Bank > Configuration** (managers only): Connections, Approvers & Delegates, API Logs |
| Added to payments | A **Basis Bank** section (transfer type, Basis Bank State, Bank Internal ID, bank errors) and the buttons **Submit for Approval**, **Approve**, **Send to Basis Bank**, **Resync from Bank**, **Reset to Pending**. In the payment list: action **Basis Bank: Reset to Pending** |
| Added to batch payments | A **Basis Bank** section (Basis Bank Endpoint, Basis Bank State) and the buttons **Submit for Approval**, **Approve**, **Send to Basis Bank**, **Resync from Bank**, **Reset to Pending** (on an *Unknown* or *Failed* batch). The standard **Validate** button is hidden on Basis batches |
| Added to bank journals | A **Basis Bank** section: Is Basis Bank Journal, Basis Bank Connection |
| Who can use it | **Basis Bank: User** and **Basis Bank: Manager**, see [Who can do what](#who-can-do-what) |
| Must be installed | Invoicing (Enterprise accounting), Batch Payment, Account Bank Statement Import, Georgia - Accounting Extensions (GEC), Bank Channels |
| Works with | Payroll Bank Channels: **Pay Salaries** prepares the salary batches that this module sends ([12.3](#123-pay-salaries)) |
| Bank | Basis Bank, BIC `CBASGE22`, internet-banking API at `bis.bankonline.ge` |
| Scheduled jobs | *Basis Bank — 48h report confirmation check* (hourly, on) and *Basis Bank — Daily statement sync* (daily, off until you switch it on) |

---

## 3. How it works

```text
┌─────────────────────────────────────────────┐
│ Payment on a Basis journal                  │
│ from a bill, Pay Salaries, or by hand       │
└──────────────────────┬──────────────────────┘
                       ▼
┌─────────────────────────────────────────────┐
│ Optional: several payments in one batch     │
│ Optional: Submit for Approval, then Approve │
└──────────────────────┬──────────────────────┘
                       ▼
┌─────────────────────────────────────────────┐
│ Send to Basis Bank + Digipass OTP           │
│ bank answers: Sent / Failed / Unknown       │
└──────────────────────┬──────────────────────┘
                       ▼
┌─────────────────────────────────────────────┐
│ Proof: Import Statement, Resync from Bank,  │
│ or the hourly 48-hour check                 │
└──────────────────────┬──────────────────────┘
                       ▼
┌─────────────────────────────────────────────┐
│ Confirmed by Statement; the imported line   │
│ is matched with it: payment Reconciled      │
└─────────────────────────────────────────────┘
```

Every outgoing payment on a Basis journal starts as *Pending*. You send it alone or in a
batch with the OTP, and the bank's reply sets *Sent to Bank*, *Failed* or *Unknown*. The
proof comes later and separately: when the statement, a Resync or the 48-hour check finds the
debit, the payment becomes *Confirmed by Statement*. A statement import also matches the
statement line with the payment, which makes it *Reconciled* in Odoo, as for any bank payment.

---

## 4. Set it up (once)

1. **Give people access.** In the user form, set **Basis Bank** to *User* for everyone who
   sends, imports or approves, and to *Manager* for those who configure. The administrator is
   a Manager after installation. Approvers and delegates must be internal users and need at
   least *User*: without it they see **Approve** but get an access error when they click it.
2. **Create the approver** (only for the *Approve in Odoo first* mode).
   **Basis Bank > Configuration > Approvers & Delegates**, **New**: a **Primary Approver**
   and, if needed, **Delegates** who may approve in the approver's place. The primary approver
   cannot also be a delegate.
3. **Create the connection.** **Basis Bank > Configuration > Connections**, **New**. One
   connection per company.

   | Field | Enter | Note |
   |---|---|---|
   | Company | The company that owns the Basis account | A branch without its own connection uses the nearest parent company's connection |
   | Login Name, Password | The internet-banking API credentials from the bank | Visible to managers only. Replace the bank's initial password with **Change Password** ([step by step](#126-change-the-bank-password)) |
   | API Host, API Version | `bis.bankonline.ge`, `v2` | Filled in by default; leave them |
   | Processing Mode | See the table below | *Approve in Odoo first* is the default |
   | Approver | The record from step 2 | Required in *Approve in Odoo first* mode, so the connection cannot be saved without it. Cleared when you switch to another mode |
   | Allow Self-Approval | Off (the default) | Shown in *Approve in Odoo first* mode. Off: the person who created a payment or batch cannot approve it, so two people are always involved. Turn it on only when nobody else can approve |

   | Processing Mode | What happens after you click Send |
   |---|---|
   | Approve in Odoo first | Nobody can send until an approver has clicked **Approve**; the bank then executes the transfer |
   | Direct (bank auto-confirms) | You send straight from a *Pending* payment or a *Draft* batch; the bank executes at once |
   | Manual confirmation in Internet Banking | You send with the OTP; the batch waits as *Awaiting Confirmation in Internet Banking* until someone confirms it in the bank's portal |

   Click **Test Connection**. "Connection successful." and state *Active* mean the credentials
   work. *Error* means the bank refused the username or password: the hourly check stops logging
   in until **Test Connection** succeeds, because repeated wrong logins make the bank block the
   client. Any other failed login (service suspended, technical error) keeps the state and shows
   under **Last Error**. *Blocked* means the bank blocked the client, and Odoo refuses every
   send. A connection that already has API logs cannot be deleted.
4. **Set up the bank journal.** In **Accounting > Configuration > Accounting > Journals**,
   open the Basis bank journal and enter the account's **IBAN**. A Georgian IBAN with bank
   code `BS` fills in Bank Name *BasisBank* and BIC `CBASGE22` by itself. Once its company
   (or a parent company) has a connection, the journal's **Basis Bank** section shows
   **Is Basis Bank Journal** ticked. Without the IBAN nothing can be sent or imported.
5. **Check the outgoing payment method.** Journal, tab **Outgoing Payments**: the line
   **Basis Bank Transfer** is added by itself when the journal's bank account has the Basis
   BIC, and needs **Outstanding Payments accounts** = `120410 Outstanding Payments` (filled in
   by itself on a new line). Every method you send with needs an Outstanding Payments account
   that allows reconciliation and is neither a bank or cash account nor the journal's own
   account; otherwise the send refuses and names the method. The *Manual* line has no such
   account by default: fill it in or use Basis Bank Transfer.
6. **Trust the recipients' bank accounts.** On each vendor's or employee's bank account, turn
   on **Trust bank account** (the list column is **Send Money**). Only users with the
   *Validate bank account* right can do this. An untrusted account blocks the send, and it is
   the usual first blocker. Treasury payments have no recipient account: you type the
   **Treasury Code** on the payment, and Pay Salaries takes it from the **Treasury Code** on
   the State Treasury contact.
7. **Optional: switch on the daily import.** In developer mode, **Settings > Technical >
   Automation > Scheduled Actions**, open *Basis Bank — Daily statement sync* and tick
   **Active**. It imports yesterday and today for every Basis journal with an IBAN, once a
   day.

Create the connection before the journal has payments: at that moment every outgoing payment
already on the journal becomes *Pending* and shows **Send to Basis Bank**, including old
payments that were paid another way.

### Who can do what

| Access | Can |
|---|---|
| Basis Bank: User (also gives Invoicing access) | The **Operations** menu: send, import statements, Resync, Reset to Pending; approve when named as approver or delegate. Sending needs the right to edit the payment or batch: a user who can only read them gets an access error. A User cannot use **Test Connection**, **Re-authenticate** or **Logout** on a connection. Users outside this group do not see **Send to Basis Bank**, **Resync from Bank** or **Reset to Pending**, and Odoo refuses those actions to them |
| Basis Bank: Manager (includes User, no extra accounting rights) | Also the **Configuration** menu: connections (**Test Connection**, **Re-authenticate**, **Logout**, **Change Password**), approvers, API logs |
| Payroll Administrator | **Pay Salaries** on the pay run (module Payroll Bank Channels), which prepares the salary batches. No Basis Bank group is needed for it |

---

## 5. Basis Bank State: Paid in Odoo is not proof

Odoo's own status (*Draft*, *Paid*, *Reconciled*) is bookkeeping: *Paid* only means the entry
is posted. What the bank did is in **Basis Bank State**. Only **Confirmed by Statement** means
the bank report showed the debit. The state, the approval (who and when), the send date and
the bank's answers cannot be edited by hand or imported: only the buttons change them.

```text
Pending ──Submit──► Awaiting Approval ──Approve──► Awaiting OTP
   │                                                     │
   └────────────► Send to Basis Bank + OTP ◄─────────────┘
                              │
                              ▼
                           Sending ──► Sent to Bank ──► Confirmed by Statement
```

In *Direct* and *Manual confirmation* mode, *Pending* goes straight to the send. The side
paths:

| From | What happened | Becomes |
|---|---|---|
| Sending | The bank rejected the transfer (no funds, wrong account ...) | Failed |
| Sending | Wrong OTP or expired session: nothing reached the bank | Back to Pending or Awaiting OTP: send again with a new OTP |
| Sending | Timeout, no answer, or a reply Odoo could not read | Unknown |
| Awaiting Approval, Awaiting OTP | What the bank receives was edited: amount, currency, partner, recipient account, memo, payment reference, journal, transfer type, treasury or foreign details | Pending (approval voided) |
| Sending, Sent to Bank, Unknown | 48 hours passed and the bank report shows nothing | Not in Bank Report |
| Unknown | Resync or the 48-hour check finds it on the report | Confirmed by Statement |
| Not in Bank Report | Resync or a later statement import finds it | Confirmed by Statement |
| Not in Bank Report, Failed | **Reset to Pending** (the report is checked first) | Pending, or Confirmed if the bank has it |

| Basis Bank State | Meaning | Odoo status |
|---|---|---|
| Pending | Not sent yet | Draft, or Paid if you posted it |
| Awaiting Approval, Awaiting OTP | In the approval workflow | Draft or Paid |
| Sending | Request on its way, or cut off by a crash: it cannot be sent twice | Paid (opening the OTP dialog confirms a draft payment) |
| Sent to Bank | The bank accepted it; waiting for the statement | **Paid**, held there on purpose |
| **Confirmed by Statement** | Seen on the statement: the money moved | **Reconciled** once its statement line is matched (an import matches it at once); Paid after a Resync until then |
| Not in Bank Report | No trace 48 hours after sending; flagged for review | Paid: the entry is not touched |
| Failed | The bank rejected it; no money moved | **Rejected**: the entry is kept, for you to cancel it or to correct and resend it |
| Unknown | Outcome unclear. **Resync, never resend** | Paid |

A batch has its own **Basis Bank State**:

| Batch state | Meaning |
|---|---|
| Draft | Not sent; payments can be added or removed |
| Awaiting Approval, Awaiting OTP | In the approval workflow |
| Sending | Request on its way |
| Sent (Pending Confirmation) | The bank accepted it; waiting for the statement |
| Awaiting Confirmation in Internet Banking | Sent in *Manual confirmation* mode; confirm it in the bank's portal |
| Done | Every payment in it that the bank did not reject is *Confirmed by Statement* |
| Failed | The bank rejected the whole batch, or every payment in it |
| Unknown | Outcome unclear, or a payment was flagged by the 48-hour check. **Resync from Bank** |

---

## 6. Transfer types

Odoo fills in the **Basis Bank Transfer Type** of an outgoing payment from the recipient: a **Treasury Code** gives
*Treasury*; otherwise the bank of the **Recipient Bank Account** decides (Basis Bank: *Internal*; another Georgian bank
and GEL: *National*; any other bank or currency: *Foreign*). For *Foreign*, **Receiver Country** (code such as DE),
**Receiver City** and **Receiver Address** come from the contact. Check them; change any of them when needed. When
the recipient account has no valid bank code (BIC), pick the type yourself.

| Transfer type | Use it for | Needs |
|---|---|---|
| Internal (within Basis Bank) | A recipient who also banks at Basis | Trusted recipient account, memo |
| National (GEL to other GE bank) | A recipient at another Georgian bank | GEL; trusted recipient account with a BIC; memo |
| Foreign (SWIFT) | A recipient abroad | Trusted recipient account with a BIC; **Receiver Country**, **Receiver City**, **Receiver Address**, **Charges** (*Each side pays its bank (SHA)* by default); memo. **Purpose Code** and **Intermediate Bank BIC/Name** are optional |
| Treasury | Budget payments such as taxes | GEL; **Treasury Code**; no recipient account |

Every Basis payment needs a partner. The **Memo** (or **Payment Reference**) is sent to the
bank as the purpose of payment. The bank checks the recipient's name against the account: Odoo
sends the account holder name from the bank account, else the partner's company name.

---

## 7. Batches: which bank operation

Put payments in a batch to send them with one OTP: in **Basis Bank > Operations > Payments**
select them and use **Actions > Create batch payment**, or create one in **Basis Bank >
Operations > Batches**. Every payment must be outgoing, on the same Basis journal, and
*Pending*. Odoo picks the bank operation and shows it in **Basis Bank Endpoint**:

| Batch content | Basis Bank Endpoint | The bank decides |
|---|---|---|
| Salary batch from Pay Salaries, all GEL | Salary Package | For the whole batch at once |
| Only *Internal* transfers, all GEL | GEL Package | For the whole batch at once |
| Only *Treasury* transfers, all GEL | Treasury Package | For the whole batch at once |
| Anything else: mixed types, any *National* or *Foreign*, any non-GEL payment | Single Transfers Batch | Payment by payment: some can pass while others fail |

**Example.** A batch of three GEL payments: 1,500.00 and 800.00 *Internal*, 250.00
*National*. The National one makes it a **Single Transfers Batch**. The bank accepts
1,500.00 and 800.00 (each gets its own Bank Internal ID) and rejects 250.00 with "Wrong
receiver account": that payment becomes *Failed* and the batch *Sent (Pending Confirmation)*.
Without the National payment the same batch would be a **GEL Package**, and one bad
payment would fail all of them.

The batch **name** is sent to the bank as the package name, so it must be unique per journal
and bank operation.

---

## 8. Approval

Only in *Approve in Odoo first* mode.

1. **Submit for Approval** on a *Pending* payment or a *Draft* batch. On a payment the send
   checks already run here, so a missing BIC or an untrusted account is reported now; on a
   batch they run at send time. The approver and delegates are added as followers and
   notified.
2. The approver or a delegate clicks **Approve**. The person who created the payment or batch
   cannot approve it unless **Allow Self-Approval** is on for the connection
   ([setup step 3](#4-set-it-up-once)). Odoo records who approved and when, and the state
   becomes *Awaiting OTP*.
3. Anyone with Basis Bank access clicks **Send to Basis Bank** and types the OTP. Odoo checks
   again that the person who approved is still the approver or a delegate.

Editing what the bank receives voids the approval of an approved payment: the amount,
currency, partner, recipient bank account, memo, payment reference, journal, transfer type, or
the treasury code or foreign details. The payment goes back to *Pending*, its batch back to
*Draft*, and the chatter says why. Adding a payment to an approved batch or removing one from
it voids the batch's approval, also when it is done from the payment. Only the batch name does
not void it, so leave it alone after approval.

**Batches Awaiting Approval** lists every Basis batch awaiting approval, not only yours, and no
single payments; the **Approve** button itself is still checked against the approver list and
the creator rule.

---

## 9. Statement import

**Basis Bank > Operations > Import Statement** opens *Import Basis Bank Statement*: **Bank
Journal**, **Currency** (filled in from the journal; it cannot be changed), **From**, **To**.
Click **Import**. Odoo reads every page of the bank report, creates the statement lines and shows
"Imported … lines, skipped …, confirmed … payments."

- Importing the same days twice creates nothing new: each line carries the bank's
  transaction number. The daily import reads yesterday and today, so its *skipped* count is
  usually not zero.
- Lines without a bank transaction number, lines without a readable date, zero amounts, and
  lines where the journal's IBAN is on neither side are skipped and counted.
- Only outgoing lines confirm payments; an incoming line never confirms anything. Incoming
  lines wait in the bank reconciliation like any other statement line.
- *confirmed* counts the outgoing payments this import confirmed, whether they were
  *Sending*, *Sent to Bank*, *Unknown* or *Not in Bank Report* before it.
- The statement line of each confirmed payment is matched with that payment, the way Odoo's
  own end-to-end matching does: the payment becomes *Reconciled*, its batch *Reconciled* once
  every payment is, the bill *Paid*, and `120410 Outstanding Payments` is back to zero. A
  payment that Resync or the 48-hour check already confirmed is matched the same way when
  its line arrives. Other lines are matched by Odoo's usual rules or by you in the bank
  reconciliation.

**Example.** The daily import reads 12 items for yesterday and today. 5 were imported
yesterday and 1 has no transaction number: "Imported 6 lines, skipped 6, confirmed 2
payments" when two of the six are outgoing transfers Odoo had sent.

---

## 10. The 48-hour check

Every hour, Odoo looks at payments that are *Sending*, *Sent to Bank* or *Unknown* and were
sent more than 48 hours ago. It reads the bank report once per journal and currency:

| The report | Odoo does |
|---|---|
| Shows the payment | *Confirmed by Statement*; the payment becomes *Reconciled* when its statement line is imported |
| Does not show it | Sets *Not in Bank Report*, writes in the chatter and gives the person who created the payment an activity *Basis Bank transfer not confirmed*. The journal entry and its match with the bill or payslip stay as they are. The batch becomes *Unknown* |

**Example.** A payment is sent on Monday 9 March at 10:00. From Wednesday 11 March at 10:00
the next hourly run reads the report from 7 March to 12 March (two days before the send date
to the day after today). If the debit is not there, the payment is flagged; the bill keeps
showing *In payment*.

A missing report line proves nothing: the bank may still book the transfer. Check with the
bank before you resend: **Resync from Bank** first
([step by step](#125-after-failed-or-not-in-bank-report-resend-safely)).

---

## 11. What the accountant sees in the books

| Moment | Entry | Booked by |
|---|---|---|
| Register Payment | Nothing yet (Draft), or the payment entry if you confirm it | Standard Odoo |
| Send to Basis Bank (the OTP dialog opens) | The payment entry, if it was still a draft: Dr Payable (`310110` for a vendor) / Cr `120410 Outstanding Payments` | Standard posting, started when the OTP dialog opens |
| Import Statement | Statement lines on the Basis journal | Standard statement import |
| Confirmation by Resync or the 48-hour check | No entry; Basis Bank State becomes *Confirmed by Statement* | This module |
| Import Statement | The line of a confirmed payment is matched with it: Dr `120410 Outstanding Payments` / Cr the journal's bank account; the payment becomes *Reconciled* | This module, through Odoo's own matching; other lines automatically when the memo matches, otherwise you |

**Example.** A vendor bill of 1,340.00 GEL paid through Basis: at the send, Dr 310110
1,340.00 / Cr 120410 1,340.00. When the statement line is matched, Dr 120410 1,340.00 / Cr bank
1,340.00, and 120410 is back to zero.

---

## 12. Step by step

### 12.1 Pay a vendor bill

1. On the posted bill, **Pay** (Register Payment) with the Basis journal and the method
   **Basis Bank Transfer**. The **Recipient Bank Account** field is shown.
2. On the payment, check the **Basis Bank Transfer Type** Odoo filled in ([section 6](#6-transfer-types)) and
   the **Memo**.
3. Approval mode: **Submit for Approval**, the approver clicks **Approve**.
4. **Send to Basis Bank**, type the code in **Digipass OTP**, **Send**. You see "Payment sent to
   Basis Bank." and *Sent to Bank* with the bank's reference in **Bank Internal ID**. Odoo
   status: *Paid*.
5. Later, **Import Statement** for the journal and the days. The payment becomes *Confirmed by
   Statement* and *Reconciled*.

### 12.2 Send a batch

1. Create the batch ([section 7](#7-batches-which-bank-operation)) and check **Basis Bank
   Endpoint**.
2. Approval mode: **Submit for Approval**, then **Approve**.
3. **Send to Basis Bank**, type the OTP, **Send**. You see "Batch sent to Basis Bank." and the
   batch is *Sent (Pending Confirmation)* (or *Awaiting Confirmation in Internet Banking* in manual mode).
4. After the import has confirmed every payment, the batch is *Done*.

### 12.3 Pay salaries

1. A Payroll Administrator clicks **Pay Salaries** on the pay run. It creates the payments
   and puts them in a salary batch (net pay) and, where needed, an authority batch (pension
   agency, income tax to the State Treasury, benefit vendors). It refuses when a recipient's
   account has no BIC or a payment is not in GEL. It does not send.
2. Each payment gets its transfer type by itself: *Treasury* for a recipient with a Treasury
   Code, *Internal* for an account at Basis, *National* for other banks.
3. Open the batch in **Basis Bank > Operations > Batches** and continue with
   [12.2](#122-send-a-batch). The salary batch goes as a **Salary Package**; an
   authority batch follows the table in [section 7](#7-batches-which-bank-operation).

### 12.4 After Unknown: Resync

1. Do not send again: the bank may already have executed the transfer.
2. On the payment or batch, click **Resync from Bank**. On a batch, check the dates in
   *Resync from Basis Bank* (two days around the send date by default) and click **Run
   Resync**.
3. Found: *Confirmed by Statement*. Not found: the payment says "Not found on the statement
   yet. The transfer may still be pending."; the batch lists the unmatched payments. Resync
   never resets or resends anything; the 48-hour check takes over later.

### 12.5 After Failed or Not in Bank Report: resend safely

1. Fix the cause (the error is in **Last Bank Error** on the payment, or in the chatter).
2. If the payment is *Rejected* or *Canceled*, click **Reset to Draft** first and correct it.
   To give it up instead, Reset to Draft and **Cancel**.
3. **Reset to Pending**: the button on a *Failed* or *Not in Bank Report* payment (confirm the
   warning), or the list action **Basis Bank: Reset to Pending**. Odoo reads the bank report
   first: if the transfer did execute, the payment is confirmed instead, with "do NOT resend
   them".
4. The payment is *Pending* again. If it sits in a Basis batch, remove it from that batch
   (tab **Batch Content**) and send it alone or in a new batch. Or reset the whole batch:
   on a batch in *Unknown* or *Failed*, **Reset to Pending** resets its *Failed* and *Not in
   Bank Report* payments (the bank report is checked first), keeps the ones the bank
   confirmed, and returns the batch to *Draft* to be approved and sent again for the pending
   payments only. It refuses while a payment is still *Sending*, *Sent to Bank* or *Unknown*.

### 12.6 Change the bank password

**Basis Bank > Configuration > Connections**, open the connection, **Change Password**: type
**New Password**, **Confirm New Password** and the **Digipass OTP**, then **Change Password**.
Odoo uses the stored current password and saves the new one.

---

## 13. When the bank refuses or does not answer

| Situation | What Odoo does | What you do |
|---|---|---|
| Wrong OTP or expired session | Nothing reached the bank; the payments stay confirmed and go back to *Pending* or *Awaiting OTP* (a batch to *Awaiting OTP*) | Send again with a new OTP |
| Timeout, bank unreachable, bank technical error | State *Unknown* | **Resync from Bank**. Never resend |
| Odoo stopped (restart, crash, time limit) while the bank was answering | The payment stays *Sending*: it was claimed before the request, so it cannot be sent again | **Resync from Bank**; after 48 hours the check flags it if the report shows nothing |
| The bank rejected a payment | *Failed* with the bank's message; Odoo status *Rejected*, entry kept | Fix, then [12.5](#125-after-failed-or-not-in-bank-report-resend-safely), or Reset to Draft and Cancel |
| The bank rejected a whole package | Every payment of that send *Failed* and *Rejected*; payments confirmed in an earlier send stay *Confirmed*; batch *Failed* | Fix the cause, then 12.5 |
| The reply leaves out some payments of a batch | Reported ones *Sent to Bank*, missing ones *Unknown*, batch *Unknown*; the chatter lists the missing ones | Resync |
| Client blocked | Connection *Blocked*; every send refused | Call the bank, then **Test Connection** |
| Service suspended | Connection stays *Active* (**Last Error** shows it); the payments of that send become *Failed* | After the service is back: 12.5 |

| Bank code | Bank message | Result in Odoo |
|---:|---|---|
| 0 | Successful | Continues |
| 1 | Wrong username or password | The send stops before anything leaves Odoo; the hourly check sets the connection to *Error* |
| 2 | OTP code is wrong | Back to *Pending* or *Awaiting OTP* |
| 3 | Session ticket is invalid | On a send: back to *Pending* or *Awaiting OTP*. Report reads log in again and retry once by themselves |
| 4, 5 | Client is blocked | Connection *Blocked* |
| 6 | Service suspended | Payments *Failed*; connection stays *Active* |
| 7 | Insufficient funds | *Failed* |
| 8 | Wrong amount | *Failed* |
| 9 | Wrong receiver bank BIC | *Failed* |
| 10 | Wrong treasury code | *Failed* |
| 11 | Error in one of the batch transactions | Package: whole batch *Failed*; Single Transfers Batch: that payment *Failed* |
| 12 | No such account exists | *Failed* |
| 13 | Wrong receiver account | *Failed* |
| 999 | Bank technical issue (also timeouts) | *Unknown*: Resync |

---

## 14. When Odoo refuses

Messages that already say what to fix (a missing partner or transfer type, two passwords
that differ, a second connection for the same company) are not repeated here.

**Sending**

| The message starts with | Why | What to do |
|---|---|---|
| These receiver accounts are not trusted for outbound payments | **Trust bank account** is off | Turn it on ([setup step 6](#4-set-it-up-once)) |
| These payments have no receiver bank account | No **Recipient Bank Account** | Set it (not needed for Treasury) |
| These national/foreign payments have no receiver bank BIC | The recipient account has no BIC | Enter the full Georgian IBAN, which fills the BIC, or type the BIC |
| These payments need a description/purpose before sending | Empty **Memo** and **Payment Reference** | Fill the memo |
| National and Treasury transfers must be in GEL | Wrong currency for the type | Pay in GEL or use another type |
| … has no Outstanding Payments account / … must allow reconciliation / … is a bank/cash account / … is the journal's own account | The payment method setup | Fix the method line ([setup step 5](#4-set-it-up-once)) |
| … has no IBAN, so the bank cannot identify the sender | The journal has no IBAN | Enter it on the journal |
| Treasury payments require a Treasury Code / Foreign currency transfers require: | Fields of that type are empty | Fill them ([section 6](#6-transfer-types)) |
| This payment belongs to a Basis Bank batch | Sent from the payment form | Send the batch |
| These payments are not in a fresh 'Pending' state / These payments were already sent | Payments that may already be at the bank | Resync, or Reset to Pending first |
| This payment is in an unknown state / This batch is in an unknown state | Previous send unclear | [12.4](#124-after-unknown-resync) |
| This payment cannot be sent / This batch cannot be sent in its current state | Already sent, done, failed, or cut off while *Sending* | Check the state; see 12.4 and 12.5 |
| This payment is already being sent, was already sent, or its outcome is unknown | Another send claimed it first | Reload the payment; Resync if it stays *Sending* |
| These payments are already matched with the bank statement, rejected or cancelled | The payment is not *Paid* in Odoo | Reset to Draft and correct it, or leave it |
| This transfer must be approved in Odoo before it can be sent | Approval mode, not approved | Submit and approve |
| This transfer was not approved by an authorized approver | The approver was removed from the list after approving | Have a current approver approve again |
| A package with the same name already exists | Batch name used before on this journal and operation | Rename the batch |
| The Basis Bank connection is blocked. Contact the bank. | Connection *Blocked* | Call the bank, then **Test Connection** |
| No Basis Bank connection is configured for company | The company has no connection | Create it ([setup step 3](#4-set-it-up-once)) |
| Could not authenticate with Basis Bank: | Login failed | Check the connection, **Test Connection** |

**Approval, recovery and payroll**

| The message starts with | Why | What to do |
|---|---|---|
| You are not authorized to approve Basis Bank transfers | You are not the approver or a delegate | Ask the approver |
| You created this transfer, so you cannot approve it | The creator cannot approve, and the connection does not allow self-approval | Ask another approver, or turn on **Allow Self-Approval** on the connection |
| Only transfers awaiting approval can be approved | The payment or batch is not *Awaiting Approval* | Submit it for approval first |
| These fields are set by the bank integration and cannot be changed directly | A form, an import or an API call tried to write the state, the approval, the send date or a bank answer | Use the buttons: Submit for Approval, Approve, Send to Basis Bank, Resync from Bank, Reset to Pending |
| These payments are at the bank, or may be, so their journal entry cannot be reset, cancelled or deleted | The payment is *Sending*, *Sent to Bank*, *Unknown*, *Not in Bank Report* or *Confirmed*; refused on the payment and on its journal entry | Resync; use Reset to Pending for Not in Bank Report |
| Only payments flagged 'Not in Bank Report' or 'Failed' can be reset to pending | Other state | Resync instead |
| Reset the journal entry of … to draft before resetting it to pending | The payment is *Rejected* or *Canceled* | **Reset to Draft** first |
| Basis Bank needs the bank (BIC) of these recipients' accounts | Pay Salaries found accounts without a BIC | Enter the full Georgian IBANs on those employees' accounts |
| Basis payroll payments must be in GEL | A non-GEL salary payment | Pay salaries in GEL |

**Setup and import**

| The message starts with | Why | What to do |
|---|---|---|
| An approver is required when processing mode is 'Approve in Odoo first' | No approver on the connection | Create one ([setup step 2](#4-set-it-up-once)) or change the mode |
| Authentication failed: | **Test Connection** failed | Check Login Name and Password; see **Last Error** |
| This connection has no current password set | No stored password | Enter the current password on the connection first |
| A bank connection with API logs cannot be deleted | The logs are the audit trail of its transfers | Keep the connection; the message names the states Draft and Blocked, which the form does not offer |

---

## 15. Rules to remember

| Rule | Why |
|---|---|
| **After Unknown or a timeout: Resync, never resend** | The bank may have executed the transfer ([12.4](#124-after-unknown-resync)) |
| **Paid is not proof; Confirmed by Statement is** | Only the bank report shows that money moved ([section 5](#5-basis-bank-state-paid-in-odoo-is-not-proof)) |
| **Trust recipient accounts before the payment run** | Every send refuses untrusted accounts |
| **The OTP is the last step before a real transfer** | Approval mode adds a second person; Direct mode does not |
| **The creator cannot approve their own transfer** | Releasing money takes two people; **Allow Self-Approval** on the connection lifts this, so keep it off unless nobody else can approve |
| **Do not edit a payment's bank details after sending** | Cancel, delete and reset are blocked, but not every field is read-only |
| **Do not use Reject on a sent payment** | Odoo's Reject button only marks the payment; the module keeps *Sent to Bank*. Resetting or cancelling the payment or its journal entry is refused |
| **Keep the 48-hour check on** | Without it, unproven payments stay *Sent to Bank* forever; it only flags, it never changes the books |
| **Prefer journals in the payment's currency** | Matching converts amounts between currencies, but that path is little used |

---

## 16. Common questions

**The import says 0 confirmed, but I know the transfer went out.**
Check the dates, the currency, and that the payment was *Sent to Bank*: a *Pending* payment is
never confirmed by an import. Package payments are matched by the document number the bank
repeats on the statement; if the bank shows one combined line per package, they cannot be
confirmed automatically.

**Send to Basis Bank is not shown on my payment.**
The payment must be outgoing, on a Basis journal, *Draft* or *Paid* in Odoo, and *Pending*
(or *Awaiting OTP*). In approval mode you first see **Submit for Approval**. A payment in a
Basis batch is sent from the batch.

**How long does the bank session last?**
About nine minutes, and each call extends it. Odoo logs in again when needed; you never
manage the session.

---

## 17. Known limitations

| Limitation | What to do |
|---|---|
| Package payments get no bank reference per payment; confirmation depends on the bank repeating Odoo's document number on the statement | Test with one small real package before the first salary run |
| A send cut off by a crash stays *Sending* until the 48-hour check flags it, so it can be resent only after 48 hours | Resync from Bank meanwhile; it confirms the payment if the bank has it |
| The import writes no opening or closing balance, and skipped items are only counted | Compare the balance with Internet Banking |
| Bank code 6 (service suspended) marks payments *Failed* although nothing was sent | Reset to Pending after the service is back |
| The *Basis Bank* choice in the journal's bank feed options does nothing | Use Import Statement or the daily sync |

---

## 18. Glossary

| Term | Meaning here |
|---|---|
| OTP | The one-time code from the Digipass device; needed for every send and for a password change |
| Basis Bank State | The module's field with what the bank did, separate from Odoo's payment status |
| Bank Internal ID | The bank's reference for a transfer, stored on the payment; one payment per reference and company |
| Package | A bank operation that accepts or rejects the whole batch at once (Salary, GEL, Treasury) |
| Single Transfers Batch | A bank operation with a verdict per payment |
| Resync | Reading the bank report again to find out what happened to a send |
| Not in Bank Report | The report showed nothing 48 hours after sending; the payment is flagged for review, its entry untouched |
| Outstanding Payments | Account `120410`, which holds a payment between the send and the statement match |
