import logging

from requests.exceptions import RequestException

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.pos_platform_order_wolt.utils import const, preorder_status
from odoo.addons.pos_platform_order_wolt.utils.wolt_request import WoltClient

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    wolt_order_type = fields.Selection([('instant', "Instant"), ('preorder', "Preorder")], string="Wolt Order Type", readonly=True, copy=False)
    wolt_self_delivery = fields.Boolean(string="Delivered by Venue", readonly=True, copy=False,
        help="Wolt order delivered by the venue's own couriers instead of Wolt couriers.")

    # Wolt can send two notifications for a new order at the same time; the second import must fail, not duplicate.
    _wolt_order_ref_uniq = models.UniqueIndex("(platform_order_ref) WHERE wolt_order_type IS NOT NULL", "This Wolt order already exists.")

    @api.model
    def _find_order_from_data(self, provider_code, notification_data, raise_if_not_found=True):
        if provider_code != const.PROVIDER_CODE:
            return super()._find_order_from_data(provider_code, notification_data, raise_if_not_found)
        order_ref = (notification_data.get('order') or {}).get('id')
        order = order_ref and self.search([('platform_order_ref', '=', order_ref), ('wolt_order_type', '!=', False)], limit=1)
        if not order and raise_if_not_found:
            raise ValidationError(self.env._("Wolt: no order found for %s.", order_ref))
        return order or self.browse()

    def _update_order_status_from_data(self, notification_data):
        self.ensure_one()
        if self.platform_order_provider_code != const.PROVIDER_CODE:
            return super()._update_order_status_from_data(notification_data)
        if self.platform_order_status in ('delivered', 'cancelled', 'failed'):
            return None

        notification_type = notification_data.get('type')
        status = notification_data['order'].get('status')
        if not (self.session_id or self.config_id.current_session_id) and (
                notification_type == 'pickup_completed.notification'
                or (notification_type == 'order.notification' and status == 'DELIVERED')):
            # Core needs a session to pay an order: the cron pays it once the POS opens.
            target = 'collected' if notification_type == 'pickup_completed.notification' else 'delivered'
            if self.platform_order_status != target:
                self._update_state(('new', 'accepted', 'driver_allocated', 'driver_arrived', 'collected'), target)
            return None
        # Notifications can arrive late or twice: a transition the order is already past is skipped.
        try:
            # Wolt sends these only after acceptance: a lost PRODUCTION must not leave the order unpaid.
            if self.platform_order_status == 'new' and (
                    notification_type in ('courier.notification', 'pickup_completed.notification')
                    or (notification_type == 'order.notification' and status in ('PRODUCTION', 'DELIVERED'))):
                self._set_accepted()
            if notification_type == 'courier.notification' and self.platform_order_status == 'accepted':
                self._set_driver_allocated()
            elif notification_type == 'pickup_completed.notification':
                if self.platform_order_status == 'accepted':
                    self._set_driver_allocated()
                self._set_collected()
            elif notification_type == 'order.notification':
                if status == 'READY':
                    if not self.platform_order_food_ready:
                        self.platform_order_food_ready = True
                        self.config_id.notify_platform_order_synchronisation(self)
                elif const.ORDER_STATUS_MAPPING.get(status) == 'delivered':
                    self._set_delivered()
                elif const.ORDER_STATUS_MAPPING.get(status) == 'cancelled':
                    self._set_cancelled()
        except UserError as error:
            _logger.info("Wolt: skipped %s %s on %s: %s", notification_type, status, self.platform_order_ref, error)
            if status == 'CANCELED':
                self.message_post(body=self.env._("Wolt cancelled this order after it was paid in "
                    "Odoo: refund it in the POS if Wolt does not pay it."))
        return None

    def _reject_order_handler(self, reason):
        if self.platform_order_provider_code != const.PROVIDER_CODE:
            return super()._reject_order_handler(reason)
        if self.platform_order_status != 'new':
            raise UserError(self.env._("Contact Wolt support to reject an order that is already accepted."))
        # Unlike core, keep the order when Wolt refuses (it may have accepted it) and let its acceptance print it.
        try:
            self._send_reject_order_request(reason)
        except UserError as error:
            self.platform_order_printed = False
            self.message_post(body=self.env._("Wolt refused the rejection: %s", error))
            raise
        self._set_cancelled(reason=reason)
        return {'success': True, 'message': self.env._("Order has been rejected successfully.")}

    def _order_status_update_handler(self, status, **kwargs):
        if status == 'delivered' and self.platform_order_provider_code == const.PROVIDER_CODE:
            return self._wolt_delivered_handler()
        return super()._order_status_update_handler(status, **kwargs)

    def _wolt_delivered_handler(self):
        """Tell Wolt a takeaway or self-delivered order reached the customer (mandatory for takeaway)."""
        self.ensure_one()
        if self.platform_order_type != 'pickup' and not self.wolt_self_delivery:
            raise UserError(self.env._("Wolt couriers report delivery themselves."))
        if not self.platform_order_food_ready:
            raise UserError(self.env._("Mark the order as ready first."))
        if self.platform_order_status not in ('accepted', 'driver_allocated', 'driver_arrived', 'collected'):
            raise UserError(self.env._("Only an accepted order that is not delivered or cancelled can be marked as delivered."))
        self._wolt_request(lambda client: client.mark_delivered(self.platform_order_ref))
        self._set_delivered()
        return {'success': True, 'message': self.env._("Order marked as delivered.")}

    def cancel_order_from_pos(self):
        """Closing a session cancels its open orders: settle what Wolt already did first, refuse an order still running at Wolt."""
        actions, wolt_statuses = {}, {}
        for order in self.filtered(lambda o: o.state == 'draft' and o.wolt_order_type):
            if order.platform_order_status in ('collected', 'delivered'):
                actions[order] = 'pay'
                continue
            try:
                data = order._wolt_request(lambda client: client.get_order(order.platform_order_ref))
            except UserError as error:
                message = self.env._("Odoo cannot check Wolt order %s, try closing the session again: %s", order.floating_order_name, error)
                raise UserError(message) from error
            wolt_status = wolt_statuses[order] = data.get('order_status')
            acceptance = (data.get('order_handling') or {}).get('acceptance_status')
            if wolt_status == 'delivered':
                actions[order] = 'deliver'
            elif wolt_status == 'rejected':
                actions[order] = 'cancel'
            elif order.platform_order_status == 'new' and (
                    preorder_status(data) == 'waiting' or (data.get('type') != 'preorder' and acceptance == 'to_be_accepted_by_venue')):
                actions[order] = 'reject'
            elif wolt_status in const.LIVE_ORDER_STATUSES:
                actions[order] = 'live'
            else:
                actions[order] = 'cancel'  # refunded, other or a status Wolt adds later: nothing will move it at Wolt
        live = [order.floating_order_name for order, action in actions.items() if action == 'live']
        if live:
            raise UserError(self.env._("Wolt order %s is still in progress at Wolt: wait until Wolt reports it delivered or cancelled, "
                "then close the session again.", ', '.join(live)))
        for order, action in actions.items():
            if action == 'deliver':
                order._update_order_status_from_data({'type': 'order.notification', 'order': {'status': 'DELIVERED'}})
            elif action == 'cancel':
                order._update_order_status_from_data({'type': 'order.notification', 'order': {'status': 'CANCELED'}})
                if wolt_statuses[order] != 'rejected':
                    order.message_post(body=self.env._("Wolt reports this order as %s: Odoo cancelled it without payment when the "
                        "session was closed.", wolt_statuses[order]))
            if action in ('pay', 'deliver') and order.state == 'draft' and not order.payment_ids:
                order.write(order._get_payment_method_values())
        # the rejects below cannot be undone at Wolt: a failing write must fail before them (transactions.md §7)
        self.env.cr.flush()
        for order, action in actions.items():
            if action == 'reject':
                order._reject_order_handler(self.env._("Cancelled when the session was closed."))
        return super().cancel_order_from_pos()

    def _get_payment_method_values(self):
        values = super()._get_payment_method_values()
        if self.platform_order_provider_code == const.PROVIDER_CODE and not self.session_id:
            values['session_id'] = self.config_id.current_session_id.id
        return values

    def _send_accept_order_request(self):
        self.ensure_one()
        if self.platform_order_provider_code != const.PROVIDER_CODE:
            return super()._send_accept_order_request()
        if self.wolt_order_type == 'preorder':
            self._wolt_request(lambda client: client.confirm_preorder(self.platform_order_ref))
        else:
            self._wolt_request(lambda client: client.accept_order(self.platform_order_ref, self.wolt_self_delivery))
        return None

    def _send_reject_order_request(self, reason):
        self.ensure_one()
        if self.platform_order_provider_code != const.PROVIDER_CODE:
            return super()._send_reject_order_request(reason)
        code = reason if reason in const.REJECT_CODES else 'GENERIC'
        # Wolt shows the reason text to the customer.
        reason_text = {
            'GENERIC': self.env._("The restaurant cannot take your order right now."),
            'ITEMS_UNAVAILABLE': self.env._("Some items are not available."),
            'VENUE_CLOSING_SOON': self.env._("The restaurant is closing soon."),
        }[code]
        self._wolt_request(lambda client: client.reject_order(self.platform_order_ref, reason_text, code))
        return None

    def _send_food_ready_request(self):
        self.ensure_one()
        if self.platform_order_provider_code != const.PROVIDER_CODE:
            return super()._send_food_ready_request()
        self._wolt_request(lambda client: client.mark_ready(self.platform_order_ref))
        return None

    def _wolt_request(self, call):
        try:
            return call(WoltClient(self.platform_order_store_id))
        except RequestException as error:
            raise UserError(self.env._("Wolt request failed: %s", error)) from error
