# TBC Bank Integration (`tbc_bank`)

Sends payments from Odoo to TBC Bank and brings TBC's account statements back into Odoo
for reconciliation, through TBC's Business Integration Services (BIS) API.

**Who this is for:** accountants who pay suppliers and salaries through TBC, the person who
approves transfers, and the administrator who sets up the connection. Developers: see
[README_DEV.md](README_DEV.md). The TBC API itself is described in [BIS_API.md](BIS_API.md).

## 1. What it does

| Feature | What you get |
|---|---|
| Send a payment to TBC | A confirmed outbound payment becomes a TBC transfer with one click, typed automatically from the recipient's IBAN |
| Send a batch | Every TBC payment of a batch payment goes out in one click |
| Approval in Odoo (optional) | A second person must approve each transfer before it can be sent; submitting a transfer checks it and notifies the approvers |
| Pay salaries through TBC | In **Pay Salaries** TBC is one of the banks: salaries, pension and income tax go out through TBC |
| Confirm from the statement | A transfer turns *Confirmed* when it appears on the imported TBC statement, and its statement line is matched with it, also when TBC's status confirmed it earlier |
| Import statements | TBC account movements become a bank statement; a line that is one of your sent transfers is reconciled with it at once |
| Balance snapshots | Opening and closing balance and turnover for a period, as TBC reports them |
| Safe recovery | A send whose answer was lost is looked up at TBC instead of being sent twice |
| Safeguards | A refused transfer cannot be sent again until it is corrected and reset; a confirmed transfer is never failed by a later status |

## 2. Quick facts

| | |
|---|---|
| Menu | **TBC Bank**: Transfers, Pending Approval, Connections, Import Statement, Statements, Fetch Statement, Approvers, API Logs |
| Buttons on payments | **Submit for TBC Approval**, **Approve TBC Transfer**, **Send to TBC**, **Reset to Pending**, **Refresh TBC Status**, **Recover from TBC**, **Confirm Manually** |
| Buttons on batch payments | **Submit for TBC Approval**, **Approve TBC Transfers**, **Send to TBC** |
| Button on bank journals | **Import TBC Statement** |
| On the payment | The **TBC Transfer** group of the payment form, and the optional **Bank State** column of the payment list (shared by the bank integrations) |
| Who can use it | **TBC Bank: User** sends, resets, recovers and confirms transfers (no one else can, also not over the API), sees **Submit for TBC Approval**, imports and reads the connection; an approver or delegate approves without a TBC group; **TBC Bank: Manager** also edits connections and approvers and reads the API logs. Paying salaries needs Payroll Administrator (see **Pay Salaries**), and sending the salary batch needs **TBC Bank: User** |
| Needs | Accounting and Batch Payments (installed with it); Payroll Bank Channels (gec_payroll_bank) for paying salaries |
| Works with | **Pay Salaries** of Payroll Bank Channels; the Georgian localization fills TBC's BIC from a Georgian IBAN |

## 3. How it works

```text
Payment (Accounting)  ──Confirm──►  Paid in Odoo
        │
        ├─ (Approve in Odoo first)  Submit ──► Approve
        ▼
   Send to TBC  ──►  TBC creates the transfer  ──►  Sent
        │                                            │
        │                         TBC status "Finished" or the statement line
        ▼                                            ▼
   no answer ──► Unknown ──Recover from TBC──►   Confirmed
```

You confirm the payment first, so Odoo has the journal entry before any money leaves. Odoo
then sends it to TBC and stores TBC's transfer ID. The transfer is *Confirmed* when TBC
reports it finished or when it appears on the TBC statement you import. The import also
reconciles that statement line with the payment, so the payment becomes *Reconciled* in Odoo
and the bill *Paid*. When the answer to a send is lost, **Recover from TBC** asks TBC: it finds
the transfer (the payment turns *Sent*, and *Confirmed* once TBC reports it finished) or learns
that TBC never received it (back to *Pending*, safe to send again).

## 4. Set it up (once)

1. **TBC Bank > Connections > New.** Pick the company, **Environment** (Test or Production),
   paste **Client ID** and **Client Secret**, choose a **Processing Mode** (table below). Click
   **Test Connection**: the message reads "Connection successful." and the state becomes
   *Active*. One connection per company; a branch without its own uses its nearest parent company's.
