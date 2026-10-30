from odoo.addons.pos_self_order.controllers.orders import PosSelfOrderController
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import consteq
from werkzeug.exceptions import Unauthorized


class L10nBePosBlackboxController(PosSelfOrderController):

    def _verify_pos_config_l10n_be_blackbox(self, access_token):
        pos_config = super()._verify_pos_config(access_token)
        # These routes are only used by a kiosk signing with its own blackbox
        if not pos_config.l10n_be_blackbox_be_id or pos_config.self_ordering_mode != 'kiosk':
            raise Unauthorized("Invalid access token")
        return pos_config

    def _verify_pos_session_l10n_be_blackbox(self, access_token, session_id):
        pos_config = self._verify_pos_config_l10n_be_blackbox(access_token)
        session = pos_config.env['pos.session'].sudo().search([
            ('id', '=', int(session_id)),
            ('config_id', '=', pos_config.id),
        ], limit=1)
        if not session:
            raise Unauthorized("Invalid session")
        return pos_config, session

    @http.route('/l10n_be_pos_blackbox_self_order/clock', auth='public', type='jsonrpc')
    def l10n_be_pos_blackbox_self_order_clock(self, access_token, config_id, session_id, clock_in=True):
        pos_config, session = self._verify_pos_session_l10n_be_blackbox(access_token, session_id)
        default_user = pos_config.self_ordering_default_user_id
        if clock_in:
            session.l10n_be_users_clocked_ids |= default_user
            session._create_clock_events(default_user, 'in')
        else:
            session.l10n_be_users_clocked_ids -= default_user
            session._create_clock_events(default_user, 'out')
        return {'success': True}

    @http.route('/l10n_be_pos_blackbox_self_order/handle_blackbox_signature', auth='public', type='jsonrpc')
    def l10n_be_pos_blackbox_self_order_handle_blackbox_signature(self, access_token, config_id, session_id, payload):
        _pos_config, session = self._verify_pos_session_l10n_be_blackbox(access_token, session_id)
        session.handle_blackbox_signature(payload)
        return {'success': True}

    @http.route('/l10n_be_pos_blackbox_self_order/get_sale_details', auth='public', type='jsonrpc')
    def l10n_be_pos_blackbox_self_order_get_sale_details(self, access_token, config_id, session_id):
        pos_config, session = self._verify_pos_session_l10n_be_blackbox(access_token, session_id)
        sale_details = pos_config.env['report.point_of_sale.report_saledetails'].sudo().get_sale_details(
            False, False, False, session.ids, before_closing=True
        )
        return sale_details

    @http.route('/l10n_be_pos_blackbox_self_order/get_l10n_be_user_report_data', auth='public', type='jsonrpc')
    def l10n_be_pos_blackbox_self_order_get_l10n_be_user_report_data(self, access_token, config_id, session_id):
        _pos_config, session = self._verify_pos_session_l10n_be_blackbox(access_token, session_id)
        return session.get_l10n_be_user_report_data(True)

    @http.route('/l10n_be_pos_blackbox_self_order/generate_l10n_z_reports_attachments', auth='public', type='jsonrpc')
    def l10n_be_pos_blackbox_self_order_generate_l10n_z_reports_attachments(self, access_token, config_id, session_id, sale_details, user_report_data):
        _pos_config, session = self._verify_pos_session_l10n_be_blackbox(access_token, session_id)
        # The kiosk generates the Z reports once its session is closed, and only once
        session.lock_for_update(allow_referencing=True)
        if session.state != 'closed' or session.l10n_be_reports_generated:
            raise UserError(request.env._("The Z reports of this session can't be generated."))
        session.generate_l10n_z_reports_attachments(sale_details, user_report_data)
        return {'success': True}

    @http.route('/l10n_be_pos_blackbox_self_order/save_order_signature', auth='public', type='jsonrpc')
    def l10n_be_pos_blackbox_self_order_save_order_signature(self, access_token, order_id, order_access_token, signature_data):
        pos_config = self._verify_pos_config_l10n_be_blackbox(access_token)
        allowed_fields = {
            'l10n_be_short_signature', 'l10n_be_event_label', 'l10n_be_event_counter',
            'l10n_be_total_counter', 'l10n_be_fdm_id', 'l10n_be_fdm_date_time',
            'l10n_be_pos_id', 'l10n_be_terminal_id', 'l10n_be_device_id',
            'l10n_be_verification_url', 'l10n_be_pos_date_time', 'l10n_be_vat_calc',
            'l10n_be_footer',
        }
        safe_data = {k: v for k, v in signature_data.items() if k in allowed_fields}
        # An already signed order can't be signed again
        order = request.env['pos.order'].sudo().search([
            ('id', '=', int(order_id)),
            ('config_id', '=', pos_config.id),
            ('l10n_be_short_signature', '=', False),
        ], limit=1)
        if order and consteq(order.access_token, order_access_token) and safe_data:
            order.write(safe_data)
        return {'success': True}
