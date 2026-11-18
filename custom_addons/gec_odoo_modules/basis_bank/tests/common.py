from unittest.mock import MagicMock, patch

from odoo import Command
from odoo.tests.common import TransactionCase, new_test_user


class BasisCommon(TransactionCase):
    """Shared fixture for the Basis Bank tests. The HTTP layer is always mocked."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # In test mode registry.cursor() shares this transaction, so durable writes do not wait on its locks.
        cls.enterClassContext(cls.registry_test_mode())
        cls.company = cls.env.company
        cls.service = cls.env['basisbank.service']
        cls.approver = new_test_user(
            cls.env, login='basis_approver',
            groups='base.group_user,account.group_account_manager,basis_bank.group_basisbank_user')
        cls.approval = cls.env['basisbank.approval'].create({
            'approver_id': cls.approver.id, 'company_id': cls.company.id})

        # One connection per company: reuse a real one if the database has it (rolled back after the test).
        connection_vals = {
            'login_name': 'test-login',
            'password': 'test-password',
            'processing_mode': 'direct',
            'state': 'active',
            'ticket_id': False,
            'ticket_expiry': False,
        }
        Connection = cls.env['basisbank.connection']
        cls.connection = Connection.search([('company_id', '=', cls.company.id)], limit=1)
        if cls.connection:
            cls.connection.write(connection_vals)
        else:
            cls.connection = Connection.create(dict(connection_vals, company_id=cls.company.id))

        cls.company_bank = cls.env['res.partner.bank'].create({
            'account_number': 'GE29CB7777777777777701',
            'partner_id': cls.company.partner_id.id,
            'bank_bic': 'CBASGE22',
        })
        cls.gel = cls.env.ref('base.GEL')
        cls.gel.active = True
        cls.journal = cls.env['account.journal'].create({
            'name': 'Basis GEL', 'type': 'bank', 'code': 'BASTG',
            'bank_account_id': cls.company_bank.id, 'currency_id': cls.gel.id,
        })
        method = cls.env.ref('basis_bank.account_payment_method_basisbank')
        cls.method_line = cls.journal.outbound_payment_method_line_ids.filtered(
            lambda line: line.payment_method_id == method)[:1]
        if not cls.method_line:
            cls.method_line = cls.env['account.payment.method.line'].create({
                'name': method.name, 'payment_method_id': method.id, 'journal_id': cls.journal.id})
        if not cls.method_line.payment_account_id:
            cls.method_line.payment_account_id = cls.env['account.account'].create({
                'name': 'Basis Outstanding', 'code': 'BASOUT', 'account_type': 'asset_current',
                'reconcile': True})

        cls.partner = cls.env['res.partner'].create({'name': 'Basis Beneficiary', 'vat': '123456789'})
        cls.partner_bank = cls.env['res.partner.bank'].create({
            'account_number': 'GE29CB9999999999999999',
            'partner_id': cls.partner.id,
            'bank_bic': 'CBASGE22',
            'allow_out_payment': True,
        })
        cls.other_bank = cls.env['res.partner.bank'].create({
            'account_number': 'GE29TB9999999999999998',
            'partner_id': cls.partner.id,
            'bank_bic': 'TBCBGE22',
            'allow_out_payment': True,
        })

    def _new_payment(self, post=True, **vals):
        base = {
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.partner.id,
            'partner_bank_id': self.partner_bank.id,
            'journal_id': self.journal.id,
            'payment_method_line_id': self.method_line.id,
            'amount': 50.0,
            'memo': 'Basis test transfer',
            'basisbank_transfer_type': 'internal',
        }
        base.update(vals)
        payment = self.env['account.payment'].create({key: value for key, value in base.items() if value is not None})
        if post:
            payment.action_post()
        return payment

    def _new_batch(self, payments):
        return self.env['account.batch.payment'].create({
            'journal_id': self.journal.id,
            'batch_type': 'outbound',
            'payment_method_id': self.method_line.payment_method_id.id,
            'payment_ids': [Command.set(payments.ids)],
        })

    def _with_ticket(self):
        self.connection.store_ticket('ticket-1')

    def _service_patch(self, method, **kwargs):
        return patch.object(type(self.service), method, **kwargs)

    def _set_odoo_approve(self):
        self.connection.write({'processing_mode': 'odoo_approve', 'approval_id': self.approval.id})

    @staticmethod
    def _response(status=200, payload=None):
        """A stand-in for requests.Response carrying only what the service reads."""
        response = MagicMock()
        response.status_code = status
        response.json.return_value = payload or {}
        response.text = 'x' if payload is not None else ''
        response.raise_for_status.return_value = None
        return response
