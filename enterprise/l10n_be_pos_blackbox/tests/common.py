# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command
from odoo.addons.pos_restaurant.tests.test_frontend import TestFrontendCommon


class TestL10nBePosBlackboxCommon(TestFrontendCommon):
    """POS configured with a certified FDM, shared by every blackbox test suite."""

    @classmethod
    @TestFrontendCommon.setup_country('be')
    def setUpClass(cls):
        super().setUpClass()
        blackbox_be = cls.env['pos.blackbox.be'].sudo().create({
            'fdm_id': 'VCB01002601',
            'local_ip': "0.0.0.0",
        })
        cls.bbox_printer = cls.env['pos.printer'].create({
            'name': 'Printer',
            'printer_type': 'epson_epos',
            'printer_ip': '0.0.0.0',
            'use_type': 'receipt',
        })

        cls.main_pos_config.write({
            'l10n_be_blackbox_be_id': blackbox_be.id,
            'l10n_be_pos_id': 'CPOS0031234567',
            'other_devices': True,
            'establishment_number': '8789456149',
            'receipt_printer_ids': [(4, cls.bbox_printer.id)],
            'preparation_printer_ids': [Command.clear()]
        })
        cls.env.user.l10n_be_insz_or_bis_number = '00000000097'
        cls.pos_user.l10n_be_insz_or_bis_number = '00000000097'
        cls.pos_admin.sudo().l10n_be_insz_or_bis_number = '00000000097'
        cls.env.company.write({
            'street': 'Rue de Ramilles 1',
            'vat': 'BE0477472701',
        })