2. **Accounting > Configuration > Journals > New**, type Bank, with the company's TBC IBAN as
   the account number. With the Georgian localization the bank (BIC `TBCBGE22`) fills in from
   the IBAN; otherwise type it as the SWIFT code. The journal then becomes a TBC journal: it
   gets the payment method **TBC Bank Transfer** and the bank feed **TBC Bank**.
3. On that journal's **TBC Bank Transfer** line (Outgoing Payments tab) check **Outstanding
   Payments**: a new line gets Odoo's default Outstanding Payments account by itself. Without
   one Odoo posts no payment entry, so **Send to TBC** refuses the payment and names the line.
4. For **Approve in Odoo first**: **TBC Bank > Approvers > New**, pick the **Primary
   Approver** and optional **Delegates**, then set it as **Approver** on the connection.
   **Allow Self-Approval** on the connection (off by default) lets the person who created a
   transfer approve it too; leave it off whenever a second person can approve.
5. Scheduled jobs, in **Settings > Technical > Scheduled Actions**: **TBC Bank — Daily statement sync** and
   **TBC Bank — Transfer status poll** are on after a new install; a database that had the module before keeps its
   own setting, so check that they are on there. **TBC Bank — Live statement snapshots** is off: switch it on only
   if you read the snapshots under **TBC Bank > Statements**. The status poll asks TBC about at most 100 open transfers (Sent or
   Unknown, with a TBC reference) per run, the one written least recently first, so none waits
   forever; each answer is stored as **TBC Status (raw)** on the payment. Every scheduled
   action skips a company whose connection is *Draft* or *Blocked*; one in *Error* is tried
   again, and **Test Connection** makes it Active.

| Processing Mode | What happens after **Send to TBC** |
|---|---|
| Approve in Odoo first | Nothing can be sent until someone other than its creator approves it in Odoo (unless **Allow Self-Approval** is on). **Submit for TBC Approval** appears only in this mode |
| Direct (bank auto-confirms) | Sent at once; Odoo asks TBC for the status right away |
| Manual confirmation in Internet Banking | TBC receives the transfer, but someone must release it in TBC's Internet Bank before money moves |

## 5. Transfer types

Odoo picks the type from the recipient's bank account. Change it only for a treasury payment
or an unusual case.

| Recipient account | TBC Transfer Type | Also needed |
|---|---|---|
| A TBC account of your own company | To Own Account | — |
| Another TBC account | Within TBC (another TBC account) | — |
| Another Georgian bank, payment in GEL | To Other Bank (GEL / national) | optional Beneficiary Tax Code |
| Anything else | To Other Bank (Foreign / SWIFT) | Beneficiary Name, Address, Bank (BIC/Code), Charge Details SHA or OUR |
| None (State Treasury) | Treasury | GEL, a 9-digit Treasury Code; Taxpayer Code and Name when you pay for someone else |

## 6. Transfer states

```text
Pending ──Submit──► Awaiting Approval ──Approve──► Approved
   │                                                  │
   └──────────────────── Send to TBC ◄────────────────┘
                              │
                              ▼
                 Sending ──► Sent ──► Confirmed
                    │          │
                    ▼          ▼
                 Unknown     Failed ──Reset to Pending──► Pending
```

| State | Meaning | What you do |
|---|---|---|
| Sent | TBC has the transfer; the money may still be waiting for release | Wait for the status or the statement, or use **Confirm Manually** |
| Confirmed | TBC reported it finished, it was on the statement (the form then shows *Bank Statement*), or someone used **Confirm Manually** (*Manual*) | Nothing. A later "failed" status from TBC does not undo it: a note is posted on the payment, check it with TBC |
| Failed | TBC refused it; the payment is marked Rejected, its entry kept | Correct the payment: **Reset to Draft**, edit, **Confirm**, then **Reset to Pending** and **Send to TBC** (a transfer TBC had created and then failed is sent under a new request id). To drop it, reset the payment to draft and **Cancel** it |
| Unknown | Odoo got no clear answer (timeout, server error) | **Recover from TBC**. Never create a new payment for it, and do not confirm it by hand. TBC's "no record" counts only 15 minutes after the send: it may still be processing it |
| Sending, for a long time | The send stopped half-way (server restart) | After 15 minutes, **Recover from TBC** |

**Recover from TBC** works only on a transfer in *Sending* or *Unknown*. **Reset to Pending**
works only on a *Failed* one; the resend reuses the request ID, or gets a new one when TBC had
created the transfer. A *Failed* transfer is not sent again until it is reset, whether you send
it alone or in a batch.

