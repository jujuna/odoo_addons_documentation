# tbc_bank code review (2026-10-28 → 2026-10-30)

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

## 2. Fixed — tbc_bank (this commit)

- [x] T1. [Certain] The 20.0.1.6.0 pre-migrate wrote "Pending" on every payment of the database → it copies only
  outbound `tbc_transfer` rows, and only into empty or computed-pending columns. **A client already on 20.0.1.6.0 does
  not run it again: use the T1 part of the repair SQL there.**
- [x] T2. [Likely] Recover on an Unknown transfer could create a second transfer → "not found" moves it to Pending only
  15 minutes after the last write.
- [x] T3. [Certain] Any Treasury Code on a contact skipped the trusted-account check → `_gec_bank_treasury_transfer`
  hook; only transfer type Treasury skips it.
- [x] T4. [Certain] Confirm Manually was accepted on Unknown → only on Sent (README wins over TESTING.md, which is
  updated), with a confirm dialog; Reset to Pending also asks first.
- [x] M-T1. A request id collision aborted the batch → the request id is drawn again on collision.
- [x] M-T6. Status confirmation sets `gec_bank_confirmed_source = 'status'`.
- [x] M-T7. A contact's Treasury Code change now recomputes the Treasury Code and transfer type of its **Pending** TBC
  transfers only (`models/res_partner.py`, new).
- [x] Docs: TESTING.md sections 11-12, method links in BIS_API.md.
- Test fixture: `tests/test_tbc.py` setUpClass stores a valid token (sends log in before the claim now).

## 3. Open (need TBC's answers or a decision)

- [ ] Ask TBC whether 'Error' and 'Cancelled' are final (C4).

## 4. Checked, not a defect

- M-T5. Transfer log rows are kept on purpose (audit trail).

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
