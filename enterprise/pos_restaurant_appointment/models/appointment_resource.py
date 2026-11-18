# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import timezone

from odoo import fields, models, api
from odoo.fields import Domain


class AppointmentResource(models.Model):
    _name = 'appointment.resource'
    _inherit = ['appointment.resource', 'pos.load.mixin']

    # this should be one2one
    pos_table_ids = fields.One2many('restaurant.table', 'appointment_resource_id', string='POS Table')
    is_used = fields.Json("Is Used", compute='_compute_is_used', help="Indicates if the resource is currently used in a calendar event for the given date range.", readonly=False)

    @api.model
    def _load_pos_data_domain(self, data):
        if not data['pos.config'].module_pos_restaurant:
            return False

        return [('pos_table_ids', 'in', data['restaurant.table'].ids)]

    @api.model
    def _load_pos_data_dependencies(self):
        return ['restaurant.table']

    @api.model
    def _load_pos_data_fields(self, config):
        return ['pos_table_ids', 'capacity']

    @api.depends_context('start_date', 'stop_date')
    def _compute_is_used(self):
        """ Find the booking occupying each resource during the start_date/stop_date slot of the context:
        the earliest overlapping one that is not cancelled, no-show, or already over without being checked in. """
        self.is_used = {}
        start = fields.Datetime.to_datetime(self.env.context.get('start_date'))
        stop = fields.Datetime.to_datetime(self.env.context.get('stop_date'))
        if not start or not stop:
            return
        now = fields.Datetime.now()
        occupying_domain = Domain('stop', '>', max(start, now))
        if start < now:
            start_of_day = fields.Datetime.context_timestamp(self, start).replace(hour=0, minute=0, second=0)
            occupying_domain |= Domain([
                ('appointment_status', '=', 'attended'),
                ('start', '>=', start_of_day.astimezone(timezone.utc).replace(tzinfo=None)),
            ])
        events = self.env['calendar.event'].search(Domain([
            ('appointment_resource_ids', 'in', self.ids),
            ('appointment_status', 'not in', ('cancelled', 'no_show')),
            ('start', '<', stop),
        ]) & occupying_domain, order='start')
        for resource in self:
            event = events.filtered(lambda e: resource in e.appointment_resource_ids)[:1]
            if event:
                resource.is_used = {
                    'event_start': fields.Datetime.to_string(event.start),
                    'event_stop': fields.Datetime.to_string(event.stop),
                    'capacity': event.waiting_list_capacity,
                    'event_id': event.id,
                    'total_capacity': sum(event.resource_ids.mapped('capacity')),
                }

    @api.depends('capacity')
    def _compute_display_name(self):
        if not self.env.context.get('from_pos_booking'):
            return super()._compute_display_name()
        for resource in self:
            resource_name_capacity = f"{resource.name} 🪑{resource.capacity}"
            display_name = resource_name_capacity if resource.capacity > 1 else resource.name
            resource.display_name = display_name
