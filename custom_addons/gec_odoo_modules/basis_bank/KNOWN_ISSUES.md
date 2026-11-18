# basis_bank — Open Issues

> Re-checked on 2026-09-23 against the Odoo 20 code (module version 20.0.1.15.0), after the Odoo 20
> port and the fix round. Items B7-B10 and C3-C6 were added, and B1, C1 and E corrected, on 2026-09-25 from the
> verified developer-map analysis (commit 3ab74d7). Fixed items are removed from this file, not marked.
> Line numbers were re-checked on 2026-10-03 against the working tree; re-check after edits.
> 2026-10-02: B7 fixed; a batch in Unknown or Failed has a Reset to Pending that resends only its pending members; the log table is vacuumed like TBC's (`log_retention_days`).
> 2026-10-03: A1, A2, B1, B8 and B9 fixed (48-hour check only flags; the statement import reconciles the line it matches; each payment is claimed durably before the upload; `gec_bank` fills the Outstanding account on every new Basis method line). C3 narrowed to core Reject. C7 added; the statement import now also reconciles payments Resync or the 48-hour check confirmed earlier.
> 2026-11-17: B5 fixed: a single send's reply without our `ClientInternalID` leaves the payment *Unknown*.
> 2026-11-16: B10 fixed: the import passes `import_file`, so core's auto-reconcile of more than 80 lines no longer commits inside it.

---

## A. Accounting risks

### A3. Historical payments become sendable when a connection is created

