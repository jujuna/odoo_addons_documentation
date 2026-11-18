# Bank Channels (`gec_bank`)

The shared base of the Georgian bank integrations. It holds what every bank client
needs — crash-safe sends, the audit log, the approver, the connection settings, the
channel checks and, for TBC Bank and Bank of Georgia, the transfer state of a payment —
so Basis Bank, TBC Bank and Bank of Georgia follow the same rules.
Who this is for: the admin who sets up a bank connection and the accountants who send
payments and import bank statements. Developer guide: [README_DEV.md](README_DEV.md).

## What it does

| It gives you | What that means |
|---|---|
| Crash-safe sends | A payment sent to the bank cannot be sent twice, even if the browser is closed mid-send |
| An audit log per bank call | Every call to the bank is recorded with what was sent and what came back, with secrets hidden. A connection that has log rows cannot be deleted |
| One Bank State on a payment | A TBC or Bank of Georgia transfer shows the same states in the same words, in one **Bank State** column on the payment list |
| Fields only the bank writes | The bank state, the bank's references, the approval and the bank's answers are set by the bank integration, never by hand or by an import |
| Payment protection | A payment the bank already has cannot be reset, cancelled or deleted by accident, and cannot move to another bank |
| Approvers and delegates | One person approves transfers, plus named deputies, per bank. The person who created a transfer cannot approve it unless the connection allows it |
| Channel checks | A misconfigured bank channel is refused before money can leave through it; a bank journal gets its bank's API payment method automatically |
| Automatic log cleanup | Old log rows are removed nightly, but rows that moved money are kept forever |
| Statement confirmation | A bank statement line confirms a transfer only when the amount matches |

## Quick facts

- **Menus:** none of its own. Everything appears inside the bank modules
  (Basis Bank, TBC Bank, Bank of Georgia) and in Pay Salaries.
- **Added to existing screens:** the **Bank State** column on the payment lists
  (for example **Accounting > Vendors > Payments**). It is an optional column: tick it
  in the optional-columns menu at the right end of the list header.
- **What must be installed:** nothing. Installing a bank module installs this
  module automatically; it never brings payroll with it.
- **Who can use it:** everyone who can use the bank modules; the approver rules
  only concern the people you name as approver and delegates.

## How it works

```text
Create a payment          ──►  Channel checks refuse a bad setup
      │
      ▼
Send to the bank          ──►  The payment is claimed once, then the request id
      │                        survives even a crash
      ▼
Bank answers              ──►  Held: payment marked sent
      │                        Rejected: payment rejected, entry kept
      ▼
Bank statement arrives    ──►  A debit line for the right amount confirms it
```

Money moves one way: the payment is created and posted in Odoo first, the channel
checks confirm the setup, the send claims the payment before it talks to the bank,
and the bank statement is what finally confirms the money left.

## Set it up (once)

All of this happens on the bank's own connection screen (for example
**Basis Bank > Configuration > Connections**):

1. **Pick a Primary Approver.** This person (or a delegate) must approve
   transfers when the processing mode asks for it.
2. **Add Delegates** if you want deputies. The same person cannot be both the
   primary approver and a delegate.
3. **Leave Allow Self-Approval off.** Off, the user who created a transfer cannot
   approve it, so releasing money always takes two people. Turn it on only if your
   team has nobody else to approve.
4. **Choose a Processing Mode:**
   | Mode | What happens |
   |---|---|
   | Approve in Odoo first | The approver approves the transfer in Odoo before it goes to the bank (default) |
   | Manual confirmation in Internet Banking | The bank is approved from the bank's own internet banking |
   | Direct | The bank confirms on its own |
5. **Leave Log Retention (days) at 90** unless you want a longer or shorter
   audit trail. Set 0 to keep everything.
6. **Check the bank channel** on the bank journal: it must be outbound, on a bank
   journal, have an Outstanding Payments account, and — for an API channel — an
   IBAN on the journal. Saving a new channel fills the Outstanding Payments
   account automatically.

A bank journal saved with its bank's BIC gets that bank's API payment method line
by itself. The same check runs whenever the journal's bank account, IBAN, BIC or type
is edited.

Nothing else needs setup: there is no menu of this module to configure.

## The Bank State of a payment

A TBC or Bank of Georgia transfer carries one **Bank State**. Basis Bank keeps its own
state fields and states, described in its guide.

