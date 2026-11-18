import copy
import logging

from requests.exceptions import ConnectionError as RequestsConnectionError, RequestException, Timeout

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.glovo_base.utils import const
from odoo.addons.glovo_base.utils.glovo_client import GlovoClient, GlovoRateLimitError, GlovoServerError, GlovoUnauthorizedError
from odoo.addons.pos_platform_order_glovo.const import PROVIDER_CODE

_logger = logging.getLogger(__name__)

# Values of a synced order that only the server decides for a Glovo order
SERVER_ONLY_SYNC_KEYS = ('lines', 'payment_ids', 'partner_id', 'fiscal_position_id', 'amount_total', 'amount_tax', 'amount_paid', 'amount_return')


class GlovoOrderLockedError(UserError):
    """A change to a Glovo order the user may not make; sync_from_ui keeps the server's version instead of raising."""


def changed_by(records, vals, field_names):
    """The records on which vals changes one of field_names; the POS resends unchanged values on every sync."""
    return records.filtered(lambda record: any(
        record[name] != record._fields[name].convert_to_record(record._fields[name].convert_to_cache(vals[name], record), record)
        for name in field_names if name in vals
    ))


class PosOrder(models.Model):
    _inherit = 'pos.order'

    glovo_payment_method = fields.Char(string="Glovo Payment Method", readonly=True, copy=False,
        help="As sent by Glovo: CASH (the courier pays the store in cash) or DELAYED (paid by Glovo invoice).")

    def write(self, vals):
        """Only superuser paths (Glovo's notification, the manager wizard) may cancel a Glovo order or mark it paid.

        No user action changes platform_order_status: only those paths and the framework _set_* handlers do.
        """
        if not self.env.su:
            changed_by(self, vals, ['platform_order_status'])._check_glovo_order_unchanged()
            if vals.get('state') == 'cancel':
                self._check_glovo_cancel_allowed()
            elif vals.get('state') == 'paid':
                changed_by(self, vals, ['state'])._check_glovo_order_unchanged()
        changed_by(self, vals, ['partner_id', 'fiscal_position_id'])._check_glovo_order_unchanged()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_glovo_not_cancelled(self):
        self._check_glovo_cancel_allowed()

    def _check_glovo_cancel_allowed(self):
        """Glovo has no API for the store to refuse an order: only Glovo's cancelled notification may cancel it."""
        if self.filtered(lambda o: o.platform_order_provider_code == PROVIDER_CODE and o.platform_order_status != 'cancelled'):
            raise GlovoOrderLockedError(_("Glovo orders can't be cancelled here. Refuse the order in the Glovo Partner Webapp or via Glovo support."))

    def _check_glovo_order_unchanged(self):
        """Glovo pays the store: only Glovo's notifications and the manager actions, both superuser, may change its orders."""
        if not self.env.su and self.filtered(lambda o: o.platform_order_provider_code == PROVIDER_CODE):
            raise GlovoOrderLockedError(_("Glovo orders can't be changed or paid in the POS. Glovo pays the store when the courier picks up the "
                "order."))

    def _check_glovo_manager_only(self):
        """Refunding a Glovo order and deleting its payments stay available to POS managers, as a repair tool."""
        glovo_orders = self.filtered(lambda o: o.platform_order_provider_code == PROVIDER_CODE)
        if not self.env.su and glovo_orders and not glovo_orders._is_glovo_pos_manager():
            raise GlovoOrderLockedError(_("Only a POS manager can refund a Glovo order or delete its payments."))

    def _is_glovo_pos_manager(self):
        """With pos_hr, the employee logged in on the POS decides, not the Odoo user the POS device runs as.

        The manager roles mirror pos_hr's hr.employee._load_pos_data_read.
        """
        employee_id = self.env.context.get('current_cashier_id')
        if not employee_id or not all(self.config_id.mapped('module_pos_hr')):
            return self.env.user.has_group('point_of_sale.group_pos_manager')
        employee = self.env['hr.employee'].sudo().browse(employee_id)
        return all(
            employee in config.manager_employee_ids or config.group_pos_manager_id in employee.user_id.all_group_ids
            for config in self.config_id.sudo()
        )

    @api.model
    def _process_order(self, order, existing_order):
        return self._sync_keeping_glovo_server_version(super()._process_order, order, existing_order)

    def process_saved_payments(self, order, existing_order):
        return self._sync_keeping_glovo_server_version(super().process_saved_payments, order, existing_order)

    @api.model
    def _sync_keeping_glovo_server_version(self, sync_step, order, existing_order):
        """Apply a POS sync step; when it would change a Glovo order, keep the server's version and log it.

        Raising would fail the whole sync batch, so the cashier's normal sales would stop syncing too.
        """
        if self.env.su or not existing_order or existing_order.platform_order_provider_code != PROVIDER_CODE:
            return sync_step(order, existing_order)
        client_order = copy.deepcopy(order)
        try:
            with self.env.cr.savepoint():
                return sync_step(order, existing_order)
        except GlovoOrderLockedError as error:
            _logger.warning("Glovo: order %s: kept the server's version, dropped the POS changes (%s).", existing_order.platform_order_ref, error)
        server_order = {key: value for key, value in client_order.items() if key not in SERVER_ONLY_SYNC_KEYS}
        server_order['state'] = existing_order.state
        return sync_step(server_order, existing_order)

    def _reject_order_handler(self, reason):
        if self.platform_order_provider_code == PROVIDER_CODE:
            raise UserError(_("Refuse the order in the Glovo Partner Webapp or via Glovo support."))
        return super()._reject_order_handler(reason)

    @api.model
    def _find_order_from_data(self, provider_code, notification_data, raise_if_not_found=True):
        if provider_code != PROVIDER_CODE:
            return super()._find_order_from_data(provider_code, notification_data, raise_if_not_found)

        order_ref = str(notification_data['order_id'])
        order = self.search([('platform_order_ref', '=', order_ref), ('platform_order_provider_code', '=', PROVIDER_CODE)], limit=1)
        if not order and raise_if_not_found:
            raise UserError(_("Glovo: no order found matching order ID %s.", order_ref))
        return order

    def _update_order_status_from_data(self, notification_data):
        """Only the cancelled body carries cancel_reason; a picked-up order already cancelled or paid is refused."""
        self.ensure_one()
        if self.platform_order_provider_code != PROVIDER_CODE:
            return super()._update_order_status_from_data(notification_data)

        if 'cancel_reason' in notification_data:
            self._set_cancelled(notification_data['cancel_reason'])
        elif self.state == 'cancel' or self.platform_order_status == 'cancelled':
            raise UserError(_("Glovo: order %s was picked up by the courier but is cancelled in Odoo. Check it in the Glovo Partner Webapp.",
                self.platform_order_ref))
        elif self.payment_ids:
            raise UserError(_("Order already paid in Odoo; check it manually"))
        else:
            self._set_delivered()
        return None

    def _get_payment_method_values(self):
        """Glovo books the total recomputed from its locked lines, not a stored amount_total a cashier could write.

        A CASH order is paid by the courier at pickup, so it is booked on the register's cash method.
        """
        is_glovo = self.platform_order_provider_code == PROVIDER_CODE
        if is_glovo:
            self._compute_prices()
        values = super()._get_payment_method_values()
        if is_glovo and self.glovo_payment_method == 'CASH':
            if not (cash_method := self.config_id._get_cash_payment_method()):
                raise UserError(_("Add a cash payment method to %s for Glovo CASH orders.", self.config_id.name))
            values['payment_ids'] = [Command.create({'payment_method_id': cash_method.id, 'amount': self.amount_total})]
        return values

    def _send_food_ready_request(self):
        self.ensure_one()
        if self.platform_order_provider_code != PROVIDER_CODE:
            return super()._send_food_ready_request()
        self._glovo_call('ready_for_pickup', "Glovo: failed to mark order %s ready for pickup: %s",
            _("Glovo couldn't mark this order ready. Check the order in the Glovo Partner Webapp or ask a POS manager."))
        return None

    def _glovo_call(self, call, log_message, generic_message):
        """Send a call of this order to Glovo; a failure becomes the one sentence the cashier reads."""
        # sudo: the token is restricted to POS managers, the cashier acts on the order
        provider_sudo = self.platform_order_provider_id.sudo()
        base_url = const.STAGE_BASE_URL if provider_sudo.state == 'test' else const.PRODUCTION_BASE_URL
        try:
            getattr(GlovoClient(base_url, provider_sudo.glovo_token), call)(self.platform_order_ref, self.platform_order_store_id.external_id)
        except RequestException as error:
            # the technical detail is for the log only; the cashier gets what to do
            _logger.error(log_message, self.platform_order_ref, error)
            if isinstance(error, GlovoUnauthorizedError):
                message = _("Glovo refused the store's token. Ask a POS manager to check the Glovo token.")
            elif isinstance(error, (GlovoRateLimitError, GlovoServerError, Timeout, RequestsConnectionError)):
                message = _("Glovo isn't responding. Try again in a minute.")
            else:
                message = generic_message
            raise UserError(message) from error

    def _order_status_update_handler(self, status, **kwargs):
        if status != 'customer_picked_up' or self.platform_order_provider_code != PROVIDER_CODE:
            return super()._order_status_update_handler(status, **kwargs)
        if self.platform_order_type != 'pickup' or self.state != 'draft' or self.platform_order_status == 'cancelled':
            raise UserError(_("Only an order the customer collects at the store can be marked picked up by the customer."))
        # the payment is booked first and rolled back when Glovo refuses; the irreversible call goes last
        with self.env.cr.savepoint():
            # sudo: Glovo orders change only on superuser paths; this books the payment as Glovo's picked-up notification does
            self.sudo()._set_delivered()
            self.env.cr.flush()
            self._glovo_call('customer_picked_up', "Glovo: failed to mark order %s picked up by the customer: %s",
                _("Glovo couldn't mark this order picked up. Check the order in the Glovo Partner Webapp or ask a POS manager."))
        return {'success': True, 'message': _("The customer picked up the order; the sale is booked.")}

    def _food_ready_handler(self):
        """A Glovo order already marked ready counts as success: the preparation display's Done may mark it again."""
        if self.platform_order_provider_code == PROVIDER_CODE and self.platform_order_food_ready:
            return {'success': True, 'message': _("Food is already marked as ready for pickup.")}
        return super()._food_ready_handler()

    @api.model
    def _load_pos_preparation_data_fields(self):
        return super()._load_pos_preparation_data_fields() + ['platform_order_provider_code']

    def _send_accept_order_request(self):
        """Glovo orders are created accepted; Glovo needs no acceptance call for courier orders."""
        self.ensure_one()
        if self.platform_order_provider_code != PROVIDER_CODE:
            return super()._send_accept_order_request()
        return None
