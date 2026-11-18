# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import odoo.tests
from odoo.addons.pos_restaurant.tests.test_frontend import TestFrontend
from odoo import Command, fields
from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from unittest import skip


@odoo.tests.tagged('post_install', '-at_install')
class TestUi(TestFrontend):

    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.env.user.group_ids += cls.quick_ref('appointment.group_appointment_manager')

        cls.appointment_type = cls.env['appointment.type'].create({
            'appointment_tz': 'US/Eastern',
            'event_videocall_source': False,
            'is_auto_assign': True,
            'name': 'Table Booking Test',
            'manage_capacity': True,
            'manual_confirmation_percentage': 0.8,
            'schedule_based_on': 'resources',
        })

        cls.pos_config.write({
            'module_pos_appointment': True,
            'appointment_type_id': cls.appointment_type.id,
        })

        cls.main_floor_table_4 = cls.env['restaurant.table'].search([
            ('table_number', '=', 4),
            ('floor_id', '=', cls.main_floor.id)
        ], limit=1)

        cls.table_4_resource = cls.env['appointment.resource'].create({
            'name': 'Test Main Floor - Table 4',
            'capacity': 2,
            'appointment_type_ids': [(6, 0, [cls.appointment_type.id])],
            'pos_table_ids': [(6, 0, [cls.main_floor_table_4.id])]
        })

        cls.table_5_resource = cls.env['appointment.resource'].create({
            'name': 'Test Main Floor - Table 5',
            'capacity': 2,
            'appointment_type_ids': [(6, 0, [cls.appointment_type.id])],
            'pos_table_ids': [(6, 0, [cls.main_floor_table_5.id])]
        })

    @skip("To much random crash with indexed DB see rb build 116709961")
    @freeze_time('2026-01-28 12:00:00')
    def test_pos_restaurant_appointment_tour_basic(self):
        now = fields.Datetime.now()
        self.env['calendar.event'].create([{
                    'name': "Test Lunch",
                    'start': now + relativedelta(minutes=30),
                    'stop': now + relativedelta(minutes=150),
                    'appointment_type_id': self.appointment_type.id,
                    'booking_line_ids': [(0, 0, {'appointment_resource_id': self.table_5_resource.id, 'capacity_reserved': 2})],
                }, {
                    'name': "Tomorrow Appointment",
                    'start': now + relativedelta(days=1, minutes=30),
                    'stop': now + relativedelta(days=1, minutes=90),
                    'appointment_type_id': self.appointment_type.id,
                    'booking_line_ids': [(0, 0, {'appointment_resource_id': self.table_4_resource.id, 'capacity_reserved': 2})],
                }])
        # open a session, the /pos/ui controller will redirect to it
        self.pos_config.with_user(self.pos_admin).open_ui()

        self.start_pos_tour('RestaurantAppointmentTour', login="pos_admin")

    @freeze_time('2025-08-27 12:18:56')
    def test_appointment_kanban_view(self):
        self.start_pos_tour("test_appointment_kanban_view", login="pos_admin")

    def test_table_without_ressources(self):
        """ This test make sure that appointment ressource can be recreated if missing during opening"""
        self.pos_config.floor_ids.table_ids.appointment_resource_id.unlink()
        self.assertFalse(self.pos_config.floor_ids.table_ids.appointment_resource_id)
        self.pos_config.with_user(self.pos_admin).open_ui()
        self.start_pos_tour("test_table_without_ressources", login="pos_admin")
        self.assertEqual(len(self.pos_config.floor_ids.table_ids.appointment_resource_id.ids), 5)

    @freeze_time('2025-08-27 12:18:56')
    def test_booking_available_seats_and_check_in(self):
        appointment_type = self.env['appointment.type'].create({
            'appointment_tz': 'US/Eastern',
            'event_videocall_source': False,
            'is_auto_assign': True,
            'name': 'Seats Booking Test',
            'manage_capacity': True,
            'schedule_based_on': 'resources',
        })
        self.pos_config.appointment_type_id = appointment_type
        # A group of four linked 2-seat tables, a 4-seat table linked to a 2-seat table
        # and a standalone 4-seat table: 18 seats in total.
        resources = self.env['appointment.resource'].create([{
            'name': f'Booking Table {name}',
            'capacity': capacity,
            'sequence': sequence,
            'appointment_type_ids': [Command.set(appointment_type.ids)],
        } for sequence, (name, capacity) in enumerate([
            ('A', 2), ('B', 2), ('C', 2), ('D', 2), ('E', 4), ('F', 2), ('G', 4),
        ], start=1)])
        table_a, table_b, table_c, table_d, table_e, table_f, _table_g = resources
        table_a.linked_resource_ids = table_b | table_c | table_d
        table_b.linked_resource_ids = table_a | table_c | table_d
        table_c.linked_resource_ids = table_a | table_b | table_d
        table_e.linked_resource_ids = table_f

        self.pos_config.with_user(self.pos_admin).open_ui()
        self.start_pos_tour('test_booking_available_seats_and_check_in', login="pos_admin")

        bookings = self.env['calendar.event'].search([('appointment_type_id', '=', appointment_type.id)])
        booking_one, booking_two, booking_three = (
            bookings.filtered(lambda b: b.name == name) for name in ('Booking One', 'Booking Two', 'Booking Three')
        )
        self.assertEqual(booking_one.resource_ids, table_a)
        self.assertEqual(booking_two.resource_ids, table_b)
        self.assertFalse(booking_three.resource_ids)
        self.assertEqual(set(bookings.mapped('appointment_status')), {'attended'})