| Bank State | What it means |
|---|---|
| Pending | Created; nothing has been asked of the bank. Every transfer starts here |
| Awaiting Approval | Submitted for approval in Odoo; an approver must approve it |
| Approved | Approved and not sent yet |
| Sending | A send is in progress; the payment is already locked as at the bank |
| Sent | The bank holds the transfer; the payment shows as sent |
| Confirmed | The money left. **Confirmed By** says how: Bank Statement, Status Check or Manual |
| Failed | The bank refused it and no money moved; the payment becomes **Rejected** and is not sent again until it is reset to Pending |
| Unknown | The bank gave no answer or an unclear one, so it may hold the transfer. Recover it from the bank first |
| Awaiting Confirmation | Bank of Georgia only: the bank asked whether to create the document anyway; nothing was created |
| Created at Bank (unsigned) | Bank of Georgia only: the document exists at the bank but nobody signed it; no money moved |

On the payment list the badge is green for Confirmed, blue for Approved, red for Failed
and Unknown, and orange for the states in between; Pending has no colour.

### Fields only the bank integration sets

Bank State, Bank Reference (the bank's own id), Bank Request ID (the id Odoo sends with
every attempt so the bank can refuse a second one), Bank Error, Approved By, Approved On
and Confirmed By are read-only on the screen and are also refused on import and over the
API. The same goes for each bank's own answer fields, for example **TBC Status (raw)**.
Use the bank's buttons instead: they set these fields as part of their action.

### Changing a transfer after approval

If the amount, recipient or purpose of a transfer that is awaiting approval or approved
is edited, the approval is cancelled: the transfer goes back to **Pending**, a note is
posted on the payment, and it must be submitted for approval again. A transfer already at
the bank keeps its approval as the record of who released the money.

### Moving a payment to another bank

If a payment's journal or payment method is edited so that another bank (or no bank
transfer) carries it, that bank starts clean: the earlier transfer's state, reference,
request id, error and approval are cleared, and the old state, reference, request id and
approver are posted on the payment's chatter first. This is refused while the transfer is
at the bank.

## Payment protection ("at the bank")

A payment that the bank already holds, or may hold, is locked down in Odoo. For TBC and
Bank of Georgia that is **Sending**, **Sent**, **Confirmed**, **Unknown** and, for Bank of
Georgia, **Created at Bank (unsigned)**; Basis Bank applies the same rule to its own states.

- **Reset to Draft** and **Cancel** are refused on the payment itself.
- The same buttons are refused on the payment's journal entry.
- Deleting the payment is refused everywhere, including batch delete and imports.
- Moving the payment to another bank or payment method is refused.

This exists because the money may still leave the bank: without the journal
entry the bill would read unpaid and be paid again. To unlock a payment, check
with the bank first — refresh the payment, recover it or resync it — and only
then undo it.

## The audit log

Each bank connection has an **API Logs** button. One row appears per call to the
bank, showing the endpoint, HTTP status, request, response, error and how long
the call took. Passwords, tokens and other secrets are replaced by
`[REDACTED]` in both the request and the response.

Rows that moved money (transfers) are never deleted. Routine rows are removed
automatically after the retention days. A connection that has log rows cannot be
deleted, because the logs are the audit trail of its transfers: set the connection to
**Draft** or **Blocked** instead.

## Step by step: a transfer from start to finish

1. Create and post the payments (or run Pay Salaries). You see them as **Paid**.
2. Open the bank batch and press the bank module's send button.
   - If a payment is still Draft, the send refuses and asks you to confirm it first.
   - If a payment is already matched with a statement, rejected or cancelled, the
     send refuses, because it would pay twice.
   - For TBC and Bank of Georgia: if a payment is already marked as sent, or its Bank
     State is **Unknown** or **Failed**, the send refuses (see "When Odoo refuses").
   - For TBC and Bank of Georgia, where approval is required: the approver must still be
     an approver when the send runs; otherwise the approval is withdrawn and the transfer
     goes back to **Pending**.
3. The bank answers **Held**: the payment shows as **Sent**.
   The bank answers **Rejected**: the payment becomes **Rejected** and keeps its
   journal entry for the accountant.
4. The bank statement arrives. A debit line for the right amount confirms the
   transfer, and the bill is paid automatically.

If you double-click the send button, nothing bad happens: the second click finds
the payment already claimed and reuses the same request id.

### How a statement line confirms a transfer

