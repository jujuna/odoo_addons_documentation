# Bank of Georgia Integration (`bog_bank`)

Sends payment orders to **Bank of Georgia Business Online** and imports your account statements back for
reconciliation, using OAuth2 client credentials. Salaries are paid through it from Pay Salaries, where
Bank of Georgia is one of the banks to choose.

**Who this is for:** accountants and the administrator who sets the module up, and the approvers who
release transfers. Developers: [README_DEV.md](README_DEV.md).

## What it does

| Feature | What it gives you |
|---|---|
| Transfers to Bank of Georgia | Send domestic payments straight from a payment, alone or as a batch, in the currency of the journal's account. Foreign (SWIFT) transfers are refused until BOG's foreign document is built: pay them in Business Online or through TBC |
| Batch sending | One call sends a whole payroll or vendor run; 500 lines per batch |
| Maker-checker approval | A transfer is checked and submitted by one person and approved by another before it can be sent; the approvers are notified |
| Statement import | Pull a period's movements into Odoo and reconcile them like any bank statement |
| Automatic confirmation | A sent transfer is confirmed and matched the moment its debit appears on the statement; one the status check already confirmed is matched then too |
| Recovery | A send whose answer never arrived (timeout, crash) can be found at the bank without resending |
| Protection against double payment | A failed transfer is sent again only after a reset, a batch is not sent again while an earlier send is open, and the bank's answers and approvals cannot be typed over by hand |
| API log | Every call to the bank is kept, redacted, with the correlation ID the bank asks for |
| Live snapshots | The bank's daily summaries are saved for reporting (optional, by cron) |

## Quick facts

| | |
|---|---|
| Menus | **Bank of Georgia > Transfers, Pending Approval, Connections, Import Statement, Statements, Approvers, API Logs** |
| Buttons added | On a payment: **Submit for Approval, Approve, Send to BOG, Create Anyway, Upload Attachments, Reset to Pending, Refresh Status, Recover from BOG, Cancel at Bank, Confirm Manually**, plus a **Bank of Georgia** tab. On a batch: **Submit for Approval, Approve, Send to BOG, Send One by One, Refresh Batch Status, Cancel at Bank**. On the journal: **Import BOG Statement**. A button shows only when it can work: Send to BOG only on a confirmed payment, Refresh Status and Cancel at Bank only once the bank has given a document key |
| Who can use it | **Bank of Georgia / User**: sends, resets, recovers, cancels and confirms transfers, uploads attachments and imports statements (no one else can, also not over the API). Importing statements also needs Accounting rights beyond Billing (bank statements are read-only for Billing). Sending a payroll batch needs this group too. **Bank of Georgia / Manager** adds connections (Test Connection), approvers and API logs |
| Needs | Accounting, Batch Payments, and the **Bank of Georgia / User** group (Billing is implied by it) |
| Works with | Payroll Bank Channels (`gec_payroll_bank`) — pay salaries through BOG; `gec_localization` — fills the bank (BIC) from a Georgian IBAN; TBC Bank (`tbc_bank`) — the payment list has one optional **Bank State** column for both banks, and each bank's buttons act only on its own transfers |

## How it works

```text
Pending ──Submit──► Awaiting Approval ──Approve──► Approved
                                                      │
   ┌─── Send to BOG ──────────────────────────────────┘
   ▼
Sending ──bank answers──► Created at Bank (unsigned) ──status check──► Sent
                                                                        │
   Confirmed ◄─ status check, or the debit on the statement ────────────┘
```

A transfer is created as a normal payment, submitted for approval, approved by a second person, and sent.
Bank of Georgia creates a *document*: depending on how your API application is registered, the bank signs
it itself or someone signs it in Business Online. Only the status check (or the statement) moves the payment
past *Created at Bank*, so the money is never assumed to have moved before the bank proves it. When the
debit appears on the statement, the payment is reconciled and the bill becomes **Paid**.

Side paths: **Awaiting Confirmation** (the bank warned and did not create the document), **Failed** (the
bank refused or the document was cancelled) and **Unknown** (the answer never arrived).

## Set it up (once)

1. Register the application at <https://bonline.bog.ge/admin/api/> and note the **Client ID** and
   **Client Secret**.
