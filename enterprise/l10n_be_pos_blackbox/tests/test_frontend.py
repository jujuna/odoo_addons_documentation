import odoo

from odoo.addons.l10n_be_pos_blackbox.tests.common import TestL10nBePosBlackboxCommon


@odoo.tests.tagged('post_install_l10n', 'post_install', '-at_install')
class TestL10nBePosBlackbox(TestL10nBePosBlackboxCommon):

    def _assert_session_event_counters(self, session, expected):
        self.assertEqual(session.l10n_be_N_event_counter, expected.get("N_event_counter", 0))
        self.assertEqual(session.l10n_be_N_event_amount, expected.get("N_event_amount", 0))
        self.assertEqual(session.l10n_be_P_event_counter, expected.get("P_event_counter", 0))
        self.assertEqual(session.l10n_be_P_event_amount, expected.get("P_event_amount", 0))
        self.assertEqual(session.l10n_be_I_event_counter, expected.get("I_event_counter", 0))
        self.assertEqual(session.l10n_be_I_event_amount, expected.get("I_event_amount", 0))
        self.assertEqual(session.l10n_be_T_event_counter, expected.get("T_event_counter", 0))
        self.assertEqual(session.l10n_be_T_event_amount, expected.get("T_event_amount", 0))

    def test_l10n_be_pos_blackbox_sign_sale_refund_tour(self):
        """ Test signing a sale and a refund """
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self.start_tour("/pos/ui/%d" % self.main_pos_config.id, 'l10n_be_pos_blackbox_sign_sale_refund_tour', login="pos_admin")
        self._assert_session_event_counters(session, {
            "N_event_counter": 4,
            "N_event_amount": 2.2,
            "P_event_counter": 1,
            "P_event_amount": 4.4,
        })
        self.assertEqual(len(session.pos_clock_in_out_ids), 1)

    def test_l10n_be_pos_blackbox_sign_sale_refund_retail_tour(self):
        """ Test signing a sale and a refund on a POS that is not a bar/restaurant """
        self.main_pos_config.module_pos_restaurant = False
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self.start_tour("/pos/ui/%d" % self.main_pos_config.id, 'l10n_be_pos_blackbox_sign_sale_refund_retail_tour', login="pos_admin")
        self._assert_session_event_counters(session, {
            "N_event_counter": 2,
            "N_event_amount": 0,
        })
        orders = self.env["pos.order"].search([('session_id', '=', session.id)])
        self.assertEqual(len(orders), 2)
        self.assertTrue(all(orders.mapped('l10n_be_short_signature')))
        self.assertEqual(len(session.pos_clock_in_out_ids), 1)

    def test_l10n_be_pos_blackbox_sign_sale_invoice_tour(self):
        """ Test signing a sale with an invoice """
        self.partner_bbox = self.env["res.partner"].create({"name": "A blackbox partner"})
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self.start_tour("/pos/ui/%d" % self.main_pos_config.id, 'l10n_be_pos_blackbox_sign_sale_invoice_tour', login="pos_admin")
        self._assert_session_event_counters(session, {
            "N_event_counter": 1,
            "N_event_amount": 2.2,
            "P_event_counter": 2,
            "P_event_amount": 2.2,
            "I_event_counter": 1,
            "I_event_amount": 2.2,
        })
        self.assertEqual(len(session.pos_clock_in_out_ids), 1)

    def test_l10n_be_pos_blackbox_merge_transfer_tour(self):
        """ Test to merge/transfer orders between tables """
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self.start_tour("/pos/ui/%d" % self.main_pos_config.id, 'l10n_be_pos_blackbox_transfer_tour', login="pos_admin")
        self._assert_session_event_counters(session, {
            "N_event_counter": 1,
            "N_event_amount": 6.6,
            "P_event_counter": 6,
            "P_event_amount": 6.6,
        })
        self.assertEqual(len(session.pos_clock_in_out_ids), 1)

    def test_l10n_be_pos_blackbox_split_table_tour(self):
        """ Test to split/transfer orders between tables """
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self.start_tour("/pos/ui/%d" % self.main_pos_config.id, 'l10n_be_pos_blackbox_split_table_tour', login="pos_admin")
        self._assert_session_event_counters(session, {
            "N_event_counter": 2,
            "N_event_amount": 6.6,
            "P_event_counter": 6,
            "P_event_amount": 11,
        })

    def test_l10n_be_pos_blackbox_cash_move_cancel_order_tour(self):
        """ Test that cancel an order then make a cash move """
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self.start_tour("/pos/ui/%d" % self.main_pos_config.id, 'l10n_be_pos_blackbox_cash_move_cancel_order_tour', login="pos_admin")
        self._assert_session_event_counters(session, {
            "N_event_counter": 1,
            "P_event_counter": 2,
            "P_event_amount": 0,
        })
        self.assertEqual(len(session.pos_clock_in_out_ids), 1)

    def test_l10n_be_pos_blackbox_sign_sale_backend_offline(self):
        """ Test signing a sale when the backend is unreachable """
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self.start_tour("/pos/ui/%d" % self.main_pos_config.id, 'test_l10n_be_pos_blackbox_sign_sale_backend_offline', login="pos_admin")
        # Check that the order that was signed offline, is now synced with its blackbox signature
        signed_order = self.env["pos.order"].search([('session_id', '=', session.id)])
        self.assertEqual(len(signed_order), 1, "There should be one signed order.")
        self.assertEqual(signed_order.l10n_be_short_signature, "ca39a3ee5e6b4b0d3255bfef95601890afd80709")
        self.assertEqual(signed_order.state, "paid")
        self._assert_session_event_counters(session, {
            "N_event_counter": 1,
            "N_event_amount": 2.2,
        })
        self.assertEqual(len(session.pos_clock_in_out_ids), 1)

    def test_l10n_be_pos_blackbox_sign_sale_blackbox_offline(self):
        """ Test that we should not be able to confirm a sale when the blackbox is unreachable """
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self.start_tour("/pos/ui/%d" % self.main_pos_config.id, 'test_l10n_be_pos_blackbox_sign_sale_blackbox_offline', login="pos_admin")
        # Check that the order that was attempted to be signed offline, is still in draft and has no blackbox signature
        order = self.env["pos.order"].search([('session_id', '=', session.id)])
        self.assertEqual(len(order), 1, "There should be one order.")
        self.assertFalse(order.l10n_be_short_signature)
        self.assertEqual(order.state, "draft")
        # Here the 'order' P event is not counted despite the order is synced, because P events are not awaited, and the tour finish before the P event is processed
        self._assert_session_event_counters(session, {})
        self.assertEqual(len(session.pos_clock_in_out_ids), 1)

    def test_l10n_be_pos_blackbox_sign_sale_backend_offline_blackbox_offline(self):
        """ Test that we should not be able to confirm a sale when the blackbox and the backend are unreachable """
        self.main_pos_config.with_user(self.pos_user).open_ui()
        session = self.main_pos_config.current_session_id
        self.start_tour("/pos/ui/%d" % self.main_pos_config.id, 'test_l10n_be_pos_blackbox_sign_sale_backend_offline_blackbox_offline', login="pos_admin")
        # Check that the order that was attempted to be signed offline, is still in draft and has no blackbox signature
        order = self.env["pos.order"].search([('session_id', '=', session.id)])
        self.assertEqual(len(order), 1, "There should be one order.")
        self.assertFalse(order.l10n_be_short_signature)
        self.assertEqual(order.state, "draft")
        # Here the 'order' P event is not counted despite the order is synced, because P events are not awaited, and the tour finish before the P event is processed
        self._assert_session_event_counters(session, {})
        self.assertEqual(len(session.pos_clock_in_out_ids), 1)

    def test_l10n_be_pos_blackbox_be_close_session_z_reports(self):
        """ Test that closing a session generates the Z reports as PDF attachments """
        self.main_pos_config.with_user(self.pos_user).open_ui()
        current_session = self.main_pos_config.current_session_id
        self.start_tour("/pos/ui/%d" % self.main_pos_config.id, 'l10n_be_pos_blackbox_be_close_session_z_reports', login="accountman")
        pdf_attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'pos.session'),
            ('res_id', '=', current_session.id),
            ('mimetype', '=', 'application/pdf')
        ])
        self.assertEqual(len(pdf_attachments), 2, "There should be 2 PDF attachments (Sale Details and User Report).")
        self._assert_session_event_counters(current_session, {
            "N_event_counter": 1,
            "N_event_amount": 2.2,
        })
        # Two clock events (one in, one out)
        self.assertEqual(len(current_session.pos_clock_in_out_ids), 2)

    def test_l10n_be_pos_blackbox_z_report_older_session(self):
        """ Printing the Z report of an older closed session stores its reference on that session only if it had none
        yet (otherwise it is only a copy), never on the current session which will be signed and set at closing """
        z_ref = {'fdmId': 'VCB01002601', 'eventLabel': 'R', 'eventCounter': 1, 'totalCounter': 1}
        old_sessions = self.env['pos.session']
        for has_z_report in (True, False):
            self.main_pos_config.with_user(self.pos_user).open_ui()
            old_session = self.main_pos_config.current_session_id
            self.env['pos.clock.in.out'].create({'type': 'in', 'session_id': old_session.id, 'user_id': self.pos_user.id})
            # Closing from the backend does not sign the Z reports
            old_session.close_session_from_ui()
            if has_z_report:
                old_session.l10n_be_turnover_z_report_fdm_ref = z_ref
            old_sessions |= old_session
        session_with_z, session_without_z = old_sessions
        report_counter = self.main_pos_config.l10n_be_report_counter

        self.main_pos_config.with_user(self.pos_user).open_ui()
        current_session = self.main_pos_config.current_session_id
        self.start_tour("/pos/ui/%d" % self.main_pos_config.id, 'l10n_be_pos_blackbox_z_report_older_session', login="accountman")

        # The session with a Z report only got a copy, the other one its first Z report
        self.assertEqual(session_with_z.l10n_be_turnover_z_report_fdm_ref, z_ref)
        self.assertTrue(session_without_z.l10n_be_turnover_z_report_fdm_ref)
        self.assertFalse(session_without_z.l10n_be_user_z_report_fdm_ref)
        self.assertEqual(current_session.state, 'closed')
        self.assertTrue(current_session.l10n_be_turnover_z_report_fdm_ref)
        self.assertTrue(current_session.l10n_be_user_z_report_fdm_ref)
        # Turnover Z of the older session without Z + turnover Z and user Z of the current one
        self.assertEqual(self.main_pos_config.l10n_be_report_counter, report_counter + 3)