| | |
|---|---|
| Where | [models/account_payment.py:101](models/account_payment.py#L101) `_compute_basisbank_state` |
| What happens | Creating the connection turns every outbound payment already on the company's Basis journals into *Pending*. A posted, unmatched old payment then shows *Send to Basis Bank*, and sending it would pay again. It needs a deliberate OTP send, and v19 had the same exposure (the state defaulted to *Pending* on every payment). |
| Proposed fix | Create the connection before the first payments on the journal, or only give *Pending* to draft payments. |

---

## B. Flows

### B2. Package payments are matched by document number only

- Where: package replies carry no per-payment bank reference ([models/account_batch_payment.py](models/account_batch_payment.py) `_basisbank_apply_response`)
- What happens: confirmation relies on the bank echoing `DocNum` (the Odoo payment id); a transfer made outside Odoo with the same `DocNum`, same amount and same debit IBAN would match. Whether the report shows one line per package item is an open question with the bank.

### B3. No statement balance control

- Where: [wizard/basisbank_statement_import_wizard.py:118](wizard/basisbank_statement_import_wizard.py#L118) `_build_line_vals`
- What happens: imported statements carry no opening/closing balance, so Odoo's balance check never fires; items without `BankInternalID` are skipped with a counter only. The GetReport API returns no balances ([basisbank_api.md](../../../basisbank_api.md) §5), so this can only be improved by surfacing the skipped items (chatter on the journal).

### B4. Bank code 6 (service suspended) marks payments Failed

- Where: [models/account_payment.py:463](models/account_payment.py#L463), [models/account_batch_payment.py:333](models/account_batch_payment.py#L333) (any non-zero code outside the retry/unknown sets rejects)
- Decide whether code 6 should park payments in *Unknown* or keep them retryable instead.

---

## C. Access, multi-company and open questions

### C1. Approver company is filtered in the form only

- Where: [models/basisbank_connection.py:44](models/basisbank_connection.py#L44) `approval_id` domain `company_id = company_id` and `check_company=True`
- The form offers only approver records of the connection's own company, so a branch connection cannot pick its parent's approver there. The model does not set `_check_company_auto`, so nothing enforces it on save: code or an import can store another company's approver.

### C2. Open question: concurrent bank sessions

- If parent and branch (or two companies) ever share one bank client's credentials, each connection keeps its own ticket; if the bank allows only one session, they would invalidate each other (code 3 loops on sends). Ask the bank before any two-connection-per-client setup.

### C3. Core Reject passes the sent-payment guard

- Where: `gec_bank` guards reset to draft, cancel and delete of the payment and of its journal entry (`_gec_bank_check_not_at_bank`); core Reject (`action_reject`, addons/account/models/account_payment.py:1229) is not guarded, and the guard lifts when the journal stops being a Basis journal (connection deleted).
- A payment rejected that way keeps `basisbank_state = sent`, and a matching statement line later marks it confirmed ([models/account_bank_statement_line.py](models/account_bank_statement_line.py) does not filter on `state`).

### C5. Approvers outside the Basis User group see Approve but cannot use it

- Where: `basisbank_can_approve` reads the approval with sudo ([models/account_payment.py:272](models/account_payment.py#L272)); `action_basisbank_approve` does not ([models/account_payment.py:363](models/account_payment.py#L363)); approval read access is Basis User only ([security/ir.access.csv](security/ir.access.csv))
- A named approver without the Basis User group gets an access error on the button that was shown to them. Same for batches.

### C6. A failed send leaves the OTP in the dialog row

- Where: [wizard/basisbank_otp_wizard.py:30](wizard/basisbank_otp_wizard.py#L30)
- The web client saves the dialog record in its own request before calling the button (addons/web/static/src/views/form/form_controller.js:726-735). The dialog deletes itself before sending, but when the send is refused before the payments are claimed (state, approval, checks, login), the rollback restores the row with the OTP in plain text until the transient autovacuum removes it.

### C7. Basis Bank users without accounting rights cannot import statements

- Where: [security/basisbank_groups.xml:18](security/basisbank_groups.xml#L18) — *Basis Bank / User* implies only `account.group_account_invoice`; the import creates the statement as the user through core `_create_bank_statements` ([wizard/basisbank_statement_import_wizard.py:88](wizard/basisbank_statement_import_wizard.py#L88))
- Creating `account.bank.statement` and its lines needs `account.group_account_basic` (addons/account/security/ir.access.csv:24, :28), so a Basis user with only Invoicing gets an access error on **Import Statement**. Bookkeepers and accountants are not affected, nor is the daily sync (cron). TBC and BOG users have the same limit.
- Decide: make the bank user groups imply `account.group_account_basic`, or keep imports for accounting users.

---

## D. Code quality

| # | Item | Where | Action |
|---|---|---|---|
| D1 | Send pipeline duplicated on payment and batch (checks, auth, durable claim, reply recording) | [models/account_payment.py](models/account_payment.py) `basisbank_send_with_otp`, [models/account_batch_payment.py](models/account_batch_payment.py) `basisbank_send_with_otp` | Move the skeleton into `basisbank.sendable`; keep per-model build/apply |
| D2 | Ticket expiry is refreshed after error replies too | [services/basisbank_service.py:267](services/basisbank_service.py#L267) | Refresh only on success |

---

## E. Verified strengths — do not "fix" these

- No custom journal entries anywhere: all GL via standard `action_post`, standard payment register, standard statement lines.
- Send path: every payment is claimed durably before the upload and every answer is written the same way (`gec.bank.service`), so a crash or a re-run of the request cannot send twice (real-cursor probe, 2026-10-03); every uncertain outcome parks in `unknown` + Resync instead of guessing; a wrong OTP changes no accounting.
- A rejection keeps the entry (core's Rejected, as core's online payment maps it), so no bill or payslip is reopened silently.
- The 48-hour check never changes accounting: it flags the payment and creates an activity.
- Reset to Pending re-checks the bank report first — a resend cannot duplicate an executed transfer.
- One report-matching rule for resync, Reset to Pending and the 48h cron (`_basisbank_match_report_items`): bank reference before document number, our debit IBAN when both sides carry one, exact amount. Imported statement lines use their own rule in `_basisbank_auto_match` (same journal, bank reference, then document number for payments without one, amount).
- Send-time setup check refuses methods without a reconcilable outstanding account, so the confirmation flow cannot silently break.
- Core batch Validate button hidden for Basis batches (no file-export path).
- OTP not kept after a successful send (see C6 for a failed one); credentials/ticket redacted in API logs; `unique_import_id` dedup backed by a DB unique constraint; sudo-writing helpers not callable over RPC.

---

## Checked on the Odoo 20 test database (2026-09-23)

The module was installed on a throwaway database (`gec20_basisbank_test`) with the real basis_bank code, the real gec_payroll_bank Python code and the real IBAN-fill file of gec_localization (their unrelated v20 view/chart issues set aside). The two module tests pass, and a smoke run passed 38 of 39 checks; the one failure is B6.