While a transfer is Sending, Sent, Confirmed or Unknown, Odoo refuses to reset, cancel or
delete its payment or its journal entry: the money has left, or may leave, the bank. Odoo's
**Validate** button is hidden on TBC batches; use **Send to TBC**.

The **TBC Transfer** group of the payment form shows **Bank State**, **TBC Transfer Type**,
**Bank Reference** (TBC's transfer ID), **Bank Request ID** (the ID Odoo sends with every
attempt), **Approved By**, **Bank Error** and **TBC Status (raw)** (the status exactly as TBC
last returned it). Only the integration writes the state, reference, request ID, error,
approval and raw status; Odoo refuses to edit them by hand, in the form, in an import or over
the API. The TBC Transfer Type and the beneficiary fields are yours to edit.

## 7. Pay salaries through TBC

Salaries are paid from **Pay Salaries** (Payroll Bank Channels), where you choose a bank for
each employee and for each authority. Pick the TBC journal's **TBC Bank Transfer** there; the
full steps are in the Payroll Bank Channels guide, section *Paying a month, step by step*.

What TBC sends for one payslip, with a 1,000.00 GEL wage of a pension member:

| Line on the payslip | Amount | Sent through TBC as |
|---|---|---|
| Net salary to the employee | 784.00 | Within TBC or To Other Bank, from the employee's IBAN |
| Pension (employee 20.00 + company 20.00) | 40.00 | Into the Pension Agency's own TBC account, Within TBC |
| Income tax to the State Treasury | 196.00 | Treasury transfer with code 101001000 |

Before anything is created, Pay Salaries refuses a TBC row when the State Treasury's Treasury
Code is not 9 digits, when a recipient's account is not a Georgian IBAN, when the TBC journal
has no IBAN, or when the TBC connection is missing or blocked. The payslips then stay
confirmed and nothing is paid.

After **Pay Salaries** the payroll batches are ready; open each one and:
1. In **Approve in Odoo first** mode: **Submit for TBC Approval** (the approvers are notified),
   then the approver clicks **Approve TBC Transfers**.
2. **Send to TBC** and confirm. The message shows how many were sent, failed or are uncertain, and names
   every payment that was refused before sending, with the reason. A payment that is *Failed*
   is skipped: correct it and **Reset to Pending** on the payment first (section 6).

## 8. Statements

| Task | Where | Result |
|---|---|---|
| Import transactions | **TBC Bank > Import Statement**, or **Import TBC Statement** on the journal | One bank statement *TBC Bank &lt;from&gt; - &lt;to&gt;* with the new lines; lines already imported, and movements without a readable date, are skipped |
| Balance for a period | **TBC Bank > Fetch Statement** | A statement snapshot: opening and closing balance, total credit and debit as TBC reports them |
| Automatic | The daily sync re-imports the last 7 days; live snapshots, when switched on, refresh the month to date every 2 hours | |

The **Currency** of the import is the journal's currency and cannot be typed: the lines are
booked in it. Movements still waiting for authorization at TBC are not imported; the message
says how many and they come in with a later import. If TBC stops sending part-way through a
period (fewer movements than its own total), Odoo refuses the import and imports nothing:
import the period again later. A statement line that carries the transfer's TBC reference,
for the payment's amount, confirms the matching sent payment and is reconciled with it. The
snapshot from **Fetch Statement** is for reading only; Odoo does not compare it with the
imported statement.

## 9. When Odoo refuses

