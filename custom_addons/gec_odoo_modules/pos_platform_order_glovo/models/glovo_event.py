import json
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain
from odoo.sql_db import PG_CONCURRENCY_EXCEPTIONS_TO_RETRY

from odoo.addons.pos_platform_order_glovo.const import PROVIDER_CODE

_logger = logging.getLogger(__name__)


class GlovoEvent(models.Model):
    _inherit = 'glovo.event'

    # no check_company: the order belongs to the POS's company, which may be a branch of the event's company
    order_id = fields.Many2one('pos.order', string="POS Order", readonly=True, index='btree_not_null')

    def action_retry(self):
        """Reprocess the stored payloads as if Glovo resent them; POS managers repair failed events with it."""
        self.check_access('read')
        if not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_("Only a POS manager can retry Glovo events."))
        # sudo: POS managers only read events; the webhook applies them as superuser too
        events_sudo = self.sudo()
        if events_sudo.try_lock_for_update() != events_sudo:
            raise UserError(_("This event is being processed right now. Try again in a moment."))
        if self.filtered(lambda event: event.state == 'processed'):
            raise UserError(_("Processed Glovo events can't be retried."))
        events_sudo._retry_notifications()

    def _retry_notifications(self):
        for event_sudo in self.sorted('id'):
            try:
                data = json.loads(event_sudo.payload)
                stores_sudo = self.env['platform.order.entity'].sudo()._find_store_from_data(PROVIDER_CODE, data)
            except (TypeError, ValueError, ValidationError) as error:
                event_sudo.write({'state': 'failed', 'error': str(error)})
                continue
            store_sudo = stores_sudo.filtered(lambda store: store.company_id == event_sudo.company_id)[:1]
            if not store_sudo:
                event_sudo.write({'state': 'failed', 'error': _("Glovo: no store found matching ID %s.", data['store_id'])})
                continue
            event_sudo._process_notification(store_sudo, data)

    @api.model
    def _cron_retry_failed_events(self):
        """Glovo retries a notification only 3 times; failed ones are retried here while recent."""
        hours = self.env['ir.config_parameter'].sudo().get_int('pos_platform_order_glovo.event_retry_hours', 24)
        # sudo: one run serves every company's stores and events, whatever user the cron runs as
        stores = self.env['platform.order.entity'].sudo().search([
            ('provider_code', '=', PROVIDER_CODE),
            ('provider_id.state', '!=', 'disabled'),
        ]).filtered('config_id.current_session_id')
        stores_domain = Domain.OR(Domain('store_external_id', '=', store.external_id) & Domain('company_id', '=', store.company_id.id)
            for store in stores)
        events = self.sudo().search(Domain([
            ('state', '=', 'failed'),
            ('create_date', '>=', fields.Datetime.now() - timedelta(hours=hours)),
        ]) & stores_domain, order='id')
        self.env['ir.cron']._commit_progress(remaining=len(events))
        for event in events:
            event._retry_notifications()
            if not self.env['ir.cron']._commit_progress(1):
                break

    def _process_notification(self, store_sudo, data):
        """Apply a Glovo notification once; a failure is stored on the event so the webhook still answers 200."""
        self.ensure_one()
        if not self.try_lock_for_update():
            _logger.info("Glovo: %s event of order %s is locked; skipped.", self.event_type, self.glovo_order_id)
            return
        if self.state == 'processed':
            return
        if store_sudo.provider_id.state == 'disabled':
            _logger.warning("Glovo: %s of order %s skipped: provider disabled.", self.event_type, self.glovo_order_id)
            self.write({'state': 'failed', 'error': _("Glovo provider is disabled")})
            return
        self.write({'state': 'received', 'error': False})
        try:
            with self.env.cr.savepoint():
                self._apply_notification(store_sudo, data)
        except PG_CONCURRENCY_EXCEPTIONS_TO_RETRY:
            raise
        except Exception as error:  # noqa: BLE001 - any failure is recorded on the event
            _logger.exception("Glovo: failed to process %s event for order %s.", self.event_type, self.glovo_order_id)
            self.write({'state': 'failed', 'error': str(error)})
        else:
            if self.state == 'received':
                self.state = 'processed'
        order = self.env['pos.order'].search([('platform_order_ref', '=', self.glovo_order_id), ('platform_order_store_id', '=', store_sudo.id)],
            limit=1)
        if order and order != self.order_id:
            self.order_id = order

    def _apply_notification(self, store_sudo, data):
        order_sudo = self.env['pos.order'].sudo()._find_order_from_data(PROVIDER_CODE, data, raise_if_not_found=self.event_type != 'dispatched')
        if order_sudo and order_sudo.platform_order_store_id != store_sudo:
            raise UserError(_("Glovo: order %s belongs to another store.", self.glovo_order_id))
        if self.event_type != 'dispatched':
            order_sudo._update_order_status_from_data(data)
        elif not order_sudo and store_sudo._create_order_from_data(data):
            # Glovo guarantees no event order: apply the updates that failed before this order existed
            pending = self.search([
                ('glovo_order_id', '=', self.glovo_order_id),
                ('event_type', '!=', 'dispatched'),
                ('state', '!=', 'processed'),
                ('company_id', '=', self.company_id.id),
                ('store_external_id', '=', store_sudo.external_id),
            ], order='id')
            for event in pending:
                event._process_notification(store_sudo, json.loads(event.payload))
