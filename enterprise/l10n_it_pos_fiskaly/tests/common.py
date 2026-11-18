from contextlib import nullcontext

from odoo import Command
from odoo.addons.l10n_it_pos_fiskaly.models import pos_order
from odoo.addons.point_of_sale.tests.common import TestPoSCommon


class TestL10nItPosFiskalyCommon(TestPoSCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.basic_config
        cls.tax_22 = cls._l10n_it_tax('IT 22%', 22)
        cls.tax_10 = cls._l10n_it_tax('IT 10%', 10)
        cls.tax_4 = cls._l10n_it_tax('IT 4%', 4)
        cls.tax_exempt = cls._l10n_it_tax('IT Esenti', 0, exempt_reason='N4')
        cls.product_22 = cls.create_product('Product 22', cls.categ_basic, 122.0, tax_ids=cls.tax_22.ids)
        cls.product_10 = cls.create_product('Product 10', cls.categ_basic, 110.0, tax_ids=cls.tax_10.ids)
        cls.product_4 = cls.create_product('Product 4', cls.categ_basic, 104.0, tax_ids=cls.tax_4.ids)
        cls.product_exempt = cls.create_product('Product Exempt', cls.categ_basic, 100.0, tax_ids=cls.tax_exempt.ids)

    @classmethod
    def _l10n_it_tax(cls, name, amount, exempt_reason=False):
        values = {
            'name': name,
            'amount': amount,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'price_include_override': 'tax_included',
            'company_id': cls.company.id,
        }
        if exempt_reason and 'l10n_it_exempt_reason' in cls.env['account.tax']._fields:
            values['l10n_it_exempt_reason'] = exempt_reason
        return cls.env['account.tax'].create(values)

    def _order(self, lines, payment=None):
        order = self.env['pos.order'].create({
            'session_id': self.pos_session.id,
            'company_id': self.company.id,
            'lines': [Command.create(values) for values in lines],
            'is_refund': any(values.get('refunded_orderline_id') for values in lines),
            'amount_tax': 0.0,
            'amount_total': 0.0,
            'amount_paid': 0.0,
            'amount_return': 0.0,
        })
        order._compute_prices()
        if payment is None:
            payment = order.amount_total
        if payment:
            order.add_payment({
                'amount': payment,
                'payment_method_id': self.cash_pm1.id,
                'pos_order_id': order.id,
            })
        order.amount_paid = payment
        return order

    def _line(self, product, qty, price_unit, exemption=False, discount=0.0, taxes=None):
        taxes = product.taxes_id if taxes is None else taxes
        amounts = taxes.compute_all(
            price_unit * (1 - discount / 100), self.currency, qty, product=product)
        values = {
            'product_id': product.id,
            'qty': qty,
            'price_unit': price_unit,
            'discount': discount,
            'tax_ids': [Command.set(taxes.ids)],
            'price_subtotal': amounts['total_excluded'],
            'price_subtotal_incl': amounts['total_included'],
        }
        if exemption:
            values['l10n_it_fiskaly_vat_exemption'] = exemption
        return values

    def _l10n_it_return(self, original, quantities):
        lines = [
            {
                **self._line(line.product_id, -quantity, line.price_unit),
                'refunded_orderline_id': line.id,
            }
            for line, quantity in zip(original.lines, quantities)
            if quantity
        ]
        refund = self._order(lines, payment=0.0)
        refund.add_payment({
            'amount': refund.amount_total,
            'payment_method_id': self.cash_pm1.id,
            'pos_order_id': refund.id,
        })
        refund.amount_paid = refund.amount_total
        return refund._l10n_it_fiskaly_operation()

    def _entries(self, document):
        return {entry['data']['text']: entry['data'] for entry in document['entries']}

    def setUp(self):
        super().setUp()
        self.open_new_session()

    def _l10n_it_fake_fiskaly(self):
        calls = []

        class FakeClient:
            attempts = 0

            def create_record(self, content, idempotency_key=None, scope_identifier=None):
                calls.append(content['type'])
                if content['type'] == 'INTENTION':
                    return {'id': f'01890000-0000-7000-8000-{len(calls):012d}'}
                return {'id': f'record-{len(calls)}', 'state': 'COMPLETED', 'compliance': {'data': 'IT-0001'}}

        self.patch(pos_order, 'fiskaly_client', lambda company, subject=False: nullcontext(FakeClient()))
        self.config.write({
            'l10n_it_fiskaly_system_id': '01890000-0000-7000-8000-000000000020',
            'l10n_it_fiskaly_system_state': 'COMMISSIONED',
        })
        return calls

    def _l10n_it_assert_signed(self, order, calls):
        self.assertEqual(order.state, 'paid')
        self.assertEqual(calls, ['INTENTION', 'TRANSACTION'])
        self.assertTrue(order.l10n_it_fiskaly_record_id)
        self.assertEqual(order.l10n_it_fiskaly_compliance_number, 'IT-0001')
