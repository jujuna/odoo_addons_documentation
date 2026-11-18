from odoo import Command
from odoo.addons.l10n_it_pos_fiskaly.tests.common import TestL10nItPosFiskalyCommon
from odoo.tests import tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nItPosFiskalyLoyalty(TestL10nItPosFiskalyCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.gift_card_product = cls.create_product('Gift Card', cls.categ_basic, 0.0, tax_ids=[])
        cls.gift_card_program = cls.env['loyalty.program'].create({
            'name': 'Gift Card Program',
            'program_type': 'gift_card',
            'applies_on': 'future',
            'trigger': 'auto',
            'rule_ids': [Command.create({
                'reward_point_mode': 'money',
                'reward_point_amount': 1,
                'product_ids': cls.gift_card_product.ids,
            })],
            'reward_ids': [Command.create({
                'reward_type': 'discount',
                'discount_mode': 'per_point',
                'discount': 1,
                'discount_applicability': 'order',
                'required_points': 1,
            })],
            'trigger_product_ids': cls.gift_card_product.ids,
        })

    def test_gift_card_issuance_is_not_subject(self):
        order = self._order([self._line(self.gift_card_product, 1, 50.0)])
        document = order._l10n_it_fiskaly_document()
        entry = document['entries'][0]['data']
        self.assertEqual(entry['vat'], {'type': 'VAT_EXEMPTION', 'code': 'NOT_SUBJECT'})
        self.assertEqual(entry['unit']['price']['inclusive'], entry['unit']['price']['exclusive'])
        self.assertEqual(document['totals']['vat']['inclusive'], '50.00')

    def test_gift_card_redemption_is_not_an_entry(self):
        card = self.env['loyalty.card'].create({
            'program_id': self.gift_card_program.id,
            'points': 50,
        })
        redemption = {
            **self._line(self.gift_card_product, 1, -22.0),
            'is_reward_line': True,
            'reward_id': self.gift_card_program.reward_ids.id,
            'card_id': card.id,
        }
        order = self._order([self._line(self.product_22, 1, 122.0), redemption])
        document = order._l10n_it_fiskaly_document()
        self.assertEqual(len(document['entries']), 1)
        self.assertEqual(document['entries'][0]['data']['vat']['code'], 'STANDARD')
        self.assertEqual(document['totals']['vat']['inclusive'], '122.00')

    def _l10n_it_free_product_line(self, product, qty):
        program = self.env['loyalty.program'].create({
            'name': 'Free Product',
            'program_type': 'promotion',
            'trigger': 'auto',
            'rule_ids': [Command.create({'product_ids': product.ids, 'minimum_qty': 1})],
            'reward_ids': [Command.create({
                'reward_type': 'product',
                'reward_product_id': product.id,
                'reward_product_qty': qty,
                'required_points': 1,
            })],
        })
        return {
            **self._line(product, qty, 0.0),
            'is_reward_line': True,
            'reward_id': program.reward_ids.id,
        }

    def test_free_product_is_a_gift_next_to_the_paid_units(self):
        order = self._order([
            self._line(self.product_22, 2, 122.0),
            self._l10n_it_free_product_line(self.product_22, 1),
        ])
        document = order._l10n_it_fiskaly_document()
        sale, gift = (entry['details'] for entry in document['entries'])
        self.assertNotIn('purpose', sale)
        self.assertEqual(gift['purpose'], 'GIFT')
        self.assertEqual(document['entries'][0]['data']['unit']['quantity'], '2.00')
        self.assertEqual(document['entries'][1]['data']['unit']['price']['inclusive'], '122.00000000')
        self.assertEqual(document['totals']['vat']['inclusive'], '366.00')
        self.assertEqual(
            sum(float(payment['details']['amount']) + float(payment['details'].get('discount', 0))
                for payment in document['payments']),
            244.0)

    def test_free_product_gift_declares_the_product_value(self):
        order = self._order([
            self._line(self.product_22, 2, 122.0),
            self._l10n_it_free_product_line(self.product_22, 1),
        ])
        gift = order._l10n_it_fiskaly_document()['entries'][1]['data']
        self.assertEqual(gift['value'], {'base': '100.00000000', 'discount': '0.00000000'})
        self.assertEqual(gift['unit']['price'], {'inclusive': '122.00000000', 'exclusive': '100.00000000'})
        self.assertEqual(gift['vat']['exclusive'], '100.00000000')

    def test_return_after_a_gift_uses_the_sent_entry_number(self):
        original = self._order([
            self._l10n_it_free_product_line(self.product_22, 1),
            self._line(self.product_10, 1, 110.0),
        ])
        original.l10n_it_fiskaly_record_id = '01890000-0000-7000-8000-000000000012'
        operation = self._l10n_it_return(original, [0, 1])
        self.assertEqual(operation['data']['entries'][0]['details']['number'], '1')

    def test_free_product_alone_is_still_declared(self):
        order = self._order([
            self._line(self.product_10, 1, 110.0),
            self._l10n_it_free_product_line(self.product_22, 1),
        ])
        document = order._l10n_it_fiskaly_document()
        self.assertEqual(len(document['entries']), 2)
        self.assertEqual(document['entries'][1]['details']['purpose'], 'GIFT')
        self.assertEqual(document['entries'][1]['data']['text'], 'Product 22')
        self.assertEqual(document['totals']['vat']['inclusive'], '232.00')

    def _l10n_it_discount_reward_line(self, program, product, amount):
        return {
            **self._line(product, 1, amount),
            'is_reward_line': True,
            'reward_id': program.reward_ids.id,
        }

    def test_order_discount_code_on_multiple_vat_rates(self):
        program = self.env['loyalty.program'].create({
            'name': '10% Code',
            'program_type': 'promo_code',
            'trigger': 'with_code',
            'rule_ids': [Command.create({'code': 'TEN', 'minimum_qty': 0})],
            'reward_ids': [Command.create({
                'reward_type': 'discount',
                'discount': 10,
                'discount_mode': 'percent',
                'discount_applicability': 'order',
                'required_points': 1,
            })],
        })
        order = self._order([
            self._line(self.product_22, 1, 122.0),
            self._line(self.product_10, 1, 110.0),
            self._l10n_it_discount_reward_line(program, self.product_22, -12.2),
            self._l10n_it_discount_reward_line(program, self.product_10, -11.0),
        ])
        document = order._l10n_it_fiskaly_document()
        self.assertEqual(len(document['entries']), 2)
        self.assertEqual(
            {entry['data']['text']: entry['data']['value'] for entry in document['entries']},
            {
                'Product 22': {'base': '100.00000000', 'discount': '12.20000000'},
                'Product 10': {'base': '100.00000000', 'discount': '11.00000000'},
            })
        self.assertEqual({vat['code']: vat for vat in document['breakdown']}, {
            'STANDARD': {
                'type': 'VAT_RATE',
                'code': 'STANDARD',
                'percentage': '22',
                'exclusive': '90.00000000',
                'inclusive': '109.80',
                'amount': '19.80000000',
            },
            'REDUCED_1': {
                'type': 'VAT_RATE',
                'code': 'REDUCED_1',
                'percentage': '10',
                'exclusive': '90.00000000',
                'inclusive': '99.00',
                'amount': '9.00000000',
            },
        })
        self.assertEqual(document['totals']['vat'], {
            'amount': '28.80000000',
            'exclusive': '180.00000000',
            'inclusive': '208.80',
        })
