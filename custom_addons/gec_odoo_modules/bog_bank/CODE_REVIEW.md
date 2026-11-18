# bog_bank code review (2026-10-28 → 2026-10-30)

Confidence tags: [Certain] = read in source or reproduced in a test; [Likely] = strong inference; [Guessing] = gap-filling.
Audit of `bog_bank` and `tbc_bank` together (2026-10-28 → 2026-10-30); many fixes live in the shared module `gec_bank`.
No new tests were written for these fixes (the rule was: ask first); the existing suites pass (section 6).

---

## 1. Fixed — both banks, mostly in `gec_bank` (this commit)

- [x] C1. [Certain] Any Invoicing user could send, reset, cancel or confirm bank transfers → the bank User group is
  required: `_gec_bank_user_group_for` / `_gec_bank_check_user` in check_transfer, confirm manual, reset, recover,
  cancel, batch send and cancel, plus `groups=` on the buttons. The refusal is an AccessError, checked once for a
  multi-send. **Payroll Administrators who send salary batches need the bank User group too.**
- [x] C2. [Certain] A login failure after the claim left payments stuck in "Sending" → the token is fetched before the
  claim.
- [x] C3. [Certain] No `neutralize.sql`: a production copy kept working bank access → `data/neutralize.sql` (connection
  blocked, no secret or token).
- [x] C4. [Certain] Reset to Pending kept the old request id, so a resend looped → reset of a Failed transfer with a
  bank reference clears the request id (before the state). **Not confirmed with the banks that every "failed" state is
  final; a non-final one could pay twice.**
- [x] M-T4. Maker/checker used only `create_uid`; an approver could edit a clerk's payment and approve it alone → new
  field `gec_bank_prepared_by` (set on every change of amount, recipient, purpose); the approver check refuses the
  creator and the last changer (`gec_bank_approval_mixin._gec_bank_check_approver`).
- [x] M-B5. A journal's bank account / BIC could change while payments on it were at the bank → refused
  (`_gec_bank_check_bank_kept`, `account.journal.write`, `res.partner.bank.write`).
- [x] M-T3. The status poll wrote without a state condition and could overwrite a statement confirmation → the polls
  write only over the state they read (`_durable_write(..., expected_state=...)`, context `gec_bank_poll`).
- [x] M-B8, M-T2. 401/429 on a send turned the payment Failed/Rejected → the claim is given back
  (`_gec_bank_release_claim`); on a batch the previous batch state comes back.
- [x] M-B6, M-B7. Upload log stored the dict key instead of the file name; `refresh_token` / `id_token` not redacted →
  file names logged, both tokens redacted.
- [x] Docs: READMEs (groups, reset, confirm, unknown), gec_bank README_DEV (version, nine models, undo list, confirm),
  developer maps' version.

## 2. Fixed — bog_bank (this commit)

- [x] B2. [Certain] Batch send result was not saved durably: the package was orphaned at BOG → every login write is one
  own-cursor UPDATE (`_gec_bank_write_connection`); a batch that lost its key takes it back from its members
  (`_bog_adopt_orphan_package`, also run by the bulk cron); `flush_all()` before the swallowing savepoints.
- [x] B3. [Certain] Core "Reject" was not blocked and the payment could get stuck → `action_reject` fenced like
  `action_cancel` (gec_bank).
- [x] B4. [Certain] Warning-code transfers were resent without "Create Anyway" → `_bog_check_sendable` refuses
  awaiting-confirmation unless context `bog_create_anyway`; the batch skips them.
- [x] B5. [Certain] One failed re-login stopped all BOG crons silently → the crons take connections in state active or
  error.
- [x] B6. [Certain] Confirm Manually allowed on unsigned "Created" documents → only on Sent, with a confirm dialog.
- [x] B7 / F6. PayerInn no longer sent (`_bog_payer_inn` removed; `test_payer_inn_is_not_sent`).
- [x] B7 / F5. Foreign transfers refused before any send (`_gec_bank_check_instructions`) until a foreign builder exists.
- [x] M-B1. Status letter `N` no longer posts an "unrecognised status" note every poll.
- [x] M-B2. The 10,000 GEL BULK cap applies to every domestic GEL BOG payment, not only payroll.
- [x] M-B3. A payment whose currency differs from the journal account's currency is refused.
- [x] M-B4. A package line with a result code BOG did not fail posts one chatter note with the code's meaning.
- [x] M-B10. The batch claim is undone on any exception (it caught only UserError).
- [x] Docs: `bog.md` F-status and method links.

## 3. Open (need BOG's answers or a decision)

- [ ] B1. Pre-Oct-4 BOG transfer data was never copied on upgrade: repair SQL only (section 5); run it on client DBs.
- [ ] Ask BOG: is PayerInn really unwanted (F6/Q7); the foreign document spec (F5); currency and ResultCode meaning
  (M-B3, M-B4); whether package state `C` is final (C4).
- [ ] M-B9. A BOG User with only Invoicing rights cannot import statements: kept, README says so.
- [ ] On Create Anyway + 401/429, the BOG warning text in Bank Error is replaced by the 401/429 text (code stays).

## 4. Checked, not a defect

- M-B11. Raw BOG error texts are stored; no secrets found in them.

## 5. Before deploying

- Add every user who sends, resets, recovers or confirms transfers (Payroll Administrators sending salary batches
  included) to the bank's User group. Only the admin is in the bank groups after install.
- Data repair for old upgrades is a hand-run SQL file, not a migration (no migration scripts rule):
  `bank_repair_sql_2026-10-28.sql` (checks the columns, prints counts, ends with ROLLBACK; COMMIT only after checking).
  Dry run on `gec_main`: nothing to repair. Run it on each client database.

## 6. Run the tests

Scratch DB, dropped afterwards:
```
docker exec odoo20_odoo sh -c 'cd /opt/odoo && python odoo-bin -c /etc/odoo.conf --db_host odoo20_db \
  --db_user odoo --db_password odoo -d bank_tmp -i gec_bank,bog_bank,tbc_bank --test-enable \
  --test-tags /gec_bank,/bog_bank,/tbc_bank --stop-after-init --http-port=8079'
docker exec odoo20_db dropdb -U odoo --force bank_tmp
```
Test suites share the transaction with the "own" cursor, so they cannot catch own-cursor conflicts; only a probe on a
real cursor can (done for the token write: draft → active, no error).
