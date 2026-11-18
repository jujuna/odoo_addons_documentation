# Part of Odoo. See LICENSE file for full copyright and licensing details.

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCalendarEvent(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.appointment_type, cls.other_appointment_type = cls.env['appointment.type'].create([{
            'appointment_tz': 'UTC',
            'event_videocall_source': False,
            'name': name,
            'manage_capacity': True,
            'schedule_based_on': 'resources',
        } for name in ('Table Booking', 'Other Table Booking')])

        # Four 2-seat tables and a 4-seat table: 12 seats in total
        cls.resources = cls.env['appointment.resource'].create([{
            'name': f'Table {number}',
            'capacity': capacity,
            'appointment_type_ids': [Command.set(cls.appointment_type.ids)],
        } for number, capacity in enumerate([2, 2, 2, 2, 4], start=1)])
        cls.other_resource = cls.env['appointment.resource'].create({
            'name': 'Other Table',
            'capacity': 4,
            'appointment_type_ids': [Command.set(cls.other_appointment_type.ids)],
        })

        cls.total_capacity = cls.appointment_type.resource_total_capacity
        cls.start = fields.Datetime.to_datetime('2026-10-01 12:00:00')
        cls.stop = cls.start + relativedelta(hours=2)

    def _create_booking(self, name, resources, **vals):
        return self.env['calendar.event'].create({
            'name': name,
            'start': self.start,
            'stop': self.stop,
            'appointment_type_id': self.appointment_type.id,
            'booking_line_ids': [Command.create({
                'appointment_resource_id': resource.id,
                'capacity_reserved': resource.capacity,
            }) for resource in resources],
            **vals,
        })

    def _get_available_capacity(self, booking=None):
        """ Available capacity of an existing booking, or of a new booking at the default time. """
        self.env.invalidate_all()
        if not booking:
            booking = self.env['calendar.event'].new({
                'start': self.start,
                'stop': self.stop,
                'appointment_type_id': self.appointment_type.id,
            })
        return booking.available_capacity

    def test_available_capacity(self):
        table_1, table_2, table_3, table_4, table_5 = self.resources
        self.assertEqual(self.total_capacity, 12)

        # 5 seats on two 2-seat tables: only the 4 seats of the tables are occupied
        booking_1 = self._create_booking('Booking 1', table_1 | table_2, waiting_list_capacity=5)
        self.assertEqual(self._get_available_capacity(), self.total_capacity - 4)

        booking_2 = self._create_booking('Booking 2', table_3)
        self._create_booking('Booking 3', table_4)
        self.assertEqual(self._get_available_capacity(), self.total_capacity - 8)

        # A booking doesn't take seats away from itself
        self.assertEqual(self._get_available_capacity(booking_1), self.total_capacity - 4)
        self.assertEqual(self._get_available_capacity(booking_2), self.total_capacity - 6)

        # Bookings not overlapping the default time slot are ignored
        capacity = self.total_capacity - 8
        self._create_booking(
            'Booking Before', table_5,
            start=self.start - relativedelta(hours=2), stop=self.start,
        )
        self._create_booking(
            'Booking After', table_5,
            start=self.stop, stop=self.stop + relativedelta(hours=2),
        )
        self._create_booking(
            'Booking Tomorrow', table_5,
            start=self.start + relativedelta(days=1), stop=self.stop + relativedelta(days=1),
        )
        self.assertEqual(self._get_available_capacity(), capacity)

        # Cancelled and no show bookings don't occupy their tables
        self._create_booking('Booking Cancelled', table_5, appointment_status='cancelled')
        self._create_booking('Booking No Show', table_5, appointment_status='no_show')
        self.assertEqual(self._get_available_capacity(), capacity)

        # Tables of another appointment type are ignored
        self._create_booking(
            'Booking Other Type', self.other_resource,
            appointment_type_id=self.other_appointment_type.id,
        )
        self.assertEqual(self._get_available_capacity(), capacity)

        # Sanity check: an overlapping booking on the last table is counted
        self._create_booking('Booking 4', table_5)
        self.assertEqual(self._get_available_capacity(), 0)

    def _get_event_resources(self, required_resources, capacity):
        """ Tables assigned to a new booking of `capacity` seats created from the `required_resources` gantt row. """
        booking = self.env['calendar.event'].with_context(default_resource_ids=required_resources.ids).new({
            'start': self.start,
            'stop': self.stop,
            'appointment_type_id': self.appointment_type.id,
            'waiting_list_capacity': capacity,
            'resource_ids': [Command.set(required_resources.ids)],
        })
        return booking._get_event_resources()

    def test_event_resources_with_required_table(self):
        table_1, table_2, table_3, _table_4, table_5 = self.resources
        table_1.linked_resource_ids = table_2 | self.other_resource

        # The linked table is enough: the rest of the pool isn't used
        self.assertEqual(self._get_event_resources(table_1, 4), table_1 | table_2)

        # The linked table is kept and the missing seats are taken from the rest of the pool,
        # tables linked from another appointment type are ignored
        self.assertEqual(self._get_event_resources(table_1, 8), table_1 | table_2 | table_5)

        # A table without links is completed with the rest of the pool
        self.assertEqual(self._get_event_resources(table_3, 6), table_3 | table_5)

    def _get_used_by(self, resource, booking):
        """ Booking returned by is_used for `resource` when looking at the time slot of `booking`. """
        self.env.invalidate_all()
        is_used = resource.with_context(
            tz='UTC',
            start_date=fields.Datetime.to_string(booking.start),
            stop_date=fields.Datetime.to_string(booking.stop),
        ).is_used
        return self.env['calendar.event'].browse(is_used and is_used['event_id'])

    def _assert_used_by(self, resource, expected):
        for booking, used_by in expected.items():
            self.assertEqual(
                self._get_used_by(resource, booking), used_by,
                f"{resource.name} seen from {booking.name}",
            )

    @freeze_time('2026-09-30 16:00:00')
    def test_is_used(self):
        table_1, table_2 = self.resources[:2]
        no_booking = self.env['calendar.event']

        def create_booking(name, start, stop, resources, capacity):
            return self._create_booking(
                name, resources, waiting_list_capacity=capacity,
                start=fields.Datetime.to_datetime(f'2026-09-30 {start}:00'),
                stop=fields.Datetime.to_datetime(f'2026-09-30 {stop}:00'),
            )

        a = create_booking('a', '12:00', '13:30', table_1, 4)
        b = create_booking('b', '12:30', '14:00', table_1, 2)
        c = create_booking('c', '14:30', '15:30', table_1, 5)
        d = create_booking('d', '15:45', '17:45', table_1, 3)
        e = create_booking('e', '19:45', '21:00', table_1, 2)
        f = create_booking('f', '20:15', '21:45', table_1 | table_2, 4)
        # Guests checked in yesterday and never checked out don't hold the table today
        self._create_booking(
            'Yesterday', table_1, appointment_status='attended',
            start=fields.Datetime.to_datetime('2026-09-29 12:00:00'),
            stop=fields.Datetime.to_datetime('2026-09-29 14:00:00'),
        )

        # Past bookings that were never checked in are ignored, the others hold the table when they overlap
        self._assert_used_by(table_1, {
            a: no_booking, b: no_booking, c: no_booking, d: d, e: e, f: e,
        })
        self._assert_used_by(table_2, {a: no_booking, d: no_booking, e: f, f: f})

        # Checked-in guests hold the table until now, even past the end of their booking
        c.appointment_status = 'attended'
        self._assert_used_by(table_1, {
            a: no_booking, b: no_booking, c: c, d: c, e: e, f: e,
        })

        # The earliest checked-in booking is the one returned
        b.appointment_status = 'attended'
        self._assert_used_by(table_1, {a: b, b: b, c: b, d: b, e: e})
        a.appointment_status = 'attended'
        self._assert_used_by(table_1, {a: a, b: a, c: a, d: a, e: e})

        # No show and cancelled bookings don't hold the table
        a.appointment_status = 'no_show'
        self._assert_used_by(table_1, {a: b, b: b, c: b, d: b})
        e.appointment_status = 'cancelled'
        self._assert_used_by(table_1, {e: f, f: f})
