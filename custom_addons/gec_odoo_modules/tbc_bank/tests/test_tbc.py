from datetime import date, timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.models import get_public_method
from odoo.tests import Form
from odoo.tests.common import TransactionCase, new_test_user, tagged

from odoo.addons.gec_bank.models.account_payment import GEC_BANK_TRANSFER_FIELDS


@tagged('post_install', '-at_install')
class TestTbc(TransactionCase):
    """Unit tests for the TBC Bank integration; the HTTP layer is always mocked."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Test mode: registry.cursor() must share this transaction, or independent-cursor writes block on its row lock.
        cls.enterClassContext(cls.registry_test_mode())
        cls.company = cls.env.company
        cls.service = cls.env['tbc.service']

        # One connection per company: reuse a real one if it exists; the rollback restores it.
        connection_vals = {
            'client_id': 'test-client-id',
            'client_secret': 'test-secret',
            'environment': 'test',
            'api_host': False,
            'processing_mode': 'direct',
            'state': 'draft',
            # A valid token: a send logs in before it claims the payment, and the tests mock only the bank calls.
            'access_token': 'test-token',
            'token_expiry': fields.Datetime.now() + timedelta(hours=1),
        }
        Connection = cls.env['tbc.connection']
        cls.connection = Connection.search([('company_id', '=', cls.company.id)], limit=1)
        if cls.connection:
            cls.connection.write(connection_vals)
        else:
            cls.connection = Connection.create(dict(connection_vals, company_id=cls.company.id))

        cls.company_bank = cls.env['res.partner.bank'].create({
            'account_number': 'GE29TB7777777777777701',
            'partner_id': cls.company.partner_id.id,
            'bank_bic': 'TBCBGE22',
        })
        cls.journal = cls.env['account.journal'].create({
            'name': 'TBC GEL', 'type': 'bank', 'code': 'TBCTG',
            'bank_account_id': cls.company_bank.id,
        })

        method = cls.env.ref('tbc_bank.account_payment_method_tbc')
        cls.method_line = cls.env['account.payment.method.line'].search([
            ('journal_id', '=', cls.journal.id),
            ('payment_method_id', '=', method.id),
        ], limit=1)
        if not cls.method_line:
            cls.method_line = cls.env['account.payment.method.line'].create({
                'name': method.name,
                'payment_method_id': method.id,
                'journal_id': cls.journal.id,
            })

        cls.partner = cls.env['res.partner'].create({'name': 'Test Beneficiary'})
        cls.partner_bank = cls.env['res.partner.bank'].create({
            'account_number': 'GE29TB9999999999999999',
            'partner_id': cls.partner.id,
            'bank_bic': 'TBCBGE22',
            'allow_out_payment': True,
        })
        cls.startClassPatcher(patch.object(type(cls.env['tbc.service']), 'get_single_transfer_status', return_value={}))

    def _new_payment(self, post=True, **vals):
        """A TBC payment, confirmed by default: only those may be sent."""
        base = {
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'journal_id': self.journal.id,
            'partner_id': self.partner.id,
            'partner_bank_id': self.partner_bank.id,
            'payment_method_line_id': self.method_line.id,
            'amount': 20.5,
            'memo': 'test transfer',
            'tbc_transfer_type': 'internal',
        }
        bank_vals = {key: vals.pop(key) for key in list(vals) if key in GEC_BANK_TRANSFER_FIELDS}
        base.update(vals)
        payment = self.env['account.payment'].create(base)
        if bank_vals:
            payment._gec_bank_internal_write(bank_vals)
        if post:
            payment.action_post()
        return payment

    def test_redaction_masks_secrets(self):
        redacted = self.service._redact_data({
            'client_secret': 'x', 'access_token': 'y', 'Authorization': 'z', 'keep': 1,
        })
        self.assertEqual(redacted['client_secret'], '[REDACTED]')
        self.assertEqual(redacted['access_token'], '[REDACTED]')
        self.assertEqual(redacted['Authorization'], '[REDACTED]')
        self.assertEqual(redacted['keep'], 1)

    def test_format_dt_and_date(self):
        self.assertEqual(self.service._format_dt(date(2026, 6, 1)), '2026-06-01T00:00:00')
        self.assertEqual(self.service._format_date(date(2026, 6, 1)), '2026-06-01T00:00:00')
        self.assertEqual(self.service._format_date(date(2026, 6, 1), end_of_day=True),
                         '2026-06-01T23:59:59')

    def test_url_building(self):
        self.assertEqual(self.service._host(self.connection), 'test-api.tbcbank.ge')
        self.assertEqual(self.service._token_url(self.connection),
                         'https://test-api.tbcbank.ge/oauth/token')
        self.assertEqual(self.service._api_url(self.connection, 'accounts/movements'),
                         'https://test-api.tbcbank.ge/bab/v1/accounts/movements')

    def test_token_cache(self):
        self.connection.store_token('tok-123', 3600)
        self.assertTrue(self.connection.token_is_valid())
        self.assertEqual(self.connection.sudo().access_token, 'tok-123')
        self.connection.clear_token()
        self.assertFalse(self.connection.token_is_valid())

    def test_token_methods_cannot_be_called_over_rpc(self):
        for name in ('store_token', 'clear_token', 'token_is_valid'):
            with self.assertRaises(AccessError):
                get_public_method(self.connection, name)

    def test_test_connection_needs_write_access(self):
        reader = new_test_user(self.env, login='tbc_reader', groups='base.group_user,tbc_bank.group_tbc_user')
        with self.assertRaises(AccessError):
            self.connection.with_user(reader).action_test_connection()

    def test_build_order_transfer_type_and_fields(self):
        payment = self._new_payment(gec_bank_request_id='820032080')
        order = payment._tbc_build_order()
        self.assertEqual(order['transferType'], 'TransferWithinBank')
        self.assertEqual(order['transferExternalId'], '820032080')
        self.assertEqual(order['debitAccount']['accountNumber'], 'GE29TB7777777777777701')
        self.assertEqual(order['creditAccount']['accountNumber'], 'GE29TB9999999999999999')
        self.assertEqual(order['amount']['amount'], 20.5)
        self.assertEqual(order['description'], 'test transfer')

    def test_build_order_national_carries_the_tax_code(self):
        payment = self._new_payment(
            tbc_transfer_type='national', tbc_beneficiary_tax_code='405123456')
        order = payment._tbc_build_order()
        self.assertEqual(order['transferType'], 'TransferToOtherBankNationalCurrency')
        self.assertEqual(order['beneficiaryTaxCode'], '405123456')
        self.assertNotIn('treasuryCode', order)
        self.assertNotIn('chargeDetails', order)

    def test_build_order_treasury_carries_taxpayer_fields(self):
        """Treasury transfers are how Georgian companies pay the state."""
        payment = self._new_payment(
            tbc_transfer_type='treasury',
            tbc_treasury_code='101001000',
            tbc_taxpayer_code='405123456',
            tbc_taxpayer_name='GEC Business LLC',
        )
        order = payment._tbc_build_order()
        self.assertEqual(order['transferType'], 'TreasuryTransfer')
        self.assertEqual(order['treasuryCode'], '101001000')
        self.assertEqual(order['taxpayerCode'], '405123456')
        self.assertEqual(order['taxpayerName'], 'GEC Business LLC')
        self.assertNotIn('beneficiaryTaxCode', order)
        self.assertNotIn('beneficiaryBankCode', order)

    def test_build_order_foreign_carries_swift_fields(self):
        payment = self._new_payment(
            tbc_transfer_type='foreign',
            tbc_beneficiary_name='Acme GmbH',
            tbc_beneficiary_address='Musterstr 1, Berlin',
            tbc_beneficiary_bank_code='DEUTDEFF',
            tbc_beneficiary_bank_name='Deutsche Bank',
            tbc_intermediary_bank_code='CHASUS33',
            tbc_intermediary_bank_name='JPMorgan Chase',
            tbc_charge_details='OUR',
        )
        order = payment._tbc_build_order()
        self.assertEqual(order['transferType'], 'TransferToOtherBankForeignCurrency')
        self.assertEqual(order['beneficiaryName'], 'Acme GmbH')
        self.assertEqual(order['beneficiaryAddress'], 'Musterstr 1, Berlin')
        self.assertEqual(order['beneficiaryBankCode'], 'DEUTDEFF')
        self.assertEqual(order['beneficiaryBankName'], 'Deutsche Bank')
        self.assertEqual(order['intermediaryBankCode'], 'CHASUS33')
        self.assertEqual(order['intermediaryBankName'], 'JPMorgan Chase')
        self.assertEqual(order['chargeDetails'], 'OUR')
        self.assertNotIn('treasuryCode', order)

    def test_build_order_drops_empty_optional_fields(self):
        """TBC rejects null fields, so empties must not be sent at all."""
        payment = self._new_payment(tbc_transfer_type='foreign')
        order = payment._tbc_build_order()
        for key in ('beneficiaryAddress', 'beneficiaryBankCode',
                    'intermediaryBankCode', 'chargeDetails'):
            self.assertNotIn(key, order)

    def test_debit_currency_follows_the_account_not_the_payment(self):
        """A SWIFT payment declares the debit account in the account's own currency."""
        company_currency = self.journal.company_id.currency_id
        # active_test=False: a fresh database has only the company currency active.
        other = self.env['res.currency'].with_context(active_test=False).search(
            [('id', '!=', company_currency.id)], limit=1)
        self.assertTrue(other, "need a second currency to test with")
        other.active = True
        self.env['res.currency.rate'].create({
            'currency_id': other.id,
            'rate': 2.0,
            'name': '2026-01-01',
            'company_id': self.journal.company_id.id,
        })
        payment = self._new_payment(
            tbc_transfer_type='foreign', currency_id=other.id)
        order = payment._tbc_build_order()

        self.assertEqual(order['amount']['currency'], other.name)
        self.assertEqual(order['creditAccount']['accountCurrencyCode'], other.name)
        self.assertEqual(order['debitAccount']['accountCurrencyCode'],
                         company_currency.name,
                         "the debit account keeps its own currency")

    def test_build_order_description_fallback(self):
        payment = self._new_payment(memo=False)
        order = payment._tbc_build_order()
        self.assertTrue(order['description'], "description must never be empty")

    def _mock_send(self, return_value):
        return patch.object(type(self.service), 'import_single_transfer',
                            return_value=return_value)

    def test_send_refuses_an_untrusted_account_before_calling_the_bank(self):
        """A recipient account nobody trusted is refused before anything reaches TBC."""
        payment = self._new_payment()
        self.partner_bank.allow_out_payment = False
        with self._mock_send({'http_status': 200,
                              'data': {'succeeded': [{'transferId': 1}], 'failed': []},
                              'error_text': ''}) as sent:
            with self.assertRaisesRegex(UserError, 'not trusted'):
                payment._tbc_send_one()
        self.assertFalse(sent.called)
        self.assertNotIn(payment.gec_bank_state, ('sending', 'sent'))

    def test_send_success(self):
        payment = self._new_payment()
        with self._mock_send({'http_status': 200,
                              'data': {'succeeded': [{'transferId': 19806}], 'failed': []},
                              'error_text': ''}):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_state, 'sent')
        self.assertEqual(payment.gec_bank_reference, '19806')

    def test_send_business_failure(self):
        payment = self._new_payment()
        with self._mock_send({'http_status': 200,
                              'data': {'succeeded': [],
                                       'failed': [{'errors': ["'Description' must not be empty."]}]},
                              'error_text': ''}):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_state, 'failed')
        self.assertIn('Description', payment.gec_bank_error)

    def test_confirm_manual(self):
        payment = self._new_payment()
        payment._gec_bank_internal_write({'gec_bank_state': 'sent'})
        payment.action_tbc_confirm_manual()
        self.assertEqual(payment.gec_bank_state, 'confirmed')
        self.assertEqual(payment.gec_bank_confirmed_source, 'manual')

    def test_external_id_is_written_before_the_post(self):
        """The idempotency key is persisted BEFORE the money-moving POST, else a crash leaves nothing for
        Recover from TBC to look up. No assertRaises: its savepoint rollback would discard the reservation."""
        payment = self._new_payment()
        self.assertFalse(payment.gec_bank_request_id)
        crash = patch.object(type(self.service), 'import_single_transfer',
                             side_effect=RuntimeError("worker killed mid-POST"))
        with crash:
            try:
                payment._tbc_send_one()
            except RuntimeError:
                pass
            else:
                self.fail("the mocked send was expected to raise")

        # Raw read without flush: the independent cursor must have written it already.
        self.env.cr.execute(
            "SELECT gec_bank_request_id, gec_bank_state FROM account_payment WHERE id = %s",
            (payment.id,))
        external_id, state = self.env.cr.fetchone()
        self.assertTrue(external_id,
                        "the idempotency key must be committed before the POST")
        self.assertEqual(state, 'sending',
                         "a crashed send must stay 'sending', not fall back to 'pending'")

    def test_reserve_blocks_a_second_send(self):
        """The conditional UPDATE is the mutex: the second claim finds nothing."""
        payment = self._new_payment()
        external_id = payment._gec_bank_reserve_send()['gec_bank_request_id']
        self.assertTrue(external_id)
        with self.assertRaises(UserError):
            payment._gec_bank_reserve_send()
        self.assertEqual(payment.gec_bank_request_id, external_id,
                         "a blocked second claim must not rotate the key")

    def test_resend_after_failure_reuses_external_id(self):
        """A resend carries the SAME transferExternalId so TBC can deduplicate."""
        payment = self._new_payment()
        with self._mock_send({'http_status': 400, 'data': {},
                              'error_text': 'Debit account not assigned'}):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_state, 'failed')
        self.assertEqual(payment.state, 'rejected')
        first_id = payment.gec_bank_request_id
        self.assertTrue(first_id)

        payment.action_draft()
        payment.action_post()
        payment.action_tbc_reset_to_pending()
        with self._mock_send({'http_status': 200,
                              'data': {'succeeded': [{'transferId': 4242}], 'failed': []},
                              'error_text': ''}):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_request_id, first_id,
                         "resend must reuse the key, or TBC sees a new transfer")
        self.assertEqual(payment.gec_bank_state, 'sent')

    def test_send_requires_approval_when_mode_is_odoo_approve(self):
        """Approval is checked before anything is reserved or transmitted."""
        approval = self.env['tbc.approval'].create({
            'approver_id': self.env.user.id,
            'company_id': self.company.id,
        })
        # One write: the constraint fires if processing_mode changes alone.
        self.connection.write({
            'processing_mode': 'odoo_approve',
            'approval_id': approval.id,
        })
        payment = self._new_payment()
        # try/except, not assertRaises: its savepoint rollback would clear the key and hide a burned one.
        try:
            payment._tbc_send_one()
        except UserError as exc:
            self.assertIn('must be approved', str(exc))
        else:
            self.fail("sending without approval was expected to raise")

        payment.invalidate_recordset(['gec_bank_request_id', 'gec_bank_state'])
        self.assertFalse(payment.gec_bank_request_id,
                         "a rejected send must not burn an idempotency key")
        self.assertEqual(payment.gec_bank_state, 'pending')

    def _set_approval_mode(self, approver, allow_self=False):
        approval = self.env['tbc.approval'].create({
            'approver_id': approver.id,
            'company_id': self.company.id,
        })
        # One write: the constraint fires if processing_mode changes alone.
        self.connection.write({
            'processing_mode': 'odoo_approve',
            'approval_id': approval.id,
            'allow_self_approval': allow_self,
        })
        return approval

    def test_creator_cannot_approve_own_transfer(self):
        """Maker-checker is the point of the feature; self-approval defeats it."""
        self._set_approval_mode(self.env.user)
        payment = self._new_payment()
        payment.action_tbc_submit_approval()
        self.assertEqual(payment.gec_bank_state, 'awaiting_approval')
        with self.assertRaisesRegex(UserError, 'you cannot approve it'):
            payment.action_tbc_approve()

    def test_self_approval_allowed_when_explicitly_enabled(self):
        self._set_approval_mode(self.env.user, allow_self=True)
        payment = self._new_payment()
        payment.action_tbc_submit_approval()
        payment.action_tbc_approve()
        self.assertEqual(payment.gec_bank_state, 'approved')
        self.assertEqual(payment.gec_bank_approved_by, self.env.user)

    def _second_approver(self, login):
        """A second user who can act on payments, through group_tbc_manager."""
        return self.env['res.users'].create({
            'name': 'Second Approver', 'login': login,
            'group_ids': [(6, 0, [self.env.ref('tbc_bank.group_tbc_manager').id])],
        })

    def test_approve_moves_out_of_awaiting_approval(self):
        """Otherwise the 'Pending TBC Approval' list never clears."""
        other = self._second_approver('tbc_second_approver')
        self._set_approval_mode(other)
        payment = self._new_payment()
        payment.action_tbc_submit_approval()
        payment.with_user(other).action_tbc_approve()
        self.assertEqual(payment.gec_bank_state, 'approved')
        pending = self.env['account.payment'].search([
            ('id', '=', payment.id), ('gec_bank_state', '=', 'awaiting_approval')])
        self.assertFalse(pending, "an approved transfer must leave the pending list")

    def test_editing_amount_revokes_approval(self):
        other = self._second_approver('tbc_third_approver')
        self._set_approval_mode(other)
        payment = self._new_payment()
        payment.action_tbc_submit_approval()
        payment.with_user(other).action_tbc_approve()
        self.assertEqual(payment.gec_bank_state, 'approved')
        payment.amount = 999.0
        self.assertEqual(payment.gec_bank_state, 'pending',
                         "changing the amount must void the approval")
        self.assertFalse(payment.gec_bank_approved_by)

    def test_multi_send_reports_failures(self):
        """A multi-select send must never silently drop transfers."""
        good = self._new_payment()
        # Not a TBC transfer: _tbc_send_one raises UserError for it.
        bad = self._new_payment()
        bad._gec_bank_internal_write({'gec_bank_state': 'confirmed'})
        with self._mock_send({'http_status': 200,
                              'data': {'succeeded': [{'transferId': 501}], 'failed': []},
                              'error_text': ''}):
            result = (good | bad).action_tbc_send()
        self.assertIsInstance(result, dict, "a multi-send must return a notification")
        message = result['params']['message']
        self.assertIn('1 sent', message)
        self.assertIn('1 failed', message)
        self.assertEqual(result['params']['type'], 'warning')

    def test_batch_send_sends_every_payment(self):
        payments = self._new_payment() | self._new_payment()
        batch = self.env['account.batch.payment'].create({
            'journal_id': self.journal.id,
            'batch_type': 'outbound',
            'payment_ids': [Command.set(payments.ids)],
        })
        # Distinct transferIds: (company_id, gec_bank_reference) is unique.
        ids = iter([101, 102])

        def one_per_call(*_args, **_kwargs):
            return {'http_status': 200, 'error_text': '',
                    'data': {'succeeded': [{'transferId': next(ids)}], 'failed': []}}

        with patch.object(type(self.service), 'import_single_transfer',
                          side_effect=one_per_call):
            batch.action_tbc_send_batch()
        self.assertEqual(set(payments.mapped('gec_bank_state')), {'sent'})
        self.assertTrue(all(payments.mapped('gec_bank_request_id')))

    def test_batch_send_rejects_non_tbc_journal(self):
        journal = self.env['account.journal'].create({
            'name': 'Cash box', 'type': 'bank', 'code': 'TBCNO',
        })
        batch = self.env['account.batch.payment'].create({
            'journal_id': journal.id, 'batch_type': 'outbound',
        })
        with self.assertRaisesRegex(UserError, 'not on a TBC Bank journal'):
            batch.action_tbc_send_batch()

    def test_status_poll_cron_skips_terminal_transfers(self):
        self.connection.state = 'active'
        confirmed = self._new_payment()
        confirmed._gec_bank_internal_write({'gec_bank_state': 'confirmed', 'gec_bank_reference': '900'})
        pending = self._new_payment()
        pending._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': '901'})
        seen = []

        def fake_status(_self, _connection, transfer_id):
            seen.append(transfer_id)
            return {'status': 'Finished'}

        with patch.object(type(self.service), 'get_single_transfer_status', fake_status):
            self.env['account.payment']._cron_tbc_status_poll()
        self.assertIn('901', seen)
        self.assertNotIn('900', seen, "a confirmed transfer must not be re-polled")
        self.assertEqual(pending.gec_bank_state, 'confirmed')

    def test_live_statement_cron_upserts_one_row_per_journal(self):
        self.connection.state = 'active'
        payload = {'openingBalance': 10.0, 'closingBalance': 25.0,
                   'creditSum': 20.0, 'debitSum': 5.0}
        with patch.object(type(self.service), 'get_account_statement',
                          return_value=payload):
            self.env['tbc.statement']._cron_fetch_live_statements()
            self.env['tbc.statement']._cron_fetch_live_statements()
        live = self.env['tbc.statement'].search([
            ('journal_id', '=', self.journal.id), ('snapshot_type', '=', 'live')])
        self.assertEqual(len(live), 1, "the live snapshot must be upserted, not appended")
        self.assertEqual(live.closing_balance, 25.0)

    def test_daily_statement_sync_cron_imports(self):
        self.connection.state = 'active'
        movements = [{'movementId': 'CRON-1', 'documentDate': '2026-06-09T10:00:00', 'amount': 12.0, 'isDebit': False,
                      'purpose': 'cron import'}]
        with patch.object(type(self.service), 'fetch_all_movements',
                          return_value=movements):
            self.env['tbc.connection']._cron_daily_statement_sync()
        line = self.env['account.bank.statement.line'].search([
            ('journal_id', '=', self.journal.id),
            ('unique_import_id', '=', 'tbcbank-%s-CRON-1' % self.journal.id)])
        self.assertEqual(len(line), 1)

    def _second_company_setup(self):
        company = self.env['res.company'].create({'name': 'TBC Second Co'})
        account = self.env['res.partner.bank'].create({
            'account_number': 'GE29TB2222222222222222',
            'partner_id': company.partner_id.id,
            'bank_bic': 'TBCBGE22',
            'company_id': company.id,
        })
        journal = self.env['account.journal'].create({
            'name': 'TBC Second', 'type': 'bank', 'code': 'TBC2',
            'bank_account_id': account.id,
            'company_id': company.id,
        })
        connection = self.env['tbc.connection'].create({
            'company_id': company.id,
            'client_id': 'second-client',
            'client_secret': 'second-secret',
            'environment': 'test',
            'processing_mode': 'direct',
        })
        return company, journal, connection

    def test_each_company_resolves_its_own_connection(self):
        _company, journal, connection = self._second_company_setup()
        self.assertEqual(self.journal.tbc_connection_id, self.connection)
        self.assertEqual(journal.tbc_connection_id, connection)
        self.assertNotEqual(journal.tbc_connection_id, self.connection)

    def test_one_connection_per_company_is_enforced(self):
        from psycopg2 import IntegrityError
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env['tbc.connection'].create({
                'company_id': self.company.id,
                'client_id': 'duplicate',
                'client_secret': 'duplicate',
                'environment': 'test',
            })

    def test_company_rule_hides_another_companys_connection(self):
        """The multi-company record rules have to actually bite."""
        _company, _journal, other_connection = self._second_company_setup()
        user = self.env['res.users'].create({
            'name': 'Company A only', 'login': 'tbc_company_a_only',
            'company_id': self.company.id,
            'company_ids': [(6, 0, [self.company.id])],
            'group_ids': [(6, 0, [self.env.ref('tbc_bank.group_tbc_manager').id])],
        })
        visible = self.env['tbc.connection'].with_user(user).search([])
        self.assertIn(self.connection, visible)
        self.assertNotIn(other_connection, visible,
                         "another company's connection must not be visible")

    def test_api_logs_are_scoped_per_company(self):
        _company, _journal, other_connection = self._second_company_setup()
        mine = self.env['tbc.api.log'].create({
            'connection_id': self.connection.id, 'endpoint': 'accounts/movements'})
        theirs = self.env['tbc.api.log'].create({
            'connection_id': other_connection.id, 'endpoint': 'accounts/movements'})
        self.assertEqual(mine.company_id, self.company)
        self.assertEqual(theirs.company_id, other_connection.company_id)

    def _make_log(self, endpoint, age_days):
        log = self.env['tbc.api.log'].create({
            'connection_id': self.connection.id,
            'endpoint': endpoint,
            'http_status': 200,
        })
        # create_date is readonly; age it directly.
        self.env.cr.execute(
            "UPDATE tbc_api_log SET create_date = now() - interval '%s days' WHERE id = %s",
            (age_days, log.id))
        log.invalidate_recordset(['create_date'])
        return log

    def test_gc_removes_old_routine_logs(self):
        self.connection.log_retention_days = 30
        old = self._make_log('accounts/movements', 90)
        recent = self._make_log('accounts/movements', 5)
        self.env['tbc.api.log']._gc_gec_bank_api_logs()
        self.assertFalse(old.exists(), "a stale routine log must be vacuumed")
        self.assertTrue(recent.exists(), "a log inside the window must survive")

    def test_gc_never_removes_transfer_logs(self):
        """Transfer logs are the audit trail for money leaving the company."""
        self.connection.log_retention_days = 30
        for endpoint in ('transfers/single', 'transfers/batch/9/status',
                         'transfers/single/55/status'):
            log = self._make_log(endpoint, 900)
            self.env['tbc.api.log']._gc_gec_bank_api_logs()
            self.assertTrue(log.exists(),
                            "%s must never be vacuumed" % endpoint)

    def test_gc_disabled_when_retention_is_zero(self):
        self.connection.log_retention_days = 0
        old = self._make_log('oauth/token', 900)
        self.env['tbc.api.log']._gc_gec_bank_api_logs()
        self.assertTrue(old.exists(), "0 must mean keep everything")

    def test_gc_reports_remaining_work(self):
        """Returning (done, remaining) lets Odoo's autovacuum re-queue us."""
        self.connection.log_retention_days = 1
        for index in range(3):
            self._make_log('accounts/movements/%s' % index, 30)
        done, remaining = self.env['tbc.api.log']._gc_gec_bank_api_logs()
        self.assertEqual(done, 3)
        self.assertEqual(remaining, 0)

    def _import_wizard(self, journal):
        return self.env['tbc.statement.import.wizard'].create({
            'journal_id': journal.id,
            'start_date': '2026-06-01 00:00:00',
            'end_date': '2026-06-30 00:00:00',
        })

    def test_movement_mapping(self):
        wizard = self._import_wizard(self.journal)
        movement = {
            'movementId': '018745219864.1',
            'amount': 100.0,
            'isDebit': True,
            'purpose': 'Invoice payment',
            'documentDate': '2026-06-09T00:00:00',
            'date': '2026-06-20T00:00:00',
            'paymentId': '412',
            'externalPaymentId': '18745219864',
            'partnerAccountInfo': {'partnerName': 'Acme', 'accountIban': 'GE00X'},
            'documentNumber': '200004',
        }
        vals = wizard._movement_to_line_vals(movement)
        self.assertEqual(vals['amount'], -100.0)          # debit -> negative
        self.assertEqual(vals['partner_name'], 'Acme')     # partnerName
        self.assertEqual(vals['account_number'], 'GE00X')  # accountIban
        self.assertEqual(str(vals['date']), '2026-06-09')  # documentDate, not date
        self.assertEqual(vals['gec_bank_match_keys'], '412')

    def test_unique_import_id_is_scoped_to_the_journal(self):
        """unique_import_id is global, so a bare movement id would collide."""
        other_journal = self.env['account.journal'].create({
            'name': 'TBC USD', 'type': 'bank', 'code': 'TBCUS',
            'bank_account_id': self.company_bank.id,
        })
        movement = {'movementId': 'SAME-ID', 'documentDate': '2026-06-09T10:00:00', 'amount': 5.0, 'isDebit': False}
        first = self._import_wizard(self.journal)._movement_to_line_vals(movement)
        second = self._import_wizard(other_journal)._movement_to_line_vals(movement)
        self.assertNotEqual(first['unique_import_id'], second['unique_import_id'])
        self.assertIn(str(self.journal.id), first['unique_import_id'])

    def test_import_is_idempotent(self):
        wizard = self._import_wizard(self.journal)
        movements = [{'movementId': 'M-1', 'documentDate': '2026-06-09T10:00:00', 'amount': 5.0, 'isDebit': False},
                     {'movementId': 'M-2', 'documentDate': '2026-06-09T10:00:00', 'amount': 7.0, 'isDebit': True}]
        self.assertEqual(wizard._create_statement_lines(movements), 2)
        self.assertEqual(wizard._create_statement_lines(movements), 0,
                         "re-importing the same movements must create nothing")

    def test_import_skips_movements_without_an_id(self):
        wizard = self._import_wizard(self.journal)
        created = wizard._create_statement_lines([
            {'documentDate': '2026-06-09T10:00:00', 'amount': 5.0, 'isDebit': False},  # no id
            {'movementId': 'M-9', 'documentDate': '2026-06-09T10:00:00', 'amount': 5.0, 'isDebit': False},
        ])
        self.assertEqual(created, 1)

    def test_paging_stops_at_the_ceiling(self):
        """An API that never shortens a page must not spin forever."""
        from odoo.addons.tbc_bank.services import tbc_bank_service as svc
        page = {'transactions': [{'movementId': 'x'}] * 2}
        with patch.object(svc, 'MAX_MOVEMENT_PAGES', 3), \
             patch.object(type(self.service), 'get_account_movements',
                          return_value=page) as mocked:
            with self.assertRaises(UserError):
                self.service.fetch_all_movements(
                    self.connection, 'GE29TB7777777777777701', 'GEL',
                    '2026-06-01', '2026-06-30', page_size=2)
        self.assertEqual(mocked.call_count, 3)

    def _fetch_pages(self, *pages, page_size=2):
        with patch.object(type(self.service), 'get_account_movements', side_effect=pages) as mocked:
            movements = self.service.fetch_all_movements(
                self.connection, 'GE29TB7777777777777701', 'GEL',
                '2026-06-01', '2026-06-30', page_size=page_size)
        return movements, mocked.call_count

    def test_short_page_is_not_the_end_while_the_total_is_not_reached(self):
        """TBC may cap a page below the size asked for; the total says when the period ends."""
        movements, calls = self._fetch_pages(
            {'transactions': [{'movementId': 1}], 'total': 3},
            {'transactions': [{'movementId': 2}, {'movementId': 3}], 'total': 3})
        self.assertEqual(len(movements), 3)
        self.assertEqual(calls, 2)

    def test_period_that_stops_before_its_total_is_refused(self):
        with self.assertRaisesRegex(UserError, '2 of the 3 movements'):
            self._fetch_pages({'transactions': [{'movementId': 1}, {'movementId': 2}], 'total': 3},
                              {'transactions': [], 'total': 3})

    def test_short_page_ends_a_period_without_a_total(self):
        movements, calls = self._fetch_pages({'transactions': [{'movementId': 1}]})
        self.assertEqual((len(movements), calls), (1, 1))

    def test_eleven_char_bic_still_detected_as_tbc(self):
        account = self.env['res.partner.bank'].create({
            'account_number': 'GE29TB1111111111111111',
            'partner_id': self.company.partner_id.id,
            'bank_bic': 'TBCBGE22XXX',
        })
        journal = self.env['account.journal'].create({
            'name': 'TBC Branch Journal', 'type': 'bank', 'code': 'TBCBR',
            'bank_account_id': account.id,
        })
        self.assertTrue(journal.is_tbc, "the 11-char branch BIC must still match")

    def test_tbc_journal_gets_the_tbc_bank_feed(self):
        self.assertEqual(self.journal.bank_statements_source, 'tbcbank')

    def test_non_tbc_journal_keeps_its_feed(self):
        journal = self.env['account.journal'].create({
            'name': 'Other Bank', 'type': 'bank', 'code': 'OTHR',
        })
        self.assertNotEqual(journal.bank_statements_source, 'tbcbank')

    def _statement_line_vals(self, keys, amount=-20.5):
        return {
            'journal_id': self.journal.id,
            'payment_ref': 'movement %s' % keys,
            'amount': amount,
            'date': '2026-06-20',
            'gec_bank_match_keys': keys,
        }

    def test_auto_match_confirms_a_whole_batch(self):
        first = self._new_payment()
        first._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': 'T-1'})
        second = self._new_payment()
        second._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': 'T-2'})
        self.env['account.bank.statement.line'].create([
            self._statement_line_vals('T-1'),
            self._statement_line_vals('T-2'),
        ])
        self.assertEqual(first.gec_bank_state, 'confirmed')
        self.assertEqual(second.gec_bank_state, 'confirmed')

    def test_auto_match_never_claims_one_transfer_twice(self):
        payment = self._new_payment()
        payment._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': 'T-DUP'})
        other = self._new_payment()
        other._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': 'T-OTHER'})
        self.env['account.bank.statement.line'].create([
            self._statement_line_vals('T-DUP'),
            self._statement_line_vals('T-DUP'),
        ])
        self.assertEqual(payment.gec_bank_state, 'confirmed')
        self.assertEqual(other.gec_bank_state, 'sent', "an unrelated transfer must be untouched")

    def test_auto_match_runs_one_query_per_batch(self):
        """One search per batch, not per statement line; counted inside _gec_bank_auto_match only."""
        payments = self.env['account.payment']
        for index in range(3):
            payment = self._new_payment()
            payment._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': 'Q-%s' % index})
            payments |= payment

        lines = self.env['account.bank.statement.line'].create(
            [self._statement_line_vals('Q-%s' % index) for index in range(3)])
        # create() already matched them; reset so the counted call matches again.
        payments._gec_bank_internal_write({'gec_bank_state': 'sent'})

        Payment = type(self.env['account.payment'])
        original_search = Payment.search
        calls = []

        def counting_search(records, *args, **kwargs):
            calls.append(1)
            return original_search(records, *args, **kwargs)

        with patch.object(Payment, 'search', counting_search):
            lines._gec_bank_auto_match()
        self.assertEqual(len(calls), 1,
                         "the batch must resolve in one search, not one per line")
        self.assertEqual(set(payments.mapped('gec_bank_state')), {'confirmed'})

    def test_auto_match_confirms_transfer(self):
        payment = self._new_payment(gec_bank_request_id='REQ-XYZ')
        payment._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': '19806'})
        self.env['account.bank.statement.line'].create({
            'journal_id': self.journal.id,
            'payment_ref': 'incoming',
            'amount': -20.5,
            'date': '2026-06-20',
            'gec_bank_match_keys': '19806 REQ-XYZ',
        })
        self.assertEqual(payment.gec_bank_state, 'confirmed')
        self.assertEqual(payment.gec_bank_confirmed_source, 'statement')

    def test_duplicate_request_is_never_failed(self):
        """400 DUPLICATED_SINGLE_TRANSFER_REQUEST means the transfer exists: resolve it by lookup, not 'failed'."""
        payment = self._new_payment()
        duplicate = {'http_status': 400, 'error_text': '',
                     'data': {'code': 'DUPLICATED_SINGLE_TRANSFER_REQUEST',
                              'title': 'Duplicated Single Transfer Request'}}
        lookup = {'http_status': 201, 'data': {'transferId': 7001}, 'error_text': ''}
        with self._mock_send(duplicate), \
             patch.object(type(self.service), 'get_single_transfer_by_external_id',
                          return_value=lookup), \
             patch.object(type(self.service), 'get_single_transfer_status',
                          return_value={'status': 'In progress'}):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_state, 'sent')
        self.assertEqual(payment.gec_bank_reference, '7001')

    def test_duplicate_request_stays_unknown_if_lookup_fails(self):
        payment = self._new_payment()
        duplicate = {'http_status': 400, 'error_text': '',
                     'data': {'code': 'DUPLICATED_SINGLE_TRANSFER_REQUEST'}}
        with self._mock_send(duplicate), \
             patch.object(type(self.service), 'get_single_transfer_by_external_id',
                          return_value={'http_status': 0, 'data': {}, 'error_text': 'timeout'}):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_state, 'unknown')

    def test_unknown_transfer_cannot_be_resent(self):
        payment = self._new_payment()
        with self._mock_send({'http_status': 504, 'data': {}, 'error_text': 'timeout'}):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_state, 'unknown')
        with self._mock_send({'http_status': 207, 'error_text': '',
                              'data': {'succeeded': [{'transferId': 1}], 'failed': []}}) as mocked:
            with self.assertRaisesRegex(UserError, 'outcome of the previous send is unknown'):
                payment._tbc_send_one()
        self.assertFalse(mocked.called, "an unknown transfer must not be posted again")

    def test_success_array_named_succeed(self):
        """TBC's docs name the success array 'succeed' and 'succeeded'."""
        payment = self._new_payment()
        with self._mock_send({'http_status': 207, 'error_text': '',
                              'data': {'succeed': [{'position': 1, 'transferId': 414}], 'failed': []}}):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_state, 'sent')
        self.assertEqual(payment.gec_bank_reference, '414')

    def test_status_completed_confirms(self):
        """TBC's docs name the success status 'Completed' and 'Finished'."""
        payment = self._new_payment()
        payment._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': '502341'})
        with patch.object(type(self.service), 'get_single_transfer_status',
                          return_value={'status': 'Completed',
                                        'singleTransferData': {'transferStatus': 'Completed'}}):
            payment._tbc_refresh_status()
        self.assertEqual(payment.gec_bank_state, 'confirmed')

    def test_charge_details_has_no_ben(self):
        selection = dict(self.env['account.payment']._fields['tbc_charge_details'].selection)
        self.assertEqual(set(selection), {'SHA', 'OUR'})

    def test_treasury_order_has_no_credit_account(self):
        payment = self._new_payment(tbc_transfer_type='treasury', tbc_treasury_code='101001000')
        order = payment._tbc_build_order()
        self.assertNotIn('creditAccount', order)
        self.assertNotIn('beneficiaryName', order)

    def _assert_rejected_before_reservation(self, payment, fragment):
        try:
            payment._tbc_send_one()
        except UserError as exc:
            self.assertIn(fragment, str(exc))
        else:
            self.fail("an invalid order was expected to be rejected")
        payment.invalidate_recordset(['gec_bank_request_id', 'gec_bank_state'])
        self.assertFalse(payment.gec_bank_request_id, "a rejected order must not burn a key")
        self.assertEqual(payment.gec_bank_state, 'pending')

    def test_treasury_code_must_have_nine_digits(self):
        payment = self._new_payment(tbc_transfer_type='treasury', tbc_treasury_code='1010')
        with self._mock_send({}) as mocked:
            self._assert_rejected_before_reservation(payment, 'Treasury Code')
        self.assertFalse(mocked.called)

    def test_foreign_transfer_requires_charge_details(self):
        payment = self._new_payment(tbc_transfer_type='foreign',
                                    tbc_beneficiary_address='Street 1',
                                    tbc_beneficiary_bank_code='DEUTDEFF')
        with self._mock_send({}) as mocked:
            self._assert_rejected_before_reservation(payment, 'SHA or OUR')
        self.assertFalse(mocked.called)

    def test_missing_credit_account_is_not_sent_as_false(self):
        payment = self._new_payment(partner_bank_id=False)
        self.assertNotIn('creditAccount', payment._tbc_build_order())
        with self._mock_send({}) as mocked:
            self._assert_rejected_before_reservation(payment, 'recipient bank account')
        self.assertFalse(mocked.called)

    def test_unauthorized_movements_are_not_imported(self):
        """statusCode 1/2 = still awaiting authorization at the bank."""
        payment = self._new_payment()
        payment._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': '777'})
        wizard = self._import_wizard(self.journal)
        created = wizard._create_statement_lines([
            {'movementId': 'A-1', 'documentDate': '2026-06-09T10:00:00', 'amount': 5.0, 'isDebit': True, 'statusCode': 0},
            {'movementId': 'A-2', 'documentDate': '2026-06-09T10:00:00', 'amount': 20.5, 'isDebit': True, 'statusCode': 1,
             'paymentId': '777'},
            {'movementId': 'A-3', 'documentDate': '2026-06-09T10:00:00', 'amount': 9.0, 'isDebit': True, 'statusCode': 2},
        ])
        self.assertEqual(created, 1)
        self.assertEqual(payment.gec_bank_state, 'sent',
                         "an unauthorized movement must not confirm the transfer")

    def test_external_payment_id_does_not_match(self):
        """externalPaymentId is a POS/ATM/cash id, not our transferExternalId."""
        payment = self._new_payment(gec_bank_request_id='18745219864')
        payment._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': '999'})
        wizard = self._import_wizard(self.journal)
        wizard._create_statement_lines([{'movementId': 'X-1', 'documentDate': '2026-06-09T10:00:00', 'amount': 20.5, 'isDebit': True,
                                         'externalPaymentId': '18745219864'}])
        self.assertEqual(payment.gec_bank_state, 'sent')

    def test_statement_period_covers_the_whole_last_day(self):
        captured = {}

        def fake_call(_self, _connection, path, method='GET', params=None, **_kwargs):
            captured.update(params or {})
            return {}

        with patch.object(type(self.service), '_call', fake_call):
            self.service.get_account_statement(self.connection, 'GE29TB7777777777777701', 'GEL',
                                               date(2026, 6, 1), date(2026, 6, 30))
        self.assertEqual(captured['PeriodFrom'], '2026-06-01T00:00:00')
        self.assertEqual(captured['PeriodTo'], '2026-06-30T23:59:59')

    def test_journal_created_in_one_save_gets_the_tbc_line(self):
        # The UI sends the account number with the journal; Odoo attaches the bank account after the method lines.
        journal = self.env['account.journal'].create({
            'name': 'TBC One Save', 'type': 'bank', 'code': 'TBC1S',
            'bank_account_number': 'GE29TB5555555555555555',
            'bank_bic': 'TBCBGE22',
        })
        self.assertTrue(journal.is_tbc)
        self.assertTrue(journal._tbc_method_line())

    def test_georgian_tbc_iban_gets_the_tbc_line_at_once(self):
        """gec_localization fills the BIC from a Georgian IBAN."""
        journal = self.env['account.journal'].create({
            'name': 'TBC At Once', 'type': 'bank', 'code': 'TBCAO',
            'bank_account_number': 'GE29TB6666666666666666',
        })
        self.assertEqual(journal.bank_bic, 'TBCBGE22')
        self.assertTrue(journal._tbc_method_line())

    def test_journal_gets_the_tbc_line_when_swift_is_added_later(self):
        # Not a Georgian IBAN: no BIC is filled in.
        journal = self.env['account.journal'].create({
            'name': 'TBC Later', 'type': 'bank', 'code': 'TBCLT',
            'bank_account_number': 'TBCLATER0000000000001',
        })
        self.assertFalse(journal._tbc_method_line())
        journal.bank_bic = 'TBCBGE22'
        self.assertTrue(journal._tbc_method_line())
        journal.bank_bic = 'TBCBGE22XXX'
        lines = journal.outbound_payment_method_line_ids.filtered(
            lambda l: l.payment_method_id.code == 'tbc_transfer')
        self.assertEqual(len(lines), 1, "the line must not be added twice")

    def test_non_tbc_journal_gets_no_tbc_line(self):
        journal = self.env['account.journal'].create({
            'name': 'Other Bank', 'type': 'bank', 'code': 'OTHB',
            'bank_account_number': 'GE90BG0000000589021505',
            'bank_bic': 'BAGAGE22',
        })
        self.assertFalse(journal._tbc_method_line())

    def test_ibans_are_sent_without_spaces(self):
        # Odoo stores a valid IBAN formatted in groups of four.
        self.company_bank.account_number = 'GE29 TB77 7777 7777 7777 01'
        partner_bank = self.env['res.partner.bank'].create({
            'account_number': 'GE90 BG00 0000 0589 0215 05',
            'partner_id': self.partner.id,
        })
        payment = self._new_payment(partner_bank_id=partner_bank.id, tbc_transfer_type='national',
                                    tbc_beneficiary_tax_code='12345678901')
        order = payment._tbc_build_order()
        self.assertEqual(order['debitAccount']['accountNumber'], 'GE29TB7777777777777701')
        self.assertEqual(order['creditAccount']['accountNumber'], 'GE90BG0000000589021505')

    def test_statement_import_queries_the_iban_without_spaces(self):
        self.company_bank.account_number = 'GE29 TB77 7777 7777 7777 01'
        wizard = self.env['tbc.statement.import.wizard'].create({
            'journal_id': self.journal.id,
            'start_date': '2026-06-01 00:00:00', 'end_date': '2026-06-02 00:00:00',
        })
        with patch.object(type(self.service), 'fetch_all_movements', return_value=[]) as fetch:
            wizard.action_import()
        self.assertEqual(fetch.call_args.args[1], 'GE29TB7777777777777701')

    def test_send_never_writes_the_payment_through_the_orm(self):
        # The send commits on independent cursors; an ORM write of the same row would hit a serialization error.
        payment = self._new_payment()
        payment.flush_recordset()
        success = {'http_status': 207, 'error_text': '',
                   'data': {'succeeded': [{'transferId': 19806}], 'failed': []}}
        with self._mock_send(success), \
                patch.object(type(self.service), 'get_single_transfer_status',
                             return_value={'status': 'Finished'}), \
                patch.object(type(payment), 'write', side_effect=AssertionError("ORM write")):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_state, 'confirmed')
        self.assertEqual(payment.gec_bank_reference, '19806')

    def test_reserved_external_id_reaches_tbc(self):
        # Production re-reads from a snapshot older than the reservation; the id must come from the cache.
        payment = self._new_payment()
        payment._gec_bank_reserve_send()
        with self.assertQueryCount(0):
            external_id = payment.gec_bank_request_id
            state = payment.gec_bank_state
        self.assertTrue(external_id)
        self.assertEqual(state, 'sending')

        payment = self._new_payment()
        with self._mock_send({'http_status': 207, 'error_text': '',
                              'data': {'succeeded': [], 'failed': [{'errors': ['x']}]}}) as send:
            payment._tbc_send_one()
        order = send.call_args.args[1]
        self.assertEqual(order['transferExternalId'], payment.gec_bank_request_id)
        self.assertTrue(order['transferExternalId'])

    def test_state_change_is_posted_in_the_chatter(self):
        payment = self._new_payment()
        with self._mock_send({'http_status': 207, 'error_text': '',
                              'data': {'succeeded': [], 'failed': [{'errors': ['rejected']}]}}):
            payment._tbc_send_one()
        bodies = ' '.join(payment.message_ids.mapped('body'))
        self.assertIn('Sending', bodies)
        self.assertIn('Failed', bodies)

    def test_blocked_state_is_not_written_through_the_orm(self):
        from unittest.mock import MagicMock
        self.connection.write({'state': 'active'})
        self.connection.store_token('tok', 3600)
        self.connection.flush_recordset()
        response = MagicMock(status_code=400,
                             text='{"title": "USER_IS_BLOCKED", "status": 400, "code": "DomainError"}')
        with patch('odoo.addons.tbc_bank.services.tbc_bank_service.requests.request',
                   return_value=response), \
                patch.object(type(self.connection), 'write', side_effect=AssertionError("ORM write")):
            try:
                self.service._call(self.connection, 'accounts/movements')
            except UserError:
                pass
            else:
                self.fail("a blocked user was expected to raise")
        self.connection.invalidate_recordset(['state'])
        self.assertEqual(self.connection.state, 'blocked')

    def test_draft_payment_cannot_be_sent(self):
        payment = self._new_payment(post=False)
        with self._mock_send({'http_status': 207, 'error_text': '',
                              'data': {'succeeded': [{'transferId': 1}], 'failed': []}}) as send, \
                self.assertRaisesRegex(UserError, 'Confirm these payments'):
            payment._tbc_send_one()
        send.assert_not_called()
        self.assertEqual(payment.gec_bank_state, 'pending')
        self.assertFalse(payment.gec_bank_request_id, "nothing may be reserved for a draft")

    def _make_unknown(self):
        payment = self._new_payment()
        with self._mock_send({'http_status': 0, 'data': {}, 'error_text': 'Request timed out'}):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_state, 'unknown')
        return payment

    def test_recover_treats_tbc_not_found_400_as_never_received(self):
        # The real answer of the TBC test environment for an unknown id. Within 15 minutes of the send TBC may
        # still be processing it, so "not found" counts only after that.
        payment = self._make_unknown()
        not_found = {'http_status': 400, 'error_text': '', 'data': {
            'title': 'Specified single transfer external id is not found for a current client',
            'status': 400}}
        with patch.object(type(self.service), 'get_single_transfer_by_external_id',
                          return_value=not_found):
            payment.action_tbc_recover()
            self.assertEqual(payment.gec_bank_state, 'unknown')
            self.env.flush_all()
            self.env.cr.execute(
                "UPDATE account_payment SET write_date = write_date - interval '20 minutes' WHERE id = %s",
                (payment.id,))
            payment.invalidate_recordset(['write_date'])
            payment.action_tbc_recover()
        self.assertEqual(payment.gec_bank_state, 'pending')

    def test_recover_keeps_unknown_on_any_other_400(self):
        payment = self._make_unknown()
        other = {'http_status': 400, 'error_text': '',
                 'data': {'title': 'INVALID_ACCOUNT', 'status': 400}}
        with patch.object(type(self.service), 'get_single_transfer_by_external_id',
                          return_value=other):
            payment.action_tbc_recover()
        self.assertEqual(payment.gec_bank_state, 'unknown')

    def _left_sending(self, minutes_ago=20):
        """A payment a crash left 'sending': reserved, no answer, `minutes_ago` minutes old."""
        payment = self._new_payment()
        payment._gec_bank_reserve_send()
        self.assertEqual(payment.gec_bank_state, 'sending')
        self.env.cr.execute(
            "UPDATE account_payment SET write_date = write_date - %s * interval '1 minute' "
            "WHERE id = %s", [minutes_ago, payment.id])
        payment.invalidate_recordset(['write_date'])
        return payment

    def test_recover_waits_while_a_send_may_still_run(self):
        """Recovering a send that is still running could pay twice: TBC answers 'not found'."""
        payment = self._left_sending(minutes_ago=1)
        with patch.object(type(self.service), 'get_single_transfer_by_external_id') as lookup, \
             self.assertRaisesRegex(UserError, 'may still be on its way'):
            payment.action_tbc_recover()
        lookup.assert_not_called()
        self.assertEqual(payment.gec_bank_state, 'sending')

    def test_recover_finds_a_transfer_left_sending_by_a_crash(self):
        """A crash between the reservation and TBC's answer leaves 'sending' with no result."""
        payment = self._left_sending()
        found = {'http_status': 200, 'data': {'transferId': 7002}, 'error_text': ''}
        with patch.object(type(self.service), 'get_single_transfer_by_external_id',
                          return_value=found), \
             patch.object(type(self.service), 'get_single_transfer_status',
                          return_value={'status': 'In progress'}):
            payment.action_tbc_recover()
        self.assertEqual((payment.gec_bank_state, payment.gec_bank_reference), ('sent', '7002'))

    def test_recover_of_a_sending_transfer_keeps_its_request_id(self):
        """TBC never got it: the payment may be sent again, under the same request id."""
        payment = self._left_sending()
        external_id = payment.gec_bank_request_id
        not_found = {'http_status': 404, 'error_text': '', 'data': {}}
        with patch.object(type(self.service), 'get_single_transfer_by_external_id',
                          return_value=not_found):
            payment.action_tbc_recover()
        self.assertEqual(payment.gec_bank_state, 'pending')
        self.assertEqual(payment.gec_bank_request_id, external_id)

    def _bank(self, number, partner=None):
        return self.env['res.partner.bank'].create({
            'account_number': number, 'partner_id': (partner or self.partner).id})

    def _type_for(self, bank, currency=None):
        # create(), not new(): defaults only interfere on a real create.
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound', 'partner_type': 'supplier', 'journal_id': self.journal.id,
            'partner_id': bank.partner_id.id, 'partner_bank_id': bank.id, 'amount': 1,
            'currency_id': (currency or self.env.ref('base.GEL')).id,
        })
        return payment.tbc_transfer_type

    def test_transfer_type_follows_the_recipient_account(self):
        eur = self.env.ref('base.EUR')
        self.assertEqual(self._type_for(self.partner_bank), 'internal')
        self.assertEqual(self._type_for(self._bank('GE90 BG00 0000 0589 0215 05')), 'national')
        self.assertEqual(self._type_for(self._bank('GE90BG0000000589021599'), eur), 'foreign')
        self.assertEqual(self._type_for(self._bank('CZ6508000000192000145399'), eur), 'foreign')
        own = self._bank('GE29TB7777777777777702', self.company.partner_id)
        self.assertEqual(self._type_for(own), 'own')

    def test_mismatched_transfer_type_is_blocked_before_sending(self):
        national_to_tbc = self._new_payment(tbc_transfer_type='national', tbc_beneficiary_tax_code='1')
        other_bank = self._bank('GE90BG0000000589021505')
        other_bank.allow_out_payment = True
        within_to_other = self._new_payment(partner_bank_id=other_bank.id, tbc_transfer_type='internal')
        for payment, message in ((national_to_tbc, 'is a TBC account'), (within_to_other, 'is not a TBC account')):
            with self._mock_send({}) as send, self.assertRaisesRegex(UserError, message):
                payment._tbc_send_one()
            send.assert_not_called()

    def test_rejected_transfer_marks_the_payment_rejected(self):
        payment = self._new_payment()
        self.assertEqual(payment.state, 'paid')
        with self._mock_send({'http_status': 207, 'error_text': '',
                              'data': {'succeeded': [], 'failed': [{'errors': ['rejected']}]}}):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_state, 'failed')
        self.assertEqual(payment.state, 'rejected')
        payment.action_draft()
        payment.action_post()
        payment.action_tbc_reset_to_pending()
        with self._mock_send({'http_status': 207, 'error_text': '',
                              'data': {'succeeded': [{'transferId': 555}], 'failed': []}}):
            payment._tbc_send_one()
        self.assertEqual(payment.gec_bank_state, 'sent')
        self.assertTrue(payment.is_sent)

    def test_sent_transfer_is_marked_sent_and_completes_the_batch(self):
        payments = self._new_payment() | self._new_payment(amount=3)
        batch = self.env['account.batch.payment'].create({
            'journal_id': self.journal.id, 'batch_type': 'outbound',
            'payment_method_id': self.method_line.payment_method_id.id,
            'payment_ids': [Command.set(payments.ids)]})
        ids = iter([701, 702])
        with patch.object(type(self.service), 'import_single_transfer',
                          side_effect=lambda *a, **k: {'http_status': 207, 'error_text': '', 'data': {
                              'succeeded': [{'transferId': next(ids)}], 'failed': []}}):
            batch.action_tbc_send_batch()
        self.assertTrue(all(payments.mapped('is_sent')))
        self.assertEqual(batch.state, 'sent')

    def test_protected_fields_are_readonly(self):
        """The web client sends every non-readonly value; a protected one would block saving the form."""
        for name in GEC_BANK_TRANSFER_FIELDS:
            self.assertTrue(self.env['account.payment']._fields[name].readonly, name)

    def test_state_and_approval_cannot_be_written_directly(self):
        """A sent transfer written back to Pending could be sent twice; a written approver would skip approval."""
        payment = self._new_payment()
        payment._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': '500'})
        for vals in ({'gec_bank_state': 'pending'}, {'gec_bank_approved_by': self.env.user.id},
                     {'gec_bank_request_id': '1'}):
            with self.assertRaises(UserError):
                payment.write(vals)
        with self.assertRaises(UserError):
            self.env['account.payment'].create({
                'payment_type': 'outbound', 'partner_type': 'supplier',
                'journal_id': self.journal.id, 'partner_id': self.partner.id,
                'payment_method_line_id': self.method_line.id, 'amount': 1,
                'gec_bank_state': 'approved'})
        self.assertEqual(payment.gec_bank_state, 'sent')

    def test_payment_form_still_saves(self):
        form = Form(self.env['account.payment'].with_context(
            default_payment_type='outbound', default_partner_type='supplier'))
        form.journal_id = self.journal
        form.partner_id = self.partner
        form.amount = 15
        form.payment_method_line_id = self.method_line
        payment = form.save()
        self.assertEqual(payment.gec_bank_state, 'pending')

    def test_failure_status_does_not_undo_a_confirmation(self):
        payment = self._new_payment()
        payment._gec_bank_internal_write({'gec_bank_state': 'confirmed', 'gec_bank_reference': '502342'})
        with patch.object(type(self.service), 'get_single_transfer_status',
                          return_value={'status': 'Failed'}):
            payment._tbc_refresh_status()
        self.assertEqual(payment.gec_bank_state, 'confirmed')
        self.assertIn('already confirmed', payment.message_ids[0].body)

    def test_recover_refuses_a_settled_transfer(self):
        """Recover's 'not found' branch writes Pending, which would reopen a paid transfer."""
        payment = self._new_payment(gec_bank_request_id='123456789')
        for state in ('confirmed', 'sent', 'pending', 'failed'):
            payment._gec_bank_internal_write({'gec_bank_state': state})
            with patch.object(type(self.service), 'get_single_transfer_by_external_id') as lookup, \
                    self.assertRaisesRegex(UserError, 'can be recovered'):
                payment.action_tbc_recover()
            lookup.assert_not_called()

    def test_statement_currency_is_the_journals(self):
        """The currency cannot be typed: another currency on the same IBAN would book wrong amounts."""
        usd = self.env.ref('base.USD')
        usd.active = True
        self.journal.currency_id = usd
        wizard = self._import_wizard(self.journal)
        self.assertEqual(wizard.currency_code, 'USD')
        self.assertTrue(wizard._fields['currency_code'].readonly)
        with patch.object(type(self.service), 'fetch_all_movements', return_value=[]) as fetch:
            wizard.action_import()
        self.assertEqual(fetch.call_args.args[2], 'USD')

    def _approve_mode(self, approver=None):
        approval = self.env['tbc.approval'].create({
            'approver_id': (approver or self.env.user).id, 'company_id': self.company.id})
        self.connection.write({'processing_mode': 'odoo_approve', 'approval_id': approval.id,
                               'allow_self_approval': True})
        return approval

    def test_failed_transfer_is_reset_to_pending_before_a_resend(self):
        payment = self._new_payment()
        with self._mock_send({'http_status': 400, 'data': {}, 'error_text': 'bad'}):
            payment._tbc_send_one()
        payment.action_draft()
        payment.action_post()
        with self.assertRaisesRegex(UserError, 'Reset to Pending'):
            payment._tbc_send_one()
        payment.action_tbc_reset_to_pending()
        self.assertEqual(payment.gec_bank_state, 'pending')
        with self.assertRaisesRegex(UserError, 'Only a failed transfer'):
            payment.action_tbc_reset_to_pending()

    def test_payment_marked_sent_is_not_sent_again(self):
        payment = self._new_payment()
        payment.mark_as_sent()
        with self.assertRaisesRegex(UserError, 'already sent'):
            payment._tbc_send_one()

    def test_submit_checks_the_order_and_notifies_the_approvers(self):
        approver = new_test_user(self.env, login='tbc_approver', groups='base.group_user,tbc_bank.group_tbc_user')
        self._approve_mode(approver)
        bad = self._new_payment(tbc_transfer_type='national')
        with self.assertRaisesRegex(UserError, 'TBC account'):
            bad.action_tbc_submit_approval()
        payment = self._new_payment()
        payment.action_tbc_submit_approval()
        self.assertEqual(payment.gec_bank_state, 'awaiting_approval')
        self.assertIn(approver.partner_id, payment.message_ids[0].partner_ids)

    def test_submit_is_refused_where_odoo_does_not_approve(self):
        payment = self._new_payment()
        with self.assertRaisesRegex(UserError, 'does not require approval'):
            payment.action_tbc_submit_approval()

    def test_removed_approver_voids_the_approval(self):
        approval = self._approve_mode()
        payment = self._new_payment()
        payment.action_tbc_submit_approval()
        payment.action_tbc_approve()
        other = new_test_user(self.env, login='tbc_new_approver', groups='base.group_user')
        approval.approver_id = other
        try:
            payment._tbc_send_one()
        except UserError as error:
            self.assertIn('may no longer approve', str(error))
        else:
            self.fail("an approval by a removed approver must not release the money")
        payment.invalidate_recordset(['gec_bank_state', 'gec_bank_approved_by'])
        self.assertEqual(payment.gec_bank_state, 'pending', "withdrawn durably, ready to submit again")
        self.assertFalse(payment.gec_bank_approved_by)

    def test_batch_report_names_a_refused_payment(self):
        good = self._new_payment()
        refused = self._new_payment(tbc_transfer_type='national')
        batch = self.env['account.batch.payment'].create({
            'journal_id': self.journal.id, 'batch_type': 'outbound',
            'payment_method_id': self.method_line.payment_method_id.id,
            'payment_ids': [Command.set((good | refused).ids)]})
        with self._mock_send({'http_status': 200, 'data': {'succeeded': [{'transferId': 8181}]},
                              'error_text': ''}):
            action = batch.action_tbc_send_batch()
        message = action['params']['message']
        self.assertIn('1 sent, 1 failed', message)
        self.assertIn(refused.display_name, message)

    def test_status_poll_stores_the_raw_status_and_rotates(self):
        """The cron reads the least recently written first, so every open transfer comes up over several runs."""
        payment = self._new_payment()
        payment._gec_bank_internal_write({'gec_bank_state': 'sent', 'gec_bank_reference': '7001'})
        with patch.object(type(self.service), 'get_single_transfer_status',
                          return_value={'status': 'InProgress'}):
            payment._tbc_refresh_status()
        self.assertEqual((payment.gec_bank_state, payment.tbc_bank_status), ('sent', 'InProgress'))

    def test_connection_with_logs_is_not_deleted(self):
        self.env['tbc.api.log'].sudo().create({'connection_id': self.connection.id, 'endpoint': 'transfers/single'})
        with self.assertRaisesRegex(UserError, 'audit trail'):
            self.connection.unlink()
