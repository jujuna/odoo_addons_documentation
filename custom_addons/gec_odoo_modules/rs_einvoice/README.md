# RS E-Invoice (`rs_einvoice`)

Files Odoo customer invoices on rs.ge, the Georgian Revenue Service portal, sends them to the
buyer and mirrors what the buyer does back onto the invoice. On the purchase side it turns the
supplier's rs.ge invoice into a vendor bill that is accepted or rejected from Odoo. The goal:
the books and the rs.ge register of VAT invoices tell the same story, and Odoo stops you
before an action that would make them disagree.

**Who this is for:** accountants who issue customer invoices and book supplier invoices, and
the administrator who sets up the rs.ge logins. Developers: [README_DEV.md](README_DEV.md).

---

## 1. What it does

| Feature | What you get |
|---|---|
| **Send customer invoices** | **Send to RS** creates the invoice on rs.ge with the same lines; **Send to buyer** hands it to the buyer for confirmation |
| **Follow the buyer** | **Check Status** reads rs.ge: a confirmation, a rejection, an accepted cancellation or correction changes the Odoo invoice accordingly |
| **Fix a confirmed invoice** | The Credit Note window offers three treatments: a corrected replacement invoice, a cancel-and-reissue, or an Odoo-only credit note |
| **Cancel on rs.ge** | **Cancel on RS** asks the buyer to accept the cancellation; when they do, the Odoo invoice is cancelled or reversed |
| **Vendor bills from rs.ge** | **Pull from rs.ge** or the **rs.ge Inbox** creates draft bills with the supplier's lines; **Accept on rs.ge** posts and confirms, **Reject on rs.ge** sends a reason |
| **Supplier corrections** | A supplier correction or cancellation is shown on the bill and imported with one button |
| **Advance invoices** | Down-payment invoices are filed as rs.ge advances and settled on the final invoice |
| **Deadlines** | A yellow banner 25 days after the invoice date, red at 30 (order 996, art. 54), until the invoice is sent to the buyer |
| **Safety** | Documents on rs.ge cannot be deleted, re-dated or re-addressed in Odoo; every rs.ge call is written to the **RS Logs** table on the tab |

## 2. Quick facts

