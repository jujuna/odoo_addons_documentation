# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict

from odoo import api, models, fields, Command


class CalendarEvent(models.Model):
    _name = 'calendar.event'
    _inherit = 'calendar.event'

    available_capacity = fields.Integer(string="Available Capacity", compute='_compute_available_capacity', help="Used to determine current total available capacity")
    is_conflicted = fields.Boolean(string="Is Conflicted", compute='_compute_is_conflicted')

    @api.depends('appointment_type_id.resource_ids', 'appointment_type_id.meeting_ids', 'start', 'stop')
    def _compute_available_capacity(self):
        for record in self:
            appointment_type = record.appointment_type_id
            if not appointment_type or not record.start or not record.stop:
                record.available_capacity = 0
                continue
            occupied_resources = self.env['appointment.booking.line'].search([
                ('appointment_resource_id', 'in', appointment_type.resource_ids.ids),
                ('calendar_event_id', '!=', record._origin.id),
                ('calendar_event_id.appointment_status', 'not in', ('cancelled', 'no_show')),
                ('event_start', '<', record.stop),
                ('event_stop', '>', record.start),
            ]).appointment_resource_id
            record.available_capacity = appointment_type.resource_total_capacity - sum(occupied_resources.mapped('capacity'))

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ['available_capacity']

    @api.model
    def _send_table_notifications(self, command):
        today = fields.Date.context_today(self)
        config_events_map = defaultdict(lambda: self.env['calendar.event'])

        for event in self:
            # Don't include the event if it's not for today
            if event.start.date() != today:
                continue

            # tables that are booked for this event
            event_table_ids = event.booking_line_ids.appointment_resource_id.sudo().pos_table_ids
            configs = event_table_ids.mapped('floor_id.pos_config_ids')

            for config in configs:
                if (
                    config.current_session_id
                    and config.appointment_type_id
                    and config.appointment_type_id.id == event.appointment_type_id.id
                ):
                    config_events_map[config] |= event

        for config, events in config_events_map.items():
            config._notify((
                'TABLE_BOOKING',
                {
                    'command': command,
                    'data': {
                        'calendar.event': self._load_pos_data_read(events, config),
                        'res.partner': self.env['res.partner']._load_pos_data_read(events.partner_ids, config),
                    },
                },
            ))

    @api.model_create_multi
    def create(self, vals_list):
        new_events = super().create(vals_list)
        new_events._send_table_notifications("ADDED")
        return new_events

    def write(self, vals):
        self._send_table_notifications("REMOVED")
        events_removed_all_resources = []
        is_from_pos = self.env.context.get('from_pos_booking')

        if is_from_pos and 'resource_ids' in vals:
            resources_to_remove = {
                r[1] for r in vals['resource_ids']
                if isinstance(r, (list, tuple)) and r[0] == Command.UNLINK
            } if vals.get('resource_ids', []) else set()
            for event in self:
                if resources_to_remove:
                    event.booking_line_ids.filtered(lambda l: l.appointment_resource_id.id in resources_to_remove).unlink()
                elif not vals['resource_ids']:
                    event.booking_line_ids.unlink()
                if not event.booking_line_ids:
                    events_removed_all_resources.append(event.id)
        result = super().write(vals)
        booking_lines = []

        if is_from_pos and vals.get('resource_ids'):
            for event in self.filtered(lambda e: e.id not in events_removed_all_resources):
                resources = event._get_event_resources()
                event.booking_line_ids.unlink()
                booking_lines.extend([
                    {
                        'appointment_resource_id': resource.id,
                        'calendar_event_id': event.id,
                        'capacity_reserved': resource.capacity,
                    } for resource in resources
                ])
            if booking_lines:
                self.env['appointment.booking.line'].sudo().create(booking_lines)
        self._send_table_notifications("ADDED")
        return result

    def unlink(self):
        self._send_table_notifications("REMOVED")
        return super().unlink()

    @api.model
    def _appointment_resource_domain(self, data):
        if data['pos.config'].module_pos_restaurant:
            return [
                ('booking_line_ids.appointment_resource_id', 'in', data['restaurant.table'].appointment_resource_id.ids)
            ]
        else:
            return super()._appointment_resource_domain(data)

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        if (
            'waiting_list_capacity' in fields
            and self.env.context.get('from_pos_booking')
            and (default_resource_ids := self.env.context.get('default_resource_ids'))
        ):
            res['waiting_list_capacity'] = sum(self.env['appointment.resource'].browse(default_resource_ids).mapped('capacity'))
        return res

    @api.onchange('waiting_list_capacity')
    def _onchange_waiting_list_capacity(self):
        for event in self:
            event.resource_ids = event._get_event_resources()

    def _get_event_resources(self):
        self.ensure_one()
        appointment_type = self.appointment_type_id
        if not appointment_type or not self.start or not self.stop:
            return self.env['appointment.resource']
        appointment_type = appointment_type.with_context(ignore_event_ids=self.ids)
        default_resources = self.env['appointment.resource'].browse(self.env.context.get('default_resource_ids') or [])
        required_resources = default_resources & self.resource_ids._origin
        if required_resources:
            remaining_capacity = self.waiting_list_capacity - sum(required_resources.mapped('capacity'))
            candidate_resources = appointment_type.resource_ids - required_resources
            # Prefer tables linked to the required ones, complete with the rest of the pool if they can't seat everyone
            linked_resources = self.env['appointment.resource'].union(appointment_type._get_resources_for_capacity(
                remaining_capacity, self.start, self.stop,
                available_resources=required_resources.linked_resource_ids & candidate_resources,
            ))
            other_resources = self.env['appointment.resource'].union(appointment_type._get_resources_for_capacity(
                remaining_capacity - sum(linked_resources.mapped('capacity')), self.start, self.stop,
                available_resources=candidate_resources - linked_resources,
            ))
            resources = required_resources | linked_resources | other_resources
        else:
            resource_info = appointment_type._get_resources_for_capacity(self.waiting_list_capacity, self.start, self.stop)
            resources = self.env['appointment.resource'].union(resource_info)
        return resources.sorted('id')

    def _compute_is_conflicted(self):
        for event in self:
            if not event.resource_ids:
                event.is_conflicted = False
                continue

            domain = [
                ('id', '!=', event.id),
                ('resource_ids', 'in', event.resource_ids.ids),
                ('start', '<', event.stop),
                ('stop', '>', event.start),
            ]
            event.is_conflicted = bool(event.search_count(domain))

    def assign_available_resources_to_event(self, config_id, resource_id):
        self.ensure_one()
        config = self.env['pos.config'].browse(config_id)
        resources = self._get_event_resources()
        self.booking_line_ids.filtered(lambda l: l.appointment_resource_id.id == resource_id).unlink()
        self.resource_ids |= resources
        return {
            'calendar.event': self._load_pos_data_read(self, config),
            'appointment.resource': self.env['appointment.resource']._load_pos_data_read(self.resource_ids, config),
        }

    def swap_resources_between_events(self, destination_event_id, config_id):
        self.ensure_one()
        config = self.env['pos.config'].browse(config_id)
        destination_event = self.browse(destination_event_id)
        source_resource_ids = self.resource_ids
        destination_resource_ids = destination_event.resource_ids
        self.booking_line_ids.unlink()
        destination_event.booking_line_ids.unlink()
        self.resource_ids = destination_resource_ids
        destination_event.resource_ids = source_resource_ids
        return {
            'calendar.event': self._load_pos_data_read(self | destination_event, config),
            'appointment.resource': self.env['appointment.resource']._load_pos_data_read(self.resource_ids | destination_event.resource_ids, config),
        }

    def reassign_resources_to_event(self, existing_event_id, resource_id, config_id):
        self.ensure_one()
        config = self.env['pos.config'].browse(config_id)
        existing_event = self.browse(existing_event_id)
        resources = self.env['appointment.resource'].browse(resource_id)
        existing_event.booking_line_ids.filtered(lambda l: l.appointment_resource_id.id == resource_id).unlink()
        existing_event.total_capacity_reserved = sum(existing_event.resource_ids.mapped('capacity'))
        self.booking_line_ids.unlink()
        self.resource_ids |= resources
        return {
            'calendar.event': self._load_pos_data_read(self | existing_event, config),
            'appointment.resource': self.env['appointment.resource']._load_pos_data_read(self.resource_ids | existing_event.resource_ids, config),
        }
