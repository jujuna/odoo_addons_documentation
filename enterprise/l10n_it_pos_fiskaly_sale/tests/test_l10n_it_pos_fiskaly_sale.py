from odoo.addons.l10n_it_pos_fiskaly.tests.common import TestL10nItPosFiskalyCommon
from odoo.tests import tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nItPosFiskalySale(TestL10nItPosFiskalyCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.down_payment_product = cls.create_product('Down Payment', cls.categ_basic, 0.0, tax_ids=cls.tax_22.ids)
        cls.config.down_payment_product_id = cls.down_payment_product

    def test_down_payment_collection_keeps_vat(self):
        order = self._order([self._line(self.down_payment_product, 1, 122.0)])
        document = order._l10n_it_fiskaly_document()
        entry = document['entries'][0]['data']
        self.assertEqual(entry['vat']['type'], 'VAT_RATE')
        self.assertEqual(entry['vat']['code'], 'STANDARD')
        self.assertEqual(document['totals']['vat']['inclusive'], '122.00')

    def test_down_payment_settle_is_an_entry_discount(self):
        order = self._order([
            self._line(self.product_22, 1, 610.0),
            self._line(self.down_payment_product, -1, 122.0),
        ])
        document = order._l10n_it_fiskaly_document()
        entries = self._entries(document)
        self.assertNotIn('Down Payment', entries)
        self.assertEqual(len(document['entries']), 1)
        goods = entries['Product 22']
        self.assertEqual(float(goods['value']['discount']), 122.0)
        self.assertEqual(document['totals']['vat']['inclusive'], '488.00')
        self.assertEqual(document['payments'][0]['details']['amount'], '488.00')

    def test_down_payment_settle_declares_the_remaining_balance(self):
        order = self._order([
            self._line(self.product_22, 30, 106.14),
            self._line(self.product_10, 10, 14.85),
            self._line(self.down_payment_product, -1, 1061.40, taxes=self.tax_22),
            self._line(self.down_payment_product, -1, 49.50, taxes=self.tax_10),
        ])
        document = order._l10n_it_fiskaly_document()
        entries = self._entries(document)
        self.assertEqual(len(document['entries']), 2)
        standard = entries['Product 22']
        self.assertEqual(float(standard['value']['base']), 2610.0)
        self.assertAlmostEqual(float(standard['value']['discount']), 1061.40, places=2)
        self.assertAlmostEqual(float(standard['vat']['exclusive']), 1740.0, places=2)
        self.assertAlmostEqual(float(standard['vat']['amount']), 382.80, places=2)
        reduced = entries['Product 10']
        self.assertEqual(float(reduced['value']['base']), 135.0)
        self.assertAlmostEqual(float(reduced['value']['discount']), 49.50, places=2)
        self.assertAlmostEqual(float(reduced['vat']['exclusive']), 90.0, places=2)
        self.assertAlmostEqual(float(reduced['vat']['amount']), 9.0, places=2)
        totals = document['totals']['vat']
        self.assertAlmostEqual(float(totals['exclusive']), 1830.0, places=2)
        self.assertAlmostEqual(float(totals['amount']), 391.80, places=2)
        self.assertEqual(totals['inclusive'], '2221.80')
        self.assertEqual(document['payments'][0]['details']['amount'], '2221.80')

    def test_down_payment_settle_mixed_rates(self):
        order = self._order([
            self._line(self.product_22, 1, 122.0),
            self._line(self.product_10, 1, 110.0),
            self._line(self.down_payment_product, -1, 122.0),
        ])
        document = order._l10n_it_fiskaly_document()
        self.assertEqual(len(document['entries']), 2)
        codes = {vat['code'] for vat in document['breakdown']}
        self.assertEqual(codes, {'STANDARD', 'REDUCED_1'})
        self.assertEqual(document['totals']['vat']['inclusive'], '110.01')
        self.assertEqual(document['payments'][0]['details']['discount'], '0.01')

    def test_entry_discount_never_reaches_the_line_total(self):
        order = self._order([
            self._line(self.product_22, 1, 122.0),
            self._line(self.down_payment_product, -1, 122.0),
        ], payment=0.0)
        document = order._l10n_it_fiskaly_document()
        goods = document['entries'][0]['data']
        line_total = float(goods['unit']['price']['inclusive']) * float(goods['unit']['quantity'])
        self.assertLess(float(goods['value']['discount']), line_total)
        self.assertEqual(document['payments'][0]['details']['discount'], '0.01')