2. Install the module.
3. Create a bank journal whose bank account has BIC `BAGAGE22`. In Odoo 20 the BIC lives on the bank
   account; with `gec_localization` it is filled automatically from a Georgian IBAN with code `BG`.
   The journal is then recognised as a Bank of Georgia journal by itself — **if the bank account's BIC
   is blank, nothing works**.
4. **Bank of Georgia > Connections > New**: pick the company, paste the credentials, press
   **Test Connection**. The state bar turns **Active**. A branch without its own connection uses its
   nearest parent company's.
5. Create the approver under **Bank of Georgia > Approvers**: a primary approver and optional delegates
   (the primary approver cannot also be a delegate).
6. Leave **Processing Mode** on **Approve in Odoo first** unless you have a specific reason not to.
   Pick the **Approver** (a connection in this mode refuses to save without one). **Allow Self-Approval**
   stays off unless your team has no second person: with it off, the creator of a transfer can never
   approve it.
7. The daily statement import and the two status polls are active after install (see below). On a
   database that already had the module, their old on/off setting stays: check
   **Settings > Technical > Scheduled Actions** once a connection is Active.

A connection that has API logs cannot be deleted, because the logs are the audit trail of its transfers:
set it to Draft or Blocked instead.

There is no sandbox: Bank of Georgia publishes one host, and every call from a configured connection
reaches production and moves real money. The connection form says so. Test with an amount of
**0.01 GEL** to an account you control.

## Sending a single transfer

1. Create the payment on the BOG journal (the **Bank of Georgia Transfer** payment method is offered
   automatically there).
2. On the **Bank of Georgia** tab: **BOG Transfer Type** (domestic or foreign), **Dispatch Type**
   (MT103 individual, or BULK up to 10,000.00 GEL a line), **Value Date**, and optionally
   **Is Salary**, **Verify Beneficiary ID** (only for accounts inside Bank of Georgia), the
   beneficiary's ID and bank code, and **Attachments** (an invoice or contract — some transfers are
   refused until one is attached).
3. In **Approve in Odoo first** mode (the only mode that shows **Submit for Approval**): press it. The
   payment is checked as the send will check it (it must be confirmed and still Paid, and the Bank of
   Georgia channel must be set up), and the approvers are notified and follow the payment. Then an
   approver clicks **Approve** (under **Bank of Georgia > Pending Approval** they see the Bank of Georgia
   transfers that wait for them). The creator cannot approve their own transfer unless the connection has
   **Allow Self-Approval** on.
4. **Send to BOG**. You see a confirmation pop-up first: *This sends a real payment order to Bank of
   Georgia. Continue?* If the approver was removed from the connection's approver list after approving,
   the approval is withdrawn at this point, the transfer goes back to **Pending**, and you submit it
   again.

The bank's own fields on the **Bank of Georgia** tab (state, bank reference, request ID, document
number, status, codes, approval) are filled in by the module. They cannot be edited by hand, by import or
by an API call.

