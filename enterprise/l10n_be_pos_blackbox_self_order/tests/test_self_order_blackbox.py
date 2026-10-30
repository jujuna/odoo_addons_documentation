import odoo.tests
from odoo import Command
from odoo.tests.common import JsonRpcException
from odoo.tools import mute_logger

from odoo.addons.pos_restaurant.tests.test_frontend import TestFrontendCommon


@odoo.tests.tagged("post_install_l10n", "post_install", "-at_install")
class TestSelfOrderBlackbox(TestFrontendCommon):

    @classmethod
    @TestFrontendCommon.setup_country('be')
    def setUpClass(cls):
        super().setUpClass()
        blackbox_be = cls.env['pos.blackbox.be'].sudo().create({
            'fdm_id': 'VCB01002601',
            'local_ip': "0.0.0.0",
        })
        cls.pos_categ_blackbox = cls.env['pos.category'].create({
            'name': 'Blackbox products',
        })

        # Create a product with a price 0, so we can have a tour that go to the confirmation page (no payment needed since price is 0) and sign the order with the blackbox
        cls.product = cls.env['product.product'].create({
            'name': 'Test product',
            'is_storable': True,
            'list_price': 0,
            'taxes_id': False,
            'available_in_pos': True,
            'pos_categ_ids': [(4, cls.pos_categ_blackbox.id)],
            'default_code': '12345',
        })
        cls.pos_config.write({
            'payment_method_ids': [Command.set([cls.bank_payment_method.id])],
            'l10n_be_blackbox_be_id': blackbox_be.id,
            'l10n_be_pos_id': 'CPOS0031234567',
            'establishment_number': '8789456149',
            'self_ordering_mode': 'kiosk',
            'self_ordering_pay_after': 'each',
            'self_ordering_service_mode': 'counter',
            'iface_available_categ_ids': [Command.set([cls.pos_categ_blackbox.id])],
            'limit_categories': True,
        })
        cls.env.user.l10n_be_insz_or_bis_number = '00000000097'
        cls.pos_user.l10n_be_insz_or_bis_number = '00000000097'
        cls.pos_admin.sudo().l10n_be_insz_or_bis_number = '00000000097'
        cls.env.company.write({
            'street': 'Rue de Ramilles 1',
            'vat': 'BE0477472701',
        })

    def test_l10n_be_pos_blackbox_kiosk_tour(self):
        self.pos_config.with_user(self.pos_user).open_ui()
        self.pos_config.current_session_id.set_opening_control(0, "")
        current_session = self.pos_config.current_session_id
        self_route = self.pos_config._get_self_order_route()
        # Logged in to close the session during the tour, as the kiosk can't
        self.start_tour(self_route, "test_l10n_be_pos_blackbox_kiosk_tour", login="pos_user")
        pdf_attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'pos.session'),
            ('res_id', '=', current_session.id),
            ('mimetype', '=', 'application/pdf')
        ])
        self.assertEqual(len(pdf_attachments), 2, "There should be 2 PDF attachments (Sale Details and User Report).")
        # Two clock events (one in, one out)
        self.assertEqual(len(current_session.pos_clock_in_out_ids), 2)

        # The Z reports of a session can't be generated twice
        self.assertTrue(current_session.l10n_be_reports_generated)
        with self.assertRaises(JsonRpcException), mute_logger('odoo.http'):
            self.make_jsonrpc_request('/l10n_be_pos_blackbox_self_order/generate_l10n_z_reports_attachments', {
                'access_token': self.pos_config.access_token,
                'config_id': self.pos_config.id,
                'session_id': current_session.id,
                'sale_details': {},
                'user_report_data': {},
            })
        self.assertEqual(self.env['ir.attachment'].search_count([
            ('res_model', '=', 'pos.session'),
            ('res_id', '=', current_session.id),
            ('mimetype', '=', 'application/pdf'),
        ]), 2)

    def test_l10n_be_pos_blackbox_kiosk_public_tour(self):
        """ The kiosk only needs its access token, no user is logged in """
        self.pos_config.with_user(self.pos_user).open_ui()
        current_session = self.pos_config.current_session_id
        current_session.set_opening_control(0, "")
        self.start_tour(self.pos_config._get_self_order_route(), "test_l10n_be_pos_blackbox_kiosk_public_tour")
        self.assertTrue(current_session.order_ids.l10n_be_short_signature)
        self.assertEqual(current_session.pos_clock_in_out_ids.mapped('type'), ['in'])

        # Once a manager closed the session, the kiosk generates its Z reports
        current_session.close_session_from_ui()
        params = {
            'access_token': self.pos_config.access_token,
            'config_id': self.pos_config.id,
            'session_id': current_session.id,
        }
        sale_details = self.make_jsonrpc_request('/l10n_be_pos_blackbox_self_order/get_sale_details', params)
        user_report_data = self.make_jsonrpc_request('/l10n_be_pos_blackbox_self_order/get_l10n_be_user_report_data', params)
        self.make_jsonrpc_request('/l10n_be_pos_blackbox_self_order/generate_l10n_z_reports_attachments', {
            **params,
            'sale_details': sale_details,
            'user_report_data': user_report_data,
        })
        self.assertTrue(current_session.l10n_be_reports_generated)
        z_report_messages = current_session.message_ids.filtered('attachment_ids')
        self.assertEqual(len(z_report_messages.attachment_ids), 2)
        self.assertEqual(z_report_messages.author_id, self.pos_config.self_ordering_default_user_id.partner_id)

    def test_l10n_be_pos_blackbox_kiosk_z_report_without_customer(self):
        """ A kiosk session closed before any customer started ordering never clocked in,
        its Z report must still contain the turnover data required by the FDM. """
        self.pos_config.with_user(self.pos_user).open_ui()
        current_session = self.pos_config.current_session_id
        current_session.set_opening_control(0, "")
        current_session.close_session_from_ui()
        self.assertFalse(current_session.pos_clock_in_out_ids)

        sale_details = self.make_jsonrpc_request('/l10n_be_pos_blackbox_self_order/get_sale_details', {
            'access_token': self.pos_config.access_token,
            'config_id': self.pos_config.id,
            'session_id': current_session.id,
        })
        for key in ('posDevices', 'fdmDevices', 'turnoverTransactions', 'departments', 'vats', 'l10_be_payments',
                    'drawersOpenCount', 'negQuantities', 'priceChanges', 'reportNo', 'reportBookingDate'):
            self.assertIn(key, sale_details)


