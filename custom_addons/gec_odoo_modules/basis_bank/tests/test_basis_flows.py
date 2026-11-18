from datetime import timedelta
from unittest.mock import patch

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user
from odoo.tools import mute_logger

from .common import BasisCommon


@tagged('post_install', '-at_install')
class TestBasisFlows(BasisCommon):
    """The Basis Bank flows of the bank flow lab, with the bank answers mocked."""

    def setUp(self):
        super().setUp()
        self._with_ticket()

    def _post_patch(self, payload):
        return patch('odoo.addons.basis_bank.services.basisbank_service.requests.post', return_value=self._response(payload=payload))

    def _report_item(self, payment, bank_id, amount=None):
        return {
            'BankInternalID': bank_id,
            'DocNum': payment.id,
            'DebitAcc': self.company_bank.account_number,
            'CreditAcc': payment.partner_bank_id.account_number,
            'Amount': amount if amount is not None else payment.amount,
            'DocDate': fields.Date.to_string(fields.Date.today()),
            'Descrip': payment.memo,
        }

    def test_two_internal_transfers_go_as_one_gel_package(self):
        payments = self._new_payment(post=False) | self._new_payment(post=False)
        batch = self._new_batch(payments)
        self.assertEqual(batch.basisbank_endpoint, 'package_gel')
        action = batch.action_send_basisbank()
        self.assertEqual(action['res_model'], 'basisbank.otp.wizard')
        self.assertEqual(set(payments.mapped('state')), {'paid'}, "the drafts are posted first")
        with self._service_patch('upload_package', return_value={'ErrorCode': 0}) as upload:
            batch.basisbank_send_with_otp('123456')
        self.assertEqual(upload.call_args.args[1], 'gel')
        self.assertEqual(set(payments.mapped('basisbank_state')), {'sent'})
        self.assertTrue(all(payments.mapped('is_sent')))
        self.assertEqual(batch.basisbank_state, 'sent_pending_confirm')

    def test_wrong_otp_returns_the_batch_for_another_code(self):
        payments = (self._new_payment(basisbank_transfer_type='national', partner_bank_id=self.other_bank.id)
                    | self._new_payment(basisbank_transfer_type='national', partner_bank_id=self.other_bank.id))
        batch = self._new_batch(payments)
        self.assertEqual(batch.basisbank_endpoint, 'single_batch')
        with self._service_patch('upload_single_batch', return_value={'ErrorCode': 2}):
            batch.basisbank_send_with_otp('000000')
        self.assertEqual(set(payments.mapped('basisbank_state')), {'pending'})
        self.assertEqual(batch.basisbank_state, 'awaiting_otp')
        self.assertFalse(any(payments.mapped('is_sent')))

    def test_one_refused_transfer_of_three(self):
        internal = self._new_payment()
        national = self._new_payment(basisbank_transfer_type='national', partner_bank_id=self.other_bank.id)
        refused = self._new_payment(basisbank_transfer_type='national', partner_bank_id=self.other_bank.id)
        batch = self._new_batch(internal | national | refused)
        answer = {'ErrorCode': 0, 'Data': {
            'InternalTransfers': [{'ClientInternalID': internal.id, 'ErrorCode': 0, 'BankInternalID': 'X1'}],
            'NationalCurrencyTransfers': [
                {'ClientInternalID': national.id, 'ErrorCode': 0, 'BankInternalID': 'X2'},
                {'ClientInternalID': refused.id, 'ErrorCode': 13, 'Msg': 'Wrong receiver account'}],
        }}
        with self._service_patch('upload_single_batch', return_value=answer):
            batch.basisbank_send_with_otp('123456')
        self.assertEqual((internal | national).mapped('basisbank_state'), ['sent', 'sent'])
        self.assertEqual(national.basisbank_bank_internal_id, 'X2')
        self.assertEqual(refused.basisbank_state, 'failed')
        self.assertEqual(refused.state, 'rejected')
        self.assertEqual(batch.basisbank_state, 'sent_pending_confirm')

    def test_approved_national_transfer_is_sent_once(self):
        self._set_odoo_approve()
        payment = self._new_payment(basisbank_transfer_type='national', partner_bank_id=self.other_bank.id)
        with self.assertRaisesRegex(UserError, 'must be approved'):
            payment.action_basisbank_send()
        payment.action_basisbank_submit_for_approval()
        payment.with_user(self.approver).action_basisbank_approve()
        payment.action_basisbank_send()
        answer = {'ErrorCode': 0, 'Data': {'NationalCurrencyTransfers': [
            {'ClientInternalID': payment.id, 'ErrorCode': 0, 'BankInternalID': 'N-1'}]}}
        with self._service_patch('upload_single_batch', return_value=answer) as upload:
            payment.basisbank_send_with_otp('123456')
        self.assertIn('NationalCurrencyTransfers', upload.call_args.args[2])
        self.assertEqual(payment.basisbank_state, 'sent')
        self.assertEqual(payment.basisbank_bank_internal_id, 'N-1')
        with self.assertRaises(UserError):
            payment.basisbank_send_with_otp('123456')

    def test_send_lists_every_problem_and_keeps_the_payment_draft(self):
        self.partner_bank.allow_out_payment = False
        payment = self._new_payment(post=False, memo=False)
        with self.assertRaises(UserError) as error:
            payment.action_basisbank_send()
        self.assertIn('not trusted', str(error.exception))
        self.assertIn('description/purpose', str(error.exception))
        payment.invalidate_recordset(['state'])
        self.assertEqual(payment.state, 'draft', "the posting rolls back with the refusal")

    def test_changed_amount_voids_the_approval(self):
        self._set_odoo_approve()
        payment = self._new_payment()
        payment.action_basisbank_submit_for_approval()
        payment.with_user(self.approver).action_basisbank_approve()
        self.assertEqual(payment.basisbank_state, 'awaiting_otp')
        payment.action_draft()
        payment.amount = 60
        self.assertEqual(payment.basisbank_state, 'pending')
        self.assertFalse(payment.basisbank_approved_by)

    def test_statement_import_confirms_a_single_transfer_and_a_package_member(self):
        single = self._new_payment()
        single._basisbank_write_result({'basisbank_state': 'sent', 'basisbank_bank_internal_id': 'B-812',
                                        'basisbank_sent_date': fields.Datetime.now()})
        member = self._new_payment()
        batch = self._new_batch(member)
        member._basisbank_write_result({'basisbank_state': 'sent'})
        batch._gec_bank_internal_write({'basisbank_state': 'sent_pending_confirm'})
        items = [self._report_item(single, 'B-812'), self._report_item(member, 'B-815')]
        wizard = self.env['basisbank.statement.import.wizard'].create({'journal_id': self.journal.id})
        with self._service_patch('fetch_report_items', return_value=items):
            wizard.action_import()
        self.assertEqual((single | member).mapped('basisbank_state'), ['confirmed', 'confirmed'])
        self.assertEqual(member.basisbank_bank_internal_id, 'B-815')
        self.assertTrue(single.is_matched and member.is_matched)
        self.assertEqual(batch.basisbank_state, 'done')

    def test_timed_out_package_is_confirmed_by_resync(self):
        payments = self._new_payment() | self._new_payment()
        batch = self._new_batch(payments)
        with self._service_patch('upload_package', side_effect=UserError("timed out")):
            batch.basisbank_send_with_otp('123456')
        self.assertEqual(set(payments.mapped('basisbank_state')), {'unknown'})
        self.assertEqual(batch.basisbank_state, 'unknown')
        items = [self._report_item(payment, 'R-%s' % payment.id) for payment in payments]
        wizard = self.env['basisbank.resync.wizard'].with_context(default_batch_id=batch.id).create({})
        with self._service_patch('fetch_report_items', return_value=items):
            wizard.action_resync()
        self.assertEqual(set(payments.mapped('basisbank_state')), {'confirmed'})
        self.assertEqual(batch.basisbank_state, 'done')

    def test_48_hour_check_flags_a_transfer_missing_from_the_report(self):
        payment = self._new_payment()
        payment._basisbank_write_result({
            'basisbank_state': 'sent',
            'basisbank_sent_date': fields.Datetime.now() - timedelta(hours=60)})
        with self._service_patch('fetch_report_items', return_value=[]):
            self.env['account.payment']._cron_basisbank_confirm_or_reset()
        self.assertEqual(payment.basisbank_state, 'not_in_report')
        self.assertEqual(payment.state, 'paid', "the journal entry is left as it is")
        self.assertTrue(payment.activity_ids)
        with self.assertRaises(UserError):
            payment.action_draft()

    def test_reset_to_pending_confirms_a_payment_the_report_shows(self):
        payment = self._new_payment()
        payment._basisbank_write_result({'basisbank_state': 'sent', 'basisbank_sent_date': fields.Datetime.now()})
        payment._gec_bank_internal_write({'basisbank_state': 'not_in_report'})
        with self._service_patch('fetch_report_items', return_value=[self._report_item(payment, 'Z-1')]):
            payment.action_basisbank_reset_to_pending()
        self.assertEqual(payment.basisbank_state, 'confirmed')

    def test_connection_makes_its_company_journals_basis(self):
        self.assertTrue(self.journal.is_basisbank)
        payment = self._new_payment(post=False)
        self.connection.unlink()
        self.assertFalse(self.journal.is_basisbank)
        self.connection = self.env['basisbank.connection'].create({
            'company_id': self.company.id, 'login_name': 'x', 'password': 'y',
            'processing_mode': 'direct'})
        self.assertTrue(self.journal.is_basisbank)
        self.assertEqual(payment.basisbank_state, 'pending')

    def _bank_of(self, account_number, bic):
        return self.env['res.partner.bank'].create({
            'account_number': account_number,
            'partner_id': self.partner.id,
            'bank_bic': bic,
            'allow_out_payment': True,
        })

    def _detected_type(self, **vals):
        return self._new_payment(post=False, basisbank_transfer_type=None, **vals).basisbank_transfer_type

    def test_transfer_type_follows_the_recipient_bank(self):
        usd = self.env.ref('base.USD')
        usd.active = True
        self.assertEqual(self._detected_type(), 'internal')
        self.assertEqual(self._detected_type(partner_bank_id=self.other_bank.id), 'national')
        self.assertEqual(self._detected_type(partner_bank_id=self.other_bank.id, currency_id=usd.id), 'foreign')
        german_bank = self._bank_of('DE89370400440532013000', 'DEUTDEFF')
        self.assertEqual(self._detected_type(partner_bank_id=german_bank.id), 'foreign')
        junk_bank = self._bank_of('GE29TB9999999999999997', 'BOG')
        self.assertFalse(self._detected_type(partner_bank_id=junk_bank.id))
        switched = self._new_payment(post=False, basisbank_transfer_type=None)
        self.assertEqual(switched.basisbank_transfer_type, 'internal')
        switched.partner_bank_id = junk_bank
        self.assertFalse(switched.basisbank_transfer_type, "a type from the previous account is not kept")
        self.assertEqual(self._detected_type(basisbank_treasury_code='101001000'), 'treasury')
        inbound = self._new_payment(post=False, basisbank_transfer_type=None, payment_type='inbound', partner_type='customer',
            payment_method_line_id=None, partner_bank_id=None)
        self.assertFalse(inbound.basisbank_transfer_type)

    def test_receiver_fields_come_from_the_contact_and_can_be_changed(self):
        contact = self.env['res.partner'].create({
            'name': 'Berlin Supplier',
            'country_id': self.env.ref('base.de').id,
            'city': 'Berlin',
            'street': 'Hauptstrasse 1',
            'street2': 'Floor 2',
        })
        payment = self._new_payment(post=False, partner_id=contact.id, partner_bank_id=None)
        self.assertEqual((payment.basisbank_receiver_country, payment.basisbank_receiver_city), ('DE', 'Berlin'))
        self.assertEqual(payment.basisbank_receiver_address, 'Hauptstrasse 1, Floor 2')
        payment.basisbank_receiver_city = 'Munich'
        self.assertEqual(payment.basisbank_receiver_city, 'Munich')

    def test_foreign_payment_without_an_address_is_saved_but_not_sent(self):
        german_bank = self._bank_of('DE89370400440532013000', 'DEUTDEFF')
        payment = self._new_payment(post=False, basisbank_transfer_type=None, partner_bank_id=german_bank.id)
        self.assertEqual(payment.basisbank_transfer_type, 'foreign')
        with self.assertRaises(UserError) as error:
            payment.action_basisbank_send()
        self.assertIn("a foreign transfer needs Receiver Country, Receiver City, Receiver Address", str(error.exception))

    def test_connection_change_keeps_the_type_of_a_payment(self):
        payment = self._new_payment(basisbank_transfer_type='national')
        self.connection.unlink()
        self.connection = self.env['basisbank.connection'].create({
            'company_id': self.company.id,
            'login_name': 'x',
            'password': 'y',
            'processing_mode': 'direct',
        })
        self.assertEqual(payment.basisbank_transfer_type, 'national')

    def test_branch_journal_uses_its_parent_connection(self):
        branch = self.env['res.company'].create({'name': 'Basis Branch', 'parent_id': self.company.id})
        branch_bank = self.env['res.partner.bank'].create({
            'account_number': 'GE29CB7777777777777702',
            'partner_id': branch.partner_id.id,
            'bank_bic': 'CBASGE22',
        })
        journal = self.env['account.journal'].create({
            'name': 'Basis Branch', 'type': 'bank', 'code': 'BASBR',
            'company_id': branch.id, 'bank_account_id': branch_bank.id,
        })
        self.assertEqual(journal.basisbank_connection_id, self.connection)
        self.assertTrue(journal.is_basisbank)

    def test_primary_approver_cannot_be_a_delegate(self):
        with self.assertRaises(ValidationError):
            self.approval.delegate_ids = self.approver

    def test_vacuum_keeps_the_transfer_logs(self):
        Log = self.env['basisbank.api.log'].sudo()
        old = fields.Datetime.now() - timedelta(days=400)
        routine = Log.create({'connection_id': self.connection.id, 'endpoint': 'main/getreport'})
        transfer = Log.create({'connection_id': self.connection.id, 'endpoint': 'main/uploadpackagegel'})
        self.env.cr.execute("UPDATE basisbank_api_log SET create_date = %s WHERE id IN %s",
                            [old, (routine.id, transfer.id)])
        self.connection.log_retention_days = 90
        Log._gc_gec_bank_api_logs()
        self.assertFalse(routine.exists())
        self.assertTrue(transfer.exists())

    def test_creator_cannot_approve_without_self_approval(self):
        self._set_odoo_approve()
        self.approval.approver_id = self.env.user
        payment = self._new_payment()
        payment.action_basisbank_submit_for_approval()
        self.assertFalse(payment.basisbank_can_approve)
        with self.assertRaisesRegex(UserError, 'You created this transfer'):
            payment.action_basisbank_approve()
        self.connection.allow_self_approval = True
        payment.invalidate_recordset(['basisbank_can_approve'])
        self.assertTrue(payment.basisbank_can_approve)
        payment.action_basisbank_approve()
        self.assertEqual(payment.basisbank_state, 'awaiting_otp')

    def test_journal_created_in_one_save_gets_the_basis_line(self):
        account = self.env['res.partner.bank'].create({
            'account_number': 'GE29CB7777777777777733', 'partner_id': self.company.partner_id.id,
            'bank_bic': 'CBASGE22'})
        journal = self.env['account.journal'].create({
            'name': 'Basis One Save', 'type': 'bank', 'code': 'BAS1S', 'bank_account_id': account.id})
        self.assertIn('basisbank_transfer', journal.outbound_payment_method_line_ids.mapped('code'))

    def test_channel_check_needs_no_basis_group(self):
        """The channel check runs as a Payroll Administrator, who need not be in a Basis group."""
        user = self.env['res.users'].create({
            'name': 'Payroll Only', 'login': 'payroll_only',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                       self.env.ref('account.group_account_manager').id])],
        })
        self.assertEqual(self.method_line.with_user(user)._gec_bank_config_errors(), [])

    def test_service_suspended_login_keeps_the_connection_active_and_wrong_login_sets_error(self):
        with self._post_patch({'ErrorCode': 6}):
            self.assertFalse(self.service.authenticate(self.connection))
        self.assertEqual(self.connection.state, 'active')
        self.assertEqual(self.connection.last_error_code, 6)
        with self._post_patch({'ErrorCode': 6}), self.assertRaises(UserError):
            self.connection.action_test_connection()
        with self._post_patch({'ErrorCode': 1}):
            self.assertFalse(self.service.authenticate(self.connection))
        self.assertEqual(self.connection.state, 'error')
        with self._post_patch({'ErrorCode': 4}):
            self.assertFalse(self.service.authenticate(self.connection))
        self.assertEqual(self.connection.state, 'blocked')

    def test_hourly_check_tries_a_refused_login_once_per_connection(self):
        bank = self.env['res.partner.bank'].create({
            'account_number': 'GE29CB7777777777777702',
            'partner_id': self.company.partner_id.id,
            'bank_bic': 'CBASGE22',
        })
        journal = self.env['account.journal'].create({
            'name': 'Basis GEL 2',
            'type': 'bank',
            'code': 'BASTH',
            'bank_account_id': bank.id,
            'currency_id': self.gel.id,
        })
        method = self.env.ref('basis_bank.account_payment_method_basisbank')
        line = journal.outbound_payment_method_line_ids.filtered(lambda mline: mline.payment_method_id == method)[:1]
        line.payment_account_id = self.method_line.payment_account_id
        payments = self._new_payment() | self._new_payment(journal_id=journal.id, payment_method_line_id=line.id)
        for payment in payments:
            payment._basisbank_write_result({'basisbank_state': 'sent', 'basisbank_sent_date': fields.Datetime.now() - timedelta(hours=60)})
        self.connection.clear_ticket()
        with self._post_patch({'ErrorCode': 1}) as post, mute_logger('odoo.addons.basis_bank.models.account_payment'):
            self.env['account.payment']._cron_basisbank_confirm_or_reset()
        self.assertEqual(post.call_count, 1)
        self.assertTrue(post.call_args.args[0].endswith('/api/auth'))
        self.assertEqual(self.connection.state, 'error')
        self.assertEqual(payments.mapped('basisbank_state'), ['sent', 'sent'])

    def test_hourly_check_keeps_the_connection_when_the_bank_report_is_suspended(self):
        payment = self._new_payment()
        payment._basisbank_write_result({'basisbank_state': 'sent', 'basisbank_sent_date': fields.Datetime.now() - timedelta(hours=60)})
        with self._post_patch({'ErrorCode': 6}), mute_logger('odoo.addons.basis_bank.models.account_payment'):
            self.env['account.payment']._cron_basisbank_confirm_or_reset()
        self.assertEqual(self.connection.state, 'active')
        self.assertEqual(payment.basisbank_state, 'sent')

    def test_reply_without_our_transfer_leaves_the_payment_unknown(self):
        payment = self._new_payment()
        answer = {'ErrorCode': 0, 'Data': {'InternalTransfers': [{'ClientInternalID': payment.id + 1000, 'ErrorCode': 0, 'BankInternalID': 'X9'}]}}
        with self._service_patch('upload_single_batch', return_value=answer):
            payment.basisbank_send_with_otp('123456')
        self.assertEqual(payment.basisbank_state, 'unknown')
        self.assertFalse(payment.basisbank_bank_internal_id)

    def test_money_actions_need_the_basis_user_group(self):
        user = new_test_user(self.env, login='basis_no_group', groups='base.group_user,account.group_account_invoice')
        payment = self._new_payment().with_user(user)
        with self.assertRaises(AccessError):
            payment.basisbank_send_with_otp('123456')
        with self.assertRaises(AccessError):
            payment.action_basisbank_resync()
