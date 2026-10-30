# Part of Odoo. See LICENSE file for full copyright and licensing details

from datetime import datetime
from dateutil.relativedelta import relativedelta
from odoo import Command
from odoo.addons.planning_field_service_sale_timesheet.tests.common import TestPlanningFieldServiceSaleTimesheetCommon
from odoo.tests import Form, tagged


@tagged('post_install', '-at_install')
class TestWorksheet(TestPlanningFieldServiceSaleTimesheetCommon):

    _test_user_groups = None  # FIXME list needed groups

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.worksheet_template = cls.env['worksheet.template'].create({
            'name': 'New worksheet',
            'res_model': 'planning.slot',
        })
        cls.second_worksheet_template = cls.env['worksheet.template'].create({
            'name': 'Second worksheet',
            'res_model': 'planning.slot',
        })

    def test_service_worksheet_template_propagation(self):
        """
            1) Add new service with worksheet template != its project worksheet template
            2) Add new Sale order with this service
            3) Assert task added with the good worksheet template and project
        """
        self.env['planning.slot'].create({
            'name': 'Fsm task',
            'partner_id': self.partner_1.id,
            'worksheet_template_id': self.worksheet_template.id,
            'start_datetime': datetime.now(),
            'end_datetime': datetime.now() + relativedelta(hours=2),
        })
        expected_interventions_with_worksheet_template_count = self.env['planning.slot'].search_count([('worksheet_template_id', '=', self.worksheet_template.id)])
        expected_interventions_with_second_worksheet_template_count = self.env['planning.slot'].search_count([('worksheet_template_id', '=', self.second_worksheet_template.id)])

        service = self.env['product.product'].create({
            'name': 'Service',
            'type': 'service',
            'planning_enabled': True,
            'worksheet_template_id': self.second_worksheet_template.id,
        })
        sale_order = self.env['sale.order'].create({
            'partner_id': self.partner_1.id,
            'order_line': [
                Command.create({
                    'name': 'description',
                    'product_id': service.id,
                    'product_uom_qty': 10.0,
                    'price_unit': 25.0,
                }),
            ],
        })
        sale_order.action_confirm()
        actual_interventions_with_worksheet_template_count = self.env['planning.slot'].search_count([('worksheet_template_id', '=', self.worksheet_template.id)])
        actual_interventions_with_second_worksheet_template_count = self.env['planning.slot'].search_count([('worksheet_template_id', '=', self.second_worksheet_template.id)])
        self.assertEqual(actual_interventions_with_worksheet_template_count, expected_interventions_with_worksheet_template_count)
        self.assertEqual(actual_interventions_with_second_worksheet_template_count, expected_interventions_with_second_worksheet_template_count + 1)

        service.planning_enabled = False
        self.assertFalse(service.worksheet_template_id, "The worksheet template should be removed from the service product is planning feature is disabled.")

    def test_apply_shift_template_with_worksheet_on_sale_slot(self):
        """
            Test that a shift template holding a worksheet template still plans a shift linked to a sales order item
        """
        self.env.user.tz = 'UTC'
        resource = self.george_employee.resource_id
        resource.tz = 'UTC'
        role = self.env['planning.role'].create({'name': 'Installation'})
        self.planning_service_product.planning_role_id = role
        slot_template = self.env['planning.slot.template'].create({
            'start_time': 13.0,
            'end_time': 17.0,
            'role_id': role.id,
            'worksheet_template_id': self.worksheet_template.id,
        })
        sale_order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [Command.create({
                'product_id': self.planning_service_product.id,
                'product_uom_qty': 10,
            })],
        })
        sale_order.action_confirm()
        slot = self.env['planning.slot'].create({
            'resource_ids': resource.ids,
            'sale_line_id': sale_order.order_line.id,
            'worksheet_template_id': self.worksheet_template.id,
            'start_datetime': datetime(2026, 9, 10, 6, 0),
            'end_datetime': datetime(2026, 9, 10, 7, 0),
        })

        with Form(slot) as slot_form:
            slot_form.template_id = slot_template

        self.assertEqual(slot.template_id, slot_template)
        self.assertEqual(slot.start_datetime, datetime(2026, 9, 10, 13, 0))
        self.assertEqual(slot.end_datetime, datetime(2026, 9, 10, 17, 0))
