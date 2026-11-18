from unittest.mock import patch

from odoo import Command
from odoo.addons.l10n_ke_edi_oscu_pos.tests.common import CommonPosKeEdiTest
from odoo.addons.point_of_sale.tests.test_frontend import TestPointOfSaleHttpCommon
from odoo.addons.l10n_ke_edi_oscu.tests.common import TestKeEdiCommon
from odoo.addons.l10n_ke_edi_oscu.tests.test_live import TestKeEdi
from odoo.exceptions import LockError, UserError
from odoo.tests import new_test_user, tagged

from freezegun import freeze_time


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestEtimsPos(TestKeEdiCommon, CommonPosKeEdiTest):
    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    @TestKeEdi.setup_country('ke')
    def setUpClass(self):
        super().setUpClass()
        self.company.l10n_ke_server_mode = 'demo'

    def test_etims_post_order(self):
        """Testing the pos order process to make sure everything is correctly sends to eTIMS
        """
        order, _ = self.create_backend_pos_order({
            'order_data': {
                'partner_id': self.partner_moda.id
            },
            'line_data': [
                {'product_id': self.twenty_dollars_with_10_incl.product_variant_id.id}
            ],
            'payment_data': [
                {'payment_method_id': self.bank_payment_method.id}
            ]
        })

        order.action_post_order()
        self.assertEqual(order.l10n_ke_oscu_internal_data, 'GRKJVWYCFBPTYQ225X2UEYONVE')
        self.assertEqual(order.l10n_ke_oscu_signature, '123456789ODOOGR3')
        self.assertEqual(order.l10n_ke_oscu_receipt_number, 169)

        # Send stock move to eTIMS
        with self.enter_registry_test_mode():
            self.env.ref('l10n_ke_edi_oscu_stock.ir_cron_send_stock_moves').method_direct_trigger()
        self.assertEqual(order.picking_ids.l10n_ke_oscu_sar_number, 1)

    def test_combo_line_excluded_from_etims(self):
        """
        A combo adds a "0 price" parent line in the PoS, with the chosen combo item as a
        child line. Only the combo item must be sent to eTIMS, not the combo parent line.
        """
        self.pos_config_usd.open_ui()
        product = self.twenty_dollars_with_10_incl.product_variant_id
        combo = self.env['product.combo'].create({
            'name': 'Drinks Combo',
            'combo_item_ids': [Command.create({'product_id': product.id})],
        })
        combo_product = self.env['product.product'].create({
            'name': 'Burger Combo',
            'type': 'combo',
            'combo_ids': [Command.set(combo.ids)],
        })
        pos_order = self.env['pos.order'].create({
            'session_id': self.pos_config_usd.current_session_id.id,
            'partner_id': self.partner_moda.id,
            'amount_tax': 0.0,
            'amount_total': 0.0,
            'amount_paid': 0.0,
            'amount_return': 0.0,
        })
        combo_line = self.env['pos.order.line'].create({
            'order_id': pos_order.id,
            'product_id': combo_product.id,
            'qty': 1,
            'price_subtotal': 0,
            'price_subtotal_incl': 0,
        })
        combo_item_line = self.env['pos.order.line'].create({
            'order_id': pos_order.id,
            'product_id': product.id,
            'qty': 1,
            'price_unit': 100,
            'price_subtotal': 100,
            'price_subtotal_incl': 110,
            'tax_ids': product.taxes_id.ids,
            'combo_item_id': combo.combo_item_ids.id,
            'combo_parent_id': combo_line.id,
        })

        line_items = pos_order._l10n_ke_oscu_get_json_from_order_lines()
        self.assertEqual(len(line_items), 1, "the combo parent line must not be sent to eTIMS")
        self.assertEqual(line_items[0]['itemNm'], combo_item_line.name, "only the combo item line should be sent")

    def test_invoice_order(self):
        order, _ = self.create_backend_pos_order({
            'order_data': {
                'partner_id': self.partner_moda.id,
                'to_invoice': True,
            },
            'line_data': [
                {'product_id': self.twenty_dollars_with_10_incl.product_variant_id.id}
            ],
            'payment_data': [
                {'payment_method_id': self.bank_payment_method.id}
            ]
        })

        order.action_post_order()

        # As the etims call is send in the pos order, we just copy the values from pos order to invoice
        # to avoid duplicate calls
        self.assertEqual(order.l10n_ke_oscu_internal_data, order.account_move.l10n_ke_oscu_internal_data)
        self.assertEqual(order.l10n_ke_oscu_signature, order.account_move.l10n_ke_oscu_signature)
        self.assertEqual(order.l10n_ke_oscu_receipt_number, order.account_move.l10n_ke_oscu_receipt_number)

    def test_invoice_stamped_before_stock_moves_commit(self):
        """ Sending the stock moves commits, so the invoice must carry the eTIMS values by then:
        a failure after that commit would otherwise leave a sent order with an unstamped invoice. """
        order, _ = self.create_backend_pos_order({
            'order_data': {
                'partner_id': self.partner_moda.id,
                'to_invoice': True,
            },
            'line_data': [
                {'product_id': self.twenty_dollars_with_10_incl.product_variant_id.id}
            ],
            'payment_data': [
                {'payment_method_id': self.bank_payment_method.id}
            ]
        })

        invoice_signatures = []
        with patch.object(
            self.env.registry['stock.move'], '_l10n_ke_oscu_process_moves', autospec=True,
            side_effect=lambda moves: invoice_signatures.append(order.account_move.l10n_ke_oscu_signature),
        ):
            order.action_post_order()

        self.assertEqual(invoice_signatures, ['123456789ODOOGR3'])

    def test_rejected_order_does_not_keep_etims_number(self):
        """ The number of a rejected order goes back to the sequence and is taken by the next
        order, so the rejected order must not claim it (and its receipt) on its next attempt. """
        order_data = {
            'order_data': {
                'partner_id': self.partner_moda.id,
            },
            'line_data': [
                {'product_id': self.twenty_dollars_with_10_incl.product_variant_id.id}
            ],
            'payment_data': [
                {'payment_method_id': self.bank_payment_method.id}
            ]
        }
        rejected_order, _ = self.create_backend_pos_order(order_data)
        next_order, _ = self.create_backend_pos_order(order_data)

        with patch.object(
            self.env.registry['res.company'], '_l10n_ke_call_etims', autospec=True,
            return_value=({'code': '910', 'message': 'Invalid request'}, {}, None),
        ):
            rejected_order.post_order_to_etims()
        next_order.action_post_order()
        rejected_order.action_post_order()

        self.assertNotEqual(rejected_order.l10n_ke_oscu_order_number, next_order.l10n_ke_oscu_order_number)

    def _create_paid_order(self):
        order, _ = self.create_backend_pos_order({
            'order_data': {
                'partner_id': self.partner_moda.id,
            },
            'line_data': [
                {'product_id': self.twenty_dollars_with_10_incl.product_variant_id.id}
            ],
            'payment_data': [
                {'payment_method_id': self.bank_payment_method.id}
            ]
        })
        return order

    def _patch_etims(self, save_sale=None, on_call=None):
        """ Answer saveTrnsSalesOsdc with `save_sale` when given, every other endpoint as in demo mode. """
        call_etims = self.env.registry['res.company']._l10n_ke_call_etims

        def _call_etims(company, endpoint, content):
            if on_call:
                on_call(endpoint, content)
            if save_sale and endpoint == 'saveTrnsSalesOsdc':
                return save_sale
            return call_etims(company, endpoint, content)

        return patch.object(self.env.registry['res.company'], '_l10n_ke_call_etims', autospec=True, side_effect=_call_etims)

    def test_sent_order_not_filed_again(self):
        """ A request retried after the order was accepted must not send the sale to eTIMS again. """
        order = self._create_paid_order()
        order.action_post_order()
        number = order.l10n_ke_oscu_order_number

        endpoints = []
        with self._patch_etims(on_call=lambda endpoint, content: endpoints.append(endpoint)):
            order.post_order_to_etims()

        self.assertEqual(endpoints, [])
        self.assertEqual(order.l10n_ke_oscu_order_number, number)

    def test_order_being_sent_elsewhere_not_sent(self):
        """ The order is locked while it is sent, so a concurrent write cannot roll back the
        transaction after eTIMS accepted the sale; a second send is refused. """
        order = self._create_paid_order()

        endpoints = []
        with (
            patch.object(self.env.registry['pos.order'], 'lock_for_update', side_effect=LockError("locked")),
            self._patch_etims(on_call=lambda endpoint, content: endpoints.append(endpoint)),
            self.assertRaises(UserError),
        ):
            order.post_order_to_etims()

        self.assertEqual(endpoints, [])

    def test_cashier_duplicate_number_does_not_block_next_sales(self):
        """ eTIMS answering 924 to a cashier must not end in an access error on the sequence,
        and the number it already holds must not be handed to the next sale. """
        cashier = new_test_user(self.env, 'ke_cashier', groups='base.group_user,point_of_sale.group_pos_user,account.group_account_invoice', company_id=self.company.id)
        order = self._create_paid_order().with_user(cashier)

        sent = []
        with self._patch_etims(
            save_sale=({'code': '924', 'message': 'Invoice number already exists'}, {}, None),
            on_call=lambda endpoint, content: endpoint == 'saveTrnsSalesOsdc' and sent.append(content['invcNo']),
        ):
            response = order.post_order_to_etims()

        next_order = self._create_paid_order().with_user(cashier)
        with self._patch_etims(
            save_sale=({'code': '910', 'message': 'Invalid request'}, {}, None),
            on_call=lambda endpoint, content: endpoint == 'saveTrnsSalesOsdc' and sent.append(content['invcNo']),
        ):
            next_order.post_order_to_etims()

        self.assertEqual(response['error']['code'], '924')
        self.assertFalse(order.l10n_ke_order_json['invcNo'])
        self.assertEqual(len(sent), 2)
        self.assertNotEqual(sent[1], sent[0])

    def test_pending_number_recovered(self):
        """ eTIMS holds the sale this order sent before (e.g. after a timeout): recover its
        receipt, don't resend. """
        order = self._create_paid_order()
        order.l10n_ke_order_json = {'invcNo': 2}

        endpoints = []
        with self._patch_etims(on_call=lambda endpoint, content: endpoints.append(endpoint)):
            order.action_post_order()

        self.assertEqual(order.l10n_ke_oscu_order_number, 2)
        self.assertNotIn('saveTrnsSalesOsdc', endpoints)

    def test_cant_send_order_with_product_out_of_stock(self):
        order, _ = self.create_backend_pos_order({
            'order_data': {
                'partner_id': self.partner_moda.id,
            },
            'line_data': [
                {'product_id': self.twenty_dollars_with_10_incl.product_variant_id.id, 'qty': 100}
            ],
            'payment_data': [
                {'payment_method_id': self.bank_payment_method.id}
            ]
        })

        # Send order to eTIMS, should raise an error
        with self.assertRaises(UserError):
            order.action_post_order()

    def test_refund_pos_order(self):
        order, refund = self.create_backend_pos_order({
            'order_data': {
                'partner_id': self.partner_moda.id,
                'to_invoice': True,
            },
            'line_data': [
                {'product_id': self.twenty_dollars_with_10_incl.product_variant_id.id}
            ],
            'payment_data': [
                {'payment_method_id': self.bank_payment_method.id}
            ],
            'refund_data': [
                {'payment_method_id': self.cash_payment_method.id}
            ]
        })

        order.action_post_order()
        refund.action_post_order()
        self.assertEqual(refund.l10n_ke_oscu_internal_data, 'GRKJVWYCFBPTYQ225X2UEYONVE')
        self.assertEqual(refund.l10n_ke_oscu_signature, '123456789ODOOGR3')
        self.assertEqual(refund.l10n_ke_oscu_receipt_number, 169)

        # The refund must reference the KRA invoice number of the order it refunds, not its own order number.
        self.assertEqual(refund.l10n_ke_order_json['orgInvcNo'], order.l10n_ke_oscu_order_number)
        self.assertNotEqual(refund.l10n_ke_order_json['orgInvcNo'], refund.sequence_number)

    def test_send_order_complex(self):
        """
        Test that complex orders return the same values from POS and invoices.
        Mirror of test_send_invoice_complex.
        """
        with freeze_time('2024-04-15'), self.patch_session([
            ('saveTrnsSalesOsdc', 'save_pos_order_complex', 'save_sale_success'),
            ('saveItem', 'save_item_pos_1', 'success'),
            ('insertStockIO', 'save_stock_io_pos_1', 'success'),
            ('saveStockMaster', 'save_stock_master_pos_1', 'success'),
        ]):
            price_unit = 1300
            discount = 10
            qty = 2

            # ensure that the excise tax applies before the sales and withholding taxes
            wh_tax = self.env['account.chart.template'].ref('SWT10')
            (wh_tax | self.standard_rate_sales_tax).with_context(mail_notrack=True).sequence = 2

            # 1) create the complex pos order
            pos_order = self.create_backend_pos_order({
                'pos_config': self.pos_config_usd,
                'order_data': {
                    'partner_id': self.partner_a.id,
                    'lines': [
                        Command.create({
                            'product_id': self.twenty_dollars_with_10_incl.product_variant_id.id,
                            'price_unit': price_unit,
                            'price_subtotal': price_unit * qty * (1.0 - discount / 100.0),
                            'price_subtotal_incl': 0,
                            'discount': 10,
                            'qty': qty,
                            'tax_ids': [Command.set((self.excise_tax | self.standard_rate_sales_tax | wh_tax).ids)],
                    })],
                    'amount_total': price_unit * qty * (1.0 - discount) / 100.0,
                },
                'payment_data': [
                    {'payment_method_id': self.bank_payment_method.id}
            ]})[0]

            # 2) Send order to eTIMS
            # patch_session requires real sending data
            self.company.l10n_ke_server_mode = 'prod'
            pos_order.action_post_order()

            self.assertEqual(pos_order.l10n_ke_oscu_internal_data, 'GRKJVWYCFBPTYQ225X2UEYONVE')
            self.assertEqual(pos_order.l10n_ke_oscu_signature, '123456789ODOOGR3')
            self.assertEqual(pos_order.l10n_ke_oscu_receipt_number, 169)


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestEtimsComboTour(TestKeEdiCommon, TestPointOfSaleHttpCommon):

    @classmethod
    @TestKeEdi.setup_country('ke')
    def setUpClass(cls):
        super().setUpClass()
        cls.company.l10n_ke_server_mode = 'demo'
        cls.main_pos_config.payment_method_ids = [Command.link(cls.bank_payment_method.id)]

        drink = cls.env['product.product'].create({
            'name': 'Registered Drink',
            'available_in_pos': True,
            'standard_price': 30,
            'taxes_id': cls.tax_sale_a.ids,
            'l10n_ke_product_type_code': '2',
            'l10n_ke_packaging_unit_id': cls.env['l10n_ke_edi_oscu.code'].search([('code', '=', 'BA')], limit=1).id,
            'unspsc_code_id': cls.env['product.unspsc.code'].search([('code', '=', '52161557')], limit=1).id,
            'l10n_ke_origin_country_id': cls.env.ref('base.be').id,
        })
        combo = cls.env['product.combo'].create({
            'name': 'Drinks Combo',
            'combo_item_ids': [Command.create({'product_id': drink.id})],
        })
        cls.env['product.product'].create({
            'name': 'Non-registered Combo',
            'type': 'combo',
            'available_in_pos': True,
            'list_price': 10,
            'taxes_id': False,
            'combo_ids': [Command.set(combo.ids)],
        })

    def test_etims_combo(self):
        """
        A combo whose components are registered can be validated without registering the
        combo itself, and no eTIMS warning should be shown.
        """
        self.main_pos_config.open_ui()
        self.start_pos_tour('l10n_ke_edi_pos_combo_registered', login="accountman")