| Payment state | What it means | What you can do |
|---|---|---|
| Pending | not yet submitted | Submit for Approval |
| Awaiting Approval | waiting for the approver | Approve (an approver) |
| Approved | approved, not sent | Send to BOG |
| Sending | on its way to the bank right now | wait; then Recover from BOG if it stalls (Reset to Pending only after 15 minutes) |
| Created at Bank (unsigned) | the document exists, nobody signed | Refresh Status, Cancel at Bank (both need the bank's document key; Confirm Manually only once it is signed) |
| Sent | signed at the bank, money moving | Refresh Status, Confirm Manually |
| Confirmed | the bank reported the money moved | nothing |
| Awaiting Confirmation | the bank warned and did **not** create it | fix the cause, then Create Anyway on the payment (Send and the batch buttons skip it) |
| Failed | the bank refused, or it was cancelled | the payment is Rejected, so only **Reset to Draft** shows. After checking Business Online: Reset to Draft, correct it, **Confirm**, **Reset to Pending** (the approval is cleared: submit and approve again; a document BOG had created and then rejected or cancelled is sent with a new request id and document number), then Send to BOG |
| Unknown | the module could not tell what happened | Recover from BOG before anything else; it cannot be confirmed by hand. Reset to Pending only after checking Business Online: BOG blocks a repeat of the same request for 7 days only |

**Recover from BOG** works only from **Sending** and **Unknown**. A payment already marked as sent (Odoo's
**Mark as Sent**) is not sent. A payment in **Sending**, **Created at Bank**, **Sent**, **Confirmed** or
**Unknown** cannot be reset to draft, cancelled or deleted, and neither can its journal entry: the bank
holds the money, or may hold it.

## Sending a batch

On a batch payment of BOG transfers (payroll creates these): **Submit for Approval**, then **Approve** —
the same maker-checker rule per transfer — then **Send to BOG** for one bulk call, or **Send One by One**
when you want each transfer to get its own bank key immediately. One batch holds at most 500 sendable
transfers and cannot mix domestic and foreign. Transfers that are **Failed** or **Confirmed** are left
out of a send; a failed one goes out again after **Reset to Pending** on its payment.

A batch is not sent again while any of its transfers is **Sending**, **Created at Bank**, **Sent** or
**Unknown**. Wait for the bank's status, recover the unknown ones, or send the failed transfers from
their own payment or in a new batch.

The batch state follows its transfers. **Send to BOG** and **Send One by One** show in states Draft,
Failed, Partially Failed and Unknown (a send still refuses while a transfer is unsettled); **Submit for
Approval** and **Approve** only while the batch itself is in Draft; **Cancel at Bank** only when the bank gave a batch key.
A batch without a batch key (sent one by one, or after a timeout) takes its state from its transfers:
**Refresh Batch Status** first asks the bank about each transfer, then sets the state.

A bulk send answers with only a batch key. Use **Refresh Batch Status** to see each line's document and
status; the **Bank of Georgia** group on the batch shows the batch key and the bank's raw status. Each
transfer remembers the package that carried it, so a rejection or cancellation of a package only reaches
the transfers of that package; a transfer sent later on its own is left alone. **Cancel at Bank**
deletes a batch that is created but not yet signed. The standard **Validate** button is hidden on BOG
batches on purpose: sending replaces it.

- A bulk send checks every transfer first: one refusal stops the whole send. If a transfer then cannot
  be claimed (for example another user is sending it at the same moment), the transfers claimed before
  it go back to their earlier state and nothing is sent.
- If the bank answers a bulk send with success but no batch key, every transfer of the batch becomes
  **Unknown**: recover each one.
- **Send One by One** sends each transfer alone. A transfer refused before sending counts as failed and
  is named in the notification with the reason; the others are sent. The batch then has no bank key and
  its state follows its transfers (all failed: Failed; some failed: Partially Failed; all created: Created
  at Bank); **Refresh Batch Status** updates them.

## Statements

- **By hand** (Bank of Georgia / User): **Bank of Georgia > Import Statement** (or **Import BOG Statement** on the journal).
  Pick the journal, set **From**/**To** and press **Import**. The **Currency** shown is the journal's and
  cannot be typed over. You see *"N new statement line(s) imported."*
- A period the bank stops sending part-way (fewer entries than its own total, or a first page without the
  id needed to read the rest) is refused and nothing is imported: import a shorter period, or the same
  period again later.
- Imported lines go through Odoo's normal statement flow: one statement per import, entries already
  imported before are skipped, and Odoo's matching runs at once.
- A line that is the debit of a sent BOG document confirms the payment and is reconciled with it, so the
  payment becomes **Reconciled** and the bill **Paid** — no manual work.
- **Bank of Georgia > Statements** holds the bank's period summaries (closing balance, in/out totals,
  entry count) when the snapshot crons run.

## Scheduled actions (active by default, except the snapshots)

| Name | Runs | What it does |
|---|---|---|
| Bank of Georgia — Daily statement sync | daily | imports the last 7 days for every usable connection's journals; lines already imported are skipped |
| Bank of Georgia — Live statement snapshots | every 2 hours | saves the month-to-date summary per journal (inactive) |
| Bank of Georgia — Document status poll | hourly | asks the bank about sent-but-unsettled documents |
| Bank of Georgia — Batch status poll | hourly | asks the bank about sent-but-unsettled batches |

They do nothing until a connection is Active. Without them the module still works; they keep Odoo's view
of the bank up to date (a signature, an execution, a statement) and run as OdooBot. Each status poll asks about at most 100 documents (or batches)
per run, the ones checked longest ago first, so a long list is worked through over several hours;
**Refresh Status** asks about one transfer at once. The scheduled actions use connections that are
**Active** or in **Error** (one failed login does not stop them) and skip Draft and Blocked ones.

## When Odoo refuses

| Message starts with | Why | What to do |
|---|---|---|
| No pending Bank of Georgia transfer in this selection. | Submit for Approval found nothing pending; Approve says "awaiting approval" instead | select the right payments |
| Confirm these payments before sending them... / These payments are already matched with the bank statement, rejected or cancelled... | the payment is still a draft, or is no longer Paid (sending would pay twice) | confirm the draft; do not send the others |
| This transfer must be approved in Odoo before sending. | the connection uses Approve in Odoo first | submit and approve it |
| ... approved this transfer but may no longer approve, so the approval was withdrawn. | the approver or delegate was removed after approving | submit it for approval again |
| The outcome of the previous send is unknown. Recover it from the bank first - resending could pay twice. | the last send never got an answer | Recover from BOG, or check Business Online |
| This transfer failed. Correct it, then use Reset to Pending before sending it again. | a Failed transfer is never sent as it is | check Business Online, correct it, Reset to Pending |
| This payment was already sent. / This transfer is already being sent, was already sent, or its outcome is unknown... | the payment is marked as sent (Mark as Sent), or another click or user claimed it first | reload the payment, read its state, check with the bank |
| You created this transfer, so you cannot approve it. | maker-checker separation | ask another approver, or turn on Allow Self-Approval |
| You are not authorized to approve Bank of Georgia transfers. | you are not the approver or a delegate | ask the approver |
| These fields are set by the bank integration and cannot be changed directly: ... | a state, reference, answer or approval was edited by hand, import or API call | use the buttons instead |
| Only a transfer whose send did not finish, or whose outcome is unknown, can be recovered... | Recover works only from Sending and Unknown | use Refresh Status instead |
| This transfer may still be on its way... (sending started less than 15 minutes ago) | a reset too soon after a send | wait 15 minutes, then Reset to Pending |
| Bank of Georgia flagged this as a duplicate. | code 363: the bank thinks it already has it | check Business Online first; Reset to Pending only if it really is new |
| Only a document that is created but not yet signed can be cancelled. | the document is already signed | it is too late; reconcile through the statement |
| These payments are at the bank, or may be, so their journal entry cannot be reset... | the bank holds the money or may hold it | refresh or recover it first |
| No Bank of Georgia connection is configured for company X. | missing connection for that company; approving and sending both need it | create it under Connections |
| The Bank of Georgia connection is blocked. Contact the bank. | the bank blocked the API client; nothing can be approved or sent until it is unblocked | contact the bank, then Test Connection |
| A bank connection with API logs cannot be deleted... | the logs are the audit trail of its transfers | set the connection to Draft or Blocked |
| A batch cannot mix domestic and foreign transfers. | BOG has separate bulk endpoints | split the batch |
| ... is a foreign transfer. Our Bank of Georgia connection does not build BOG's foreign document yet | foreign documents need charges, address and country fields the module does not have | pay it in Business Online or through TBC |
| ... is in USD, but the journal's account is in GEL. | BOG debits the journal's account in its own currency | pay from a journal in the payment's currency |
| This batch has N sendable transfers. Split it into batches of at most 500. | over the per-call cap | split the batch |
| An earlier send of this batch is not settled yet... | a member is Sending, Created at Bank, Sent or Unknown | wait for the status, recover, or send the failed ones from their payment or a new batch |
| Bank of Georgia sends no treasury transfers from Odoo. | a recipient has a Treasury Code | pay income tax through another bank |
| Bank of Georgia pays payroll only into Georgian IBANs. | a payroll recipient has no Georgian IBAN | pay them another way, or give them a Georgian account |
| Bank of Georgia needs the bank (BIC) of these recipients' accounts. | a Georgian account without its bank | enter the full IBAN, or set the BIC |
| Bank of Georgia sent ... entries of ... Nothing was imported... | the bank stopped sending the period part-way, or sent no id to read the rest | import the period again later, or a shorter period |
| Authentication failed: ... | wrong Client ID / Secret | fix the credentials, Test Connection |
| Bank of Georgia did not confirm this transfer (timeout/server error). | the send's answer never arrived | Recover from BOG before resending |

Bank refusals are explained with a sentence instead of a bare number where the module knows them —
for example *"Working balance is insufficient."* (333) or *"An invoice or contract must be attached to
this transfer."* (669). The raw result and reject codes stay visible on the **Bank of Georgia** tab.

## Rules to remember

- **Send twice = pay twice.** Every transfer gets a fixed request ID; the bank refuses a repeat for
  7 days, and the duplicate warning (363) can never be confirmed away. When in doubt, use
  **Recover from BOG**, not another send.
- **A warning is not a refusal.** Codes 333, 444, 701 mean "not created — create it anyway?". The
  payment waits in **Awaiting Confirmation**; you fix the cause and press **Create Anyway**. The
  duplicate warning 363 is the one exception: it goes straight to **Failed**.
- **Editing after approval revokes it.** Change the amount, recipient, purpose or any other detail the
  document is built from, and a transfer that is **Awaiting Approval**, **Approved** or **Awaiting
  Confirmation** goes back to **Pending** with a note; approve it again. A transfer cannot move to another
  bank or payment method while it is at the bank or **Unknown**; otherwise its earlier values are cleared
  and noted in the chatter.
- **A Failed transfer is never sent as it is.** Reset it to Pending first, after checking Business Online.
  A payment already marked as sent is not sent either.
- **Only the bank flows write the transfer data.** State, bank reference, request ID, answers and approval
  cannot be typed, imported or written by an API call.
- **Unknown is not Failed.** A timeout or server error parks the transfer in **Unknown** because the
  document may exist at the bank. Never resend blind; recover first.
- **Nothing below the Name Match Threshold (default 80%)** passes silently: a chatter warning tells you
  the beneficiary name only matches at that percentage, so check the recipient before signing.
- **No test environment.** The connection form warns that every call reaches production.
- **Attachments are uploaded at every send**, so the bank gets the files the payment has now: a swapped
  or removed file is picked up by itself. **Upload Attachments** only does the upload ahead of time.

## Common questions

**My journal banks at Bank of Georgia but the buttons do not appear.**
The journal's bank account must carry BIC `BAGAGE22` (starts with it). Fill the Georgian IBAN (code
`BG`) on the bank account, or set the BIC by hand.

**The batch is Unknown. Can I just send it again?**
No. Recover each transfer individually (Recover from BOG works from the payment). Resending blind can
pay twice.

**Why is my payment already marked Rejected in Odoo?**
The bank definitively refused it. Odoo marks the payment Rejected (the journal entry stays): press
**Reset to Draft**, correct it, **Confirm** it, use **Reset to Pending** on the transfer, then **Send to BOG**.

**Where do I find what the bank said about a fault?**
**Bank of Georgia > API Logs**. The **Correlation ID** on the row is the number
customerservice@bog.ge asks for. Money-moving rows are never cleaned up; routine rows age out after the
connection's Log Retention (default 90 days).

## Known limitations

- Today's activities (used by Recover) only covers the current day. A document sent on an earlier day
  that is still Unknown has to be checked in Business Online.
- The bank's summary has no opening balance, so imported statements carry none and Odoo cannot flag a
  missing entry between imports.
- BOG caps one bulk line at 10,000.00 GEL. Payroll sends larger amounts as MT103 automatically; a manual payment with Dispatch Type BULK above the cap is refused before it is sent.
- The rate limit is 5 requests/second, shared by all workers; a repeating "too many requests" usually
  means a daily quota, not a burst.

## Glossary

| Word | Meaning here |
|---|---|
| Document | what BOG creates from a transfer; it must be *signed* before money moves |
| Batch | one bulk call carrying up to 500 documents |
| Processing Mode | who approves: in Odoo first, directly, or manually in Internet Banking |
| Bank Request ID / Document No. | the two keys the module reserves per transfer for recovery at the bank |
| Recover | find a sent document at the bank by its Document No. and load its state |
| Name Match % | how closely the beneficiary name matches the account holder at BOG |