| | |
|---|---|
| Menus | **Accounting > Vendors > rs.ge Inbox** |
| Added to existing screens | **RS E-Invoice** tab on customer invoices, credit notes, vendor bills and vendor credit notes, with the buttons above · **View RS Data** button in the invoice header · smart buttons **Credit Notes**, **Replaced By**, **Replaces** · **RS Treatment** in the Credit Note window · filter **rs.ge Replacement In Flight** on the invoice list · **Refresh e-Invoices Status** in the Actions menu (three-dot button next to the page title) of the customer invoice list · block **RS E-Invoice (SOAP)** in Accounting settings (a pointer only) |
| Who uses it | Anyone who edits invoices sees the tab; the inbox, the wizards and the logs need the **Invoicing** access right |
| Needs | Accounting; the `rs_base_methods` module, which stores the rs.ge login per user and per company; the Python package zeep on the server |
| Works with | Sales (down payments become advances), Purchase (imported lines link to the vendor's purchase order), `rs_base_methods` (waybill links on invoices) |

## 3. How it works

```text
SALES INVOICE
posted ──Send to RS──► Draft (0) ──Send to buyer──► Sent (Pending) (1)
                       edit or delete freely             │
                                            buyer confirms or rejects on rs.ge,
                                            seen in Odoo at Check Status
                                                         │
                     ┌───────────────────────────────────┴───────────┐
               Confirmed (2)                            rejected: back to Draft (0)
                     │                                  fix, Update on RS, Send to buyer
      ┌──────────────┴──────────────┐
 Cancel on RS               Credit Note window
      │                     "Replace RS invoice with a corrected invoice"
 Cancelled (Sent) (6)                │
 buyer confirms: (7)        corrected copy: Send to RS (4), Send to buyer (5)
 invoice cancelled          buyer accepts: Correction Confirmed (8)
 in Odoo                    original cancelled in Odoo

VENDOR BILL
supplier sends on rs.ge
      │
 Pull from rs.ge, or rs.ge Inbox ──► draft bill with the supplier's lines, Sent (Pending) (1)
      │
      ├── Accept on rs.ge ──► bill posted, Confirmed (2)
      └── Reject on rs.ge ──► reason sent to the supplier, bill cancelled
```

Everything happens on the **RS E-Invoice** tab. Until the buyer confirms, the same rs.ge
record is edited in place; after confirmation only a cancellation or a correction can change
it, and both need the buyer's acceptance. Odoo reads rs.ge only when you click **Check
Status** (or when the scheduled refresh is switched on, section 10), so that click is the
moment the automatic reactions happen.

## 4. Set it up (once)

1. **rs.ge login, per user and per company.** Switch to the company, open **Settings > Users
   & Companies > Users**, your user, tab **Revenue Service**: fill in the rs.ge username and
   password and click **Test SOAP (e-invoice)**. Odoo checks the login and stores the
   company's taxpayer id with it. Repeat in every company you work in: the login you enter
   in one company is not used in another.
2. **RS Responsible User.** In each company tick **RS Responsible User** on one user: the
   scheduled actions of that company run with that user's login. A company without one is
   skipped by the scheduled actions.
3. **Tax IDs.** The company's Tax ID and every customer's and supplier's Tax ID must be digits
   only. The company currency must be GEL.
4. **Purchase journal.** Each company needs one for the inbox and the buyer sync.
5. **Scheduled actions** (section 10). Only the deadline check is on after install. Switch on
   the others under **Settings > Technical > Scheduled Actions** once the logins are tested.

## 5. rs.ge statuses

The **RS Status** badge on the tab is the rs.ge status. It decides which buttons appear.

| Status | Meaning | What you can do |
|---|---|---|
| Draft (0) | Created on rs.ge, the buyer does not see it | Update on RS, Send to buyer, Delete on RS |
| Sent (Pending) (1) | Waiting for the buyer | Update on RS (until they confirm), Reset to Draft in Odoo to edit lines |
| Confirmed (2) | Buyer confirmed | Cancel on RS, Credit Note window |
| Corrected (Original) (3) | A correction of this invoice was accepted | Nothing: work on the correction |
| New Correction (4) | Correction created, not sent | Update on RS, Send to buyer, Delete on RS |
| Correction Sent (5) | Correction waiting for the buyer | Check Status |
| Cancelled (Sent) (6) | Cancellation waiting for the buyer | Check Status |
| Cancellation Confirmed (7) | Buyer accepted the cancellation | The Odoo document is cancelled or reversed |
| Correction Confirmed (8) | Buyer accepted the correction | The original is cancelled in Odoo |
| Deleted (-1) | Deleted on rs.ge | Nothing |

## 6. Customer invoices

### Sending

1. Confirm the invoice.
2. **RS E-Invoice** tab, **Send to RS**. Odoo checks the invoice first (section 12), creates the
   rs.ge record and pushes the lines. The tab shows the rs.ge ID and status Draft (0); every
   line gets an RS badge.
3. **Send to buyer**. Status becomes Sent (Pending) (1); **S/F Number** and **S/F Number (N)**
   fill in.
4. After the buyer acts on rs.ge, **Check Status**.

What rs.ge receives per line: the label, the unit, the quantity, the total with VAT and the VAT
amount. An invoice of 2 × 50.00 with 18% VAT becomes one rs.ge line: total 118.00, VAT 18.00.
The VAT treatment of a line comes from the **Tax Category Code** of its taxes (Accounting >
Configuration > Taxes): S is taxed and sends the VAT of the S taxes only, Z, G and K are
zero-rated (VAT 0), E and O (exempt, out of scope, small-business turnover) are VAT-free (-1). A
tax without a code (for example City Tax, a fixed amount) is not VAT: a line with only such a tax goes without VAT.
A percent tax without a code rs.ge knows (S, Z, G, K, E, O) is refused at send time, because its lines would
go without VAT: set S for VAT, or O if it is not VAT. Sending needs at least one sales tax with code S.
Foreign-currency invoices are sent in GEL at the invoice's own currency rate, the rate its journal entry uses.

### Changing an invoice that is on rs.ge

| rs.ge status | Change lines | Change date, customer or currency | Take it off rs.ge |
|---|---|---|---|
| Draft (0), New Correction (4) | Reset to Draft in Odoo, edit, confirm, **Update on RS** | **Delete on RS**, then edit and send again | **Delete on RS** |
| Sent (Pending) (1) | Reset to Draft, edit, confirm: the lines are pushed on confirmation | Not possible: Delete on RS is refused, the buyer already has it | **Cancel on RS** is not available; ask the buyer to reject, or wait |
| Confirmed (2), Correction Confirmed (8) | Credit Note window, section 7 | Credit Note window | **Cancel on RS** |

**RS Note** (a text printed on the rs.ge document) is sent with the header; it is dropped on
advance invoices. The **Advance Invoice** box is ticked by itself when every line is a down
payment.

### The buyer rejects

**Check Status** shows the red banner **Likely buyer rejection on rs.ge.** Reset to Draft, fix
the invoice, confirm, then **Send to buyer** again. The same rs.ge record is re-sent; no
correction is filed. The reason the buyer typed is on rs.ge only.

### Deadline

Order 996, art. 54 gives 30 days from the invoice date. From day 25 the tab shows **Deadline
approaching**, from day 30 **Overdue**, on posted customer invoices not yet sent to the buyer. Once an invoice is sent, the buyer need not confirm it for the deadline to be met.
The scheduled action **RS E-Invoice: Deadline Check (Art.54)** also writes one RS Logs line and
one chatter message per overdue invoice.

## 7. Fixing a confirmed invoice

Open the invoice, **Credit Note**, and pick the **RS Treatment**:

| RS Treatment | Button to click | What happens on rs.ge | What happens in Odoo |
|---|---|---|---|
| **Replace RS invoice with a corrected invoice** (pre-selected) | **Reverse and Create Invoice** | The copy is filed as a correction of the original, with the **Reason for RS correction** you picked; the buyer accepts once | A draft copy opens. Post it, **Send to RS**, **Send to buyer**. The original stays posted until the buyer accepts (status 8), then it is cancelled. No credit note |
| **Cancel old RS invoice and issue a new one** | **Reverse and Create Invoice** | A cancellation request is sent at once (status 6); the buyer confirms it (7), then confirms the new invoice | A draft copy opens, but it cannot be posted or sent until the original reaches status 7 |
| **Only correct Odoo, not rs.ge** | **Reverse** | Nothing | A credit note marked **Skip rs.ge** with the **Skip Reason** you picked |

Reasons for an rs.ge correction: **Full cancellation**, **Change tax treatment only (rare)**,
**Change price or amount**, **Goods Returned to Seller**. The reason is information for rs.ge;
it does not limit what you may edit on the copy.

Example: invoice of 2 × 50.00 + 18% = 118.00 is confirmed and the price drops to 40.00. Credit
Note, treatment *Replace RS invoice with a corrected invoice*, reason *Change price or amount*,
**Reverse and Create Invoice**; change the price on the copy to 40.00, confirm, **Send to RS**,
**Send to buyer**. rs.ge holds the correction at 94.40 (2 × 40.00 + 14.40 VAT). When the buyer
accepts, **Check Status** shows Correction Confirmed (8) on the copy and cancels the original.
Until then both invoices are posted: the yellow banner **Replacement in progress.** and the
list filter **rs.ge Replacement In Flight** find them at month-end.

If the buyer rejects the correction, the copy is reset to draft; fix it, confirm and send again.
A replacement that was cancelled instead leaves a link on the original: **Clear Cancelled
Replacement** removes it so a new attempt can start.

Skip reasons for an Odoo-only credit note: **Bad debt write-off**, **Netting / offset**,
**Down Payment internal offset**, **Warranty cash compensation**, **Inter-company mirror
entry**, **Commercial gesture / compensation**, **Replacement reversal**, **Other**. The
expense-type reasons (bad debt, warranty, commercial gesture, inter-company mirror) need lines
without taxes and on expense accounts; Odoo refuses to save them otherwise.

## 8. Cancelling a confirmed invoice

**Cancel on RS** sends the cancellation request (status 6) and creates a To-Do to wait for the
buyer. If rs.ge does not answer the request, Odoo shows an error and creates the To-Do **Check the rs.ge
cancellation**: click **Check Status**; if it shows Cancelled (Sent) the cancel went through, otherwise click **Cancel on RS** again (with
Cancel & Reissue the replacement draft is kept; rs.ge refusing the cancellation deletes it). When
the buyer confirms and you click **Check Status** (status 7):

| The invoice | What Odoo does |
|---|---|
| Belongs to the current VAT period, no payments | Cancelled |
| Belongs to an earlier month, or the period is locked | Reversed with a credit note dated today, so the declared period stays unchanged |
| Has payments or open credit notes applied | Stays posted with the red banner **rs.ge no longer counts this document, but Odoo could not cancel it.** and a To-Do. Unreconcile, then **Check Status** cancels it |
| Is already fully reversed by credit notes | Left as it is |

If the buyer refuses the cancellation, the status goes back to Confirmed (2), the invoice stays
live and a chatter message says so.

## 9. Vendor bills

### Getting a bill from rs.ge

Two ways:

- **One bill.** Create a vendor bill for the supplier, paste the rs.ge ID the supplier gave you
  into **RS Invoice ID** on the tab and click **Pull from rs.ge**.
- **Many bills.** **Accounting > Vendors > rs.ge Inbox**: set the dates, **Search rs.ge**, tick
  the rows, **Import Selected**. Rows are matched to vendors by Tax ID; a row whose Tax ID is
  unknown or shared by several vendors is listed with a note and skipped.

Pull checks on rs.ge that the seller is this bill's vendor and the buyer is this company,
sets the bill date to the rs.ge operation date, stores the status, series and number, and
copies the supplier's lines into **rs.ge Source Lines**. A draft bill without lines gets the
lines imported: a line with VAT gets the company's Default Purchase Tax (Accounting settings)
when it is a standard-rate VAT, a line without VAT is imported untaxed. **Reimport Lines** reads
rs.ge again and re-syncs the lines of a draft bill (matching lines keep their product and account; lines you
added yourself stay, with a note in the chatter; lines that came from rs.ge and are no longer there are removed; purchase-order lines no longer on rs.ge are set to quantity 0).

### Accepting or rejecting

Compare the bill with **rs.ge Source Lines**, then:

- **Accept on rs.ge**: posts the bill (a draft is posted first) and confirms on rs.ge (status 2).
  The same button confirms a supplier correction (status 5 to 8) and a supplier cancellation
  (status 6 to 7); a confirmed cancellation cancels or reverses the bill as in section 8.
  If the supplier changed the lines on rs.ge (quantity, amount or VAT) after the bill took
  them, Accept refuses: click **Reimport Lines**, check the bill
  (Reimport puts back the default 18% purchase tax and removes rs.ge lines that are no longer there)
  and post again. Your own edits (taxes, accounts, extra lines) never cause this refusal. A
  bill that already had lines when it was pulled (typed by hand, or created from a purchase
  order) is not checked until you click **Reimport Lines** once.
- **Reject on rs.ge**: opens a window for the reason (the supplier reads it on rs.ge) and
  cancels the bill. A bill with reconciled payments cannot be rejected.

A bill linked to rs.ge loses the ordinary **Confirm** and **Reset to Draft** buttons: it is
posted by Accept, and leaves posted only through Reject or a supplier cancellation. **Confirm**
returns once rs.ge shows the bill as Confirmed or Correction Confirmed, for the case that Accept
timed out after rs.ge took it: click **Accept on rs.ge** again, or **Check Status** and then Confirm.

**The supplier re-sends a bill you rejected.** The supplier fixes the same rs.ge record and
sends it again; the Inbox lists it as "Already imported". Open the cancelled bill and click
**Check Status**: the red "You rejected this" banner goes away and **Reset to Draft**
appears. Reset to Draft brings the bill back with the supplier's new lines; check them, then
**Accept on rs.ge**. Odoo does not check cancelled bills by itself.

### The supplier corrects or cancels

**Check Status** on the bill. A correction shows the yellow banner **Supplier issued a
correction on rs.ge**: click **Import Supplier Correction**. Odoo creates a replacement draft
with the corrected lines, linked through **Replaces** / **Replaced By**; this bill stays posted
until you **Accept on rs.ge** on the new draft, and is then cancelled (reversed with a credit
note dated today when it belongs to an earlier VAT month). If the correction is already confirmed on rs.ge
(status 8), the bill is cancelled (or reversed) at once and the new draft gets the To-Do **Post the corrected bill**. If you
reject the correction, this bill simply stays. **Clear Cancelled Replacement** removes the link to a rejected replacement
once the supplier deleted it on rs.ge. The import is refused while the bill is paid, has
credit notes, sits before a lock date or is in a foreign currency. A cancellation shows
Cancelled (Sent) (6): **Accept on rs.ge** confirms it and cancels the bill.

## 10. Scheduled actions

| Scheduled action | Every | On after install | What it does |
|---|---|---|---|
| RS E-Invoice: Deadline Check (Art.54) | day | yes | One RS Logs line and chatter message per customer invoice past 30 days and not yet sent to the buyer |
| RS E-Invoice: Sync Buyer Invoices | hour | no | Reads the last 72 hours of incoming rs.ge invoices of each company and creates the missing draft bills (as Pull does). Corrections, unknown vendors and shared Tax IDs are skipped |
| RS E-Invoice: Refresh Buyer Bill Status | 6 hours | no | Check Status on up to 200 posted bills in statuses 1, 2, 5, 6, 7, 8 |
| RS E-Invoice: Refresh Seller Invoice Status | 6 hours | no | The same for posted customer invoices |
| RS E-Invoice: Recover Stranded Cancellations | 6 hours | no | Finishes the local cancel of documents rs.ge already voided; makes no rs.ge call |
| RS E-Invoice: Escalate Stale Pending Actions | day | no | Chatter reminder on documents whose rs.ge request has been pending for 24 hours |
| RS E-Invoice: Detect Stuck Buyer Confirmations | day | no | Chatter reminder on invoices the buyer has not answered for 7 days, and on cancellations pending 7 days |
| RS E-Invoice: Vacuum Logs | 7 days | no | Deletes RS Logs older than 90 days (errors: 365) and rs.ge Source Lines snapshots older than 180 days |

Each company is processed with the login of its **RS Responsible User**; a failure in one
company does not stop the others. **Refresh e-Invoices Status**, in the Actions menu of the customer invoice list (the three-dot
button next to the page title), does the seller refresh for your company on demand, with your
own login.

## 11. Step by step

**Customer invoice, normal case**

1. Confirm the invoice → the RS E-Invoice tab appears with **Send to RS**.
2. **Send to RS** → rs.ge ID and status Draft (0), lines with an RS badge.
3. **Send to buyer** → Sent (Pending) (1), S/F Number filled.
4. Buyer confirms on rs.ge; **Check Status** → Confirmed (2).

**Vendor bill, normal case**

1. New vendor bill, vendor, paste the rs.ge ID in **RS Invoice ID**, **Pull from rs.ge** → lines
   imported, status Sent (Pending) (1), bill date = operation date.
2. Check the lines against **rs.ge Source Lines**.
3. **Accept on rs.ge** → bill posted, Confirmed (2).

**Month-end**

1. Invoice list, filter **rs.ge Replacement In Flight**: originals still posted while their
   replacement waits for the buyer. Chase the buyer or exclude them from the close.
2. Documents with the red banner **rs.ge no longer counts this document**: unreconcile and
   **Check Status**.
3. Documents with **Pending rs.ge action did not complete.**: section 13.

## 12. When Odoo refuses

| Message starts with | Why | What to do |
|---|---|---|
| Your rs.ge User ID for … is not set yet | No tested login for this company | Switch to the company, Preferences > Revenue Service, **Test SOAP (e-invoice)** |
| rs.ge rejected your credentials. | Wrong username or password | Correct them and test again |
| The rs.ge taxpayer id of … is not stored yet. | The login was entered before this version, or never tested in this company | **Test SOAP (e-invoice)** in that company |
| Post the invoice before sending to rs.ge | Draft invoice | Confirm it first |
| Partner '…' has no TIN | Customer without Tax ID | Fill the Tax ID on the contact |
| Company and partner share the same TIN | Self-invoicing | Check the contact |
| Company currency is … — rs.ge accepts only GEL. | Wrong company currency | Fix the company setup |
| Invoice date … is more than 5 days ahead | Future VAT period | Change the date |
| No product lines — add at least one before sending to rs.ge. | Empty invoice | Add lines |
| … line(s) have no description | rs.ge needs a label on every line | Fill the labels |
| Sending a credit note to rs.ge is no longer supported. | Credit notes are never filed | Use the Credit Note window on the original (section 7) |
| This document is already on rs.ge (ID: …) | Send to RS clicked twice | **Update on RS** or **Check Status** |
| You can only delete a record while its rs.ge status is 'Draft' or 'New Correction'. | The buyer already has it | **Cancel on RS** once confirmed |
| Only confirmed or corrected records can be cancelled. | Not confirmed yet | **Delete on RS** |
| Cannot change '…' on '…' — it is on rs.ge | Date, customer, currency or reversed invoice locked | **Delete on RS** while Draft, or the Credit Note window once confirmed |
| Cannot delete '…' — it is on rs.ge | Odoo delete of a filed document | **Delete on RS** first, or tick **Skip rs.ge** |
| Cannot post or send this replacement invoice yet. | Cancel-and-reissue: the buyer has not confirmed the cancellation | Wait for status 7 on the original, **Check Status** on it, then post |
| A previous rs.ge request on this document is still pending | rs.ge did not answer the last call | **Check Status**; then **Resolve Orphan** or **Dismiss Pending** (section 13) |
| Another rs.ge action is still running on this document. | Two people clicked at once | Wait a moment and retry |
| Cannot post buyer-side document(s) still pending on rs.ge | Confirm Entries in the list on an rs.ge bill not yet confirmed | **Accept on rs.ge** posts and confirms in one step |
| rs.ge cannot be reached to check the status of … | A button reads the status from rs.ge first and rs.ge did not answer | Try again when rs.ge is back |
| The rs.ge record … belongs to a different supplier than the partner on this bill. | The pasted ID is another supplier's invoice, or the vendor on the bill is wrong | Check the ID and the vendor |
| rs.ge ID … is a correction of … | A correction pasted as a new bill | Open the original bill, **Import Supplier Correction** |
| This bill is already … and has reconciled payment(s). | Reject on a paid bill | Unreconcile the payment first |
| Skip reason '…' is an expense, not a VAT reversal | VAT-neutral credit note with taxed lines | Remove the taxes, or pick another reason |

## 13. Rules to remember

- **Nothing reaches rs.ge until you click Send to RS, and nothing reaches the buyer until Send to
  buyer.** Confirming an invoice in Odoo files nothing.
- **Credit notes are never filed on rs.ge.** A correction is a new invoice created from the Credit
  Note window; an Odoo-only credit note is marked **Skip rs.ge** with a reason.
- **After the buyer confirms, rs.ge changes only through Cancel on RS or a correction**, and both
  wait for the buyer's answer.
- **Check Status is when Odoo reacts.** With the refresh actions off, a confirmed cancellation
  or correction changes nothing in Odoo until someone clicks it.
- **One login per company.** Test it in each company you work in; the scheduled actions use the
  RS Responsible User's login of that company.
- **An rs.ge bill is posted by Accept on rs.ge**, not by Confirm; Confirm shows only once rs.ge reports the bill confirmed.
- **A pending request must be resolved, not retried.** If rs.ge did not answer, **Send to RS**
  again could create a duplicate; use **Resolve Orphan** (paste the ID of the draft you find on
  rs.ge) or **Dismiss Pending** (only after checking rs.ge has nothing).
- **Every rs.ge call is in RS Logs** at the bottom of the tab, with the reply.

## 14. Common questions

**The buyer rejected: do I create a credit note?** No. Reset to Draft, fix, confirm, **Send to
buyer** again. The same rs.ge record is reused.

**Can I change the date or the customer after Send to RS?** While the status is Draft (0) or
New Correction (4): **Delete on RS**, change, send again. Once the buyer has it: no. Once
confirmed: the Credit Note window.

**Why is the original still posted after I sent the correction?** rs.ge keeps the original
live until the buyer accepts the correction; Odoo mirrors that. The filter **rs.ge Replacement
In Flight** lists them.

**Where is the buyer's rejection reason?** On rs.ge only; Odoo shows that a rejection happened.

**Why do I not see Refresh e-Invoices Status in the Actions menu?** It shows only when your own
login was tested in the company of the invoice list.

**Why did the vendor bill get a different date than the supplier's invoice?** Pull sets the
bill date to the rs.ge operation date, which is the date the VAT belongs to.

**What is View RS Data?** A read-only window with what rs.ge holds right now for this
document: header, lines, attached advances and waybills.

## 15. Known limitations

- The module talks to the production rs.ge service only; there is no test mode. Test with a
  test login, not a test server.
- **Accept on rs.ge** does not compare the bill amounts with **rs.ge Source Lines**; the operator
  does.
- Excise is not sent; every rs.ge line goes out with excise 0.
- Imported lines with VAT get the company's Default Purchase Tax only when it is a
  standard-rate (S) VAT; otherwise they come in untaxed and the RS Logs say so.
- The RS Note is dropped on advance invoices.
- The messages are in English; the Georgian translations of the newest ones (the per-company
  login texts) are not there yet.

## 16. Glossary

| Term | Meaning |
|---|---|
| Taxpayer id | rs.ge's number for a company or a person, looked up from the Tax ID. Stored with your login for your company, and on each contact on first use |
| Correction | rs.ge's way to change a confirmed invoice: a new document chained on the original, accepted once by the buyer. In Odoo it is the corrected copy from the Credit Note window |
| Advance invoice | A down-payment invoice filed as an rs.ge advance; the final invoice settles it, either by netting the down-payment lines or by attaching the advance natively (**Advance Settlement** on the tab; details in [rs_einvoice_down_payments.md](../../../documentations/rs_einvoice_down_payments.md)) |
| Skip rs.ge | A credit note that must not be filed, with a reason kept for the audit trail |
| Pending action | Odoo sent a request to rs.ge and did not get an answer. Until it is resolved, the document shows the red banner **Pending rs.ge action did not complete.** |
| Orphan | A draft that exists on rs.ge after such a timeout, without an Odoo document knowing its ID. **Resolve Orphan** links it |
| Operation date | The date rs.ge files the VAT under: the invoice date on the seller side, the supplier's date on a pulled bill |
| S/F Number | The series and number rs.ge assigns when a document is sent |
