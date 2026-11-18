import datetime

from requests.exceptions import RequestException

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

from odoo.addons.pos_wolt_drive.utils.drive_request import DriveClient

# Wolt Drive event -> courier status; the rank stops late events from moving a delivery backwards.
EVENT_STATUS = {
    'order.pickup_started': 'courier_assigned',
    'order.pickup_arrival': 'courier_at_pickup',
    'order.picked_up': 'picked_up',
    'order.dropoff_started': 'picked_up',
    'order.dropoff_arrival': 'picked_up',
    'order.dropoff_completed': 'delivered',
    'order.delivered': 'delivered',
    'order.not_delivered': 'not_delivered',
    'order.customer_no_show': 'not_delivered',
    'order.rejected': 'cancelled',
}
STATUS_RANK = (
    'requested', 'courier_assigned', 'courier_at_pickup', 'picked_up', 'delivered', 'not_delivered', 'cancelled',
)
FINAL_STATUSES = ('delivered', 'not_delivered', 'cancelled')


class PosOrder(models.Model):
    _inherit = 'pos.order'

    wolt_drive_ref = fields.Char(string="Wolt Drive Reference", readonly=True, copy=False, index='btree_not_null')
    wolt_drive_attempt = fields.Integer(readonly=True, copy=False)
    wolt_drive_status = fields.Selection([
        ('requested', "Courier Requested"),
        ('courier_assigned', "Courier on the Way"),
        ('courier_at_pickup', "Courier Arrived"),
        ('picked_up', "Picked Up"),
        ('delivered', "Delivered"),
        ('not_delivered', "Not Delivered"),
        ('cancelled', "Cancelled"),
    ], string="Wolt Courier Status", readonly=True, copy=False)
    wolt_drive_tracking_url = fields.Char(string="Wolt Tracking Link", readonly=True, copy=False)
    wolt_drive_price = fields.Monetary(string="Wolt Delivery Price", readonly=True, copy=False)
    wolt_drive_pickup_eta = fields.Datetime(string="Courier Pickup ETA", readonly=True, copy=False)
    wolt_drive_dropoff_eta = fields.Datetime(string="Delivery ETA", readonly=True, copy=False)

    def wolt_drive_quote(self):
        self.ensure_one()
        self._wolt_drive_check_can_book()
        partner = self.partner_id
        payload = {
            'street': ' '.join(filter(None, [partner.street, partner.street2])),
            'city': partner.city or '',
            'post_code': partner.zip or '',
            'min_preparation_time_minutes': self.config_id.wolt_drive_preparation_minutes,
            'parcels': [self._wolt_drive_parcel()],
        }
        promise = self._wolt_drive_request(lambda client: client.shipment_promise(payload))
        if not promise.get('is_binding'):
            raise UserError(self.env._("Add the customer's street and city or zip so Wolt can price the delivery."))
        return {
            'promise_id': promise['id'],
            'dropoff_location': promise['dropoff']['location'],
            'price': self._wolt_drive_amount(promise['price']),
            'eta_minutes': promise['dropoff'].get('eta_minutes'),
        }

    def wolt_drive_book(self, promise_id, dropoff_location):
        """Book the Wolt courier from a binding promise returned by wolt_drive_quote."""
        self.ensure_one()
        self._wolt_drive_check_can_book()
        partner = self.partner_id
        retry = self.wolt_drive_status == 'requested'
        attempt = self.wolt_drive_attempt + (0 if retry else 1)
        reference = f'{self.pos_reference}-{attempt}'
        payload = {
            'shipment_promise_id': promise_id,
            'dropoff': {'location': dropoff_location},
            'recipient': {'name': partner.name, 'phone_number': partner._phone_format(fname='phone') or partner.phone},
            'parcels': [self._wolt_drive_parcel()],
            # A retry after a timeout reuses the reference, so Wolt answers DUPLICATE_ORDER instead of a second courier.
            'merchant_order_reference_id': reference,
            'order_number': self.tracking_number,
        }
        if partner.email:
            payload['recipient']['email'] = partner.email
        if self.general_customer_note:
            payload['dropoff']['comment'] = self.general_customer_note
        self.env.cr.flush()
        try:
            response = DriveClient(self.config_id).create_delivery(payload)
            unconfirmed = response.status_code >= 500 or self._wolt_drive_error(response).get('error_code') == 'DUPLICATE_ORDER'
        except RequestException:
            unconfirmed = True
        if unconfirmed:
            self.write({
                'wolt_drive_status': 'requested',
                'wolt_drive_attempt': attempt,
                'wolt_drive_ref': False,
                'wolt_drive_tracking_url': False,
                'wolt_drive_price': False,
                'wolt_drive_pickup_eta': False,
                'wolt_drive_dropoff_eta': False,
            })
            self.message_post(body=self.env._(
                "Wolt did not confirm the courier request %s yet: press Wolt Courier again to check, "
                "Wolt will not book a second courier for it.", reference))
            return False
        delivery = self._wolt_drive_result(response)
        self.write({
            'wolt_drive_ref': delivery['wolt_order_reference_id'],
            'wolt_drive_attempt': attempt,
            'wolt_drive_status': 'requested',
            'wolt_drive_tracking_url': (delivery.get('tracking') or {}).get('url'),
            'wolt_drive_price': self._wolt_drive_amount(delivery['price']) if delivery.get('price') else False,
            'wolt_drive_pickup_eta': self._wolt_drive_datetime((delivery.get('pickup') or {}).get('eta')),
            'wolt_drive_dropoff_eta': self._wolt_drive_datetime((delivery.get('dropoff') or {}).get('eta')),
        })
        url = self.wolt_drive_tracking_url
        self.message_post(body=self.env._("Wolt courier booked: %s", url) if url else self.env._("Wolt courier booked."))
        return True

    def wolt_drive_cancel(self):
        """Cancel the courier; Wolt allows it only until the courier starts the pickup."""
        self.ensure_one()
        if self.wolt_drive_status != 'requested':
            raise UserError(self.env._("Contact Wolt support to cancel: the courier is already on the way."))
        if not self.wolt_drive_ref:
            raise UserError(self.env._("Wolt has not confirmed this courier yet: wait for its status update."))
        reason = self.env._("Cancelled by the merchant")
        self._wolt_drive_request(lambda client: client.cancel(self.wolt_drive_ref, reason))
        self.wolt_drive_status = 'cancelled'
        self.message_post(body=self.env._("Wolt courier cancelled."))
        return True

    def _wolt_drive_check_can_book(self):
        if self.state not in ('paid', 'done') or self.is_refund_or_negative():
            raise UserError(self.env._("Only a paid sale can get a Wolt courier."))
        if not self.config_id.wolt_drive_venue_id:
            raise UserError(self.env._("Wolt Drive is not set up for this Point of Sale."))
        if not self.config_id.wolt_drive_webhook_ready:
            raise UserError(self.env._("Wolt Drive status updates are not set up: ask an administrator to register the status webhook."))
        status = self.wolt_drive_status
        if status == 'delivered':
            raise UserError(self.env._("This order was already delivered by Wolt."))
        if status and status not in FINAL_STATUSES and (status != 'requested' or self.wolt_drive_ref):
            raise UserError(self.env._("A Wolt courier is already booked for this order."))
        if not self.partner_id.phone or not (self.partner_id.street and (self.partner_id.city or self.partner_id.zip)):
            raise UserError(self.env._("The customer needs a phone number, a street and a city or zip."))

    def _wolt_drive_parcel(self):
        currency = self.currency_id
        return {
            'description': self.pos_reference,
            'identifier': self.tracking_number,
            'count': 1,
            'price': {'amount': round(self.amount_total * 10 ** currency.decimal_places), 'currency': currency.name},
        }

    def _wolt_drive_amount(self, money):
        return money['amount'] / 10 ** self.currency_id.decimal_places

    @api.model
    def _wolt_drive_datetime(self, value):
        return isinstance(value, str) and datetime.datetime.fromisoformat(value).astimezone(datetime.UTC).replace(tzinfo=None)

    def _wolt_drive_request(self, call):
        try:
            return self._wolt_drive_result(call(DriveClient(self.config_id)))
        except RequestException as error:
            raise UserError(self.env._("Wolt Drive cannot be reached: %s", error)) from error

    def _wolt_drive_error(self, response):
        try:
            return response.json()
        except ValueError:
            return {}

    def _wolt_drive_result(self, response):
        if response.ok:
            return response.json()
        error = self._wolt_drive_error(response)
        detail = error.get('detail')
        if isinstance(detail, list):
            detail = '; '.join(item['msg'] for item in detail)
        message = error.get('reason') or detail or response.text[:300]
        if error.get('error_code') == 'SHIPMENT_PROMISE_NOT_FOUND':
            message = self.env._("The price expired: press Wolt Courier again.")
        raise UserError(self.env._("Wolt Drive: %s %s", error.get('error_code', response.status_code), message))

    @api.model
    def _wolt_drive_handle_event(self, event, config):
        """Apply a verified Wolt Drive event to its order in the company of `config`."""
        details = event.get('details') or {}
        if not (ref := details.get('wolt_order_reference_id')):
            return
        domain = [('wolt_drive_ref', '=', ref), ('company_id', '=', config.company_id.id)]
        order = self.search(domain, limit=1) or self._wolt_drive_relink(details, config.company_id)
        if not order or order.wolt_drive_status in FINAL_STATUSES:
            return
        values = {}
        if pickup_eta := (details.get('pickup') or {}).get('eta'):
            values['wolt_drive_pickup_eta'] = self._wolt_drive_datetime(pickup_eta)
        if dropoff_eta := ((details.get('dropoff') or {}).get('eta') or {}).get('max'):
            values['wolt_drive_dropoff_eta'] = self._wolt_drive_datetime(dropoff_eta)
        status = EVENT_STATUS.get(event.get('type'))
        if status and STATUS_RANK.index(status) > STATUS_RANK.index(order.wolt_drive_status or 'requested'):
            values['wolt_drive_status'] = status
        if values:
            order.write(values)
            if 'wolt_drive_status' in values:
                label = dict(self._fields['wolt_drive_status']._description_selection(self.env))[status]
                order.message_post(body=self.env._("Wolt courier: %s", label))
            order.config_id._notify('WOLT_DRIVE_UPDATE', {'order_id': order.id})

    @api.model
    def _wolt_drive_relink(self, details, company):
        """Find the order of a delivery Wolt accepted while the booking was rolled back in Odoo."""
        pos_reference, _sep, attempt = (details.get('merchant_order_reference_id') or '').rpartition('-')
        if not (pos_reference and attempt.isdigit() and details.get('venue_id')):
            return self.browse()
        domain = Domain([
            ('company_id', '=', company.id),
            ('pos_reference', '=', pos_reference),
            ('config_id.wolt_drive_venue_id', '=', details['venue_id']),
        ])
        unlinked = Domain('wolt_drive_attempt', '=', int(attempt)) & Domain('wolt_drive_ref', '=', False)
        order = self.search(domain & (Domain('wolt_drive_attempt', '<', int(attempt)) | unlinked), limit=1)
        if order:
            order.write({
                'wolt_drive_ref': details['wolt_order_reference_id'],
                'wolt_drive_attempt': int(attempt),
                'wolt_drive_status': 'requested',
                'wolt_drive_price': order._wolt_drive_amount(details['price']) if details.get('price') else False,
                'wolt_drive_tracking_url': False,
                'wolt_drive_pickup_eta': False,
                'wolt_drive_dropoff_eta': False,
            })
            order.message_post(body=self.env._("Wolt courier linked from a Wolt status update."))
        return order
