from odoo.addons.planning.tests.common import TestCommonPlanning
from odoo.tests import freeze_time
from odoo.tools import format_datetime
from odoo.exceptions import UserError
from datetime import datetime
from dateutil.relativedelta import relativedelta
from zoneinfo import ZoneInfo


class TestWhatsappPlanning(TestCommonPlanning):

    @classmethod
    @freeze_time('2026-1-1')
    def setUpClass(cls):
        super().setUpClass()
        cls.setUpEmployees()
        start = (datetime.now() - relativedelta(days=2))
        cls.role = cls.env['planning.role'].create({
            'name': 'Role',
            'color': 1,
        })
        cls.employee_janice.write({
            'work_phone': "+3281813700",
            'planning_role_ids': [cls.role.id],
        })
        cls.tz = ZoneInfo(cls.employee_janice.resource_id.tz)
        cls.slot = cls.env['planning.slot'].create({
            'name': 'Note',
            'start_datetime': start,
            'end_datetime': datetime.now(),
            'resource_ids': [cls.employee_janice.resource_id.id],
        })
        cls.env.company.planning_medium = 'whatsapp'
        cls.env.company.wa_template_schedule_published.status = 'approved'
        cls.env.company.wa_template_assigned_shift.status = 'approved'
        cls.env.company.wa_template_open_shift_available.status = 'approved'
        cls.env.company.wa_template_shift_reassigned.status = 'approved'

    @freeze_time('2026-1-1')
    def test_whatsapp_planning_send_planning(self):
        old_message = self.env['whatsapp.message'].search(
            [('wa_template_id', '=', self.env.company.wa_template_schedule_published.id)]
        )
        self.slot.action_planning_publish_and_send()
        new_message = self.env['whatsapp.message'].search(
            [('wa_template_id', '=', self.env.company.wa_template_schedule_published.id)]
        )
        self.assertEqual(len(new_message - old_message), 1, "Only one new message should be generated as the new planning only concern one person")
        message = (new_message - old_message)
        for json_element in ['free_text_1', 'free_text_2', 'free_text_4', 'button_dynamic_url_1']:
            self.assertIn(json_element, message.free_text_json, f"{json_element} should be a variable inside whatsapp planning message")
        self.assertEqual(message.free_text_json['free_text_1'], (datetime.now() - relativedelta(days=2)).strftime("%m/%d/%Y"), "The whatsapp planning message should have the correct start date")
        self.assertEqual(message.free_text_json['free_text_2'], datetime.now().strftime("%m/%d/%Y"), "The whatsapp planning message should have the correct end date")

    @freeze_time('2026-1-1')
    def test_whatsapp_planning_send_slot(self):
        old_message = self.env['whatsapp.message'].search(
            [('wa_template_id', '=', self.env.company.wa_template_assigned_shift.id)]
        )
        self.slot.action_send()
        new_message = self.env['whatsapp.message'].search(
            [('wa_template_id', '=', self.env.company.wa_template_assigned_shift.id)]
        )
        self.assertEqual(len(new_message - old_message), 1, "Only one new message should be generated for the assigned employee")
        message = new_message - old_message
        for json_element_index in range(1, 8):
            self.assertIn(f'free_text_{json_element_index}', message.free_text_json, f"free_text_{json_element_index} should be a variable inside whatsapp planning message")
        self.assertEqual(message.free_text_json['free_text_1'],
            f"{format_datetime(self.env, datetime.now() - relativedelta(days=2))} → {format_datetime(self.env, datetime.now())}",
            "The whatsapp planning message should have the correct start and end date")
        self.assertEqual(message.free_text_json['free_text_2'], "Role", "The whatsapp planning message should have the correct role")
        self.assertEqual(message.free_text_json['free_text_6'], "Note", "The whatsapp planning message should have the correct Planning Note")

    @freeze_time('2026-1-1')
    def test_whatsapp_planning_send_open_slot(self):
        open_slot = self.env['planning.slot'].create({
            'name': 'Note',
            'start_datetime': datetime.now() - relativedelta(days=2),
            'end_datetime': datetime.now(),
        })
        old_message = self.env['whatsapp.message'].search(
            [('wa_template_id', '=', self.env.company.wa_template_open_shift_available.id)]
        )
        open_slot.action_send()
        open_employee = self.env['hr.employee'].search_count([('work_phone', '!=', False), ('company_id', '=', self.env.company.id)])
        new_messages = self.env['whatsapp.message'].search(
            [('wa_template_id', '=', self.env.company.wa_template_open_shift_available.id)]
        )
        self.assertEqual(len(new_messages - old_message), open_employee, "Send one message to each employee that could fill the open slot")
        message = (new_messages - old_message)[0]
        for json_element_index in range(1, 8):
            self.assertIn(f'free_text_{json_element_index}', message[0].free_text_json, f"free_text_{json_element_index} should be a variable inside whatsapp planning message")
        self.assertEqual(message.free_text_json['free_text_1'],
            f"{format_datetime(self.env, datetime.now() - relativedelta(days=2))} → {format_datetime(self.env, datetime.now())}",
            "The whatsapp planning message should have the correct start and end date")

    @freeze_time('2026-1-1')
    def test_whatsapp_planning_reassign(self):
        self.slot.action_send()
        old_message = self.env['whatsapp.message'].search([('wa_template_id', '=', self.env.company.wa_template_shift_reassigned.id)])
        self.employee_bert.write({
            'work_phone': "+3281813700"
        })
        self.slot.write({
            'resource_ids': [self.resource_bert.id]
        })
        new_message = self.env['whatsapp.message'].search(
            [('wa_template_id', '=', self.env.company.wa_template_shift_reassigned.id)]
        )
        self.assertEqual(len(new_message - old_message), 1, "Send one reassigned message when ressource is changed")
        message = (new_message - old_message)[0]
        for json_element_index in range(1, 8):
            self.assertIn(f'free_text_{json_element_index}', message.free_text_json, f"free_text_{json_element_index} should be a variable inside whatsapp planning message")
        self.assertEqual(message.free_text_json['free_text_1'], self.employee_bert.name, "The whatsapp planning message should point to the right employee to reassign")
        self.assertEqual(message.free_text_json['free_text_2'],
            f"{format_datetime(self.env, datetime.now() - relativedelta(days=2))} → {format_datetime(self.env, datetime.now())}",
            "The whatsapp planning message should have the correct start and end date")

    def test_whatsapp_planning_unapproved_template_error(self):
        self.env.company.wa_template_schedule_published.status = 'draft'
        self.env.company.wa_template_assigned_shift.status = 'draft'
        self.env.company.wa_template_open_shift_available.status = 'draft'
        self.env.company.wa_template_shift_reassigned.status = 'draft'

        ## Planning slot
        self.assertRaises(UserError, self.slot.action_send)
        ## Assigne slot
        self.assertRaises(UserError, self.slot.action_planning_publish_and_send)

        ## Reassign slot
        self.employee_janice.write({
            'work_phone': "+3281813700"})
        self.env.company.wa_template_assigned_shift.status = 'approved'
        self.slot.action_send()
        self.assertRaises(UserError, self.slot.write, {'resource_ids': [self.resource_bert.id]})

        ## Open slot
        open_slot = self.env['planning.slot'].create({
            'name': 'Note',
            'start_datetime': datetime.now() - relativedelta(days=2),
            'end_datetime': datetime.now(),
        })
        self.assertRaises(UserError, open_slot.action_send)