For TBC and Bank of Georgia the statement import stores the bank's references on each
line. A line confirms a transfer when it is money out, for exactly the payment's amount
(in the payment's currency), and carries the payment's Bank Reference or Bank Request ID
(for Bank of Georgia, its Document No. as well). The payment becomes **Confirmed**
(**Confirmed By**: Bank Statement) and the line is reconciled with it, so the bill is
paid. A transfer already confirmed by a status check or by hand is matched too, until it
is matched with a line. A reference alone never confirms: a credit or a reversal can
carry the same reference.

## When Odoo refuses

| Message starts with | Why | What to do |
|---|---|---|
| These payments are at the bank, or may be, so their journal entry cannot be reset, cancelled or deleted... | The bank holds the payment, or a send got no answer yet | Check with the bank first: refresh, recover or resync |
| ...is at the bank, or may be, so it cannot move to another bank or payment method. | The payment was edited to another bank while the bank holds it | Check with the bank first, then undo the payment |
| Confirm these payments before sending them, so their journal entry exists... | A payment is still Draft | Post the payments, then send |
| These payments are already matched with the bank statement, rejected or cancelled... | The money already moved or was refused | Remove them from the batch or make new payments |
| These fields are set by the bank integration and cannot be changed directly... | A bank field was edited by hand, import or script | Use the bank's own buttons |
| A bank connection with API logs cannot be deleted... | The logs are the audit trail of its transfers | Keep the connection: it stays as the record of past transfers |
| Primary Approver cannot also be a delegate. Remove from the Delegates. | The same user is both | Remove the user from the Delegates list |
| You are not authorized to approve ... transfers. | You are not the Primary Approver or a delegate | Ask an approver |
| You created this transfer, so you cannot approve it... | The creator tried to approve | Ask another approver, or turn on **Allow Self-Approval** on the connection |
| ... approved this transfer but may no longer approve, so the approval was withdrawn... | The approver was removed after approving | Submit the transfer for approval again |
| The outcome of the previous send is unknown. Recover it from the bank first... | A send got no clear answer | Recover the transfer from the bank before sending again |
| This transfer failed. Correct it, then use Reset to Pending before sending it again. | The bank refused the transfer | Correct it, then **Reset to Pending** |
| This payment was already sent. | The payment is marked as sent | Do not send it again |
| This transfer is already being sent, was already sent, or its outcome is unknown... | Another click or user holds the transfer | Reload the payment and read its Bank State |
| This payment is being changed by another operation. Reload it and send again. | Another process holds the payment | Reload and send again |
| No ... connection is configured for company ... / The ... connection is blocked. Contact the bank. | The company has no usable connection for this bank | Create the connection, or ask the bank to unblock it |
| This payment is not an outbound ... transfer. | A bank's button was used on another bank's payment | Use the button of the payment's own bank |

## Rules to remember

- **Undo is refused at the bank, not after it.** The fence covers "the bank may
  hold it", including a send that never got an answer.
- **A send is claimed once.** A crash or a double click cannot send the same
  transfer twice.
- **A failed or unknown transfer is never sent again by itself.** Failed needs **Reset
  to Pending**; Unknown needs a recovery from the bank.
- **The statement, not the reference, confirms money.** A line must be money out
  for the right amount; a reference alone never counts.
- **Bank fields are not edited by hand.** Only the bank integration sets the state, the
  references and the approval.
- **The maker is not the checker.** The creator of a transfer cannot approve it unless
  the connection allows self-approval.
- **Delegates equal the primary.** There is no second approval tier.
- **The log keeps money-movement rows forever.** Only routine rows age out.

## Known limitations

- The only addition to existing screens is the optional **Bank State** column; every
  check and setting appears inside a bank module.
- The Outstanding Payments account is filled when a channel is created; a channel that
  exists without one needs it set by hand if it shows the configuration error.
- Bank name matching on accounts uses the BIC; Odoo 20 has no separate bank list.
- Basis Bank does not use the shared Bank State: its payments show Basis Bank's own state.

## Glossary

| Term | Meaning |
|---|---|
| Channel | A payment method line on a bank journal that payments are handed to |
| API channel | A channel whose bank is reached through an API; needs an IBAN on the journal |
| Bank State | The shared transfer state of a TBC or Bank of Georgia payment |
| Handoff state | Where a batch stands with the bank (prepared, pending, partial, transmitted, confirmed, failed, uncertain) |
| Outstanding Payments account | The transit account a payment posts to until the bank statement confirms it |
| Self-approval | The creator of a transfer approving it; off unless the connection allows it |
| Durable write | A write that survives even if the rest of the transaction fails |
