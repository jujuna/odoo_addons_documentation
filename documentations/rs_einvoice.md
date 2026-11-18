# rs.ge E-Invoice (`rs_einvoice`)

> **Module:** `rs_einvoice` | **Path:** [`custom_addons/gec_odoo_modules/rs_einvoice/`](../custom_addons/gec_odoo_modules/rs_einvoice/)
> Written 2026-09-25 against the 20.0 tree and the `gec20_prod1` database; updated 2026-09-29 for the logins per user and company, the file split, the partner taxpayer cache, the dashboard refresh and the offline tests (uncommitted, `gec20_prod1` not upgraded). Manual test checklist built from this research: [`Claude outputs/rs_einvoice_manual_tests.xlsx`](../Claude%20outputs/rs_einvoice_manual_tests.xlsx). Module guides: [`README.md`](../custom_addons/gec_odoo_modules/rs_einvoice/README.md) (users), [`README_DEV.md`](../custom_addons/gec_odoo_modules/rs_einvoice/README_DEV.md) and [`developer_map.html`](../custom_addons/gec_odoo_modules/rs_einvoice/developer_map.html) (developers).

## What It Does & Why It Exists

Georgian VAT payers must issue every VAT invoice electronically on rs.ge, and the buyer confirms it there. This module connects Odoo invoices to that rs.ge document over the rs.ge SOAP service, so the accountant never retypes an invoice on the portal. On the sales side it files the customer invoice, sends it to the buyer, and mirrors what the buyer does (confirm, reject, accept a cancellation or a correction) back onto the Odoo invoice. On the purchase side it turns a supplier's rs.ge invoice into a vendor bill, checks that the supplier and your company really are the parties on rs.ge, and confirms or rejects it on rs.ge. The end result: Odoo's books and rs.ge's register of VAT invoices tell the same story, and Odoo stops you before an action that would make them disagree.

---

## The Big Picture — How It Works

```
SALES SIDE (customer invoice)
Posted invoice --[Send to RS]--> Draft (0) --[Send to buyer]--> Sent (Pending) (1)
      buyer confirms on rs.ge --> Confirmed (2) --[Cancel on RS]--> Cancelled (Sent) (6) --buyer confirms--> Cancellation Confirmed (7) = Odoo cancels / reverses
      buyer rejects on rs.ge  --> back to editable --> [Update on RS] + [Send to buyer] again, or [Delete on RS]
Confirmed (2) --[Credit Note] "Replace RS invoice with a corrected invoice"--> corrected copy (stays a DRAFT)
      --[Send to RS]--> New Correction (4) --[Send to buyer]--> Correction Sent (5) --buyer accepts--> Correction Confirmed (8)
      = copy posted dated that day + old original cancelled / reversed the same day

PURCHASE SIDE (vendor bill)
Supplier sends on rs.ge --> [Pull from rs.ge] or rs.ge Inbox --> draft bill, Sent (Pending) (1)
      --[Accept on rs.ge]--> bill posted, Confirmed (2)      --[Reject on rs.ge]--> bill cancelled
      supplier fixes and re-sends the same record --> [Check Status] --> [Reset to Draft] (takes the new lines) --> [Accept on rs.ge]
Supplier corrects --> [Check Status] shows it --> [Import Supplier Correction] = new draft bill --[Accept on rs.ge]--> old bill cancelled (rejected: old bill stays)
Supplier cancels  --> [Check Status] shows Cancelled (Sent) --> [Accept on rs.ge] = bill cancelled / reversed
```

