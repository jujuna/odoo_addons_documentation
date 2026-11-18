from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase


class BogCommon(TransactionCase):
    """Shared fixture for the Bank of Georgia tests; the HTTP layer is always mocked."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Durable writes use registry.cursor(); test mode makes it share this transaction
        # instead of opening a second connection that blocks on our row lock.
        cls.enterClassContext(cls.registry_test_mode())
        cls.company = cls.env.company
        cls.service = cls.env['bog.service']

        # One connection per company: reuse an existing one (the rollback restores it).
        connection_vals = {
            'client_id': 'test-client-id',
            'client_secret': 'test-secret',
            'processing_mode': 'direct',
            'approval_id': False,
            'allow_self_approval': False,
            'state': 'draft',
            'access_token': False,
            'token_expiry': False,
        }
        Connection = cls.env['bog.connection']
        cls.connection = Connection.search([('company_id', '=', cls.company.id)], limit=1)
        if cls.connection:
            cls.connection.write(connection_vals)
        else:
            cls.connection = Connection.create(dict(connection_vals, company_id=cls.company.id))

        cls.company_bank = cls.env['res.partner.bank'].create({
            'account_number': 'GE29BG7777777777777777',
            'partner_id': cls.company.partner_id.id,
            'bank_bic': 'BAGAGE22',
        })
        cls.journal = cls.env['account.journal'].create({
            'name': 'BOG GEL', 'type': 'bank', 'code': 'BOGTG',
            'bank_account_id': cls.company_bank.id,
        })

        method = cls.env.ref('bog_bank.account_payment_method_bog')
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

        cls.partner = cls.env['res.partner'].create({'name': 'Test Beneficiary',
                                                     'vat': 'GE123456789'})
        cls.partner_bank = cls.env['res.partner.bank'].create({
            'account_number': 'GE29BG9999999999999999',
            'partner_id': cls.partner.id,
            'bank_bic': 'BAGAGE22',
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
            'amount': 100.0,
            'memo': 'Test transfer',
        }
        base.update(vals)
        payment = self.env['account.payment'].create(base)
        if post:
            payment.action_post()
        return payment

    @staticmethod
    def _response(status=200, body='', headers=None):
        """A stand-in for requests.Response."""
        response = MagicMock()
        response.status_code = status
        response.text = body
        response.headers = headers or {}
        return response
