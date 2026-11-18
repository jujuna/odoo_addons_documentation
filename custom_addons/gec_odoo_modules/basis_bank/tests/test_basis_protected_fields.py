from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import Form, tagged

from odoo.addons.basis_bank.models.account_batch_payment import BASISBANK_BATCH_PROTECTED_FIELDS
from odoo.addons.basis_bank.models.account_payment import BASISBANK_PROTECTED_FIELDS

from .common import BasisCommon


@tagged('post_install', '-at_install')
class TestBasisProtectedFields(BasisCommon):
    """Only the Basis flows write the transfer state, the bank's answers and the approval."""

    def test_protected_fields_are_readonly(self):
        """The web client sends every non-readonly value; a protected field would make forms refuse to save."""
        for model, names in (('account.payment', BASISBANK_PROTECTED_FIELDS),
                             ('account.batch.payment', BASISBANK_BATCH_PROTECTED_FIELDS)):
            for name in names:
                self.assertTrue(self.env[model]._fields[name].readonly, (model, name))

    def test_state_and_approval_cannot_be_written_directly(self):
        payment = self._new_payment()
        for vals in ({'basisbank_state': 'awaiting_otp'},
                     {'basisbank_approved_by': self.approver.id},
                     {'basisbank_bank_internal_id': 'X-1'}):
            with self.assertRaises(UserError):
                payment.write(vals)
        with self.assertRaises(UserError):
            self._new_payment(post=False, basisbank_state='sent')
        batch = self._new_batch(self._new_payment())
        with self.assertRaises(UserError):
            batch.write({'basisbank_state': 'awaiting_otp'})
        self.assertEqual(payment.basisbank_state, 'pending')

    def test_approval_flow_still_writes_its_fields(self):
        self._set_odoo_approve()
        payment = self._new_payment()
        payment.action_basisbank_submit_for_approval()
        payment.with_user(self.approver).action_basisbank_approve()
        self.assertEqual(payment.basisbank_state, 'awaiting_otp')
        self.assertEqual(payment.basisbank_approved_by, self.approver)

    def test_payment_form_still_saves(self):
        form = Form(self.env['account.payment'].with_context(
            default_payment_type='outbound', default_partner_type='supplier'))
        form.journal_id = self.journal
        form.partner_id = self.partner
        form.amount = 15
        form.payment_method_line_id = self.method_line
        payment = form.save()
        self.assertEqual(payment.basisbank_state, 'pending')

    def test_payment_joining_an_approved_batch_voids_its_approval(self):
        batch = self._new_batch(self._new_payment())
        batch._gec_bank_internal_write({'basisbank_state': 'awaiting_otp',
                                        'basisbank_approved_by': self.approver.id,
                                        'basisbank_approved_date': fields.Datetime.now()})
        self._new_payment(batch_payment_id=batch.id)
        self.assertEqual(batch.basisbank_state, 'draft')
        self.assertFalse(batch.basisbank_approved_by)

    def test_payment_leaving_an_approved_batch_voids_its_approval(self):
        first, second = self._new_payment(), self._new_payment()
        batch = self._new_batch(first | second)
        batch._gec_bank_internal_write({'basisbank_state': 'awaiting_otp',
                                        'basisbank_approved_by': self.approver.id})
        second.write({'batch_payment_id': False})
        self.assertEqual(batch.basisbank_state, 'draft')
        self.assertFalse(batch.basisbank_approved_by)

    def test_send_needs_write_access(self):
        payment = self._new_payment()
        reader = self.env['res.users'].create({
            'name': 'Basis Reader', 'login': 'basis_reader',
            'group_ids': [Command.set([self.env.ref('base.group_user').id,
                                              self.env.ref('account.group_account_readonly').id])],
        })
        with self.assertRaises(AccessError):
            payment.with_user(reader).basisbank_send_with_otp('123456')
