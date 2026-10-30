# Part of Odoo. See LICENSE file for full copyright and licensing details.

import odoo

from odoo.addons.l10n_be_pos_blackbox.tests.common import TestL10nBePosBlackboxTurnoverCommon


@odoo.tests.tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nBePosBlackboxLoyaltyTurnoverReport(TestL10nBePosBlackboxTurnoverCommon):
    """Turnover blocks of the X/Z report once `pos_loyalty` is in play.

    The FDM has no notion of a reward line, so each kind of reward is reported as
    something it understands (see `static/src/common/blackbox/utils/input_generator.js`):

    - selling a gift card is a plain untaxed transaction line, VAT label ``X``;
    - redeeming a gift card / eWallet is *not* a transaction line but a financial
      (``VOUCHER_STORE`` / ``VOUCHER_OTHER``), and `getTransactionTotal` adds it back
      so the transaction total stays the price of the goods;
    - a discount reward is spread over the lines it discounts as ``LOYALTY_DISCOUNT``
      price changes, EVENT for an order-wide one and LINE for a specific one;
    - a free product reward is a transaction line carrying the rewarded product with a
      ``LOYALTY_FREE_PRODUCT`` price change bringing its total back to 0.

    Whatever the reward, `_assert_report_balances` must keep holding:
        sum(vats.totalAmount) == sum(departments.amount)
                              == transactions[N].amount
                              == sum(payments.totalAmount)
    """

    def setUp(self):
        super().setUp()
        self.vouchers = self.env['pos.category'].create({'name': 'BB Vouchers'})

        self.gift_card_product = self.env['product.product'].create({
            'name': 'BB Gift Card 50',
            'available_in_pos': True,
            'list_price': 50.0,
            # A taxed gift card product is rejected outright with a certified FDM,
            # see `product_template._ensure_gift_card_ewallet_product_no_taxes`.
            'taxes_id': [(6, 0, [])],
            'pos_categ_ids': [(6, 0, self.vouchers.ids)],
        })
        # `loyalty.program` only fills its rules and rewards from `default_get`, so a
        # program created in Python has to spell them out.
        self.gift_card_program = self._create_payment_program(
            'BB Gift Card Program', 'gift_card', self.gift_card_product,
        )
        self.gift_card = self.env['loyalty.card'].create({
            'program_id': self.gift_card_program.id,
            'points': 50.0,
        })

        self.ewallet_product = self.env['product.product'].create({
            'name': 'BB EWallet Top-up',
            'available_in_pos': True,
            'list_price': 30.0,
            'taxes_id': [(6, 0, [])],
            'pos_categ_ids': [(6, 0, self.vouchers.ids)],
        })
        self.ewallet_program = self._create_payment_program(
            'BB EWallet Program', 'ewallet', self.ewallet_product,
        )
        self.ewallet = self.env['loyalty.card'].create({
            'program_id': self.ewallet_program.id,
            'points': 30.0,
        })

        self.promo_program = self.env['loyalty.program'].create({
            'name': 'BB Promotions',
            'program_type': 'promotion',
            'applies_on': 'current',
            'trigger': 'auto',
            'pos_config_ids': [(6, 0, self.main_pos_config.ids)],
            'rule_ids': [(0, 0, {
                'reward_point_amount': 1,
                'reward_point_mode': 'order',
                'minimum_qty': 0,
            })],
            'reward_ids': [
                (0, 0, {
                    'description': 'BB 10% on the order',
                    'reward_type': 'discount',
                    'discount_mode': 'percent',
                    'discount': 10.0,
                    'discount_applicability': 'order',
                    'required_points': 1,
                }),
                (0, 0, {
                    'description': 'BB 25% on burgers',
                    'reward_type': 'discount',
                    'discount_mode': 'percent',
                    'discount': 25.0,
                    'discount_applicability': 'specific',
                    'discount_product_ids': [(6, 0, self.burger.ids)],
                    'required_points': 1,
                }),
                (0, 0, {
                    'description': 'BB free burger',
                    'reward_type': 'product',
                    'reward_product_id': self.burger.id,
                    'reward_product_qty': 1,
                    'required_points': 1,
                }),
            ],
        })
        rewards = self.promo_program.reward_ids
        self.order_discount = rewards.filtered(
            lambda r: r.reward_type == 'discount' and r.discount_applicability == 'order'
        )
        self.burger_discount = rewards.filtered(
            lambda r: r.reward_type == 'discount' and r.discount_applicability == 'specific'
        )
        self.free_burger = rewards.filtered(lambda r: r.reward_type == 'product')

    def _create_payment_program(self, name, program_type, trigger_product):
        """Create a gift card / eWallet program funded by ``trigger_product``."""
        return self.env['loyalty.program'].create({
            'name': name,
            'program_type': program_type,
            'applies_on': 'future',
            'trigger': 'auto',
            'pos_config_ids': [(6, 0, self.main_pos_config.ids)],
            'rule_ids': [(0, 0, {
                'reward_point_amount': 1,
                'reward_point_mode': 'money',
                'reward_point_split': program_type == 'gift_card',
                'product_ids': [(6, 0, trigger_product.ids)],
                'minimum_qty': 0,
            })],
            'reward_ids': [(0, 0, {
                'description': name,
                'reward_type': 'discount',
                'discount_mode': 'per_point',
                'discount': 1.0,
                'discount_applicability': 'order',
                'required_points': 1,
            })],
        })

    # ------------------------------------------------------------------
    # Fixture: the ORM lines the POS syncs for each kind of reward
    # ------------------------------------------------------------------

    def _vat_entry(self, label, price, price_changes=()):
        return {'label': label, 'price': price, 'priceChanges': list(price_changes)}

    def _loyalty_price_change(self, name, amount, scope, grouping_id=1):
        """A reward price change, as `generatePriceChangeInput` sends it."""
        return {
            'id': '7',
            'groupingId': grouping_id,
            'name': name,
            'type': 'PUBLIC',
            'scope': scope,
            'amount': amount,
        }

    def _product_line(self, product, qty, price_changes=()):
        """A plain transaction line, optionally reduced by reward price changes.

        A loyalty reward never touches the price of the line it reduces: it is a
        separate line of its own, so the ORM amounts here stay gross and only the
        FDM payload carries the reduction.
        """
        currency = self.session.currency_id
        tax = product.taxes_id[0]
        gross = currency.round(product.list_price * qty)
        return (0, 0, {
            'name': f'{product.name} x{qty}',
            'product_id': product.id,
            'price_unit': product.list_price,
            'discount': 0,
            'qty': qty,
            'tax_ids': [(6, 0, product.taxes_id.ids)],
            'price_subtotal': currency.round(gross / (1 + tax.amount / 100)),
            'price_subtotal_incl': gross,
            'l10n_be_vats': [
                self._vat_entry(tax.tax_group_id.pos_receipt_label, gross, price_changes),
            ],
        })

    def _gift_card_sale_line(self, price=50.0):
        """The funding line that sells a gift card: untaxed goods, VAT label `X`."""
        return (0, 0, {
            'name': self.gift_card_product.name,
            'product_id': self.gift_card_product.id,
            'price_unit': price,
            'discount': 0,
            'qty': 1,
            'tax_ids': [(6, 0, [])],
            'price_subtotal': price,
            'price_subtotal_incl': price,
            'gift_card_vals': {'program_id': self.gift_card_program.id},
            'l10n_be_vats': [self._vat_entry('X', price)],
        })

    def _voucher_redemption_line(self, card, amount):
        """A gift card / eWallet redemption: a payment, never a transaction line."""
        program = card.program_id
        return (0, 0, {
            'name': program.name,
            'product_id': program.payment_program_discount_product_id.id,
            'price_unit': -amount,
            'discount': 0,
            'qty': 1,
            'tax_ids': [(6, 0, [])],
            'price_subtotal': -amount,
            'price_subtotal_incl': -amount,
            'is_reward_line': True,
            'reward_id': program.reward_ids[0].id,
            'card_id': card.id,
            'points_cost': amount,
            # Not sent to the FDM: reported as a financial instead.
            'l10n_be_vats': [],
        })

    def _discount_reward_line(self, reward, amount, taxes):
        """A discount reward line, as `getRewardLines` builds one per tax group."""
        currency = self.session.currency_id
        rate = taxes[0].amount if taxes else 0.0
        return (0, 0, {
            'name': reward.description,
            'product_id': reward.discount_line_product_id.id,
            'price_unit': -amount,
            'discount': 0,
            'qty': 1,
            'tax_ids': [(6, 0, taxes.ids)],
            'price_subtotal': currency.round(-amount / (1 + rate / 100)),
            'price_subtotal_incl': -amount,
            'is_reward_line': True,
            'reward_id': reward.id,
            # Not sent to the FDM: spread as price changes over the discounted lines.
            'l10n_be_vats': [],
        })

    def _free_product_line(self, reward, product, qty=1):
        """A free product reward: the rewarded goods at a 0 price, still reported."""
        currency = self.session.currency_id
        tax = product.taxes_id[0]
        catalog = currency.round(product.list_price * qty)
        return (0, 0, {
            'name': product.name,
            'product_id': product.id,
            'price_unit': 0.0,
            'discount': 0,
            'qty': qty,
            'tax_ids': [(6, 0, product.taxes_id.ids)],
            'price_subtotal': 0.0,
            'price_subtotal_incl': 0.0,
            'is_reward_line': True,
            'reward_id': reward.id,
            'l10n_be_vats': [self._vat_entry(
                tax.tax_group_id.pos_receipt_label,
                catalog,
                [self._loyalty_price_change('LOYALTY_FREE_PRODUCT', -catalog, 'LINE')],
            )],
        })

    def _create_signed_loyalty_order(self, line_vals, transaction_total):
        """Create, pay and sign an order built from explicit line vals.

        ``transaction_total`` is what `getTransactionTotal()` sends to the FDM: the
        sum of the transaction line totals, so it is gross of any redemption, while
        the order total and its `pos.payment` are net of it.
        """
        currency = self.session.currency_id
        lines = [vals for _command, _id, vals in line_vals]
        total = currency.round(sum(line['price_subtotal_incl'] for line in lines))
        total_tax = currency.round(sum(
            line['price_subtotal_incl'] - line['price_subtotal'] for line in lines
        ))
        order = self.env['pos.order'].create({
            'company_id': self.env.company.id,
            'session_id': self.session.id,
            'lines': line_vals,
            'amount_total': total,
            'amount_paid': total,
            'amount_tax': total_tax,
            'amount_return': 0.0,
            'l10n_be_short_signature': 'ABC123',
        })
        self.env['pos.payment'].create({
            'pos_order_id': order.id,
            'payment_method_id': self.payment_method.id,
            'amount': total,
        })
        order.state = 'paid'
        # Mirror the `signSale` event the POS sends to the FDM for this order.
        self.session.increment_l10n_be_counters('N', transaction_total)
        return order

    # ------------------------------------------------------------------
    # Gift cards and eWallets
    # ------------------------------------------------------------------

    def test_turnover_gift_card_sale_is_an_untaxed_line(self):
        """Selling a gift card is a multipurpose voucher sale: VAT label `X`."""
        self._create_signed_loyalty_order([self._gift_card_sale_line(50.0)], 50.0)

        data = self._get_turnover_data()
        vats, departments = self._vats(data), self._departments(data)

        self.assertEqual(departments['BB Vouchers']['amount'], 50.0)
        # `X` carries no VAT, so the whole amount is taxable base.
        self.assertEqual(vats['X']['rate'], 0.0)
        self.assertEqual(vats['X']['totalAmount'], 50.0)
        self.assertEqual(vats['X']['taxableAmount'], 50.0)
        self.assertEqual(vats['X']['vatAmount'], 0.0)

        # The sale is paid for like any other: no voucher financial here.
        self.assertNotIn('Gift Card', self._payments(data))

        self._assert_report_balances(data, 50.0)

    def test_turnover_gift_card_redemption_is_a_voucher_payment(self):
        """A redemption is a `VOUCHER_STORE` financial, not a discount on the goods."""
        self._create_signed_loyalty_order([
            self._product_line(self.martini, 1),
            self._product_line(self.burger, 2),
            self._voucher_redemption_line(self.gift_card, 50.0),
        ], 68.0)

        data = self._get_turnover_data()
        vats, departments, payments = (
            self._vats(data), self._departments(data), self._payments(data),
        )

        # The goods are untouched: the FDM is told the full 68, not the 18 cashed in.
        self.assertEqual(departments['BB Aperitifs']['amount'], 12.0)
        self.assertEqual(departments['BB Main Dishes']['amount'], 56.0)
        self.assertEqual(vats['A']['totalAmount'], 12.0)
        self.assertEqual(vats['B']['totalAmount'], 56.0)

        self.assertEqual(payments['Gift Card']['type'], 'VOUCHER_STORE')
        self.assertEqual(payments['Gift Card']['amount']['totalAmount'], 50.0)
        self.assertEqual(payments['Gift Card']['amount']['normalAmount'], 50.0)
        self.assertEqual(payments[self.payment_method.name]['amount']['totalAmount'], 18.0)

        self._assert_report_balances(data, 68.0)

    def test_turnover_ewallet_redemption_is_a_voucher_payment(self):
        """An eWallet redemption is the same, reported as `VOUCHER_OTHER`."""
        self._create_signed_loyalty_order([
            self._product_line(self.martini, 1),
            self._product_line(self.burger, 2),
            self._voucher_redemption_line(self.ewallet, 30.0),
        ], 68.0)

        data = self._get_turnover_data()
        payments = self._payments(data)

        self.assertEqual(payments['Ewallet']['type'], 'VOUCHER_OTHER')
        self.assertEqual(payments['Ewallet']['amount']['totalAmount'], 30.0)
        self.assertEqual(payments[self.payment_method.name]['amount']['totalAmount'], 38.0)

        self._assert_report_balances(data, 68.0)

    def test_turnover_redemption_is_not_reported_as_goods(self):
        """A redemption must leave the product tables alone, on either side.

        Its line total is negative, so `_is_refund_order_line` would file it under
        the refunds -- stating that merchandise came back, and double counting
        against the voucher payment the same report adds.
        """
        self._create_signed_loyalty_order([
            self._product_line(self.martini, 1),
            self._product_line(self.burger, 2),
            self._voucher_redemption_line(self.gift_card, 50.0),
        ], 68.0)

        data = self._get_turnover_data()
        redemption_product = self.gift_card_program.payment_program_discount_product_id
        sold = [
            product['product_id']
            for category in data['products'] + data['refund_products']
            for product in category['products']
        ]
        self.assertNotIn(redemption_product.id, sold)
        self.assertEqual(data['refund_products'], [])
        self.assertEqual(data['products_info']['total'], 68.0)

        # Nothing was returned, so no negative quantity is reported either.
        self.assertEqual(data['negQuantities'], [])

        # The visible payment table mirrors the FDM financials.
        self.assertEqual(
            {payment['name']: payment['total'] for payment in data['payments_per_method']},
            {self.payment_method.name: 18.0, 'Gift Card': 50.0},
        )
        self.assertEqual(data['total_paid'], 68.0)

    def test_turnover_gift_card_sold_and_redeemed_in_the_same_session(self):
        """Selling and spending a card are two independent, both signed, events."""
        self._create_signed_loyalty_order([self._gift_card_sale_line(50.0)], 50.0)
        self._create_signed_loyalty_order([
            self._product_line(self.martini, 1),
            self._product_line(self.burger, 2),
            self._voucher_redemption_line(self.gift_card, 50.0),
        ], 68.0)

        data = self._get_turnover_data()
        vats, departments = self._vats(data), self._departments(data)

        self.assertEqual(departments['BB Vouchers']['amount'], 50.0)
        self.assertEqual(vats['X']['totalAmount'], 50.0)
        self.assertEqual(vats['A']['totalAmount'], 12.0)
        self.assertEqual(vats['B']['totalAmount'], 56.0)

        self._assert_report_balances(data, 118.0)

    # ------------------------------------------------------------------
    # Discount rewards (EVENT and LINE scope)
    # ------------------------------------------------------------------

    def test_turnover_deducts_order_wide_loyalty_discount(self):
        """An order-wide reward is spread over every line as an EVENT price change."""
        self._create_signed_loyalty_order([
            self._product_line(self.martini, 1, [
                self._loyalty_price_change('LOYALTY_DISCOUNT', -1.20, 'EVENT'),
            ]),
            self._product_line(self.burger, 2, [
                self._loyalty_price_change('LOYALTY_DISCOUNT', -5.60, 'EVENT'),
            ]),
            # `getRewardLines` splits a discount into one line per tax group.
            self._discount_reward_line(self.order_discount, 1.20, self.martini.taxes_id),
            self._discount_reward_line(self.order_discount, 5.60, self.burger.taxes_id),
        ], 61.20)

        data = self._get_turnover_data()
        vats, departments = self._vats(data), self._departments(data)

        # 12 - 1.20 and 56 - 5.60.
        self.assertEqual(departments['BB Aperitifs']['amount'], 10.80)
        self.assertEqual(departments['BB Main Dishes']['amount'], 50.40)

        self.assertEqual(vats['A']['totalAmount'], 10.80)
        self.assertEqual(vats['A']['taxableAmount'], 8.93)
        self.assertEqual(vats['A']['vatAmount'], 1.87)

        self.assertEqual(vats['B']['totalAmount'], 50.40)
        self.assertEqual(vats['B']['taxableAmount'], 45.0)
        self.assertEqual(vats['B']['vatAmount'], 5.40)

        self._assert_report_balances(data, 61.20)

    def test_turnover_deducts_specific_loyalty_discount(self):
        """A reward scoped to one product only reduces that product's label."""
        self._create_signed_loyalty_order([
            self._product_line(self.martini, 1),
            self._product_line(self.burger, 2, [
                self._loyalty_price_change('LOYALTY_DISCOUNT', -14.0, 'LINE'),
            ]),
            self._discount_reward_line(self.burger_discount, 14.0, self.burger.taxes_id),
        ], 54.0)

        data = self._get_turnover_data()
        vats, departments = self._vats(data), self._departments(data)

        self.assertEqual(departments['BB Aperitifs']['amount'], 12.0)
        self.assertEqual(departments['BB Main Dishes']['amount'], 42.0)
        self.assertEqual(vats['A']['totalAmount'], 12.0)
        self.assertEqual(vats['B']['totalAmount'], 42.0)

        self._assert_report_balances(data, 54.0)

    def test_turnover_price_changes_block_reports_loyalty_discount(self):
        """Reward reductions are reported per VAT label like any other price change."""
        self._create_signed_loyalty_order([
            self._product_line(self.martini, 1, [
                self._loyalty_price_change('LOYALTY_DISCOUNT', -1.20, 'EVENT'),
            ]),
            self._product_line(self.burger, 2, [
                self._loyalty_price_change('LOYALTY_DISCOUNT', -5.60, 'EVENT'),
            ]),
            self._discount_reward_line(self.order_discount, 1.20, self.martini.taxes_id),
            self._discount_reward_line(self.order_discount, 5.60, self.burger.taxes_id),
        ], 61.20)

        data = self._get_turnover_data()
        discount = next(
            pc for pc in data['priceChanges'] if pc['name'] == 'LOYALTY_DISCOUNT'
        )
        self.assertEqual(discount['id'], '7')
        self.assertEqual(discount['type'], 'PUBLIC')
        amounts = {entry['label']: entry for entry in discount['amount']}
        self.assertEqual(amounts['A']['negative'], -1.20)
        self.assertEqual(amounts['A']['positive'], 0.0)
        self.assertEqual(amounts['B']['negative'], -5.60)
        self.assertEqual(amounts['B']['positive'], 0.0)

    def test_turnover_refund_of_a_loyalty_discounted_order(self):
        """A refund of a rewarded sale keeps the report balanced.

        The refund is created at the gross line price: `getRefundLinesDetails`
        copies neither `is_reward_line` nor `reward_id`, and `recomputeRewards`
        cannot rebuild a reward on a refund order, so the reward is not replayed
        """
        self._create_signed_loyalty_order([
            self._product_line(self.martini, 1),
            self._product_line(self.burger, 2, [
                self._loyalty_price_change('LOYALTY_DISCOUNT', -14.0, 'LINE'),
            ]),
            self._discount_reward_line(self.burger_discount, 14.0, self.burger.taxes_id),
        ], 54.0)
        self._create_signed_order([(self.burger, -2)], is_refund=True)

        data = self._get_turnover_data()
        vats = self._vats(data)

        self.assertEqual(vats['A']['totalAmount'], 12.0)
        # 42 sold net of the reward, 56 given back gross of it.
        self.assertEqual(vats['B']['totalAmount'], -14.0)
        refund = next(
            neg for neg in data['negQuantities'] if neg['negQuantityReason'] == 'REFUND'
        )
        self.assertEqual(refund['amount'], -56.0)
        self.assertEqual(refund['negQuantityCount'], 2)

        self._assert_report_balances(data, -2.0)

    # ------------------------------------------------------------------
    # Free product rewards
    # ------------------------------------------------------------------

    def test_turnover_free_product_reward_totals_zero(self):
        """The goods leave the store, so the FDM is told -- at a zero line total."""
        self._create_signed_loyalty_order([
            self._product_line(self.burger, 2),
            self._free_product_line(self.free_burger, self.burger),
        ], 56.0)

        data = self._get_turnover_data()
        vats, departments = self._vats(data), self._departments(data)

        # 56 of paid burgers plus a 28 burger fully reduced to 0.
        self.assertEqual(departments['BB Main Dishes']['amount'], 56.0)
        self.assertEqual(vats['B']['totalAmount'], 56.0)

        free_product = next(
            pc for pc in data['priceChanges'] if pc['name'] == 'LOYALTY_FREE_PRODUCT'
        )
        amounts = {entry['label']: entry for entry in free_product['amount']}
        self.assertEqual(amounts['B']['negative'], -28.0)
        self.assertEqual(amounts['B']['positive'], 0.0)

        # Given away, not returned: it is not a negative quantity.
        self.assertEqual(data['negQuantities'], [])

        self._assert_report_balances(data, 56.0)

    # ------------------------------------------------------------------
    # Combined, and the user report
    # ------------------------------------------------------------------

    def test_turnover_loyalty_discount_paid_with_a_gift_card(self):
        """A reward and a redemption on one order pull in opposite directions."""
        self._create_signed_loyalty_order([
            self._product_line(self.martini, 1),
            self._product_line(self.burger, 2, [
                self._loyalty_price_change('LOYALTY_DISCOUNT', -14.0, 'LINE'),
            ]),
            self._discount_reward_line(self.burger_discount, 14.0, self.burger.taxes_id),
            self._voucher_redemption_line(self.gift_card, 50.0),
        ], 54.0)

        data = self._get_turnover_data()
        vats, departments, payments = (
            self._vats(data), self._departments(data), self._payments(data),
        )

        # The reward is deducted from the goods, the redemption is not.
        self.assertEqual(departments['BB Aperitifs']['amount'], 12.0)
        self.assertEqual(departments['BB Main Dishes']['amount'], 42.0)
        self.assertEqual(vats['A']['totalAmount'], 12.0)
        self.assertEqual(vats['B']['totalAmount'], 42.0)

        self.assertEqual(payments['Gift Card']['amount']['totalAmount'], 50.0)
        self.assertEqual(payments[self.payment_method.name]['amount']['totalAmount'], 4.0)

        self._assert_report_balances(data, 54.0)

    def test_user_report_includes_voucher_payments(self):
        """A cashier's turnover is the total of their N events, gross of vouchers."""
        self._create_signed_loyalty_order([
            self._product_line(self.martini, 1),
            self._product_line(self.burger, 2),
            self._voucher_redemption_line(self.gift_card, 50.0),
        ], 68.0)

        users = self.session.get_l10n_be_user_report_data(before_closing=True)['users']
        self.assertEqual(len(users), 1)
        payments = {payment['name']: payment for payment in users[0]['payments']}
        self.assertEqual(payments['Gift Card']['type'], 'VOUCHER_STORE')
        self.assertEqual(payments['Gift Card']['amount']['totalAmount'], 50.0)
        self.assertEqual(payments[self.payment_method.name]['amount']['totalAmount'], 18.0)
        self.assertEqual(users[0]['totalAmount'], 68.0)
        self.assertEqual(
            sum(pay['amount']['totalAmount'] for pay in users[0]['payments']), 68.0,
        )

    def test_user_report_sums_voucher_payments_over_orders(self):
        """Two redemptions of the same kind land on one payment line of the user."""
        self._create_signed_loyalty_order([
            self._product_line(self.burger, 2),
            self._voucher_redemption_line(self.gift_card, 50.0),
        ], 56.0)
        self._create_signed_loyalty_order([
            self._product_line(self.martini, 1),
            self._voucher_redemption_line(self.gift_card, 5.0),
            self._voucher_redemption_line(self.ewallet, 3.0),
        ], 12.0)

        users = self.session.get_l10n_be_user_report_data(before_closing=True)['users']
        self.assertEqual(len(users), 1)
        payments = {payment['name']: payment for payment in users[0]['payments']}
        self.assertEqual(payments['Gift Card']['amount']['totalAmount'], 55.0)
        self.assertEqual(payments['Ewallet']['amount']['totalAmount'], 3.0)
        self.assertEqual(payments[self.payment_method.name]['amount']['totalAmount'], 10.0)
        self.assertEqual(users[0]['totalAmount'], 68.0)
