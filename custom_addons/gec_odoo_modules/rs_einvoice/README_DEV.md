# RS E-Invoice (`rs_einvoice`) — Developer guide

For developers changing the module. How it is used: [README.md](README.md). Business flows, history and open findings:
[documentations/rs_einvoice.md](../../../documentations/rs_einvoice.md),
[documentations/rs_multi_company.md](../../../documentations/rs_multi_company.md) (logins per
company) and [CODE_REVIEW.md](CODE_REVIEW.md).

---

## 1. Purpose and facts

The module extends `account.move` with an rs.ge identity (id, status, series, number, chain
links), a SOAP client bound to the document's company, the seller flows (create, sync lines,
send, edit, delete, cancel), the buyer flows (pull, accept, reject, import a supplier
correction, inbox), the local reactions to what rs.ge reports (cancel, reverse, reset to
draft), and per-company crons. rs.ge is the master for the status; Odoo is the master for
the lines and refuses local changes rs.ge would contradict.

| Item | Value |
|---|---|
| Depends | `accountant` (invoices, bills, `account.move.reversal`, the journal dashboard hook) · runtime: `rs_base_methods`, which depends on this module and provides the login fields and `_get_rs_credentials` on `res.users`; without it every call raises "rs.ge credentials provider is missing" · Python `zeep` |
| New models | `rs.einvoice.log`, `rs.einvoice.correction.line`, `rs.einvoice.advance.settlement` (stored) · `rs.soap.service`, `rs.einvoice.cron` (abstract) · wizards `rs.einvoice.inbox.wizard` + `rs.einvoice.inbox.line`, `rs.einvoice.reject.wizard`, `rs.einvoice.orphan.resolve.wizard`, `rs.einvoice.view.wizard` + `rs.einvoice.view.line`, `rs.einvoice.replace.preview` + `rs.einvoice.replace.preview.line` |
| Extended models | `account.move` (52 fields, guards, all flows), `account.move.line` (`rs_line_id`, `rs_synced`, `rs_sync_state`), `account.journal` (the Refresh e-Invoices Status hook), `res.partner` (`rs_un_id`), `account.move.reversal` (RS Treatment) |
| Hooks, crons, controllers | 8 crons (section 10) · no controllers |
| Endpoint | `WSDL_URL` in `rs_soap_service.py`: the production ntosservice, no test switch. `_get_client` and `_call_datatable` take an optional `wsdl_url` (another rs.ge service, e.g. petroleum invoices, passes its own); the DataTable POST goes to the WSDL's own `soap:address` |

What the data files load, in manifest order: `data/ir_cron.xml` (8 crons, `noupdate`), the
settings block, the wizard views, the invoice form tab and the list filter, the View RS Data
button, then `security/ir.access.csv` last.

## 2. Architecture

```text
   Odoo                                                   rs.ge (ntosservice, SOAP)
 ┌──────────────────────────────┐   rs.soap.service    ┌────────────────────────┐
 │ account.move                 │  login + taxpayer id │ invoice header + lines │
 │  RS E-Invoice tab buttons    │  of the document's   │ statuses -1 .. 8       │
 │  seller: create, send, edit, ├─────────────────────►│ corrections (k_id)     │
 │          delete, cancel      │  save / change_status│ advances, waybills     │
 │  buyer: pull, accept, reject,│◄─────────────────────┤                        │
 │          import correction   │  get_invoice, lists  └────────────────────────┘
 └──────────────┬───────────────┘
                │ guards: create, write, unlink, _post, button_draft, button_cancel
                │ pending markers, row locks, RS Logs, line snapshots
                ▼
   reactions: cancel or reverse, reset a rejected correction, activities, chatter
                ▲
                │ crons per company (RS Responsible User) · Refresh e-Invoices Status
```

Names in the code: the tab buttons are `action_rs_*` on `account.move`; the client is
`rs.soap.service`, obtained through `account.move._rs_get_service()`; the reactions are the
`_rs_refresh_*` steps of `action_rs_refresh_status` and the helpers in `account_move_cancel.py`;
the crons live on `rs.einvoice.cron`.

Every rs.ge write follows one shape: row lock, local checks, pending marker (committed), the
SOAP call, store the result, commit, re-lock, then the tail (line sync, verification read).
The commit in the middle is the orphan-recovery design: if rs.ge answered but Odoo crashed
after, the id is already durable; if rs.ge never answered, the marker stays and the operator
resolves it instead of creating a duplicate.

## 3. File map