@odoo.tests.tagged("post_install_l10n", "post_install", "-at_install")
class TestSelfOrderBlackboxMobileObox(TestSelfOrderBlackbox):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        obox = cls.env['obox.obox'].create({
            'name': 'Test Obox',
            'serial_number': '1234567890',
            'state': '02_paired',
            'token': 'dummy',
        })
        cls.receipt_printer = cls.env['pos.printer'].create({
            'name': 'Receipt Printer',
            'printer_type': 'epson_epos',
            'printer_ip': '127.0.0.1',
            'proxy_obox_id': obox.id,
            'use_type': 'receipt',
        })
        cls.pos_config.write({
            'self_ordering_mode': 'mobile',
            'iface_print_auto': True,
            'receipt_printer_ids': [Command.set(cls.receipt_printer.ids)],
        })

    def test_mobile_receipt_printed_once_signed(self):
        self.pos_config.with_user(self.pos_user).open_ui()
        self.pos_config.current_session_id.set_opening_control(0, "")
        order = self.env['pos.order'].create({
            'config_id': self.pos_config.id,
            'session_id': self.pos_config.current_session_id.id,
            'amount_total': 0,
            'amount_paid': 0,
            'amount_tax': 0,
            'amount_return': 0,
            'state': 'paid',
            'source': 'mobile',
            'lines': [Command.create({
                'product_id': self.product.id,
                'price_unit': 0,
                'qty': 1,
                'price_subtotal': 0,
                'price_subtotal_incl': 0,
            })],
        })
        obox_jobs_domain = [('pos_order_id', '=', order.id)]

        # Not signed yet: printing it would give a provisional bill
        order._send_self_order_receipt()
        self.assertFalse(self.env['obox.queue'].search_count(obox_jobs_domain))
        self.assertEqual(order.nb_print, 0)

        # The PoS signs the order and saves its signature
        order.get_order_to_sign()
        order.write({'l10n_be_short_signature': 'SIGNATURE', 'l10n_be_event_label': 'N'})
        self.assertEqual(self.env['obox.queue'].search_count(obox_jobs_domain), 1)
        self.assertEqual(order.nb_print, 1)

        # Saving the signature again doesn't print the receipt twice
        order.write({'l10n_be_short_signature': 'SIGNATURE'})
        self.assertEqual(self.env['obox.queue'].search_count(obox_jobs_domain), 1)
