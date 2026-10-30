# Part of Odoo. See LICENSE file for full copyright and licensing details.

import odoo

from odoo.addons.l10n_be_pos_blackbox.tests.common import TestL10nBePosBlackboxTurnoverCommon


@odoo.tests.tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nBePosBlackboxTurnoverReport(TestL10nBePosBlackboxTurnoverCommon):
    """Regression tests for the turnover blocks of the X/Z report"""

    # ------------------------------------------------------------------
    # EVENT scope (order-level / global discounts)
    # ------------------------------------------------------------------

    def test_turnover_deducts_percent_global_discount(self):
        """An EVENT price change must be deducted like a LINE one."""
        self._create_signed_order(
            [(self.martini, 1), (self.burger, 2)], global_discount=('percent', 20),
        )

        data = self._get_turnover_data()
        vats, departments = self._vats(data), self._departments(data)

        # 12 - 2.4 and 56 - 11.2, spread by the POS over the two lines.
        self.assertEqual(departments['BB Aperitifs']['amount'], 9.6)
        self.assertEqual(departments['BB Main Dishes']['amount'], 44.8)

        self.assertEqual(vats['A']['totalAmount'], 9.6)
        self.assertEqual(vats['A']['taxableAmount'], 7.93)
        self.assertEqual(vats['A']['vatAmount'], 1.67)

        self.assertEqual(vats['B']['totalAmount'], 44.8)
        self.assertEqual(vats['B']['taxableAmount'], 40.0)
        self.assertEqual(vats['B']['vatAmount'], 4.8)

        self._assert_report_balances(data, 54.4)

    def test_turnover_deducts_fixed_global_discount(self):
        """A fixed-amount global discount is spread proportionally over the lines."""
        self._create_signed_order(
            [(self.martini, 1), (self.burger, 2)], global_discount=('fixed', 10),
        )

        data = self._get_turnover_data()
        vats, departments = self._vats(data), self._departments(data)

        # -10 EUR over a 68 EUR order: -1.76 on 12 and -8.24 on 56.
        self.assertEqual(departments['BB Aperitifs']['amount'], 10.24)
        self.assertEqual(departments['BB Main Dishes']['amount'], 47.76)
        self.assertEqual(vats['A']['totalAmount'], 10.24)
        self.assertEqual(vats['B']['totalAmount'], 47.76)

        self._assert_report_balances(data, 58.0)

    def test_turnover_deducts_global_discount_with_partial_refund(self):
        """`negQuantities` must report the net refunded amount, not the gross one."""
        self._create_signed_order(
            [(self.martini, 1), (self.burger, 2)], global_discount=('percent', 20),
        )
        self._create_signed_order(
            [(self.burger, -2)], is_refund=True, global_discount=('percent', 20),
        )

        data = self._get_turnover_data()
        vats, departments = self._vats(data), self._departments(data)

        # Label A is the discriminating case: label B nets to zero with or
        # without the price changes, so it cannot detect the bug here.
        self.assertEqual(departments['BB Aperitifs']['amount'], 9.6)
        self.assertEqual(vats['A']['totalAmount'], 9.6)
        self.assertEqual(vats['A']['taxableAmount'], 7.93)
        self.assertEqual(vats['A']['vatAmount'], 1.67)

        # 2 burgers refunded at 44.8 net, not at their 56 gross.
        self.assertEqual(departments['BB Main Dishes']['amount'], 0.0)
        self.assertEqual(vats['B']['totalAmount'], 0.0)
        refund = next(
            neg for neg in data['negQuantities'] if neg['negQuantityReason'] == 'REFUND'
        )
        self.assertEqual(refund['amount'], -44.8)
        self.assertEqual(refund['negQuantityCount'], 2)

        self._assert_report_balances(data, 9.6)

    def test_report_categories_are_tagged_with_department_ids(self):
        """`data["products"]` keeps carrying the department id its consumers need.

        The `departments` block derives its ids from the order lines; the
        category rows of the human-readable table carry the same id so a
        consumer of the report data can match the two together.
        """
        self._create_signed_order([(self.martini, 1), (self.burger, 2)])

        data = self._get_turnover_data()
        category_ids = {category['name']: category['id'] for category in data['products']}
        self.assertEqual(category_ids['BB Aperitifs'], self.aperitifs.id)
        self.assertEqual(category_ids['BB Main Dishes'], self.main_dishes.id)
        departments = self._departments(data)
        self.assertEqual(
            departments['BB Aperitifs']['departmentId'], str(self.aperitifs.id),
        )

    def test_turnover_price_changes_block_reports_both_signs(self):
        """The `priceChanges` block keeps the reductions and their reversals apart."""
        self._create_signed_order(
            [(self.martini, 1), (self.burger, 2)], global_discount=('percent', 20),
        )
        self._create_signed_order(
            [(self.burger, -2)], is_refund=True, global_discount=('percent', 20),
        )

        data = self._get_turnover_data()
        global_discount = next(
            pc for pc in data['priceChanges'] if pc['name'] == 'GLOBAL_DISCOUNT_20P'
        )
        amounts = {entry['label']: entry for entry in global_discount['amount']}
        self.assertEqual(amounts['A']['negative'], -2.4)
        self.assertEqual(amounts['A']['positive'], 0.0)
        self.assertEqual(amounts['B']['negative'], -11.2)
        self.assertEqual(amounts['B']['positive'], 11.2)

    def test_user_report_totals_are_net_of_global_discount(self):
        """The user report aggregates order totals, so it never missed the discount."""
        self._create_signed_order(
            [(self.martini, 1), (self.burger, 2)], global_discount=('percent', 20),
        )

        users = self.session.get_l10n_be_user_report_data(before_closing=True)['users']
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]['totalAmount'], 54.4)
        self.assertEqual(
            sum(pay['amount']['totalAmount'] for pay in users[0]['payments']), 54.4,
        )

    # ------------------------------------------------------------------
    # LINE scope and signed lines (must keep working unchanged)
    # ------------------------------------------------------------------

    def test_turnover_deducts_line_discount(self):
        """A LINE price change keeps being deducted, and the report still balances."""
        self._create_signed_order([(self.martini, 1), (self.burger, 2, 25.0)])

        data = self._get_turnover_data()
        vats, departments = self._vats(data), self._departments(data)

        self.assertEqual(departments['BB Aperitifs']['amount'], 12.0)
        self.assertEqual(departments['BB Main Dishes']['amount'], 42.0)
        self.assertEqual(vats['A']['totalAmount'], 12.0)
        self.assertEqual(vats['B']['totalAmount'], 42.0)

        self._assert_report_balances(data, 54.0)

    def test_turnover_vats_nets_refund_order_lines(self):
        """A refund order must subtract from its VAT label, not add to it."""
        self._create_signed_order([(self.martini, 1), (self.burger, 2)])
        refund = self._create_signed_order([(self.burger, -2)], is_refund=True)

        # Guard the fixture: a synced refund order keeps the sign on the order
        # totals while its lines hold negative quantities and positive amounts.
        self.assertEqual(refund.amount_total, -56.0)
        self.assertEqual(refund.lines.qty, -2)
        self.assertEqual(refund.lines.price_subtotal_incl, 56.0)

        data = self._get_turnover_data()
        vats = self._vats(data)

        # Label B: 56 sold, then 56 refunded -> nets to zero.
        self.assertEqual(vats['B']['rate'], 12.0)
        self.assertEqual(vats['B']['taxableAmount'], 0.0)
        self.assertEqual(vats['B']['vatAmount'], 0.0)
        self.assertEqual(vats['B']['totalAmount'], 0.0)

        # Label A is untouched by the refund.
        self.assertEqual(vats['A']['taxableAmount'], 9.92)
        self.assertEqual(vats['A']['vatAmount'], 2.08)
        self.assertEqual(vats['A']['totalAmount'], 12.0)

        self._assert_report_balances(data, 12.0)

    def test_turnover_vats_nets_negative_lines_of_regular_orders(self):
        """Negative lines of regular orders share the refund accumulation path.

        CORRECTION, PRICE_CHANGE, COST_CENTER_CHANGE and VOUCHER negative
        quantities are stored as negative lines on non-refund orders.
        `_is_refund_order_line` routes every line with a negative
        `price_subtotal_incl` to the refund table, so they must subtract too.
        """
        self._create_signed_order([(self.martini, 1), (self.burger, 2), (self.burger, -2)])

        data = self._get_turnover_data()
        vats = self._vats(data)

        self.assertEqual(vats['B']['taxableAmount'], 0.0)
        self.assertEqual(vats['B']['vatAmount'], 0.0)
        self.assertEqual(vats['B']['totalAmount'], 0.0)
        self.assertEqual(vats['A']['totalAmount'], 12.0)

        self._assert_report_balances(data, 12.0)
