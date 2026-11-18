from odoo import Command

from odoo.addons.l10n_mx_edi.tests.common import TestMxEdiCommon
from odoo.tests import tagged


@tagged('post_install_l10n', 'post_install', '-at_install', *TestMxEdiCommon.extra_tags)
class TestCFDIInvoiceSale(TestMxEdiCommon):

    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.write({'group_ids': [(4, cls.env.ref('sales_team.group_sale_salesman').id)]})

    def test_global_discount(self):
        product1 = self.product
        product2 = self._create_product_mx()
        product3 = self._create_product_mx()

        to_test = list(range(10, 16))
        with self.mx_external_setup(self.frozen_today):
            for percent in to_test:
                with self.subTest(percent=percent):
                    sale_order = self.env['sale.order'].create({
                        'partner_id': self.partner_mx.id,
                        'l10n_mx_edi_payment_method_id': self.env.ref('l10n_mx_edi.payment_method_efectivo').id,
                        'order_line': [
                            Command.create({
                                'product_id': product1.id,
                                'price_unit': 6194.83,
                                'product_uom_qty': 10.0,
                            }),
                            Command.create({
                                'product_id': product2.id,
                                'price_unit': 7194.83,
                                'product_uom_qty': 5.0,
                            }),
                            Command.create({
                                'product_id': product3.id,
                                'price_unit': 8194.83,
                                'product_uom_qty': 1.0,
                            }),
                        ],
                    })
                    sale_order.action_confirm()
                    self.assertRecordValues(sale_order, [{
                        'amount_untaxed': 106117.28,
                        'amount_tax': 16978.76,
                        'amount_total': 123096.04,
                    }])

                    wizard = self.env['sale.order.discount'].create({
                        'sale_order_id': sale_order.id,
                        'discount_type': 'so_discount',
                        'discount_percentage': percent / 100.0,
                    })
                    wizard.action_apply_discount()

                    wizard = (
                        self.env['sale.advance.payment.inv']
                        .with_context({'active_model': sale_order._name, 'active_ids': sale_order.ids})
                        .create({
                            'advance_payment_method': 'delivered',
                            'amount': 0.0,
                            'fixed_amount': 0.0,
                        })
                    )
                    action_values = wizard.create_invoices()
                    invoice = self.env['account.move'].browse(action_values['res_id'])
                    invoice.action_post()
                    with self.with_mocked_pac_sign_success():
                        invoice._l10n_mx_edi_cfdi_invoice_try_send()
                    self._assert_invoice_cfdi(invoice, f"test_global_discount_{str(percent).replace('.', '_')}")

    def test_down_payment(self):
        to_test = list(range(10, 16))
        with self.mx_external_setup(self.frozen_today):
            for percent in to_test:
                with self.subTest(percent=percent):
                    sale_order = self.env['sale.order'].create({
                        'partner_id': self.partner_mx.id,
                        'l10n_mx_edi_payment_method_id': self.env.ref('l10n_mx_edi.payment_method_efectivo').id,
                        'order_line': [
                            Command.create({
                                'product_id': self.product.id,
                                'price_unit': 6194.83,
                            }),
                        ],
                    })
                    sale_order.action_confirm()
                    self.assertRecordValues(sale_order, [{
                        'amount_untaxed': 6194.83,
                        'amount_tax': 991.17,
                        'amount_total': 7186.0,
                    }])

                    wizard = (
                        self.env['sale.advance.payment.inv']
                        .with_context({'active_model': sale_order._name, 'active_ids': sale_order.ids})
                        .create({
                            'advance_payment_method': 'percentage',
                            'amount': percent,
                        })
                    )
                    action_values = wizard.create_invoices()
                    invoice = self.env['account.move'].browse(action_values['res_id'])
                    invoice.action_post()
                    with self.with_mocked_pac_sign_success():
                        invoice._l10n_mx_edi_cfdi_invoice_try_send()
                    self._assert_invoice_cfdi(invoice, f"test_down_payment_{str(percent).replace('.', '_')}")

                    wizard = (
                        self.env['sale.advance.payment.inv']
                        .with_context({'active_model': sale_order._name, 'active_ids': sale_order.ids})
                        .create({
                            'advance_payment_method': 'delivered',
                            'amount': 0.0,
                            'fixed_amount': 0.0,
                        })
                    )
                    action_values = wizard.create_invoices()
                    invoice = self.env['account.move'].browse(action_values['res_id'])
                    invoice.action_post()
                    with self.with_mocked_pac_sign_success():
                        invoice._l10n_mx_edi_cfdi_invoice_try_send()
                    self._assert_invoice_cfdi(invoice, f"test_down_payment_{str(percent).replace('.', '_')}_final")

    def test_down_payment_reversal(self):
        """
        Test that a Facturas de Anticipo and its credit note are created with
        the correct description.
        """
        def make_invoice(sale_order, args):
            wizard = (
                self.env['sale.advance.payment.inv']
                .with_context({'active_model': sale_order._name, 'active_ids': sale_order.ids})
                .create(args)
            )
            action_values = wizard.create_invoices()
            invoice = self.env['account.move'].browse(action_values['res_id'])
            invoice.action_post()
            return invoice

        def make_draft_credit(invoice):
            action = invoice.action_reverse()
            reversal_wizard = self.env[action['res_model']].with_context(
                active_ids=invoice.ids,
                active_model='account.move',
            ).create({
                'journal_id': invoice.journal_id.id,
            })
            action = reversal_wizard.reverse_moves()
            return self.env['account.move'].browse(action['res_id'])

        with self.mx_external_setup(self.frozen_today):
            sale_order = self.env['sale.order'].create({
                'partner_id': self.partner_mx.id,
                'l10n_mx_edi_payment_method_id': self.env.ref('l10n_mx_edi.payment_method_efectivo').id,
                'order_line': [
                    Command.create({
                        'product_id': self.product.id,
                        'price_unit': 6194.83,
                    }),
                ],
            })
            sale_order.action_confirm()
            self.assertRecordValues(sale_order, [{
                'amount_untaxed': 6194.83,
                'amount_tax': 991.17,
                'amount_total': 7186.0,
            }])

            # create advanced payment (downpayment) invoice
            down_payment_invoice = make_invoice(sale_order, {
                'advance_payment_method': 'percentage',
                'amount': 50,
            })
            with self.with_mocked_pac_sign_success():
                down_payment_invoice._l10n_mx_edi_cfdi_invoice_try_send()
            self.assertRecordValues(down_payment_invoice.invoice_line_ids, [{
                'name': 'Anticipo del bien o servicio',
            }])

            # create credit on advanced payment (down payment)
            credit_note = make_draft_credit(down_payment_invoice)
            credit_note.invoice_line_ids.write({'price_unit': 2000.0})
            credit_note.action_post()
            self.assertRecordValues(credit_note.invoice_line_ids, [{
                'name': 'Aplicación de anticipo',
            }])

            # Test that normal invoice lines / credits do not change
            remainder_invoice = make_invoice(sale_order, {
                'advance_payment_method': 'delivered',
                'amount': 0.0,
                'fixed_amount': 0.0,
            })
            self.assertIn(
                'Down Payment',
                remainder_invoice.invoice_line_ids.filtered('is_downpayment').name,
            )
            remainder_credit_note = make_draft_credit(remainder_invoice)
            remainder_credit_note.action_post()
            self.assertIn(
                'Down Payment',
                remainder_credit_note.invoice_line_ids.filtered('is_downpayment').name,
            )