| File | What it holds |
|---|---|
| [`__manifest__.py`](__manifest__.py) | Depends, data order, assets, and the plain-text `description` that keeps Odoo from rendering README.md as reStructuredText |
| **models/** | |
| [`account_move.py`](models/account_move.py) | Constants (statuses, status groups, skip reasons), the 52 fields and their computes, the deadline cron, logging and notification helpers, `create` / `write` (four guard steps) / `unlink` / `_post` / `button_draft` / `button_cancel`, chain helpers (`_rs_chain_parent`, `_rs_get_correction_base_id`, pending-correction lookups), `_rs_get_service`, header push, locks and pending markers, `_rs_safe_refresh_status` |
| [`account_move_seller.py`](models/account_move_seller.py) | Send to RS (`action_rs_create`, `_rs_create_invoice`, `_rs_create_invoice_correction`), native advance settlement, Update on RS, Delete on RS, Send to buyer, Cancel on RS (`_rs_cancel_core`), status routing (`_rs_apply_status_update`) |
| [`account_move_sync.py`](models/account_move_sync.py) | Check Status and its steps, line sync and payloads (`_rs_sync_lines`, `_rs_lines_to_payload`, GEL conversion, rounding), pulled-line snapshots and import, View RS Data |
| [`account_move_buyer.py`](models/account_move_buyer.py) | Pull, Reimport Lines, Accept, Reject, Import Supplier Correction (`_rs_execute_cancel_and_reissue` and its steps), Resolve Orphan, Dismiss Pending, the smart buttons, Clear Cancelled Replacement |
| [`account_move_cancel.py`](models/account_move_cancel.py) | The local reactions: `_rs_auto_cancel_after_rs_cancellation`, prior-period reversal, manual-reversal flag and activity, neutralising a corrected original, releasing a stranded replacement, resetting a rejected correction, the two activities |
| [`account_move_checks.py`](models/account_move_checks.py) | `_rs_validate` (the preflight), the five constraints, the four onchanges, the correction-reason suggestion and its extension hook |
| [`account_move_reissue.py`](models/account_move_reissue.py) | Cancel & Reissue and Correct & Reissue: the shared preflight, the two flows, the "original must be at 7" guard |
| [`account_move_line.py`](models/account_move_line.py) | `rs_line_id`, the rs.ge slot id of a line |
| [`account_journal.py`](models/account_journal.py) | The Refresh e-Invoices Status hook (Actions menu of the customer invoice list) |
| [`res_partner.py`](models/res_partner.py) | `rs_un_id`, the cached taxpayer id, cleared when the Tax ID changes |
| [`rs_einvoice_models.py`](models/rs_einvoice_models.py) | `account.move.line` sync badge compute, the log, line snapshot and advance settlement models, their vacuums |
| [`rs_einvoice_cron.py`](models/rs_einvoice_cron.py) | Date and row helpers, vendor lookup by TIN, `rs.einvoice.cron` with the buyer sync, escalations, status refreshes, stranded-cancellation recovery, vacuum |
| [`rs_soap_service.py`](models/rs_soap_service.py) | zeep client cache, credentials, `_call_datatable`, taxpayer-id helpers, one method per rs.ge operation |
| **wizard/** | |
| [`account_move_reversal.py`](wizard/account_move_reversal.py) | RS Treatment on the Credit Note window: defaults, preview, `refund_moves` and `modify_moves` routing |
| [`rs_buyer_inbox_wizard.py`](wizard/rs_buyer_inbox_wizard.py) | rs.ge Inbox: search, row matching, import through Pull, correction rows through the preview |
| [`rs_replace_preview_wizard.py`](wizard/rs_replace_preview_wizard.py) | Cancel-and-reissue preview for supplier corrections picked in the inbox |
| [`rs_einvoice_reject_wizard.py`](wizard/rs_einvoice_reject_wizard.py) | Rejection reason window |
| [`rs_einvoice_orphan_wizard.py`](wizard/rs_einvoice_orphan_wizard.py) | Candidate rs.ge id for Resolve Orphan |
| [`rs_einvoice_view_wizard.py`](wizard/rs_einvoice_view_wizard.py) | View RS Data: a transient copy of what rs.ge holds |
| **views/** | `account_move_views.xml` (the tab, its banners and buttons, the list filter), `account_move_view_data_views.xml` (View RS Data button), `rs_correction_wizard_views.xml` (RS Treatment on the reversal wizard, orphan and reject windows), `rs_buyer_inbox_wizard_views.xml` (inbox, action, menu), `rs_replace_preview_wizard_views.xml`, `rs_einvoice_view_wizard_views.xml`, `res_config_settings_views.xml` (pointer to the user preferences) |
| **data/** | `ir_cron.xml`: the eight scheduled actions (section 10) |
| **security/** | `ir.access.csv` (section 12) |
| **static/src/** | `js/rse_lines_field.js` + `xml/rse_lines_field.xml`: the lines table widget with the RS badge and rs.ge-style columns; `scss/rs_einvoice.scss`, `scss/rs_einvoice_snapshot.scss`: the tab's cards and snapshot tables |
| **tests/** | `common.py`, `soap_transport_stub.py`, `stub_responses.py`, `test_files/ntosservice.wsdl` and three test files (section 14) |
| **i18n/** | `ka_GE.po` |
| [`CODE_REVIEW.md`](CODE_REVIEW.md) | Open review findings |

## 4. Credentials, the service and taxpayer ids

`rs_base_methods` stores the rs.ge login per user **and per company** (company-dependent
fields on `res.users.settings`, proxied on `res.users`: `rs_username`, `rs_password`,
`rs_user_id`, `rs_un_id`, `rs_is_responsible`, ...). Reading them evaluates for
`env.company`, so the company in the environment decides which login a call uses.

1. `_rs_get_service(check_auth=False)`: returns `rs.soap.service.with_company(self.company_id)`,
   so a flow uses the document's company whatever the switcher shows; with `check_auth` it
   calls `_check_auth` (`chek`) before the caller's first write; the result is kept in
   `cr.cache` per user and company, so a transaction checks the login once (a savepoint rollback
   clears it).
2. `_get_credentials`: `env.user._get_rs_credentials()`; a missing provider or an untested
   login raises with the company named. `_auth_kwargs` turns it into the `user_id`, `su`, `sp`
   arguments every operation takes.
3. `_get_client`: one zeep `Client` per WSDL URL in a module-level cache, with one
   `requests.Session` (keep-alive); `SOAP_TIMEOUT` for connect and operations.
4. `_rs_company_un_id()`: the company's taxpayer id, stored on the user's login for that
   company by Test SOAP (`res.users.action_rs_test_credentials` in `rs_base_methods`, from
   `get_un_id_from_tin(company.vat)`). Every call that names the seller or the buyer of this
   company uses it, never the id of the login itself, so a representative login files under
   the company's TIN.
5. `_rs_partner_un_id(partner)`: the partner's taxpayer id, resolved once through
   `get_un_id_from_tin` and kept in `res.partner.rs_un_id` (written with `sudo`, because the
   accountant may not edit partners). `res.partner.write` clears it when `vat` changes.
6. `_call_datatable(operation, **kwargs)`: zeep builds and validates the envelope, the client's
   transport posts it, and the rows of the DataTable reply are parsed with a hardened parser
   (`_new_safe_parser`), because zeep cannot deserialise rs.ge's DataTable replies. The six
   list operations use it. Reads go through `_retry_read` (exponential backoff on transient
   errors); writes are never retried.
7. A zeep `Fault` on a write becomes a `UserError` with the operation's context
   (`save_invoice`, `save_invoice_desc`, `change_invoice_status`, the advance calls).

## 5. Send to RS

`action_rs_create` (button):

1. `_rs_acquire_row_lock('Send to RS')`: `lock_for_update` on the move; a `LockError` becomes
   "Another rs.ge action is still running".
2. Refuses a pending marker without an id, a document marked Skip, and, for a Cancel & Reissue
   replacement, an original not yet at status 7 (`_rs_assert_replacement_cancel_accepted`).
3. `_rs_validate`: the local preflight (section 11). Then refuses an existing rs.ge id.
4. `_rs_get_service(check_auth=True)`.
5. A Correct & Reissue copy (`rs_einv_replacement_mode == 'correction'`) goes to
   `_rs_create_invoice_correction`; credit notes are refused with a message per case (on
   rs.ge, no original, original not on rs.ge); everything else goes to `_rs_create_invoice`.

`_rs_create_invoice(service)`:

1. `_rs_company_un_id()` and `_rs_partner_un_id(partner_id)`; `_rs_pick_save_variant`: `advance`
   (`save_invoice_a`) when `rs_einv_is_advance`, `note` (`save_invoice_n`) when `rs_einv_note`,
   else `regular` (`save_invoice`).
2. `_rs_mark_pending('create')`: writes `rs_einv_pending_action` and commits.
3. `save_invoice(inv_id=0, operation_date, seller_un_id, buyer_un_id, variant, note)`;
   `_rs_extract_inv_id` reads the new id or raises after an RS Logs error line.
4. Stores `rs_einv_id` and status `'0'`, clears the marker, logs, commits.
5. `_rs_relock_after_commit` (`try_lock_for_update`, SKIP LOCKED); if the row is busy the line
   sync is skipped with a log line and Update on RS finishes it later.
6. `_rs_sync_lines(service)`, `_rs_stamp_sync_hash`, `_rs_sync_native_advance_settlements`.

`_rs_create_invoice_correction(service)`: refuses when the replaced original is not on rs.ge,
when the copy changed the buyer, when another correction is in flight, or when the original
carries advances rs.ge would copy; `_rs_get_correction_base_id` picks the record the
correction chains on (the newest accepted correction, else the original); marks pending
(`correction`), calls `create_correction` (`k_invoice` with `k_type`), stores the id at status
`'4'`, commits, then pushes the copy's lines as the new state.

## 6. Line sync, Update on RS, Delete on RS

`_rs_sync_lines(service, target_id=None)` is not transactional on rs.ge, so it works slot by
slot and verifies:

1. `get_invoice_desc(target)`: the slots rs.ge holds; a row without a usable id aborts before
   any write ("Sync was aborted to avoid writing to the wrong slot").
2. `_rs_get_lines_payload` → `_rs_lines_to_payload`: one payload per product line
   (`_rs_line_to_payload`: label, unit, quantity, total and VAT in GEL through
   `_rs_amount_to_gel`, which divides by the move's `invoice_currency_rate`; the VAT class and amount come from
   `_rs_line_vat_class`: the Tax Category Code of the line's taxes mapped by
   `RS_VAT_CLASS_BY_TAX_CATEGORY`, VAT = the S taxes only, 0 zero-rated, -1 exempt or no VAT); on a
   final invoice in net mode the down-payment deductions are spread across the regular lines
   and the rounding residue is placed by `_rs_spread_residual`; negative amounts on an invoice
   are refused.
3. Each payload reuses a slot when `_rs_line_matches_slot` says it is already equal (no call),
   else `save_invoice_desc` (create or overwrite); leftover slots are removed with
   `delete_invoice_desc`; `account.move.line.rs_line_id` keeps the slot id.
4. A failure after the first write sets `rs_einv_lines_sync_state = 'partial'`, schedules
   `_rs_schedule_line_sync_activity` and raises; the tab shows the red partial-sync banner and
   Send to buyer is refused until a clean Update on RS.
5. `get_invoice_desc` again and a count comparison; a mismatch raises.

`_rs_compute_line_hash` (SHA-256 of header and product-line fields) is stored by
`_rs_stamp_sync_hash` in `rs_einv_last_sync_hash`; `rs_einv_has_pending_changes` compares the
current hash with it and drives the Update on RS button and the `pending_edit` badge
(`_compute_rs_sync_state` on `account.move.line`).

`action_rs_edit` (Update on RS): lock, needs an id and a posted move, `_rs_safe_refresh_status`,
status must be 0, 1 or 4, `_rs_validate`, header push through `_rs_push_header_to_rs` unless
the status is 1 (rs.ge does not take a header change on a sent record) or the document is a
credit note that is not a correction, then `_rs_sync_lines`, hash, advances; a rejection note
is cleared. `_post` calls it automatically through `_rs_auto_sync_pending_sent_edits` after a
Sent (1) original is re-posted with edited lines; before that, `_rs_assert_edits_can_reach_rs`
re-reads rs.ge and refuses the post when the buyer confirmed meanwhile or rs.ge is unreachable.

`action_rs_delete` (Delete on RS): status 0 or 4 only, `delete_invoice`, then `get_invoice`
must report -1, otherwise the id is kept ("clearing it now would leave a live document on
rs.ge"); the id, status and hash are cleared with the `rs_allow_id_overwrite` context; the
parent of a deleted correction gets its status re-read.

## 7. Send to buyer

`action_rs_send`:

1. Lock, the cancel-and-reissue guard, an id and a posted move, `_rs_safe_refresh_status`,
   status 0 or 4 (else "You can only send a record that is in 'Draft' or 'New Correction'").
2. `_rs_validate`, service, `_rs_target_is_correction` (a status 4 record is a correction).
3. Header push (unless a non-correction credit note), `_rs_sync_lines`, hash, and
   `_rs_sync_native_advance_settlements`; when that returns False a sticky notification is
   returned and the send does not happen.
4. `send_correction` or `send_invoice` (both `change_invoice_status`, to 5 or 1);
   `_rs_send_succeeded` reads the result flag; failure logs and raises.
5. Stores the expected status and `rs_einv_sent_at`, clears the rejection note, commits.
6. Verification tail after `_rs_relock_after_commit`: `get_invoice` fills series and number
   (`_rs_extract_status_triplet`) and corrects the status when rs.ge reports another one; for
   a correction the parent is refreshed. Every failure of the tail is a warning in RS Logs,
   never an exception: rs.ge already accepted the send.

## 8. Check Status and the local reactions

`action_rs_refresh_status` (button, and the body of every automatic refresh):

1. Returns at once without an id or on a vendor bill whose pasted id was never pulled
   (`_rs_awaiting_pull`): only Pull may link a bill, after the party check.
2. `get_invoice(id)`; `_rs_refresh_header`: series, number, seller and buyer declaration
   numbers, `rs_einv_overhead_no` (the side's own number).
3. `_rs_refresh_rejection`: seller side; a status going back (2→1, 5→4, 1→0), rs.ge's
   `was_ref` flag while pending, or a drop to 0 after a send is a rejection. It is announced
   once per rs.ge state (`rs_einv_rejection_status` is the deduplication key) in
   `rs_einv_rejection_note`, RS Logs and chatter; a rejected Correct & Reissue copy is reset
   to draft (`_rs_reset_correction_to_draft_after_rejection`); a confirmation clears the note.
   Buyer side: our own reject note clears on a confirmation or when the supplier re-sends
   (0/4 back to 1/5, `resent_to_buyer`).
4. `_rs_refresh_apply_status`: stores the status. 6→2 or 6→8 is a refused cancellation:
   `rs_einv_cancel_pending_at` is cleared and an unsent Cancel & Reissue draft is released
   (`_rs_release_stranded_replacement`). Status 8 on a correction copy cancels its original
   (`_rs_neutralize_after_correction_accepted`). Status 7 on a posted invoice or bill that credit
   notes do not fully reverse cancels it, or raises a To-Do when payments or credit notes block it
   (`_rs_auto_cancel_after_rs_cancellation`). 7 and 8 are checked on every
   refresh, not only on the transition, so a cancel that failed once is retried.
   A seller move that goes from 2, 3 or 8 to 6 with no `rs_einv_cancel_pending_at` (a cancel made on the rs.ge
   portal, or one whose reply was lost) gets `_rs_schedule_cancel_pending_activity`.
5. `_rs_refresh_supplier_correction` (buyer side): `get_makoreqtirebeli` returns the pending
   correction id; a new one is stored in `rs_einv_supplier_k_id` and announced, an already
   imported one is forgotten.
6. `_rs_refresh_replacements`: the replacements of this document (`rs_einv_replaces_id`
   pointing here) get status, series and number; a correction at 8 neutralises this original.
7. Buyer side: `_rs_refresh_pulled_lines` refreshes the rs.ge Source Lines snapshots; an empty reply keeps
   the last snapshots (with `raise_on_failure` and snapshots present it raises "returned no lines").
8. `_rs_refresh_parent`: the document this one corrects is refreshed too, with the ids already
   refreshed passed in `rs_refresh_excluded_ids` so the chain never loops.

`_rs_safe_refresh_status` wraps the above for callers that must not act on an unchecked status:
a connection, timeout or HTTP transport error (`_TRANSIENT_EXCEPTIONS` of `rs_soap_service.py`) is
logged and raised as a `UserError` (`get_invoice` also turns a SOAP fault into one); `UserError` and `ValidationError` (credentials, configuration) and any other
exception pass through unchanged. It returns nothing.

`_rs_auto_cancel_after_rs_cancellation` (in `account_move_cancel.py`):

| Situation | Result |
|---|---|
| `payment_state == 'reversed'` | Left as it is, `rs_einv_reversal_pending_at` cleared, returns True |
| Payments or partial payments applied | `_rs_flag_manual_reversal`: `rs_einv_reversal_pending_at` set, RS Logs, chatter, a To-Do with the steps; returns False |
| Open credit notes linked | The same flag with its own message |
| Posted in an earlier VAT period (`_rs_is_prior_vat_period`: an earlier month, or a lock date covers it) | `_rs_reverse_in_current_period`: a credit note dated today, marked Skip with reason `replacement`, so the declared period stays unchanged |
| Otherwise | `button_draft` + `button_cancel` under `rs_skip_lock_check`, which bypasses the module's own lock guard |
| Any refusal | Flagged the same way; the next Check Status retries, the recovery cron skips flagged moves |

## 9. Cancel on RS, the Credit Note window, reissue

`action_rs_cancel` → `_rs_cancel_core`: needs an id; `_rs_safe_refresh_status`; refuses while a
correction is in flight (`_rs_find_pending_correction_blocker`); the status must be 2, 3 or 8; `cancel_invoice` (`change_invoice_status` to 6);
`_rs_apply_status_update` stores status 6 on this move and posts to chatter; `_rs_schedule_cancel_pending_activity`
(a 14-day To-Do). The button then commits and reads the record back: if the buyer already
answered, `_rs_refresh_apply_status` applies it. A transient error on `cancel_invoice` (rs.ge may have
applied it) writes an `error` `_rs_notify` with the To-Do "Check the rs.ge cancellation", replayed after the
rollback, and raises `RsNoAnswerError` (a `UserError`): Check Status then shows whether the cancel went
through. `_rs_cancel_core` does not commit itself.

`_rs_do_cancel_reissue` copies the replacement, links it, writes its log and commits before calling
`_rs_cancel_core`: if rs.ge answers late, the draft survives with the To-Do. A refusal (any other
exception) rolls back, clears the link, deletes the draft and commits before re-raising.

The Credit Note window (`account.move.reversal`):

- `default_get` pre-selects `correct_reissue` for one live customer invoice, `skip` otherwise;
  `rs_einv_needs_k_type` shows the RS fields when a selected move is on rs.ge and not skipped.
- `refund_moves` (Reverse): refuses the two reissue treatments (they need the other button),
  an original that already has a replacement, and `skip` without a reason; refreshes each move
  and runs `_rs_assert_can_be_reversed` (original must be Confirmed or Corrected) unless the
  treatment is `skip`; `_prepare_default_reversal` stamps `rs_einv_skip` and `rs_einv_skip_reason`
  on the credit note.
- `modify_moves` (Reverse and Create Invoice): exactly one customer invoice on rs.ge;
  `correct_reissue` needs a reason and calls `_rs_do_correct_reissue(k_type)`; `replace` calls
  `_rs_do_cancel_reissue`.

`_rs_replace_preflight` (both flows): customer invoice, posted, not skipped, on rs.ge at status
2 or 8, not an advance, not already replaced (a cancelled replacement must be cleared first
with `action_rs_clear_cancelled_replacement_link`), no correction in
flight. It runs before and after the refresh.

`_rs_do_correct_reissue(k_type)`: lock, preflight, refresh, preflight,
`_rs_assert_advance_correctable` (an advance fully settled on rs.ge cannot be corrected, nor below the settled VAT), then a
`copy` with `include_business_fields`, `rs_einv_replaces_id`, mode `correction`, the reason,
today's dates and a `ref`; the original gets `rs_einv_replaced_by_id`. The copy is a normal
draft: Send to RS files it as the correction (section 5), Send to buyer moves it to 5, the
buyer's acceptance (8) cancels the original at the next refresh, a rejection (4) resets the
copy to draft.

`_rs_do_cancel_reissue`: the same checks, then `_rs_cancel_core` (a real cancellation, status
6), a copy in mode `fresh`, a commit. `_rs_assert_replacement_cancel_accepted` in `_post`,
`action_rs_create` and `action_rs_send` keeps the copy from being posted or sent until the
original is at 7; a refused cancellation releases it (section 8).

## 10. Buyer side

`action_rs_buyer_pull` (Pull from rs.ge):

1. Buyer-side document, an id pasted, not skipped; `_rs_get_service(check_auth=True)`.
2. `get_invoice`: the status must exist and be in `RS_BUYER_ACTIONABLE` (1, 2, 3, 5, 6, 7, 8): a
   draft the supplier can still edit is refused.
3. `_rs_pull_check_correction_parent`: a record with a `k_id` is a correction; it is refused
   here and directed to Import Supplier Correction on the parent bill (found by
   `_rs_find_other_move_by_rs_id`), or to importing the original first.
4. `_rs_pull_verify_parties`: the record's `seller_un_id` must equal `_rs_partner_un_id(vendor)`
   and its `buyer_un_id` must equal `_rs_company_un_id()`; missing or non-numeric TINs and
   lookup failures raise with the party named.
5. `_rs_pull_apply_header`: status, series, number and, on a draft, the bill date moved to the
   rs.ge operation date in the same write that stores the status, because once the status is
   set `write` locks the date.
6. `_rs_refresh_pulled_lines`: `get_invoice_desc` into `rs.einvoice.correction.line` rows of
   type `rs_pulled` (the rs.ge Source Lines table); a draft without product lines then gets
   `_rs_auto_import_pulled_to_bill_lines` (`_rs_pulled_line_vals`: `drg_amount > 0` applies
   `_rs_get_purchase_vat_18`, the company's Default Purchase Tax mapped by the fiscal position when
   it is one standard-rate (S) tax excluded from the price, else no tax;
   `_rs_find_product_for_pulled` by name).

`action_rs_buyer_reimport_lines`: draft only; `_rs_merge_pulled_to_bill_lines` matches on the
rs.ge line id, then on the name in order, keeps purchase-linked lines and products. When any product line
has an `rs_line_id` (the bill came from rs.ge), unmatched lines without one (typed by the accountant) are kept
and reported by `_rs_notify` (log and chatter); only unmatched lines with one are removed. A bill with no `rs_line_id` keeps the old behaviour.

`action_rs_buyer_accept`: lock; refresh; a draft that the refresh shows at 2 or 8 (Accept cut off after rs.ge took it) is posted with
`rs_buyer_accept_in_progress` and the method returns, with no second rs.ge call; the target comes from `_RS_BUYER_ACCEPT_TARGETS`
(1→2, 5→8, 6→7), anything else is refused; a cancelled bill is refused; for 2 and 8 the
snapshots are refreshed with `raise_on_failure`; `_post` then refuses a draft when they no longer match
`rs_einv_pulled_lines_hash`, the fingerprint (`_rs_pulled_lines_hash`: quantity, amount and VAT
of each line; IDs and names left out) that `_rs_auto_import_pulled_to_bill_lines` and
`_rs_merge_pulled_to_bill_lines` stamp when the bill takes rs.ge's lines (Pull, Reimport Lines,
Import Supplier Correction, Reset to Draft on a re-sent bill); the bill itself is never compared,
so the accountant's edits never block; a bill that had lines before its Pull has no stamp and is
not checked until one Reimport; an empty rs.ge read keeps the snapshots, so the check still runs. New stored column: every
database needs `-u rs_einvoice`; then the draft is posted with the context
`rs_buyer_accept_in_progress`
(which lets `_post` through); `buyer_accept_invoice`
(`acsept_invoice_status`); `_rs_send_succeeded(result, 'acsept_invoice_statusResult')`; the
status is stored, committed and verified; target 7 runs
`_rs_auto_cancel_after_rs_cancellation` on the bill.

`action_rs_buyer_reject` opens `rs.einvoice.reject.wizard`; its `action_confirm` limits the
reason length and calls `_rs_do_buyer_reject(reason)`: lock, refresh, status 1 or 5, no
reconciled payments, `buyer_reject_invoice` (`ref_invoice_status`), the status falls back to
0 or 4, the reason is kept in `rs_einv_rejection_reason`, commit, then a verification read: a
record no longer pending is cancelled locally through `_rs_auto_cancel_after_rs_cancellation`;
a record still pending or unreadable is left posted with a warning that asks the operator to
cancel by hand.

`action_rs_import_supplier_correction`: needs `rs_einv_supplier_k_id` (section 8, step 5);
`_rs_check_cancel_reissue_blockers` lists why the bill cannot be replaced (paid, credit notes,
lock date, foreign currency, already replaced); `_rs_execute_cancel_and_reissue(k_id)`:
`_rs_reissue_verify_correction` reads the correction (status 5 or 8, pointing at this bill's
id), `_rs_reissue_create_draft` copies the bill into a draft in the purchase journal with the
correction's id, lines and operation date, `_rs_reissue_link_original` links the pair and keeps
the original posted (at status 8 it is neutralized at once), `_rs_reissue_post_chatter` cross-references
them, `_rs_reissue_log_and_remind` logs and, while the correction is still at 5, schedules an
Accept reminder; at 8 it schedules the To-Do "Post the corrected bill" on the new draft (the text depends on `rs_einv_reversal_pending_at`: set means the original could not be cancelled). The inbox's Import Selected sends correction rows through
`rs.einvoice.replace.preview`, whose `action_confirm` runs the same per pair in a savepoint.

The inbox (`rs.einvoice.inbox.wizard`): `action_search` calls `get_buyer_invoices` for the
company's taxpayer id (`_resolve_company_un_id`) and the date range, matches each row's seller
TIN to one vendor with `_rs_find_partner_by_tin` (several matches: a note from
`_rs_ambiguous_vendor_note`, not selectable), marks rows already in Odoo;
`action_import_selected` creates a draft bill per ticked original and runs Pull
(`RsBuyerInboxLine._do_import`), and refuses a correction whose original bill is not in Odoo
(`_rs_parent_bill`).

## 11. Guards and invariants

`_rs_validate` (before every seller write, in this order): not skipped; not buyer-side; posted;
company TIN present and digits; partner TIN present and digits; TINs differ; company currency
GEL; invoice date at most `MAX_FUTURE_DAYS` (5) ahead and `MAX_PAST_YEARS` (5) back; a credit
note not dated before its original; at least one product line; no negative quantity on an
invoice except down-payment offsets; native settlement checks (`_rs_check_native_advance_eligibility`) only when
`_rs_uses_native_advance_attach()` holds, and a leftover `native_attach` mode refuses only with attached advances;
every line named and at most `MAX_LINE_NAME_LEN` (255); an FX rate for a foreign currency; no negative-rate tax;
a sale tax with code S in the company; no percent or division tax with a rate above 0 whose Tax Category Code
rs.ge does not map (`RS_VAT_CLASS_BY_TAX_CATEGORY`).

`write` runs four guard steps:

| Step | Refuses | Bypass |
|---|---|---|
| `_rs_write_check_id` | Clearing or replacing `rs_einv_id` | `rs_allow_id_overwrite` (Delete on RS, Resolve Orphan) |
| `_rs_write_check_settlement_mode` | Changing `rs_einv_advance_settlement_mode` once the record left Draft, or switching to net with advances attached | none |
| `_rs_write_check_immutable_fields` | `partner_id`, `currency_id`, `invoice_date`, `reversed_entry_id` on a document on rs.ge (`_RS_IMMUTABLE_AFTER_RS`) | none |
| `_rs_write_check_skip_toggle` | Toggling `rs_einv_skip` on a posted document; unticking clears the reason | none |

Constraints (`account_move_checks.py`): `_check_rs_einv_id_format` (digits, positive),
`_check_rs_skip_consistency` (no Skip on a document with an id),
`_check_rs_skip_vat_neutral_lines` (expense-type reasons: no tax, expense accounts),
`_check_unique_pending_correction` (one filed correction per original). The SQL constraint
`_rs_einv_id_unique_per_company` makes an rs.ge id unique per company.

`create`: ticks `rs_einv_is_advance` on
all-down-payment invoices and their reversals, marks a standalone down-payment offset credit
note Skip (`down_payment`), and picks `native_attach` when the final invoice is eligible
(`_rs_native_advance_eligible`). Note CODE_REVIEW 1.2: the Skip mark comes after the
constraint has already run inside `super().create`.

`unlink`: refuses a document on rs.ge that is not skipped, except a vendor bill whose pasted
id was never pulled. `_post`: refuses an rs.ge bill not yet accepted (unless
`rs_buyer_accept_in_progress`), a vendor draft whose snapshots no longer match `rs_einv_pulled_lines_hash`, a Cancel & Reissue copy before status 7, a credit note on a
replaced original, a credit note whose original is not Confirmed or Corrected or has another
correction in flight (`_rs_check_cn_post_preconditions`), and edited lines on a Sent original
that rs.ge can no longer receive; it also dates a never-posted supplier correction (`rs_einv_replaces_id`, status 5 or 8) today: it is booked in
the month it is accepted, the same month its original is reversed, so the declarations match rs.ge. `button_draft`: refuses the paired reversal of a
correction, then `_rs_raise_if_locked('reset to draft', allow_pending=True)`; `button_cancel`:
`_rs_raise_if_locked('cancel')`. `_rs_raise_if_locked` refreshes and refuses while the record or
a child correction is in `RS_LOCKED_STATES` (1, 2, 3, 5, 6, 8), or when a cancelled record was
buyer-confirmed; `allow_pending` lets a Sent (1) original be reset for line edits, and a vendor
document at 1 or 5 (its local draft changes nothing on rs.ge). The context
`rs_skip_lock_check` is for the module's own reversals only. Like core's `force_delete`, it is a
context switch, not a security boundary: an RPC caller with invoice rights can send it, kept by
decision (2026-10-29) because hardening it would need sudo or an unusual context value.
`_compute_show_reset_to_draft_button` hides Reset to Draft on a bill with an rs.ge id, except a
cancelled one pending again on rs.ge (the supplier re-sent it after our reject); `button_draft`
then merges the re-sent lines into it (`_rs_merge_pulled_to_bill_lines`), so Accept never posts
the rejected lines. Cancelled bills are not refreshed by any cron; a posted bill reversed in an
earlier VAT period after a reject is not covered.

Invariants other code relies on: a document on rs.ge always carries `rs_einv_id` and a
status; `rs_einv_replaces_id` / `rs_einv_replaced_by_id` are a one-to-one pair with
`rs_einv_replacement_mode` on the copy; a pending marker without an id means a possible orphan
and blocks a new Send to RS; the taxpayer id of a company comes from `_rs_company_un_id`, never
from the login.

## 12. Security

| Model | Group | Rights | Domain |
|---|---|---|---|
| `rs.einvoice.log` | `account.group_account_invoice` | cru | company restriction row: `company_id` empty or in the user's companies |
| `rs.einvoice.advance.settlement` | `account.group_account_invoice` | cru | same restriction |
| `rs.einvoice.correction.line` | `account.group_account_invoice` | crud | same restriction |
| the seven wizard models | `account.group_account_invoice` | crud | none (transient) |

`rs.soap.service` and `rs.einvoice.cron` are abstract and need no rows. The invoice form
view has no group: the tab is visible to whoever can open the invoice.

`sudo()` in the module and why it is safe:

- `_rs_partner_un_id` writes the cached taxpayer id on the partner: a lookup result, not user
  input, and the accountant may not have partner write rights.
- The crons search and act as `account.move.sudo()`, then `with_user(responsible).sudo()
  .with_company(company)`: full access for the batch, the responsible user's login and the
  company in the environment for the calls.
- `_rs_company_passes` reads companies with `sudo()` to find the responsible users.
- `_cron_vacuum_rs_logs` deletes old logs and snapshots with `sudo()`.

## 13. Scheduled actions and the dashboard

`_rs_company_passes(label)` returns the `(company, user)` pairs: every company with a Tax ID
whose `res.users._rs_responsible_user(company)` exists; a company without one is logged and
skipped, never served through someone else's login; without `rs_base_methods` the list is
empty and an error is logged.

| Cron | Method | Per company | Notes |
|---|---|---|---|
| Sync Buyer Invoices | `_cron_sync_buyer_invoices(lookback_hours=72)` | one pass per company as its responsible user, root company first, in a savepoint, `_commit_progress` between passes | `_sync_one_user`: `_check_auth`, `_rs_company_un_id`, `get_user_invoices` over the window (rs.ge caps it at 72 h), skips rows not addressed to the company, not buyer-actionable, corrections (`k_type` with status 5 or 8), already imported (in any company with the same Tax ID, so a branch does not repeat its main company's bill), unknown or ambiguous vendor TIN; creates a draft bill in the company's first purchase journal and runs Pull, each row in a savepoint |
| Refresh Buyer Bill Status, Refresh Seller Invoice Status | `_cron_refresh_status(is_buyer_side, batch_size=200)` | one search of `batch_size` moves per company that has a responsible user, so a company without one cannot fill the batch | posted, in `RS_REFRESH_STATUSES` (1, 2, 5, 6, 7, 8), not skipped, oldest `write_date` first; per move `try_lock_for_update` (SKIP LOCKED, an operator's action wins), a savepoint, `_rs_safe_refresh_status`, `_commit_progress(1)` |
| Recover Stranded Cancellations | `_cron_rs_recover_stranded_cancellations` | not needed: no rs.ge call | posted moves at status 7, or originals whose correction copy is at 8, with no reversal and no manual-reversal flag: re-drives the local cancel; a failure sets `rs_einv_reversal_pending_at` so it is not retried every run |
| Escalate Stale Pending Actions | `_cron_escalate_pending_actions(age_hours=24)` | no | chatter + RS Logs once per 24 h on moves with a pending marker older than the age |
| Detect Stuck Buyer Confirmations | `_cron_detect_stuck_sends(age_days=7)` | no | sent invoices still at 1 or 5, and cancellations still at 6, older than the age; `_escalate_stuck_moves` posts once per period |
| Vacuum Logs | `_cron_vacuum_rs_logs` | no | `rs.einvoice.log._cron_vacuum` (90 days, errors 365) and `rs.einvoice.correction.line._cron_vacuum_snapshots` (pulled snapshots, 180 days) |
| Deadline Check (Art.54) | `account.move._cron_rs_einv_check_deadlines` | no | posted customer invoices with a partner TIN, not skipped, not in a done state (`_RS_DEADLINE_DONE_STATES`: sent to the buyer, 1 and 5, or later), dated 30 days ago or more and computed `overdue`; one `[DEADLINE` log line ever per invoice, plus chatter |

`_commit_progress` commits: never exercise these methods in `odoo shell` on a database that
must stay unchanged.

Refresh e-Invoices Status (core, an entry of the Actions menu of the customer invoice list, also
of the list a dashboard journal card opens): `account.journal._compute_show_refresh_out_einvoices_status_button`
turns the core flag on for sales journals of a company the current user holds a tested login for
(`rs_username` and `rs_un_id` read `with_company(journal.company_id)`), and
`button_refresh_out_einvoices_status` calls `rs.einvoice.cron._rs_refresh_seller_statuses(company)`:
up to 200 of the company's posted customer documents in the refresh statuses, as the user who
clicked, a `UserError` per document logged and skipped.

## 14. Tests

```bash
data_venv/bin/python odoo-bin -c odoo.conf -d <test-db> -u rs_einvoice \
    --test-tags /rs_einvoice --stop-after-init
```

The tests are `post_install` and need a database with `rs_base_methods` installed (it holds
the login fields the fixture writes). No call reaches rs.ge: `tests/common.py` puts a zeep
client backed by `SoapTransportStub` in the service's client cache, with the bundled
`tests/test_files/ntosservice.wsdl`, and answers each operation with the recorded envelopes
of `tests/stub_responses.py`; the flows' `cr.commit()` is patched to `flush` for the duration.

| File | Covers |
|---|---|
| `test_seller_flow.py` | Send to RS then Send to buyer against recorded replies (call order, status, series and number); refused credentials; the partner's cached taxpayer id and its reset on a Tax ID change; refusal without a stored company taxpayer id |
| `test_write_guards.py` | The id guard and its audited bypass, the settlement-mode lock |
| `test_buyer_inbox.py` | Inbox search matching the vendor by TIN; a correction refused before its original |

`SoapTransportStub` records the operations called (`transport.calls`) and takes a list of
replies for an operation called several times.

## 15. Extending safely

- **Get the service through `_rs_get_service()`** on the document, never
  `self.env['rs.soap.service']` bare: the company binding is what selects the login and the
  taxpayer id. In a cron, set `with_user(responsible).sudo().with_company(company)` first.
- **Taxpayer ids only through `_rs_company_un_id()` and `_rs_partner_un_id(partner)`.** Never
  send the login's own id as the seller.
- **Keep the write shape**: lock, checks, `_rs_mark_pending` for a call that creates something
  on rs.ge, the call, store, commit, `_rs_relock_after_commit`, tail. After the commit log and
  warn, do not raise: rs.ge already has the change.
- **Errors survive the rollback of a failed rs.ge call.** The `error` rows of `_rs_log`
  (warnings are not kept: they may describe work the rollback undid), the partial-sync flag
  (`_rs_mark_lines_partial`) and the chatter and To-Do of an `error` `_rs_notify` are queued by
  `_rs_keep_after_rollback` on the cursor's `postrollback` hook, which re-runs them in a new
  cursor only if the transaction is rolled back; a commit drops the queue. Two limits: a
  failure caught inside a savepoint whose transaction then commits (the auto-sync of sent edits
  during Post, `_rs_auto_sync_pending_sent_edits`) still loses the partial flag and the To-Do;
  on a concurrency retry of the request the failed attempt's error rows are kept too.
- **A new list operation goes through `_call_datatable`**; a new write operation catches the
  zeep `Fault` and raises a `UserError` naming the operation.
- **A new status or status group** is added to `RS_STATUS` and the tuples next to it in
  `account_move.py`; the view's `invisible` expressions list statuses explicitly.
- **New constraints go in `account_move_checks.py`, new local reactions in
  `account_move_cancel.py`**, seller calls in `account_move_seller.py`, buyer calls in
  `account_move_buyer.py`; `account_move.py` keeps fields, guards and shared helpers.
- **The bypass context keys are the only way through the guards.** A new internal write that
  must pass them uses the same keys, so the audit line is written.
- **Do not put credentials on `res.company`.** The rs.ge logins are personal and the REST side
  (`rs_base_methods`) pairs a device per user; the company scoping is the company-dependent
  storage on the user.
- **Tests**: record the reply once in `stub_responses.py` and assert on `transport.calls`; never
  call rs.ge from a test.

## 16. Known limitations

- Three hand-rolled success checks remain next to `_rs_send_succeeded` (CODE_REVIEW 4.3).
- The shared zeep client and session are fine under prefork workers and not documented
  thread-safe (CODE_REVIEW 4.14).
- Accept checks that rs.ge's lines did not change, not the operator's own edits to the amounts
  (1.3); excise is always 0.
- Company checks are strict equality; branches (a child company on the document, the parent on
  the user) are not handled (CODE_REVIEW 3.4).
- The per-company login texts have no Georgian translation yet.

## 17. Upgrading an existing database

The logins moved from one slot per user to one per user and company. After `-u
rs_base_methods` (which loads this module too), the old values are not migrated: every user
re-enters the username and password in each company and clicks **Test SOAP (e-invoice)**,
which stores the company's taxpayer id; one user per company is ticked **RS Responsible User**,
otherwise the crons skip that company. Partner taxpayer ids fill themselves on first use.
