# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.addons.point_of_sale.tests.test_pos_accounting import TestPosAccounting


class TestPosAccountingSettleDue(TestPosAccounting):

    def test_settle_customer_invoice(self):
        session = self.open_pos_session()
        customer_order = self.create_pos_order(
            payment_method=[[self.customer_pm, {'amount': 10.6}]],
            products=[[self.product_6, {}]],
            extra_data={'partner_id': self.partner_1.id},
        )
        self.close_session()
        self.assertEqual(self.partner_1.total_due, 10.6)

        account_move = customer_order.account_move
        account_move.settle_invoices_from_pos(
            session.id,
            [{'payment_method_id': self.cash_pm.id, 'amount': 10.6}],
        )

        self.assertEqual(self.partner_1.total_due, 0)
        self.assertEqual(account_move.payment_state, 'paid')
        self.assertEqual(account_move.amount_residual, 0)

    def test_settle_customer_invoice_partial(self):
        session = self.open_pos_session()
        customer_order = self.create_pos_order(
            payment_method=[[self.customer_pm, {'amount': 10.6}]],
            products=[[self.product_6, {}]],
            extra_data={'partner_id': self.partner_1.id},
        )
        self.close_session()
        self.assertEqual(self.partner_1.total_due, 10.6)

        account_move = customer_order.account_move
        account_move.settle_invoices_from_pos(
            session.id,
            [{'payment_method_id': self.cash_pm.id, 'amount': 5.0}],
        )

        self.assertEqual(self.partner_1.total_due, 5.6)
        # The closing invoice is paid at closing, the debt is on the transfer entry
        transfer_line = self.env['account.move.line'].search([
            ('partner_id', '=', self.partner_1.id),
            ('account_id', '=', self.partner_1.property_account_receivable_id.id),
            ('move_id.move_type', '=', 'entry'),
            ('balance', '>', 0),
        ])
        self.assertEqual(transfer_line.amount_residual, 5.6)

    def test_settle_customer_invoice_multi_payment(self):
        session = self.open_pos_session()
        customer_order = self.create_pos_order(
            payment_method=[[self.customer_pm, {'amount': 10.6}]],
            products=[[self.product_6, {}]],
            extra_data={'partner_id': self.partner_1.id},
        )
        self.close_session()
        self.assertEqual(self.partner_1.total_due, 10.6)

        account_move = customer_order.account_move
        account_move.settle_invoices_from_pos(
            session.id,
            [
                {'payment_method_id': self.cash_pm.id, 'amount': 5.0},
                {'payment_method_id': self.bank_pm.id, 'amount': 5.6},
            ],
        )

        self.assertEqual(self.partner_1.total_due, 0)
        self.assertEqual(account_move.payment_state, 'paid')      # Waiting for card payment to be reconciled
        self.assertEqual(account_move.amount_residual, 0)
