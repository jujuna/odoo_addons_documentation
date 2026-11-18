from odoo import Command
from odoo.exceptions import ValidationError
from odoo.addons.l10n_it_pos_fiskaly.models import pos_order
from odoo.addons.l10n_it_pos_fiskaly.tests.common import TestL10nItPosFiskalyCommon
from odoo.tests import tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nItPosFiskalyDocument(TestL10nItPosFiskalyCommon):

    def test_single_line_totals(self):
        order = self._order([self._line(self.product_22, 1, 122.0)])
        document = order._l10n_it_fiskaly_document()
        entry = document['entries'][0]
        self.assertEqual(entry['type'], 'SALE')
        self.assertEqual(entry['details']['concept'], 'GOOD')
        self.assertEqual(entry['data']['type'], 'ITEM')
        self.assertEqual(entry['data']['text'], 'Product 22')
        self.assertEqual(entry['data']['unit']['quantity'], '1.00')
        self.assertEqual(document['totals']['vat']['inclusive'], '122.00')
        self.assertEqual(float(document['totals']['vat']['exclusive']), 100.0)
        self.assertEqual(float(document['totals']['vat']['amount']), 22.0)

    def test_quantity_is_reported_per_unit(self):
        order = self._order([self._line(self.product_22, 5, 122.0)])
        document = order._l10n_it_fiskaly_document()
        entry = document['entries'][0]['data']
        self.assertEqual(entry['unit']['quantity'], '5.00')
        self.assertEqual(float(entry['unit']['price']['inclusive']), 122.0)
        self.assertEqual(float(entry['value']['base']), 500.0)
        self.assertEqual(document['totals']['vat']['inclusive'], '610.00')

    def test_included_price_with_an_unrounded_base_has_no_discount(self):
        order = self._order([
            self._line(self.product_22, 1, 885.0),
            self._line(self.product_22, 1, 1799.0),
        ])
        entries = order._l10n_it_fiskaly_document()['entries']
        for entry, inclusive, exclusive in (
            (entries[0]['data'], '885.00000000', '725.40983607'),
            (entries[1]['data'], '1799.00000000', '1474.59016393'),
        ):
            self.assertEqual(entry['unit']['price']['inclusive'], inclusive)
            self.assertEqual(entry['unit']['price']['exclusive'], exclusive)
            self.assertEqual(entry['value']['base'], exclusive)
            self.assertEqual(entry['value']['discount'], '0.00000000')
            self.assertEqual(entry['vat']['exclusive'], exclusive)

    def test_mixed_rates_produce_one_bucket_each(self):
        order = self._order([
            self._line(self.product_22, 1, 122.0),
            self._line(self.product_10, 1, 110.0),
            self._line(self.product_4, 1, 104.0),
        ])
        document = order._l10n_it_fiskaly_document()
        self.assertEqual(len(document['entries']), 3)
        codes = {vat['code'] for vat in document['breakdown']}
        self.assertEqual(codes, {'STANDARD', 'REDUCED_1', 'REDUCED_3'})
        self.assertEqual(document['totals']['vat']['inclusive'], '336.00')

    def test_totals_match_the_breakdown(self):
        order = self._order([
            self._line(self.product_22, 3, 122.0),
            self._line(self.product_10, 7, 110.0),
        ])
        document = order._l10n_it_fiskaly_document()
        totals = document['totals']['vat']
        self.assertAlmostEqual(
            float(totals['amount']),
            sum(float(vat['amount']) for vat in document['breakdown']), places=8)
        self.assertAlmostEqual(
            float(totals['exclusive']),
            sum(float(vat['exclusive']) for vat in document['breakdown']), places=8)

    def test_line_discount_is_reported(self):
        order = self._order([self._line(self.product_22, 1, 122.0, discount=10.0)])
        document = order._l10n_it_fiskaly_document()
        entry = document['entries'][0]['data']
        self.assertEqual(float(entry['value']['base']), 100.0)
        self.assertAlmostEqual(float(entry['value']['discount']), 12.2, places=2)
        self.assertEqual(document['totals']['vat']['inclusive'], '109.80')
        self.assertAlmostEqual(float(entry['vat']['exclusive']), 90.0, places=6)
        self.assertAlmostEqual(float(entry['vat']['amount']), 19.8, places=6)

    def test_full_discount_is_a_gift(self):
        order = self._order([self._line(self.product_22, 1, 122.0, discount=100.0)], payment=0.0)
        document = order._l10n_it_fiskaly_document()
        entry = document['entries'][0]
        self.assertEqual(entry['details']['purpose'], 'GIFT')
        self.assertEqual(float(entry['data']['value']['discount']), 0.0)
        self.assertAlmostEqual(float(entry['data']['vat']['exclusive']), 100.0, places=6)
        self._assert_gift_declared_at_full_price(document)

    def test_gift_with_a_paid_item_declares_both_but_collects_the_paid_one(self):
        order = self._order([
            self._line(self.product_22, 1, 122.0, discount=100.0),
            self._line(self.product_22, 1, 122.0),
        ])
        document = order._l10n_it_fiskaly_document()
        self.assertEqual([entry['details'].get('purpose') for entry in document['entries']], ['GIFT', None])
        self.assertEqual(len(document['breakdown']), 1)
        self.assertAlmostEqual(float(document['breakdown'][0]['exclusive']), 200.0, places=6)
        self.assertAlmostEqual(float(document['breakdown'][0]['amount']), 44.0, places=6)
        self.assertEqual(document['totals']['vat']['inclusive'], '244.00')
        self.assertEqual(sum(float(payment['details']['amount']) for payment in document['payments']), 122.0)
        self.assertFalse(any('discount' in payment['details'] for payment in document['payments']))

    def _assert_gift_declared_at_full_price(self, document):
        self.assertEqual(len(document['breakdown']), 1)
        self.assertEqual(document['breakdown'][0]['code'], 'STANDARD')
        self.assertAlmostEqual(float(document['breakdown'][0]['exclusive']), 100.0, places=6)
        self.assertAlmostEqual(float(document['breakdown'][0]['amount']), 22.0, places=6)
        self.assertEqual(document['breakdown'][0]['inclusive'], '122.00')
        self.assertEqual(document['totals']['vat']['inclusive'], '122.00')
        self.assertAlmostEqual(float(document['totals']['vat']['exclusive']), 100.0, places=6)
        self.assertAlmostEqual(float(document['totals']['vat']['amount']), 22.0, places=6)
        self.assertEqual(document['payments'], [{
            'type': 'CASH',
            'details': {'amount': '0.00'},
        }])

    def test_cart_discount_is_distributed_proportionally(self):
        if 'discount_product_id' not in self.env['pos.config']._fields:
            self.skipTest('pos_discount is not installed')
        discount_product = self.create_product(
            'Global Discount', self.categ_basic, 0.0, tax_ids=self.tax_22.ids)
        self.config.discount_product_id = discount_product
        order = self._order([
            self._line(self.product_22, 1, 366.0),
            self._line(self.product_22, 1, 122.0),
            self._line(discount_product, 1, -61.0),
        ])
        document = order._l10n_it_fiskaly_document()
        self.assertEqual(len(document['entries']), 2)
        discounts = sorted(
            float(entry['data']['value']['discount']) for entry in document['entries'])
        self.assertAlmostEqual(sum(discounts), 61.0, places=2)
        self.assertAlmostEqual(discounts[1] / discounts[0], 3.0, places=2)

    def test_payment_discount_does_not_reduce_the_vat(self):
        plain = self._order([self._line(self.product_22, 1, 122.0)])
        expected = plain._l10n_it_fiskaly_document()['totals']['vat']['amount']
        self._enable_cash_rounding()
        order = self._order([self._line(self.product_22, 1, 122.0)], payment=0.0)
        order.add_payment({
            'amount': 120.0,
            'payment_method_id': self.cash_pm1.id,
            'pos_order_id': order.id,
        })
        order.amount_paid = 120.0
        document = order._l10n_it_fiskaly_document()
        self.assertEqual(document['totals']['vat']['amount'], expected)
        self.assertEqual(document['payments'][0]['details']['discount'], '2.00')

    def test_payment_types(self):
        order = self._order([self._line(self.product_22, 1, 122.0)], payment=0.0)
        order.add_payment({
            'amount': 22.0,
            'payment_method_id': self.cash_pm1.id,
            'pos_order_id': order.id,
        })
        order.add_payment({
            'amount': 100.0,
            'payment_method_id': self.bank_pm1.id,
            'pos_order_id': order.id,
        })
        order.amount_paid = 122.0
        document = order._l10n_it_fiskaly_document()
        types = [payment['type'] for payment in document['payments']]
        self.assertEqual(sorted(types), ['CARD', 'CASH'])
        collected = sum(float(payment['details']['amount']) for payment in document['payments'])
        self.assertEqual(collected, 122.0)

    def test_refund_is_a_correction(self):
        original = self._order([self._line(self.product_22, 1, 122.0)])
        original.l10n_it_fiskaly_record_id = '01890000-0000-7000-8000-000000000000'
        refund = self._order([{
            **self._line(self.product_22, -1, 122.0),
            'refunded_orderline_id': original.lines[0].id,
        }], payment=-122.0)
        operation = refund._l10n_it_fiskaly_operation()
        self.assertEqual(operation['type'], 'CORRECTION')
        self.assertEqual(operation['record']['id'], original.l10n_it_fiskaly_record_id)
        entry = operation['data']['entries'][0]
        self.assertEqual(entry['type'], 'RETURN')
        self.assertEqual(entry['data']['unit']['quantity'], '1.00')
        self.assertEqual(operation['data']['totals']['vat']['inclusive'], '122.00')

    def _l10n_it_jacket_and_t_shirts(self):
        jacket = self.create_product('Jacket', self.categ_basic, 61.0, tax_ids=self.tax_22.ids)
        t_shirt = self.create_product('T-shirt', self.categ_basic, 24.4, tax_ids=self.tax_22.ids)
        original = self._order([self._line(jacket, 1, 61.0), self._line(t_shirt, 2, 24.4)])
        original.l10n_it_fiskaly_record_id = '01890000-0000-7000-8000-000000000010'
        return original

    def test_partial_return_is_a_correction_of_the_returned_entry(self):
        original = self._l10n_it_jacket_and_t_shirts()
        operation = self._l10n_it_return(original, [0, 1])
        self.assertEqual(operation['type'], 'CORRECTION')
        self.assertEqual(operation['record'], {'id': original.l10n_it_fiskaly_record_id})
        self.assertEqual(operation['data']['type'], 'RECEIPT')
        [entry] = operation['data']['entries']
        self.assertEqual(entry['type'], 'RETURN')
        self.assertEqual(entry['details'], {'concept': 'GOOD', 'number': '2'})
        self.assertEqual(entry['data']['text'], 'T-shirt')
        self.assertEqual(entry['data']['unit']['quantity'], '1.00')
        self.assertEqual(entry['data']['unit']['price']['inclusive'], '24.40000000')
        self.assertEqual(entry['data']['vat']['inclusive'], '24.40')
        self.assertEqual(operation['data']['totals']['vat']['inclusive'], '24.40')
        self.assertEqual(operation['data']['breakdown'][0]['inclusive'], '24.40')
        self.assertEqual(operation['data']['payments'], [{
            'type': 'CASH',
            'details': {'amount': '24.40'},
        }])

    def test_return_after_a_combo_uses_the_sent_entry_number(self):
        original = self._order([
            self._line(self.product_22, 1, 0.0),
            self._line(self.product_10, 1, 110.0),
            self._line(self.product_4, 1, 104.0),
        ])
        parent_line, child_line, _line = original.lines
        child_line.combo_parent_id = parent_line
        original.l10n_it_fiskaly_record_id = '01890000-0000-7000-8000-000000000011'
        operation = self._l10n_it_return(original, [0, 0, 1])
        self.assertEqual(operation['data']['entries'][0]['details']['number'], '2')

    def test_full_return_lists_every_original_entry(self):
        original = self._l10n_it_jacket_and_t_shirts()
        operation = self._l10n_it_return(original, [1, 2])
        entries = operation['data']['entries']
        self.assertEqual(
            [(entry['type'], entry['details']['number'], entry['data']['text'],
              entry['data']['unit']['quantity']) for entry in entries],
            [('RETURN', '1', 'Jacket', '1.00'), ('RETURN', '2', 'T-shirt', '2.00')])
        self.assertEqual(operation['data']['totals']['vat']['inclusive'], '109.80')
        self.assertEqual(operation['data']['payments'], [{
            'type': 'CASH',
            'details': {'amount': '109.80'},
        }])

    def test_return_values_are_positive(self):
        original = self._l10n_it_jacket_and_t_shirts()
        operation = self._l10n_it_return(original, [1, 1])

        def amounts(value):
            if isinstance(value, dict):
                for item in value.values():
                    yield from amounts(item)
            elif isinstance(value, list):
                for item in value:
                    yield from amounts(item)
            elif isinstance(value, str):
                try:
                    yield float(value)
                except ValueError:
                    pass

        self.assertTrue(all(amount >= 0 for amount in amounts(operation['data'])))

    def _enable_cash_rounding(self):
        rounding = self.env['account.cash.rounding'].create({
            'name': 'Cash Rounding 0.05',
            'rounding': 0.05,
            'rounding_method': 'HALF-UP',
            'strategy': 'add_invoice_line',
            'company_id': self.company.id,
        })
        self.config.write({
            'cash_rounding': True,
            'only_round_cash_method': True,
            'rounding_method': rounding.id,
        })
        return rounding

    def test_payments_reconcile_the_document_total(self):
        order = self._order([self._line(self.product_22, 1, 122.0)])
        document = order._l10n_it_fiskaly_document()
        collected = sum(float(payment['details']['amount']) for payment in document['payments'])
        self.assertEqual(collected, float(document['totals']['vat']['inclusive']))
        self.assertNotIn('discount', document['payments'][0]['details'])

    def test_cash_rounding_is_declared_on_the_payment(self):
        self._enable_cash_rounding()
        order = self._order([self._line(self.product_22, 1, 122.0)], payment=0.0)
        rounded = order._get_rounded_amount(order.amount_total)
        order.add_payment({
            'amount': rounded,
            'payment_method_id': self.cash_pm1.id,
            'pos_order_id': order.id,
        })
        order.amount_paid = rounded
        document = order._l10n_it_fiskaly_document()
        cash = document['payments'][0]
        self.assertEqual(cash['type'], 'CASH')
        declared = float(cash['details']['amount']) + float(cash['details'].get('discount', 0.0))
        self.assertAlmostEqual(
            declared, float(document['totals']['vat']['inclusive']), places=2)

    def test_cash_rounding_does_not_change_the_vat(self):
        order = self._order([self._line(self.product_22, 1, 122.0)])
        without = order._l10n_it_fiskaly_document()['totals']['vat']['amount']
        self._enable_cash_rounding()
        rounded = self._order([self._line(self.product_22, 1, 122.0)])
        self.assertEqual(rounded._l10n_it_fiskaly_document()['totals']['vat']['amount'], without)

    def _l10n_it_cash_document(self, total, cash):
        order = self._order([self._line(self.product_22, 1, total)], payment=cash)
        return order._l10n_it_fiskaly_document()

    def test_cash_rounding_down_is_a_cash_discount(self):
        self._enable_cash_rounding()
        for total, cash, discount in (
            (23.01, 23.00, '0.01'),
            (23.02, 23.00, '0.02'),
            (23.06, 23.05, '0.01'),
            (23.07, 23.05, '0.02'),
        ):
            with self.subTest(total=total):
                document = self._l10n_it_cash_document(total, cash)
                self.assertEqual(document['totals']['vat']['inclusive'], f'{total:.2f}')
                self.assertEqual(document['payments'], [{
                    'type': 'CASH',
                    'details': {'amount': f'{cash:.2f}', 'discount': discount},
                }])

    def test_cash_rounding_up_is_added_to_the_cash_amount(self):
        self._enable_cash_rounding()
        for total, cash in (
            (23.03, 23.05),
            (23.04, 23.05),
            (23.08, 23.10),
            (23.09, 23.10),
        ):
            with self.subTest(total=total):
                document = self._l10n_it_cash_document(total, cash)
                self.assertEqual(document['totals']['vat']['inclusive'], f'{total:.2f}')
                self.assertEqual(document['payments'], [{
                    'type': 'CASH',
                    'details': {'amount': f'{cash:.2f}'},
                }])

    def test_cash_total_on_the_rounding_step_is_not_rounded(self):
        self._enable_cash_rounding()
        document = self._l10n_it_cash_document(23.05, 23.05)
        self.assertEqual(document['payments'], [{
            'type': 'CASH',
            'details': {'amount': '23.05'},
        }])

    def test_card_payment_is_not_rounded(self):
        self._enable_cash_rounding()
        order = self._order([self._line(self.product_22, 1, 23.02)], payment=0.0)
        order.add_payment({
            'amount': 23.02,
            'payment_method_id': self.bank_pm1.id,
            'pos_order_id': order.id,
        })
        order.amount_paid = 23.02
        document = order._l10n_it_fiskaly_document()
        self.assertEqual(document['payments'], [{
            'type': 'CARD',
            'kind': 'DEBIT',
            'number': '****',
            'details': {'amount': '23.02'},
        }])

    def test_exemption_codes_other_than_not_subject_are_emitted(self):
        for code in ('NOT_TAXABLE', 'CAUSE_1', 'CAUSE_2', 'CAUSE_3', 'CAUSE_4'):
            order = self._order([self._line(self.product_exempt, 1, 100.0, exemption=code)])
            document = order._l10n_it_fiskaly_document()
            self.assertEqual(document['entries'][0]['data']['vat'],
                {'type': 'VAT_EXEMPTION', 'code': code})
            self.assertEqual(document['breakdown'][0]['code'], code)

    def test_vat_total_is_not_derived_from_the_rounded_total(self):
        order = self._order([self._line(self.product_22, 3, 0.99)])
        document = order._l10n_it_fiskaly_document()
        totals = document['totals']['vat']
        exclusive = float(totals['exclusive'])
        self.assertAlmostEqual(float(totals['amount']), exclusive * 0.22, places=6)
        self.assertNotEqual(
            totals['amount'],
            self.currency.round(float(totals['inclusive']) - exclusive))

    def test_entry_text_is_capped_at_256_characters(self):
        product = self.create_product('A' * 300, self.categ_basic, 122.0, tax_ids=self.tax_22.ids)
        order = self._order([self._line(product, 1, 122.0)])
        self.assertEqual(len(order._l10n_it_fiskaly_document()['entries'][0]['data']['text']), 256)

    def test_combo_parent_is_not_an_entry(self):
        parent = self._line(self.product_22, 1, 0.0)
        order = self._order([parent, self._line(self.product_10, 1, 110.0)])
        parent_line, child_line = order.lines
        child_line.combo_parent_id = parent_line
        document = order._l10n_it_fiskaly_document()
        self.assertEqual(len(document['entries']), 1)
        self.assertEqual(document['entries'][0]['data']['text'], 'Product 10')

    def test_fiscal_position_mapping_is_used(self):
        self.tax_exempt.original_tax_ids = [Command.link(self.tax_22.id)]
        position = self.env['account.fiscal.position'].create({
            'name': 'Esportazioni',
            'company_id': self.company.id,
            'tax_ids': [Command.link(self.tax_exempt.id)],
        })
        order = self._order([self._line(self.product_22, 1, 122.0, exemption='CAUSE_1')])
        order.fiscal_position_id = position
        order.lines.invalidate_recordset(['tax_ids_after_fiscal_position'])
        document = order._l10n_it_fiskaly_document()
        self.assertEqual(document['entries'][0]['data']['vat'], {'type': 'VAT_EXEMPTION', 'code': 'CAUSE_1'})

    def test_refund_of_an_unsigned_order_is_not_transmitted(self):
        original = self._order([self._line(self.product_22, 1, 122.0)])
        refund = self._order([{
            **self._line(self.product_22, -1, 122.0),
            'refunded_orderline_id': original.lines[0].id,
        }], payment=-122.0)
        self.assertTrue(refund._l10n_it_fiskaly_requires_manual_document())
        self.config.write({
            'l10n_it_fiskaly_system_id': '01890000-0000-7000-8000-000000000001',
            'l10n_it_fiskaly_system_state': 'COMMISSIONED',
        })

        def forbidden(*args, **kwargs):
            raise AssertionError('fiskaly must not be contacted for an unsigned return')

        self.patch(pos_order, 'fiskaly_client', forbidden)
        refund.write({'state': 'paid'})
        self.assertFalse(refund.l10n_it_fiskaly_record_id)

    def test_refund_of_a_signed_order_does_not_require_a_manual_document(self):
        original = self._order([self._line(self.product_22, 1, 122.0)])
        original.l10n_it_fiskaly_record_id = '01890000-0000-7000-8000-000000000000'
        refund = self._order([{
            **self._line(self.product_22, -1, 122.0),
            'refunded_orderline_id': original.lines[0].id,
        }], payment=-122.0)
        self.assertFalse(refund._l10n_it_fiskaly_requires_manual_document())

    def test_refund_receipt_references_the_original_document(self):
        original = self._order([self._line(self.product_22, 1, 122.0)])
        original.l10n_it_fiskaly_compliance_number = 'DCW2026/0001-0001'
        refund = self._order([{
            **self._line(self.product_22, -1, 122.0),
            'refunded_orderline_id': original.lines[0].id,
        }], payment=-122.0)
        self.assertIn('Refund of DCW2026/0001-0001', refund.order_receipt_generate_html())

    def _l10n_it_clear_cash_rounding(self):
        self.config.write({'cash_rounding': False, 'rounding_method': False})
        self.env['account.cash.rounding'].search(
            [('company_id', '=', self.company.id)]).unlink()

    def test_cashier_payment_signs_the_order(self):
        calls = self._l10n_it_fake_fiskaly()
        data = self.create_ui_order_data([(self.product_22, 1)], payments=[(self.bank_pm1, 122.0)])
        self.env['pos.order'].sync_from_ui([data])
        order = self.env['pos.order'].search([('uuid', '=', data['uuid'])])
        self._l10n_it_assert_signed(order, calls)

    def test_free_item_is_a_gift_at_its_list_price(self):
        order = self._order([self._line(self.product_22, 1, 0.0)], payment=0.0)
        document = order._l10n_it_fiskaly_document()
        entry = document['entries'][0]
        self.assertEqual(entry['details']['purpose'], 'GIFT')
        self.assertEqual(entry['data']['vat']['exclusive'], '100.00000000')
        self._assert_gift_declared_at_full_price(document)

    def test_free_item_without_list_price_is_not_declared(self):
        product = self.create_product('Free Product', self.categ_basic, 0.0, tax_ids=self.tax_22.ids)
        order = self._order([
            self._line(product, 1, 0.0),
            self._line(self.product_22, 1, 122.0),
        ])
        self.assertEqual([entry['data']['text'] for entry in order._l10n_it_fiskaly_document()['entries']], ['Product 22'])

    def test_order_with_only_items_without_value_is_not_sent_to_fiskaly(self):
        calls = self._l10n_it_fake_fiskaly()
        product = self.create_product('Free Product', self.categ_basic, 0.0, tax_ids=self.tax_22.ids)
        order = self._order([self._line(product, 1, 0.0)], payment=0.0)
        order.state = 'paid'
        self.assertEqual(calls, [])

    def test_free_order_has_a_zero_cash_payment(self):
        order = self._order([self._line(self.product_22, 1, 0.0)], payment=0.0)
        self.assertEqual(order._l10n_it_fiskaly_document()['payments'], [{
            'type': 'CASH',
            'details': {'amount': '0.00'},
        }])

    def test_order_without_quantity_is_not_sent_to_fiskaly(self):
        calls = self._l10n_it_fake_fiskaly()
        order = self._order([self._line(self.product_22, 0, 122.0)], payment=0.0)
        order.state = 'paid'
        self.assertEqual(calls, [])

    def test_fiscal_printer_disables_fiskaly(self):
        calls = self._l10n_it_fake_fiskaly()
        self.config.receipt_printer_ids = self.env['pos.printer'].create({
            'name': 'Fiscal Printer',
            'printer_type': 'it_fiscal_printer',
            'use_type': 'receipt',
            'printer_ip': '192.168.1.1',
        })
        data = self.create_ui_order_data([(self.product_22, 1)], payments=[(self.bank_pm1, 122.0)])
        self.env['pos.order'].sync_from_ui([data])
        self.assertEqual(calls, [])

    def test_free_self_order_signs_the_order(self):
        calls = self._l10n_it_fake_fiskaly()
        order = self._order([self._line(self.product_22, 1, 0.0)], payment=0.0)
        order.state = 'paid'
        self._l10n_it_assert_signed(order, calls)

    def test_self_order_exempt_product_is_signed_with_its_natura(self):
        calls = self._l10n_it_fake_fiskaly()
        data = self.create_ui_order_data([(self.product_exempt, 1)], payments=[(self.bank_pm1, 100.0)])
        self.env['pos.order'].sync_from_ui([data])
        order = self.env['pos.order'].search([('uuid', '=', data['uuid'])])
        self._l10n_it_assert_signed(order, calls)
        self.assertEqual(order._l10n_it_fiskaly_document()['entries'][0]['data']['vat']['code'], 'CAUSE_1')

    def test_return_preset_prevents_opening_a_session(self):
        self.config.write({
            'use_presets': True,
            'available_preset_ids': [Command.create({'name': 'Return', 'is_return': True})],
        })
        with self.assertRaises(ValidationError):
            self.config._l10n_it_fiskaly_check_presets()

    def test_cash_rounding_is_not_created_without_the_company_accounts(self):
        self._l10n_it_clear_cash_rounding()
        self.company.write({
            'cash_rounding_profit_account_id': False,
            'cash_rounding_loss_account_id': False,
        })
        self.assertFalse(self.config._l10n_it_fiskaly_cash_rounding())
        self.config._l10n_it_fiskaly_apply_cash_rounding()
        self.assertFalse(self.config.cash_rounding)

    def test_cash_rounding_uses_the_company_accounts(self):
        self._l10n_it_clear_cash_rounding()
        profit = self.company_data['default_account_revenue']
        loss = self.company_data['default_account_expense']
        self.company.write({
            'cash_rounding_profit_account_id': profit.id,
            'cash_rounding_loss_account_id': loss.id,
        })
        self.config._l10n_it_fiskaly_apply_cash_rounding()
        rounding = self.config.rounding_method.with_company(self.company)
        self.assertTrue(self.config.cash_rounding)
        self.assertEqual(rounding.rounding, 0.05)
        self.assertEqual(rounding.profit_account_id, profit)
        self.assertEqual(rounding.loss_account_id, loss)

    def test_cash_rounding_falls_back_on_the_italian_rounding_accounts(self):
        self._l10n_it_clear_cash_rounding()
        self.company.write({
            'cash_rounding_profit_account_id': False,
            'cash_rounding_loss_account_id': False,
        })
        profit = self.company_data['default_account_revenue']
        loss = self.company_data['default_account_expense']
        self.env['ir.model.data'].create([
            {
                'module': 'account',
                'name': f'{self.company.id}_{code}',
                'model': 'account.account',
                'res_id': account.id,
            }
            for code, account in (('3210', profit), ('4910', loss))
        ])
        self.config._l10n_it_fiskaly_apply_cash_rounding()
        rounding = self.config.rounding_method.with_company(self.company)
        self.assertTrue(self.config.cash_rounding)
        self.assertEqual(rounding.profit_account_id, profit)
        self.assertEqual(rounding.loss_account_id, loss)

    def _l10n_it_paid_document(self, payments):
        order = self._order([self._line(self.product_22, 1, 122.0)], payment=0.0)
        order.partner_id = self.customer
        for method, amount in payments:
            order.add_payment({
                'amount': amount,
                'payment_method_id': method.id,
                'pos_order_id': order.id,
            })
        order.amount_paid = sum(amount for _method, amount in payments)
        return order._l10n_it_fiskaly_document()

    def test_cash_payment_is_cash(self):
        document = self._l10n_it_paid_document([(self.cash_pm1, 122.0)])
        self.assertEqual(document['payments'], [{
            'type': 'CASH',
            'details': {'amount': '122.00'},
        }])

    def test_bank_payment_is_a_debit_card(self):
        document = self._l10n_it_paid_document([(self.bank_pm1, 122.0)])
        self.assertEqual(document['payments'], [{
            'type': 'CARD',
            'kind': 'DEBIT',
            'number': '****',
            'details': {'amount': '122.00'},
        }])

    def test_customer_account_is_outstanding(self):
        document = self._l10n_it_paid_document([(self.pay_later_pm, 122.0)])
        self.assertEqual(document['payments'], [{
            'type': 'OUTSTANDING',
            'concept': 'GOOD',
            'details': {'amount': '122.00'},
        }])

    def test_each_payment_is_its_own_entry(self):
        document = self._l10n_it_paid_document([
            (self.bank_pm1, 50.0),
            (self.bank_pm1, 50.0),
            (self.cash_pm1, 22.0),
        ])
        card = {'type': 'CARD', 'kind': 'DEBIT', 'number': '****', 'details': {'amount': '50.00'}}
        self.assertCountEqual(document['payments'], [
            card,
            card,
            {'type': 'CASH', 'details': {'amount': '22.00'}},
        ])

    def test_online_payment_is_not_other(self):
        selection = self.env['pos.payment.method']._fields['type'].get_values(self.env)
        if 'online' not in selection:
            self.skipTest('pos_online_payment is not installed')
        order = self._order([self._line(self.product_22, 1, 122.0)])
        document = order._l10n_it_fiskaly_document()
        self.assertNotIn('OTHER', [payment['type'] for payment in document['payments']])

    def test_vat_rates_are_mapped(self):
        for product, code, percentage in (
            (self.product_22, 'STANDARD', '22'),
            (self.product_10, 'REDUCED_1', '10'),
            (self.product_4, 'REDUCED_3', '4'),
        ):
            order = self._order([self._line(product, 1, product.lst_price)])
            document = order._l10n_it_fiskaly_document()
            entry = document['entries'][0]['data']
            self.assertEqual(entry['vat']['type'], 'VAT_RATE')
            self.assertEqual(entry['vat']['code'], code)
            self.assertEqual(entry['vat']['percentage'], percentage)
            self.assertEqual(len(document['breakdown']), 1)
            self.assertEqual(document['breakdown'][0]['code'], code)

    def test_exempt_product_uses_natura(self):
        order = self._order([self._line(self.product_exempt, 1, 100.0, exemption='CAUSE_1')])
        document = order._l10n_it_fiskaly_document()
        entry = document['entries'][0]['data']
        self.assertEqual(entry['vat']['type'], 'VAT_EXEMPTION')
        self.assertNotIn('exclusive', entry['vat'])
        self.assertIn('exclusive', document['breakdown'][0])
        self.assertEqual(document['totals']['vat']['amount'], '0.00000000')

    def test_exempt_product_without_exemption_uses_the_tax_exemption(self):
        order = self._order([self._line(self.product_exempt, 1, 100.0)])
        entry = order._l10n_it_fiskaly_document()['entries'][0]['data']
        self.assertEqual(entry['vat']['code'], 'CAUSE_1')

    def test_untaxed_product_without_exemption_is_not_subject(self):
        product = self.create_product('Ice Tea', self.categ_basic, 3.0, tax_ids=[])
        order = self._order([self._line(product, 1, 3.0)])
        entry = order._l10n_it_fiskaly_document()['entries'][0]['data']
        self.assertEqual(entry['vat']['code'], 'NOT_SUBJECT')

    def test_tip_is_a_not_subject_entry(self):
        service = self.create_product('Restaurant service', self.categ_basic, 48.0, tax_ids=self.tax_22.ids)
        service.type = 'service'
        tip = self.create_product('Voluntary tip', self.categ_basic, 0.0, tax_ids=[])
        tip.type = 'service'
        self.config.write({'iface_tipproduct': True, 'tip_product_id': tip.id})
        order = self._order([
            self._line(service, 1, 48.0),
            self._line(tip, 1, 2.0, exemption='NOT_SUBJECT'),
        ], payment=0.0)
        order.add_payment({
            'amount': 50.0,
            'payment_method_id': self.bank_pm1.id,
            'pos_order_id': order.id,
        })
        order.amount_paid = 50.0
        document = order._l10n_it_fiskaly_document()
        entries = self._entries(document)
        self.assertEqual(entries['Restaurant service']['vat']['code'], 'STANDARD')
        tip_entry = entries['Voluntary tip']
        self.assertEqual(tip_entry['vat'], {'type': 'VAT_EXEMPTION', 'code': 'NOT_SUBJECT'})
        self.assertEqual(tip_entry['unit']['price']['inclusive'], tip_entry['unit']['price']['exclusive'])
        self.assertAlmostEqual(float(tip_entry['unit']['price']['inclusive']), 2.0, places=2)
        self.assertEqual(
            [entry['details'] for entry in document['entries']],
            [{'concept': 'SERVICE'}, {'concept': 'SERVICE'}])
        breakdown = {vat['code']: vat for vat in document['breakdown']}
        self.assertAlmostEqual(float(breakdown['STANDARD']['inclusive']), 48.0, places=2)
        self.assertEqual(breakdown['NOT_SUBJECT']['type'], 'VAT_EXEMPTION')
        self.assertAlmostEqual(float(breakdown['NOT_SUBJECT']['exclusive']), 2.0, places=2)
        totals = document['totals']['vat']
        self.assertAlmostEqual(float(totals['amount']), 8.6557377, places=6)
        self.assertAlmostEqual(float(totals['exclusive']), 41.3442623, places=6)
        self.assertEqual(totals['inclusive'], '50.00')
        self.assertEqual(document['payments'], [{
            'type': 'CARD',
            'kind': 'DEBIT',
            'number': '****',
            'details': {'amount': '50.00'},
        }])
