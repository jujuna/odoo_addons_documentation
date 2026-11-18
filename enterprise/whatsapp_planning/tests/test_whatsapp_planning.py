from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.planning.tests.common import TestCommonPlanning
from odoo.addons.whatsapp.tests.common import MockOutgoingWhatsApp
from odoo.tests import freeze_time
from odoo.tools import format_datetime
from odoo.exceptions import UserError
from datetime import datetime
from dateutil.relativedelta import relativedelta
from markupsafe import escape
from zoneinfo import ZoneInfo


class TestWhatsappPlanning(MockOutgoingWhatsApp, TestCommonPlanning):

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
        cls.janice_user = mail_new_test_user(cls.env, login="janice", name="janice")
        cls.employee_janice.write({
            'work_phone': "+3281813700",
            'planning_role_ids': [cls.role.id],
            'user_id': cls.janice_user.id,
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
        self.assertIn("for the period 12/30/2025 to 01/01/2026", message.body)

    @freeze_time('2026-1-1')
    def test_whatsapp_planning_send_planning_two_slots(self):
        earlier_slot = self.env["planning.slot"].create({
            "start_datetime": datetime.now() - relativedelta(days=12),
            "end_datetime": datetime.now() - relativedelta(days=11),
            "resource_ids": [self.employee_janice.resource_id.id],
        })
        old_messages = self.env["whatsapp.message"].search([])
        (self.slot + earlier_slot).action_planning_publish_and_send()
        message = self.env["whatsapp.message"].search([]) - old_messages
        self.assertIn("for the period 12/20/2025 to 01/01/2026", message.body)

    @freeze_time("2026-1-1")
    def test_whatsapp_planning_send_planning_without_hr_rights(self):
        bert_slot = self.env["planning.slot"].create({
            "start_datetime": datetime.now() - relativedelta(days=12),
            "end_datetime": datetime.now() - relativedelta(days=11),
            "resource_ids": [self.resource_bert.id],
        })
        old_messages = self.env["whatsapp.message"].search([])
        self.assertFalse(self.planning_manager_user.has_group("hr.group_hr_user"))
        slots = (self.slot + bert_slot).with_user(self.planning_manager_user)
        slots.action_planning_publish_and_send()
        message = (self.env["whatsapp.message"].search([]) - old_messages).filtered(
            lambda message: message.mobile_number == self.employee_janice.work_phone,
        )
        self.assertIn("for the period 12/30/2025 to 01/01/2026", message.body)

    @freeze_time("2026-1-1")
    def test_whatsapp_planning_send_planning_two_companies(self):
        company_mail = self.env["res.company"].create({"name": "Mail Company"})
        self.assertEqual(company_mail.planning_medium, "mail")
        self.employee_bert.company_id = company_mail
        slot_mail = self.env["planning.slot"].create({
            "company_id": company_mail.id,
            "start_datetime": datetime.now() - relativedelta(days=2),
            "end_datetime": datetime.now(),
            "resource_ids": self.employee_bert.resource_id.ids,
        })
        with self.mockWhatsappGateway():
            (self.slot + slot_mail).action_planning_publish_and_send()
        self.assertEqual(
            self._new_wa_msg.mail_message_id.mapped("res_id"),
            self.employee_janice._get_related_partners().ids,
        )
        self.assertEqual(self.env["mail.mail"].search_count([("email_to", "=", "bert@a.be")]), 1)

    @freeze_time("2026-1-1")
    def test_whatsapp_planning_send_wizard_two_companies(self):
        company_mail = self.env["res.company"].create({"name": "Mail Company"})
        self.employee_bert.company_id = company_mail
        slot_mail = self.env["planning.slot"].create([
            {
                "company_id": company_mail.id,
                "start_datetime": datetime.now() - relativedelta(days=2),
                "end_datetime": datetime.now(),
                "resource_ids": self.employee_bert.resource_id.ids,
            },
            {
                "start_datetime": datetime.now(),
                "end_datetime": datetime.now() + relativedelta(hours=8),
            },
        ])[0]
        wizard = self.env["planning.send"].create({
            "start_datetime": datetime.now() - relativedelta(days=3),
            "end_datetime": datetime.now() + relativedelta(days=1),
        })
        self.assertEqual(wizard.employee_ids, self.employee_janice + self.employee_bert)
        self.assertFalse(wizard.employees_no_email)
        with self.mockWhatsappGateway():
            wizard.action_send()
        self.assertEqual(
            self._new_wa_msg.mail_message_id.mapped("res_id"),
            self.employee_janice._get_related_partners().ids,
        )
        self.assertEqual(self.env["mail.mail"].search_count([("email_to", "=", "bert@a.be")]), 1)
        self.assertEqual(slot_mail.state, "2_published")

    @freeze_time('2026-1-1')
    def test_whatsapp_planning_send_planning_url(self):
        old_messages = self.env["whatsapp.message"].search([])
        self.slot.action_planning_publish_and_send()
        message = self.env["whatsapp.message"].search([]) - old_messages
        self.assertEqual(message.wa_template_id, self.env.company.wa_template_schedule_published)
        link = message.free_text_json["free_text_4"]
        self.assertEqual(
            link.split("?")[0],
            f"{message.get_base_url()}/odoo/action-planning.planning_action_open_shift",
        )
        self.assertIn(f'Planning link: <a href="{escape(link)}"', message.body)

    @freeze_time('2026-1-1')
    def test_whatsapp_planning_send_planning_self_unassign(self):
        self.env.company.write({
            'planning_employee_unavailabilities': 'unassign',
            'planning_self_unassign_days_before': 3,
        })
        old_message = self.env['whatsapp.message'].search(
            [('wa_template_id', '=', self.env.company.wa_template_schedule_published.id)],
        )
        self.slot.action_planning_publish_and_send()
        new_message = self.env['whatsapp.message'].search(
            [('wa_template_id', '=', self.env.company.wa_template_schedule_published.id)],
        )
        message = new_message - old_message
        unassign_message = "If you are unable to work an assigned shift please unassign yourself at least 3 day(s) before the shift starts."
        self.assertEqual(message.free_text_json.get('free_text_3'), unassign_message)
        self.assertIn(unassign_message, message.body)

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
        link = message.free_text_json["free_text_7"]
        self.assertIn("/odoo/action-planning.planning_action_open_shift?", link)
        self.assertIn(f'Planning link: <a href="{escape(link)}"', message.body)

    @freeze_time("2026-1-1")
    def test_whatsapp_planning_send_slot_without_hr_rights(self):
        self.employee_bert.work_phone = "+3281813701"
        self.assertFalse(self.planning_manager_user.has_group("hr.group_hr_user"))
        with self.mockWhatsappGateway():
            self.slot.with_user(self.planning_manager_user).action_send()
        self.assertEqual(self._new_wa_msg.mapped("mobile_number"), ["+3281813700"])
        self.assertEqual(
            self._new_wa_msg.wa_template_id,
            self.env.company.wa_template_assigned_shift,
        )

    @freeze_time("2026-1-1")
    def test_whatsapp_planning_send_slot_employee_without_phone(self):
        self.employee_janice.work_phone = False
        self.employee_bert.work_phone = "+3281813701"
        with self.mockWhatsappGateway():
            self.slot.action_send()
        self.assertFalse(self._new_wa_msg)

    @freeze_time("2026-1-1")
    def test_whatsapp_planning_send_wizard_skips_employee_without_phone(self):
        self.employee_bert.write({
            "company_id": self.env["res.company"].create({"name": "Mail Company"}).id,
            "work_phone": False,
        })
        self.env["planning.slot"].create({
            "company_id": self.env.company.id,
            "start_datetime": datetime.now() - relativedelta(days=2),
            "end_datetime": datetime.now(),
            "resource_ids": self.employee_bert.resource_id.ids,
        })
        wizard = self.env["planning.send"].create({
            "start_datetime": datetime.now() - relativedelta(days=3),
            "end_datetime": datetime.now() + relativedelta(days=1),
        })
        self.assertEqual(wizard.employees_no_email, self.employee_bert)
        with self.mockWhatsappGateway():
            action = wizard.action_send()
        self.assertEqual(
            action["params"]["message"],
            "Shifts published: employees without a work phone number were skipped",
        )

    @freeze_time("2026-1-1")
    def test_whatsapp_planning_send_wizard_open_shift_needs_phone(self):
        self.env["planning.slot"].create({
            "start_datetime": datetime.now(),
            "end_datetime": datetime.now() + relativedelta(hours=8),
        })
        wizard = self.env["planning.send"].create({
            "start_datetime": datetime.now() - relativedelta(days=3),
            "end_datetime": datetime.now() + relativedelta(days=1),
        })
        wizard.employee_ids |= self.employee_bert
        self.assertEqual(wizard.employees_no_email, self.employee_bert)

    @freeze_time('2026-1-1')
    def test_whatsapp_planning_send_open_slot(self):
        other_company = self.env["res.company"].create({"name": "Other Company"})
        self.janice_user.company_ids += other_company
        self.env["hr.employee"].create(
            {"name": "janice", "company_id": other_company.id, "user_id": self.janice_user.id},
        )
        open_slot = self.env['planning.slot'].create({
            'name': 'Note',
            'start_datetime': datetime.now() - relativedelta(days=2),
            'end_datetime': datetime.now(),
        })
        old_message = self.env['whatsapp.message'].search(
            [('wa_template_id', '=', self.env.company.wa_template_open_shift_available.id)]
        )
        plannings = self.env["planning.planning"].search([])
        open_slot.action_send()
        self.assertEqual(self.env["planning.planning"].search([]), plannings)
        open_employee = self.env['hr.employee'].search_count([('work_phone', '!=', False), ('company_id', '=', self.env.company.id)])
        new_messages = self.env['whatsapp.message'].search(
            [('wa_template_id', '=', self.env.company.wa_template_open_shift_available.id)]
        )
        self.assertEqual(len(new_messages - old_message), open_employee, "Send one message to each employee that could fill the open slot")
        janice_message = new_messages.filtered(
            lambda message: message.mail_message_id.res_id == self.janice_user.partner_id.id,
        )
        link = janice_message.free_text_json["free_text_7"]
        self.assertIn("/odoo/action-planning.planning_action_open_shift?", link)
        self.assertIn(f'Planning link: <a href="{escape(link)}"', janice_message.body)
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
        link = message.free_text_json["free_text_8"]
        self.assertEqual(
            link,
            f"{message.get_base_url()}/odoo/action-planning.planning_action_open_shift"
            "?date_start=2025-12-30&date_end=2026-01-01",
        )
        self.assertIn(f'Planning link: <a href="{escape(link)}"', message.body)

    @freeze_time("2026-1-1")
    def test_whatsapp_planning_reassign_without_hr_rights(self):
        self.slot.action_send()
        domain = [("wa_template_id", "=", self.env.company.wa_template_shift_reassigned.id)]
        old_message = self.env["whatsapp.message"].search(domain)
        self.assertFalse(self.planning_manager_user.has_group("hr.group_hr_user"))
        self.slot.with_user(self.planning_manager_user).write(
            {"resource_ids": [self.resource_bert.id]},
        )
        new_message = self.env["whatsapp.message"].search(domain) - old_message
        self.assertEqual(len(new_message), 1)
        self.assertEqual(new_message.free_text_json["free_text_1"], self.employee_bert.name)
        self.assertEqual(new_message.mobile_number, self.employee_janice.work_phone)

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