Everything happens on the **RS E-Invoice** tab of the invoice or bill ([account_move_views.xml:59](../custom_addons/gec_odoo_modules/rs_einvoice/views/account_move_views.xml#L59)). The tab shows coloured banners with the next step, a status card (rs.ge ID + current status), a line table with a per-line rs.ge badge, and an **RS Logs** table of every call made.

Odoo never polls rs.ge by itself unless the refresh crons are enabled — and on `gec20_prod1` they are all off except the deadline check. The operator clicks **Check Status** after anything happens on rs.ge; that read is what triggers the automatic reactions (cancel the invoice at status 7, cancel the corrected original at status 8, reset a rejected correction to draft) ([account_move_sync.py:20](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L20)).

### Key Decision Points
- **Before vs after the buyer confirms:** until the buyer acts, the same rs.ge document is edited in place (**Update on RS**), even after **Send to buyer**; re-posting a Sent invoice pushes the edited lines automatically (`_rs_auto_sync_pending_sent_edits`, [account_move.py:1174](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1174)). After confirmation only **Cancel on RS** or the **Credit Note** button remain.
- **RS Treatment in the Credit Note window** ([account_move_reversal.py:26](../custom_addons/gec_odoo_modules/rs_einvoice/wizard/account_move_reversal.py#L26)):
  - *Replace RS invoice with a corrected invoice* (pre-selected for one rs.ge invoice) — Correct & Reissue. Odoo copies the invoice; the copy is filed as an rs.ge correction chained on the original; the buyer approves once; the copy stays a draft while it waits: it is sent to rs.ge as a draft and Odoo posts it, dated the day it learns the acceptance, when the correction reaches status 8; the original is cancelled or reversed the same day, so the change lands in the acceptance month (user decision 2026-11-10). No credit note is created. A petroleum invoice (ნსაფ, `rs_spec_invoice`) uses the same treatment with its own correction types (11-14, 21, 22) and the petroleum service (`k_invoice_n`), through the hooks `_rs_correction_k_types` / `_rs_correction_copy_vals` and the shared guard `_rs_assert_correction_can_be_sent` ([account_move_reissue.py](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_reissue.py), [account_move_seller.py](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py)); see the module's README.
  - *Cancel old RS invoice and issue a new one* — Cancel & Reissue. A real rs.ge cancellation is sent at once; the new draft cannot be posted or sent until the buyer confirms the cancellation (status 7) ([account_move_reissue.py:12](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_reissue.py#L12)).
  - *Only correct Odoo, not rs.ge* — a books-only credit note marked **Skip rs.ge** with an audit reason.
- **Advance settlement mode** (Net vs Native) for final invoices with down-payment lines — see [`rs_einvoice_down_payments.md`](rs_einvoice_down_payments.md).

---

## When to Use It (and When Not To)

### This module is for:
- A Georgian VAT payer that issues customer invoices from Odoo and must file them on rs.ge.
- An accountant who receives supplier invoices on rs.ge and wants them as vendor bills with the rs.ge lines, then confirms or rejects them from Odoo.

### Use something else when:
- The document is a waybill (goods movement) — that is `rs_waybill`; linking waybills to invoices is `rs_base_methods`.
- The credit is VAT-neutral (bad debt, netting, warranty cash, inter-company mirror): there is nothing to file; use *Only correct Odoo, not rs.ge*.

---

## Real-World Scenarios

### Scenario 1: Normal sale
**Situation:** A sales accountant invoices a Georgian company for services.
**What they do:** Accounting › Customers › Invoices › New › Confirm › RS E-Invoice tab › **Send to RS** › **Send to buyer**. After the buyer confirms on rs.ge, **Check Status**.
**What happens:** rs.ge first holds the invoice as Draft (status 0), then Sent (1), then Confirmed (2). Series and number land in "S/F Number" / "S/F Number (N)".

### Scenario 2: The buyer rejects
**Situation:** The buyer rejects on rs.ge because a price is wrong.
**What they do:** **Check Status** shows the red "Likely buyer rejection" banner. Reset to Draft, fix the price, Confirm, **Update on RS**, **Send to buyer**.
**What happens:** The same rs.ge record is re-sent — no correction is filed, because rs.ge reopened it. Odoo cannot read the buyer's reason; it is on rs.ge only ([account_move_sync.py:57](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L57)).

### Scenario 3: A confirmed invoice must be voided
**Situation:** Goods were invoiced to the wrong customer and the buyer already confirmed.
**What they do:** **Cancel on RS**. The buyer confirms the cancellation on rs.ge; the accountant clicks **Check Status**.
**What happens:** Status 6, a To-Do "Waiting for buyer to confirm rs.ge cancellation" (14 days), then status 7 and the invoice is cancelled. If the invoice belongs to an earlier month (or a lock date covers it), Odoo reverses it with a credit note dated today instead, so the declared period stays unchanged ([account_move_cancel.py:66](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_cancel.py#L66), [:180](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_cancel.py#L180)). With payments applied it stays posted, raises a red banner and a To-Do; after unreconciling, the next Check Status cancels it. If rs.ge does not answer the cancel request (it may have applied it), Odoo shows an error and keeps the To-Do "Check the rs.ge cancellation" (`RsNoAnswerError`, replayed after the rollback): Check Status shows Cancelled (Sent) if it went through, and then sets the waiting To-Do; otherwise click Cancel on RS again. Cancel & Reissue commits the replacement draft before the cancel call: a late answer keeps the draft, a refusal or any other failure before the answer deletes it.

### Scenario 4: A confirmed invoice needs a lower price
**Situation:** A discount was agreed after the buyer confirmed.
**What they do:** Credit Note › *Replace RS invoice with a corrected invoice* › reason *Change price or amount* › Reverse and Create Invoice; edit the copy and, **without Confirm**, **Send to RS**; **Send to buyer**.
**What happens:** While the correction waits, the copy is a draft (Confirm is hidden and posting it by hand is refused; once sent to the buyer its rs.ge lines are locked), so only the original counts in the books (yellow "Replacement in progress" banner; filter "rs.ge Replacement In Flight"). The seller status cron (when enabled) polls the draft at status 5. When the buyer accepts (status 8), Check Status posts the copy dated that day and then cancels the original, or reverses it in an earlier VAT month (`_rs_post_accepted_correction`, [account_move_cancel.py](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_cancel.py)). If the copy cannot be posted (lines changed after sending, a posting error), the original stays as it is and a To-Do "Post the correction accepted on rs.ge" is raised once. If the buyer rejects, the copy stays a draft for another try. A correction posted before 2026-11-10 keeps the old behaviour.

### Scenario 5: A supplier invoice arrives
**Situation:** A supplier sent an invoice on rs.ge.
**What they do:** Accounting › Vendors › **rs.ge Inbox** › Search rs.ge › Import Selected (or a new bill with the pasted "RS Invoice ID (from supplier)" and **Pull from rs.ge**). Compare the bill with "rs.ge Source Lines", then **Accept on rs.ge** or **Reject on rs.ge**.
**What happens:** Pull verifies the supplier's and your company's rs.ge identity ([account_move_buyer.py:26](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L26)), sets the bill date to the rs.ge operation date and imports the lines (VAT lines get the company's Default Purchase Tax when it is a standard-rate VAT, else no tax). Accept posts the bill and confirms on rs.ge; Reject sends the reason and cancels the bill. Whenever the bill takes rs.ge's lines (Pull, Reimport Lines, Import Supplier Correction, Reset to Draft on a re-sent bill) it stores a fingerprint of them (quantity, amount and VAT of each line); Accept re-reads rs.ge, and posting (Accept, Confirm or the list's Confirm Entries) refuses a draft when rs.ge's lines no longer have that fingerprint, i.e. the supplier edited the pending invoice: Reimport Lines (it reads rs.ge again), check, post again ([account_move.py:699](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L699), [account_move_buyer.py:257](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L257)). If Accept timed out after rs.ge took it, click Accept again: it posts the bill without a second call to rs.ge. The accountant's own edits (taxes, accounts, extra lines) never trigger it. A bill that already had lines when it was pulled (typed by hand, or created from a purchase order) has no fingerprint and is not checked until one Reimport Lines. If the supplier fixes and re-sends the same rs.ge record (status back to 1, or 5 for a correction), **Check Status** clears the red "You rejected this" banner, **Reset to Draft** appears on the cancelled bill and replaces its lines with the re-sent ones ([account_move.py:1298](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1298)), then **Accept on rs.ge**. The rs.ge ID stays on the cancelled bill, so the Inbox shows the re-sent record as "Already imported" instead of creating a new bill.

### Scenario 6: The supplier corrects or cancels
**Situation:** The supplier files a correction (or a cancellation) of an invoice you confirmed.
**What they do:** **Check Status** on the bill. For a correction: **Import Supplier Correction**, then **Accept on rs.ge** on the new draft. For a cancellation: **Accept on rs.ge**.
**What happens:** A correction creates a replacement draft copy with the corrected lines and keeps the old bill posted ([account_move_buyer.py:542](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L542)); Accept on the copy (rs.ge 8) posts it with the accounting date of that day (its bill date stays the rs.ge operation date) and cancels the old bill, or reverses it in an earlier VAT month; when the acceptance is learned by Check Status or at import, the draft copy gets that day's date, through the same step the sales side uses ([account_move_cancel.py:186](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_cancel.py#L186)); a rejected copy leaves the old bill as it was. The import is refused while the bill is paid, has credit notes, sits before the lock date or is in a foreign currency ([account_move_buyer.py:467](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_buyer.py#L467)). A confirmed cancellation cancels or reverses the bill like Scenario 3. A correction already confirmed on rs.ge (8) at import cancels (or reverses) the old bill and puts the To-Do "Post the corrected bill" on the new draft. Reimport Lines keeps the lines you typed on a bill that came from rs.ge and removes only rs.ge lines that are no longer there; an empty rs.ge reply keeps the last imported lines.

---

## How Things Work Under the Hood

### Core Logic
- **`_rs_validate()`** ([account_move_checks.py:25](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_checks.py#L25)) — the local preflight before every sales-side call: posted, digits-only TINs on both sides, no self-invoicing, GEL company, invoice date at most 5 days ahead, no negative quantities except down-payment offsets, item names 1-255 characters, an FX rate for foreign currencies. Nothing reaches rs.ge when it fails. Foreign-currency amounts are sent in GEL at the invoice's own rate (`invoice_currency_rate`, the rate its journal entry uses), an advance settlement at the advance invoice's rate; a changed rate counts as a pending change.
- **`action_rs_create()`** ([account_move_seller.py:20](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_seller.py#L20)) — *Send to RS*. Chooses the save variant (advance / note / regular, [account_move.py:1575](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1575)), or files a correction for a Correct & Reissue copy. Credit notes are refused here: rs.ge corrections only go through the replacement invoice.
- **`_rs_mark_pending()`** ([account_move.py:1632](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1632)) — commits a pending marker before each create/correction call. If rs.ge times out, the marker stays and the tab offers **Resolve Orphan** / **Dismiss Pending** instead of letting a retry create a duplicate.
- **`_rs_sync_lines()`** ([account_move_sync.py:292](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L292)) — rewrites rs.ge line slots from the Odoo lines, deletes leftovers and re-reads the result; a mismatch sets the "partial line update" state and blocks sending.
- **`action_rs_refresh_status()`** ([account_move_sync.py:20](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py#L20)) — *Check Status*: header numbers, rejection detection, status reactions (6→2 refused cancellation releases an unsent Cancel & Reissue draft; 7 cancels; 8 cancels the original), supplier corrections, then the parent/children of a replacement chain.
- **Guards on core actions** — `write()` refuses to clear the rs.ge ID or change partner, currency, invoice date or reversed entry once on rs.ge ([account_move.py:862](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L862), four named guard steps and an audit of every context bypass); `unlink()` refuses deletion ([:1005](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1005)); `button_draft()` / `button_cancel()` re-read rs.ge and refuse while the document is live, except Reset to Draft at Sent (Pending), and on a vendor document at 1 or 5 ([:1238](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1238)); `_post()` refuses posting an unaccepted rs.ge bill or one whose rs.ge lines changed since the import, dates a supplier correction today, and re-checks rs.ge before re-posting an edited Sent invoice ([:682](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L682)). A button that reads the status from rs.ge first stops when rs.ge cannot be reached ([`_rs_safe_refresh_status`](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1071)), except the steps that go on with the last-known status on purpose: posting a linked credit note and the advance-settlement check. A vendor bill with an rs.ge ID hides the core Reset to Draft button, except a cancelled one that is pending on rs.ge again: the supplier re-sent it after our reject ([:1288](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1288)).
- **Credit Note window** — `default_get` pre-selects Correct & Reissue for one rs.ge invoice; the view shows only the button that fits the chosen treatment ([rs_correction_wizard_views.xml:6](../custom_addons/gec_odoo_modules/rs_einvoice/views/rs_correction_wizard_views.xml#L6)); `modify_moves` routes to Cancel/Correct & Reissue and requires a confirmed (2 or 8) original ([account_move_reissue.py:46](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_reissue.py#L46)).

### Code layout and tests
- `models/account_move.py` holds the fields, the guards on core actions and the shared helpers; the flows are split by side: `account_move_seller.py` (create, edit, delete, send, cancel), `account_move_sync.py` (Check Status, line sync, pulled lines), `account_move_buyer.py` (pull, accept, reject, supplier corrections, orphans), `account_move_cancel.py` (the local reactions: cancel, reverse, reset), `account_move_checks.py` (the preflight, constraints, onchanges), `account_move_reissue.py` (Cancel & Reissue, Correct & Reissue); `rs_soap_service.py` is the client, `rs_einvoice_cron.py` the crons.
- `tests/` runs the seller flow, the write guards and the inbox against recorded rs.ge replies through a zeep transport stub, without any network ([tests/common.py](../custom_addons/gec_odoo_modules/rs_einvoice/tests/common.py)); 12 tests, run with `-u rs_einvoice --test-tags /rs_einvoice` on a database that has `rs_base_methods`.

### Important Fields (only the ones that matter)
- `rs_einv_status` — the rs.ge status code (-1 Deleted, 0 Draft, 1 Sent (Pending), 2 Confirmed, 3 Corrected (Original), 4 New Correction, 5 Correction Sent, 6 Cancelled (Sent), 7 Cancellation Confirmed, 8 Correction Confirmed). It drives which buttons show.
- `rs_einv_skip` + `rs_einv_skip_reason` — "Skip rs.ge" on credit notes only. Expense-type reasons (bad debt, warranty, commercial gesture, inter-company mirror) must carry no tax and no income account at posting ([account_move_checks.py:210](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_checks.py#L210)).
- `rs_einv_replaces_id` / `rs_einv_replaced_by_id` / `rs_einv_replacement_mode` — the replacement chain (`correction` = Correct & Reissue, `fresh` = Cancel & Reissue or a supplier correction on the buyer side).
- `rs_einv_is_advance` — files the invoice as an rs.ge advance; set automatically when every product line is a down-payment line.
- `rs_einv_overdue_state` — 25-29 days since the invoice date = yellow banner, 30+ = red (MoF order 996, Art. 54), until the invoice is sent to the buyer: status 1 or 5 stops the clock, the buyer need not confirm ([account_move.py:349](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L349)).

---

## Configuration & Settings

- **rs.ge login per user and per company** (Settings › Users & Companies › Users › user › tab "Revenue Service", from `rs_base_methods`; the fields are company-dependent, so switch to the company first) — "RS Username" and "RS Password" are the rs.ge service user; **Test SOAP (e-invoice)** validates them, stores the rs.ge user id and the company's taxpayer id (looked up from the company TIN), which every document then names as its seller or buyer. Without it every rs.ge action in that company fails. The service is always bound to the document's company (`_rs_get_service`, [account_move.py:1381](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L1381)), whatever company the switcher shows. The Accounting settings block only points to this tab ([res_config_settings_views.xml](../custom_addons/gec_odoo_modules/rs_einvoice/views/res_config_settings_views.xml)). Design and cases: [`rs_multi_company.md`](rs_multi_company.md).
- **"RS Responsible User"** (same tab, one per company) — the user whose login the scheduled actions use for that company; a company without one is skipped and logged (`_rs_company_passes`, [rs_einvoice_cron.py:139](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_cron.py#L139)).
- **Scheduled Actions** ([ir_cron.xml](../custom_addons/gec_odoo_modules/rs_einvoice/data/ir_cron.xml)) — only *Deadline Check (Art.54)* is active at install. *Sync Buyer Invoices* (hourly, 72-hour window, skips corrections and unknown vendors), *Refresh Seller Invoice Status* / *Refresh Buyer Bill Status* (6-hourly, statuses 1, 2, 5, 6, 7, 8), *Recover Stranded Cancellations*, *Escalate Stale Pending Actions*, *Detect Stuck Buyer Confirmations* and *Vacuum Logs* are off until enabled. The rs.ge crons run one pass per company as its responsible user, each in its own savepoint. With the refresh crons off, nothing changes in Odoo until someone clicks Check Status. The refresh crons take one batch per company, so a company without a responsible user cannot starve the others; the buyer sync runs the main company first and does not import a bill that a company with the same Tax ID (a branch) already holds.
- **Refresh e-Invoices Status** (an entry of the Actions menu of the customer invoice list, the three-dot button next to the page title, a core hook; the list opened from a sales journal card of the dashboard shows it too) — refreshes up to 200 of that company's posted customer documents with the clicking user's login; shown only on sales journals of companies the user holds a tested login for ([account_journal.py](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_journal.py)).

---

## Dependencies

| Requires | Why |
|---|---|
| `accountant` | Invoices, bills, credit notes, the reversal wizard it extends. |
| `rs_base_methods` (runtime, not declared) | Provides the rs.ge credentials, stored per user and per company, and the company's taxpayer id that every document names as its seller; without it every call raises a "credentials provider is missing" error ([rs_soap_service.py](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_soap_service.py)). |
| Python `zeep` | SOAP client for `www.revenue.mof.ge/ntosservice`. |

| Works With (optional) | What It Adds |
|---|---|
| `sale` | Down-payment invoices become rs.ge advances; final invoices settle them (Net or Native). |
| `rs_base_methods` | "RS Waybills" tab and waybill links on invoices; on Pull, links bill lines to the vendor's purchase order. |

---

## Gotchas & Non-Obvious Behavior

- **Live endpoint only:** the SOAP URL is hard-coded to the production service; there is no test switch. Test users are the only isolation.
- **Credit notes never go to rs.ge:** Send to RS on a credit note is refused; rs.ge changes go through the Correct & Reissue copy, which is an invoice.
- **Vendor bills lose Confirm / Cancel / Reset to Draft** once an rs.ge ID is on them ([account_move_views.xml:42](../custom_addons/gec_odoo_modules/rs_einvoice/views/account_move_views.xml#L42)); Accept on rs.ge posts them. Confirm comes back once rs.ge shows the bill as Confirmed or Correction Confirmed (Accept timed out after rs.ge took it). Reset to Draft comes back only on a rejected bill the supplier re-sent.
- **A re-sent rejected bill is found by hand:** no cron reads cancelled bills (the status crons select posted ones), so the accountant learns of the re-send from the supplier or the Inbox ("Already imported as ...") and clicks Check Status. Not covered: a posted bill rejected in an earlier VAT period is reversed by a credit note, not cancelled; if its supplier re-sends, Accept confirms on rs.ge while the reversal stays in Odoo.
- **A pasted ID is not a link until Pull verified it:** the web client saves the pasted ID before the button runs, but a bill whose ID was never pulled (`_rs_awaiting_pull`, [account_move.py:727](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move.py#L727)) is not locked: the ID and the vendor can be changed, the bill can be deleted, and Check Status ignores it until Pull has checked the supplier and the company on rs.ge (the two defects found 2026-09-25 were fixed 2026-09-26).
- **Partner taxpayer ids are cached:** the first rs.ge call for a partner stores its taxpayer id on the contact (`rs_un_id`); a changed Tax ID clears it ([res_partner.py](../custom_addons/gec_odoo_modules/rs_einvoice/models/res_partner.py)). The company's own id lives on the user's login for that company.
- **Accept checks rs.ge, not the bill:** it refuses when rs.ge's lines changed since the bill took them, but it does not compare the bill's own amounts with them, so an amount or VAT the accountant edits still posts (CODE_REVIEW 1.3).
- **One message names a menu that does not exist in 20:** "Accounting > Configuration > Currencies" (real path: Accounting › Configuration › Accounting › Currencies).
- **RS Note is dropped on advance invoices:** the advance variant wins over the note variant.
- **The rs.ge VAT class follows the Tax Category Code of the line's taxes** (`_rs_line_vat_class`, [account_move_sync.py](../custom_addons/gec_odoo_modules/rs_einvoice/models/account_move_sync.py)): S sends the VAT of the S taxes only, Z/G sends 0 (zero-rated), E/O sends -1 (exempt, out of scope, small-business turnover); a tax without a code is not VAT, so a City Tax line goes as -1. Send is refused while the company has no sale tax with code S, and while a line carries a percent tax whose code rs.ge does not map (set S, or O if it is not VAT). A VAT tax made from scratch has no code; Duplicate keeps it. Changing a code after sending does not mark the invoice as changed (the line hash reads tax ids only).
- **The rs.ge item name is the product, not the label** (`rs_einv_goods`, [rs_einvoice_models.py](../custom_addons/gec_odoo_modules/rs_einvoice/models/rs_einvoice_models.py)): on invoices a line with a product sends the product name without its internal code, in the customer's language; only a line without a product sends its label, and section and note lines are never sent. Vendor bills keep the label, which holds the supplier's rs.ge text. The line hash reads the product itself, so editing a product line's label or renaming the product does not mark a sent invoice as changed; swapping the product does. Since 2026-10-31.
- **Keep City Tax on its own line:** on a line with an 18% tax, rs.ge may recompute VAT from the full amount, which then includes the City Tax [Likely: comment in Odoo's l10n_ge_edi].

---

## Related Docs

- [`INDEX.md`](INDEX.md)
- [`rs_einvoice_down_payments.md`](rs_einvoice_down_payments.md) — advance invoices, Net vs Native settlement.
- [`rs_multi_company.md`](rs_multi_company.md) — logins per user and company, the document-company binding, per-company crons.
- [`rs_waybill_einvoice_fix_plan.md`](../dev_notes/plans/rs_waybill_einvoice_fix_plan.md) — older open findings for `rs_waybill` / `rs_einvoice`.
- [`l10n_ge.md`](l10n_ge.md) — the Georgian taxes the invoices carry.