class TestL10nBePosBlackboxTurnoverCommon(TestL10nBePosBlackboxCommon):
    """Fixture building fiscally signed orders and reading back the X/Z turnover blocks.

    The FDM defines the turnover amounts as
        amounts = sum(VatInput.price) + sum(VatInput.priceChanges.amount)
    Every term of that sum counts: negative lines (refunds, corrections, ...)
    subtract, and every price change is deducted whatever its ``scope`` --
    ``LINE`` and ``EVENT`` only record where the reduction was entered, not how
    it is computed.

    The invariant that ties the whole report together, and that catches this
    class of bug, is
        sum(vats.totalAmount) == sum(departments.amount)
                              == transactions[N].amount
                              == sum(payments.totalAmount)
    """

    def setUp(self):
        super().setUp()
        self.aperitifs = self.env['pos.category'].create({'name': 'BB Aperitifs'})
        self.main_dishes = self.env['pos.category'].create({'name': 'BB Main Dishes'})
        self.martini = self._create_taxed_product('BB Dry Martini', 'A', 21.0, 12.0, self.aperitifs)
        self.burger = self._create_taxed_product('BB Burger', 'B', 12.0, 28.0, self.main_dishes)

        # The global discount is a separate, non-fiscal line: the POS spreads its
        # effect over the product lines as EVENT price changes instead.
        self.discount_product = self.env['product.product'].create({
            'name': 'BB Global Discount',
            'available_in_pos': True,
            'list_price': 0.0,
            'taxes_id': [(6, 0, [])],
        })
        self.main_pos_config.write({
            'module_pos_discount': True,
            'discount_product_id': self.discount_product.id,
        })

        self.main_pos_config.with_user(self.pos_user).open_ui()
        self.session = self.main_pos_config.current_session_id
        self.payment_method = self.main_pos_config.payment_method_ids[0]
        # `use_blackbox` is computed from the clock-in events of the session.
        self.env['pos.clock.in.out'].create({
            'type': 'in',
            'session_id': self.session.id,
            'user_id': self.pos_user.id,
        })

    def _create_taxed_product(self, name, letter, rate, price, category):
        """Create a POS product whose tax maps to the given FDM VAT ``letter``."""
        tax_group = self.env['account.tax.group'].create({
            'name': f'Blackbox group {letter}',
            'pos_receipt_label': letter,
            'country_id': self.env.company.country_id.id,
        })
        tax = self.env['account.tax'].create({
            'name': f'Blackbox tax {letter} {rate}%',
            'amount': rate,
            'amount_type': 'percent',
            'type_tax_use': 'sale',
            'price_include_override': 'tax_included',
            'tax_group_id': tax_group.id,
        })
        return self.env['product.product'].create({
            'name': name,
            'available_in_pos': True,
            'list_price': price,
            'taxes_id': [(6, 0, tax.ids)],
            'pos_categ_ids': [(6, 0, category.ids)],
        })

    def _spread_price_changes(self, lines, global_discount):
        """Return the per-line FDM figures the POS sends for ``lines``.

        ``lines`` holds ``(product, qty)`` or ``(product, qty, line_discount_pc)``
        tuples, ``global_discount`` is ``('percent', 20)`` or ``('fixed', 10)``.

        A reduction always carries the opposite sign of the line it reduces, so a
        refunded line (negative ``price``) gets a *positive* price change, as in
        `generatePriceChangeInput`.
        """
        currency = self.session.currency_id
        specs = []
        for spec in lines:
            product, qty = spec[0], spec[1]
            discount_pc = spec[2] if len(spec) > 2 else 0.0
            gross = currency.round(product.list_price * qty)
            reduction_sign = -1 if gross >= 0 else 1
            line_change = reduction_sign * currency.round(abs(gross) * discount_pc / 100)
            specs.append({
                'product': product,
                'qty': qty,
                'discount_pc': discount_pc,
                'gross': gross,
                'reduction_sign': reduction_sign,
                'line_change': line_change,
                'base': gross + line_change,
                'event_change': 0.0,
            })

        if global_discount:
            gd_type, gd_value = global_discount
            total_base = sum(abs(spec['base']) for spec in specs)
            for spec in specs:
                if gd_type == 'fixed':
                    # Proportional distribution of the fixed amount over the lines.
                    amount = gd_value * abs(spec['base']) / total_base if total_base else 0.0
                else:
                    amount = abs(spec['base']) * gd_value / 100
                spec['event_change'] = spec['reduction_sign'] * currency.round(amount)

        for spec in specs:
            spec['total'] = spec['base'] + spec['event_change']
        return specs

    def _line_vats(self, spec, global_discount):
        """Build the `l10n_be_vats` payload `signSale` sends for one line."""
        price_changes = []
        if spec['event_change']:
            gd_type, gd_value = global_discount
            suffix = 'F' if gd_type == 'fixed' else 'P'
            price_changes.append({
                'id': f'2_{gd_value}{suffix}',
                'groupingId': 1,
                'name': f'GLOBAL_DISCOUNT_{gd_value}{suffix}',
                'scope': 'EVENT',
                'type': 'PUBLIC',
                'amount': spec['event_change'],
            })
        if spec['line_change']:
            price_changes.append({
                'id': f'4_{spec["discount_pc"]}P',
                'groupingId': 2,
                'name': f'DISCOUNT_{spec["discount_pc"]}P',
                'scope': 'LINE',
                'type': 'PUBLIC',
                'amount': spec['line_change'],
            })
        label = spec['product'].taxes_id[0].tax_group_id.pos_receipt_label
        return [{'label': label, 'price': spec['gross'], 'priceChanges': price_changes}]

    def _create_signed_order(self, lines, is_refund=False, global_discount=None):
        """Create a fiscally signed order along with the payload signSale sent for it.

        The stored ORM signs mirror what the POS actually syncs (verified against
        real session data):
        - refund order: negative ``qty`` but *positive* line subtotals, the refund
          sign lives on the order totals;
        - negative line of a regular order (corrections, price changes, global
          discounts, ...): negative ``qty`` and negative line subtotals.
        """
        currency = self.session.currency_id
        specs = self._spread_price_changes(lines, global_discount)
        # A refund order carries the magnitudes on its lines, not the signed amounts.
        line_sign = -1 if is_refund else 1

        order_lines = []
        for spec in specs:
            product = spec['product']
            rate = product.taxes_id[0].amount
            # The ORM line holds the price net of its own discount only; the
            # global discount lives on the separate discount line below.
            subtotal_incl = line_sign * spec['base']
            order_lines.append((0, 0, {
                'name': f'{product.name} x{spec["qty"]}',
                'product_id': product.id,
                'price_unit': product.list_price,
                'discount': spec['discount_pc'],
                'qty': spec['qty'],
                'tax_ids': [(6, 0, product.taxes_id.ids)],
                'price_subtotal': currency.round(subtotal_incl / (1 + rate / 100)),
                'price_subtotal_incl': subtotal_incl,
                'l10n_be_vats': self._line_vats(spec, global_discount),
            }))

        # The POS materialises the spread as one discount line per reduced line.
        for spec in specs:
            if not spec['event_change']:
                continue
            order_lines.append((0, 0, {
                'name': self.discount_product.name,
                'product_id': self.discount_product.id,
                'price_unit': spec['event_change'],
                'discount': 0,
                'qty': 1,
                'tax_ids': [(6, 0, [])],
                'price_subtotal': spec['event_change'],
                'price_subtotal_incl': spec['event_change'],
                # Never an FDM transaction line: it is sent as EVENT price
                # changes of the product lines instead.
                'l10n_be_vats': [],
            }))

        total = currency.round(sum(spec['total'] for spec in specs))
        total_tax = currency.round(sum(
            spec['total'] - spec['total'] / (1 + spec['product'].taxes_id[0].amount / 100)
            for spec in specs
        ))
        order = self.env['pos.order'].create({
            'company_id': self.env.company.id,
            'session_id': self.session.id,
            'lines': order_lines,
            'amount_total': total,
            'amount_paid': total,
            'amount_tax': total_tax,
            'amount_return': 0.0,
            'is_refund': is_refund,
            'l10n_be_short_signature': 'ABC123',
        })
        self.env['pos.payment'].create({
            'pos_order_id': order.id,
            'payment_method_id': self.payment_method.id,
            'amount': total,
        })
        order.state = 'paid'
        # Mirror the `signSale` event the POS sends to the FDM for this order.
        self.session.increment_l10n_be_counters('N', total)
        return order

    def _get_turnover_data(self):
        return self.env['report.point_of_sale.report_saledetails'].get_sale_details(
            session_ids=[self.session.id], before_closing=True,
        )

    def _vats(self, data):
        return {vat['label']: vat for vat in data['vats']}

    def _departments(self, data):
        return {dept['departmentName']: dept for dept in data['departments']}

    def _payments(self, data):
        return {payment['name']: payment for payment in data['l10_be_payments']}

    def _assert_report_balances(self, data, expected_total):
        """Every turnover block must add up to the same signed total."""
        n_amount = next(
            t['amount'] for t in data['turnoverTransactions'] if t['eventLabel'] == 'N'
        )
        self.assertAlmostEqual(n_amount, expected_total, places=2)
        self.assertAlmostEqual(
            sum(vat['totalAmount'] for vat in data['vats']), expected_total, places=2,
            msg="the vats block must add up to the signed transactions",
        )
        self.assertAlmostEqual(
            sum(dept['amount'] for dept in data['departments']), expected_total, places=2,
            msg="the departments block must add up to the signed transactions",
        )
        self.assertAlmostEqual(
            sum(pay['amount']['totalAmount'] for pay in data['l10_be_payments']),
            expected_total, places=2,
            msg="the payments block must add up to the signed transactions",
        )