| Message starts with | Why | What to do |
|---|---|---|
| Confirm these payments before sending them | The payment is still a draft | **Confirm** it, then **Send to TBC** |
| These payments are already matched with the bank statement, rejected or cancelled | The payment is no longer *Paid*: its money already left, or it was refused | Do not send it; for a rejected one follow section 6, *Failed* |
| … has no Outstanding Payments account / … must allow reconciliation | The TBC Bank Transfer line of the journal | Fix the line (section 4, step 3) |
| These payments are at the bank, or may be | You tried to reset, cancel or delete a sent transfer | **Refresh TBC Status** or **Recover from TBC** first |
| This transfer must be approved in Odoo before sending | The connection is on **Approve in Odoo first** | Submit it and have it approved |
| … approved this transfer but may no longer approve | The approver was removed from the connection's approvers after approving; the approval is withdrawn and the transfer is back to *Pending* | Submit it for approval again |
| The TBC Bank connection does not require approval in Odoo | **Submit for TBC Approval** only exists in **Approve in Odoo first** mode | Send it directly |
| No pending TBC Bank transfer in this selection | Nothing selected can be submitted: only *Pending* transfers can | Check the state of the payments |
| You created this transfer, so you cannot approve it | Two people must be involved | Ask another approver, or turn on **Allow Self-Approval** on the connection |
| You are not authorized to approve TBC Bank transfers | You are not the connection's approver or delegate | Ask the approver |
| TBC transfer … cannot be sent | A required field is missing or the type does not fit the account (also checked when you submit for approval) | Follow the listed points |
| This transfer failed. Correct it, then use Reset to Pending | TBC refused the transfer and nobody has reset it | Section 6, *Failed* |
| Only a failed transfer can be reset to pending | **Reset to Pending** was used on another state | Use the button that fits the state (section 6) |
| This payment was already sent | Odoo's own "sent" mark is already set on the payment | Look at its Bank State; **Refresh TBC Status** if it is *Sent* |
| The outcome of the previous send is unknown | The last send got no clear answer | **Recover from TBC** first |
| Only a transfer whose send did not finish, or whose outcome is unknown, can be recovered | **Recover from TBC** works only from *Sending* or *Unknown* | Use **Refresh TBC Status** for a *Sent* transfer |
| This transfer may still be on its way to TBC | It started sending less than 15 minutes ago | Wait, then **Recover from TBC** |
| This transfer is already being sent, was already sent | Someone sent it already, a send is running, or its outcome is unknown | Reload the payment |
| These fields are set by the bank integration and cannot be changed directly | You edited the state, reference, request ID, error, approval or raw status | Leave them: only **Submit**, **Approve**, **Send**, **Reset to Pending**, **Refresh**, **Recover** and **Confirm Manually** change them |
| TBC sent … of the … movements | TBC stopped part-way through the period; nothing was imported | Import the period again later |
| The TBC Bank connection is blocked | TBC refused the integration user; nothing can be approved or sent until it is fixed | Fix the user in TBC's Business Internet Banking, then ask a TBC Bank manager to use **Test Connection** |
| No TBC Bank connection is configured | The company has no connection; approving and sending both need it | Create it (section 4) |
| A bank connection with API logs cannot be deleted | The logs are the audit trail of its transfers | Keep the connection |
| The 'From' date must be before the 'To' date | The import or fetch period is reversed | Swap the dates |

## 10. Rules to remember

- **Paid in Odoo is not money moved.** The payment is posted when you confirm it; the money
  moves when TBC executes the transfer (section 6).
- **Never pay an Unknown transfer again.** Use **Recover from TBC**: it asks TBC whether the
  transfer exists and only then allows a resend.
- **A changed payment needs a new approval.** Editing the amount, recipient, memo or bank
  details of a submitted or approved transfer puts it back to *Pending*; submit it again.
  An approval also lapses when its approver is no longer one by the time you send.
- **A Failed transfer is corrected, then reset.** **Reset to Pending** comes before the next
  send; nothing sends a *Failed* transfer on its own.
- **Confirmed stays confirmed.** A later "failed" status from TBC only leaves a note on the
  payment; only someone who checked with TBC should undo a confirmation.
- **The integration owns the transfer fields.** State, reference, request ID, error, approval
  and raw status are not edited by hand.
- **API logs keep every call.** Routine calls are removed after the **Log Retention (days)** of
  the connection (default 90; 0 keeps all); calls that moved money are never removed, and a
  connection that has logs cannot be deleted.

## 11. Common questions

**Why did a salary payment not confirm from the statement?** Only a statement line that
carries the transfer's TBC reference or its request ID confirms a payment. If it does not, use **Confirm
Manually** after checking the statement.

**Can I send the same batch twice?** No. Sent, Sending, Confirmed, Unknown and Failed payments
are skipped; only Pending and Approved ones go out. Reset a Failed payment to Pending first.

## 12. Known limitations

| Limitation | Workaround |
|---|---|
| Each payment is one request to TBC, so a large batch takes a while | Send it once and wait for the result message |
| TBC's test environment answers only its documented sample requests | Test with its sample accounts (TESTING.md) |
| Payroll through TBC only pays into Georgian IBANs | Pay foreign accounts another way |
