# Part of Odoo. See LICENSE file for full copyright and licensing details.
from datetime import date
from freezegun import freeze_time

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.addons.hr_payroll.tests.common import TestPayslipBase


@tagged('at_install', '-post_install', 'payslip_adjustment')  # LEGACY at_install
class TestSalaryAttachment(TestPayslipBase):

    def setUp(self):
        super().setUp()
        self.toto = self.env['hr.employee'].create({
            'name': 'Toto',
            'date_version': date(2027, 1, 1),
            'contract_date_start': date(2027, 1, 1),
            'contract_date_end': date(2027, 12, 31),
            'wage': 1000.0,
            'structure_type_id': self.structure_type.id,
        })
        self.toto_bank_acc = self.env['res.partner.bank'].create({
            'account_number': 'BE00111122229999',
            "partner_id": self.toto.work_contact_id.id,
            "allow_out_payment": True
        })
        self.toto.bank_account_ids = [Command.link(self.toto_bank_acc.id)]
        self.attachement_type = self.attach_salary_rule
        self.child_support_type = self.child_support_rule

    def action_pay_payslip(self, employee, date_from, date_to):
        payslip = self.env['hr.payslip'].create({
            'employee_id': employee.id,
            'date_from': date_from,
            'date_to': date_to,
        })
        payslip.compute_sheet()
        payslip.action_payslip_done()
        payslip.action_payslip_paid()
        return payslip

    def test_action_new_salary_attachment_forces_view(self):
        # The action must explicitly pin the attachment form view, otherwise
        # the client can fall back to a stale `form_view_ref` left in an
        # unrelated context (e.g. after opening a contract template through
        # an internal link) and try to render it against hr.salary.attachment.
        version = self.toto.version_id
        action = version.action_new_salary_attachment()
        expected_view = self.env.ref('hr_payroll.hr_salary_attachment_view_form')
        self.assertEqual(action['view_id'], expected_view.id)

    @freeze_time('2027-01-01')
    def test_attachment_inputs_with_same_code(self):
        attach_rule = self.env['hr.salary.rule'].create({
            'name': 'Allowance Attachment',
            'sequence': 99,
            'amount_select': 'code',
            'amount_python_compute': "result = inputs['ALW.ATT'].amount",
            'quantity': "'002.00' in worked_days and worked_days['002.00'].number_of_days",
            'code': "ALW.ATT",
            'input_usage_payslip': True,
            'category_ids': [(4, self.env.ref('hr_payroll.ALW').id)],
            'struct_ids': [(4, self.developer_pay_structure.id)],
        })

        self.env['hr.salary.attachment'].create([{
            'employee_id': self.toto.id,
            'description': 'Test Attachment 1',
            'salary_rule_id': attach_rule.id,
            'date_start': date(2027, 1, 1),
            'amount': 100,
        }, {
            'employee_id': self.toto.id,
            'description': 'Test Attachment 2',
            'salary_rule_id': attach_rule.id,
            'date_start': date(2027, 1, 1),
            'amount': 50,
        }])

        payslip = self.action_pay_payslip(
            self.toto,
            date(2027, 1, 1),
            date(2027, 1, 31)
        )

        self.assertEqual(len(payslip.input_line_ids), 2)
        self.assertCountEqual(payslip.input_line_ids.mapped('amount'), [100, 50])
        self.assertCountEqual(payslip.input_line_ids.mapped('name'), ['Test Attachment 1', 'Test Attachment 2'])
        attachment_lines = payslip.line_ids.filtered(lambda line: line.code == 'ALW.ATT')
        self.assertEqual(len(attachment_lines), 2)
        self.assertCountEqual(attachment_lines.mapped('total'), [100, 50])
        self.assertCountEqual(
            attachment_lines.mapped('name'),
            ['Allowance Attachment - Test Attachment 1', 'Allowance Attachment - Test Attachment 2'],
        )
        self.assertRecordValues(payslip.salary_attachment_ids, [
            {"salary_rule_id": attach_rule.id, "paid_amount": 100},
            {"salary_rule_id": attach_rule.id, "paid_amount": 50},
        ])

    @freeze_time('2027-01-01')
    def test_attachment_input_without_payslip_description(self):
        attachment = self.env['hr.salary.attachment'].create({
            'employee_id': self.toto.id,
            'salary_rule_id': self.attachement_type.id,
            'date_start': date(2027, 1, 1),
            'amount': 100,
        })
        payslip = self.action_pay_payslip(self.toto, date(2027, 1, 1), date(2027, 1, 31))
        line = payslip.line_ids.filtered(lambda payslip_line: payslip_line.salary_rule_id == attachment.salary_rule_id)
        self.assertEqual(line.name, attachment.salary_rule_id.name)

    @freeze_time('2027-01-01')
    def test_attachment_payslip_description_not_duplicated(self):
        attachment = self.env['hr.salary.attachment'].create({
            'employee_id': self.toto.id,
            'description': 'Court order',
            'salary_rule_id': self.attachement_type.id,
            'date_start': date(2027, 1, 1),
            'amount': 100,
        })
        payslip = self.action_pay_payslip(self.toto, date(2027, 1, 1), date(2027, 1, 31))
        line = payslip.line_ids.filtered(lambda payslip_line: payslip_line.salary_rule_id == attachment.salary_rule_id)
        self.assertEqual(line.name, f'{attachment.salary_rule_id.name} - {attachment.description}')

    @freeze_time('2027-01-01')
    def test_input_default_name_not_in_line_name(self):
        # An input keeping the default name of its rule is not a payslip description
        self.attachement_type.write({
            'input_name': 'Seized amount',
            'amount_python_compute': f"result = -inputs['{self.attachement_type.code}'].amount",
        })
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.toto.id,
            'date_from': date(2027, 1, 1),
            'date_to': date(2027, 1, 31),
            'input_line_ids': [Command.create({'salary_rule_id': self.attachement_type.id, 'amount': 100})],
        })
        self.assertEqual(payslip.input_line_ids.name, 'Seized amount')
        payslip.compute_sheet()
        line = payslip.line_ids.filtered(lambda payslip_line: payslip_line.salary_rule_id == self.attachement_type)
        self.assertEqual(line.name, self.attachement_type.name)

    @freeze_time('2027-01-01')
    def test_ytd_of_several_attachment_lines(self):
        # One line per attachment, each with a cumulative YTD: the YTD of the next payslip
        # starts from the YTD of the code, not from the sum of the YTD of its lines
        self.env['hr.salary.attachment'].create([{
            'employee_id': self.toto.id,
            'description': description,
            'salary_rule_id': self.attachement_type.id,
            'date_start': date(2027, 1, 1),
            'amount': amount,
            'is_recurring': True,
        } for description, amount in (('First adjustment', 100), ('Second adjustment', 50))])
        january = self.action_pay_payslip(self.toto, date(2027, 1, 1), date(2027, 1, 31))
        january_lines = january.line_ids.filtered(lambda line: line.code == self.attachement_type.code).sorted('id')
        self.assertEqual(january_lines.mapped('ytd'), [-100, -150])

        february = self.env['hr.payslip'].create({
            'employee_id': self.toto.id,
            'date_from': date(2027, 2, 1),
            'date_to': date(2027, 2, 28),
        })
        february.compute_sheet()
        february_lines = february.line_ids.filtered(lambda line: line.code == self.attachement_type.code).sorted('id')
        self.assertEqual(february_lines.mapped('ytd'), [-250, -300])

    @freeze_time('2027-01-01')
    def test_manual_edit_of_one_attachment_line(self):
        self.env['hr.salary.attachment'].create([{
            'employee_id': self.toto.id,
            'description': description,
            'salary_rule_id': self.attachement_type.id,
            'date_start': date(2027, 1, 1),
            'amount': amount,
        } for description, amount in (('First adjustment', 100), ('Second adjustment', 300))])
        payslip = self.env['hr.payslip'].create({
            'employee_id': self.toto.id,
            'date_from': date(2027, 1, 1),
            'date_to': date(2027, 1, 31),
        })
        payslip.compute_sheet()

        def attachment_lines():
            return payslip.line_ids.filtered(lambda line: line.code == self.attachement_type.code).sorted('id')

        payslip.write({'line_ids': [Command.update(attachment_lines()[1].id, {'name': 'Renamed second'})]})
        # The lines are recreated on each manual edit, the previous edit of the other line must stick
        payslip.write({'line_ids': [Command.update(attachment_lines()[0].id, {'name': 'Renamed first', 'amount': -40})]})
        self.assertRecordValues(attachment_lines(), [
            {'name': 'Renamed first', 'total': -40, 'manually_modified': True},
            {'name': 'Renamed second', 'total': -300, 'manually_modified': False},
        ])

    def test_salary_adjustment_multi_wizard(self):
        salary_adjustment_wizard = self.env['hr.salary.attachment.generate.multi.wizard'].create({
            'employee_ids': (self.toto + self.richard_emp).ids,
            'salary_rule_id': self.attachement_type.id,
            'date_start': date(2027, 2, 1),
            'date_end': date(2027, 6, 30),
            'amount': 1000,
        })
        salary_adjustment_wizard.action_generate_salary_adjustments()
        generated_adjustments = self.env['hr.salary.attachment'].search([
            ('employee_id', 'in', (self.toto + self.richard_emp).ids),
            ('salary_rule_id', '=', self.attachement_type.id),
        ])
        self.assertEqual(len(generated_adjustments), 2)
        for adjustment in generated_adjustments:
            self.assertRecordValues(adjustment, [{
                'salary_rule_id': self.attachement_type.id,
                'amount': 1000.0,
                'paid_amount': 0.0,
                'date_start': date(2027, 2, 1),
                'date_end': date(2027, 6, 30),
                'state': '1_open',
                'company_id': self.env.company.id,
            }])

    @freeze_time('2027-01-01')
    def test_non_recurring_attachment_partial_payment(self):
        """Test non-recurring attachment where amount is paid over multiple payslips"""
        attachment = self.env['hr.salary.attachment'].create({
            'employee_id': self.toto.id,
            'description': 'Non-recurring 1000',
            'salary_rule_id': self.attachement_type.id,
            'date_start': date(2027, 1, 1),
            'amount': 1000,
            'is_recurring': False,
        })

        # First payslip pays 300
        payslip1 = self.env['hr.payslip'].create({
            'employee_id': self.toto.id,
            'date_from': date(2027, 1, 1),
            'date_to': date(2027, 1, 31),
        })
        payslip1.compute_sheet()
        input_line = payslip1.input_line_ids.filtered(lambda l: l.code == self.attachement_type.code)
        input_line.amount = 300
        payslip1.compute_sheet()
        payslip1.action_payslip_done()
        payslip1.action_payslip_paid()

        self.assertEqual(attachment.paid_amount, 300)
        self.assertEqual(attachment.remaining_amount, 700)
        self.assertEqual(attachment.state, '1_open')

        # Second payslip pays 400 more
        payslip2 = self.env['hr.payslip'].create({
            'employee_id': self.toto.id,
            'date_from': date(2027, 2, 1),
            'date_to': date(2027, 2, 28),
        })
        payslip2.compute_sheet()
        input_line = payslip2.input_line_ids.filtered(lambda l: l.code == self.attachement_type.code)
        input_line.amount = 400
        payslip2.compute_sheet()
        payslip2.action_payslip_done()
        payslip2.action_payslip_paid()

        self.assertEqual(attachment.paid_amount, 700)
        self.assertEqual(attachment.remaining_amount, 300)
        self.assertEqual(attachment.state, '1_open')

        # Third payslip pays the remaining 300
        payslip3 = self.env['hr.payslip'].create({
            'employee_id': self.toto.id,
            'date_from': date(2027, 3, 1),
            'date_to': date(2027, 3, 31),
        })
        payslip3.compute_sheet()
        payslip3.action_payslip_done()
        payslip3.action_payslip_paid()

        self.assertEqual(attachment.paid_amount, 1000)
        self.assertEqual(attachment.remaining_amount, 0)
        self.assertEqual(attachment.state, '2_close')

    @freeze_time('2027-01-01')
    def test_non_recurring_attachment_overpayment_error(self):
        """Test that trying to pay more than remaining raises an error"""
        attachment = self.env['hr.salary.attachment'].create({
            'employee_id': self.toto.id,
            'description': 'Non-recurring 500',
            'salary_rule_id': self.attachement_type.id,
            'date_start': date(2027, 1, 1),
            'amount': 500,
            'is_recurring': False,
        })

        # First payslip pays 300
        payslip1 = self.env['hr.payslip'].create({
            'employee_id': self.toto.id,
            'date_from': date(2027, 1, 1),
            'date_to': date(2027, 1, 31),
        })
        payslip1.compute_sheet()
        input_line = payslip1.input_line_ids.filtered(lambda l: l.code == self.attachement_type.code)
        input_line.amount = 300
        payslip1.compute_sheet()
        payslip1.action_payslip_done()
        payslip1.action_payslip_paid()

        self.assertEqual(attachment.paid_amount, 300)
        self.assertEqual(attachment.remaining_amount, 200)

        # Second payslip tries to pay 300 (more than remaining 200) - should raise error
        payslip2 = self.env['hr.payslip'].create({
            'employee_id': self.toto.id,
            'date_from': date(2027, 2, 1),
            'date_to': date(2027, 2, 28),
        })
        payslip2.compute_sheet()
        input_line = payslip2.input_line_ids.filtered(lambda l: l.code == self.attachement_type.code)
        input_line.amount = 300
        payslip2.compute_sheet()
        payslip2.action_payslip_done()

        with self.assertRaises(UserError, msg='Should raise error when trying to pay more than remaining'):
            payslip2.action_payslip_paid()

    def _set_attachment_inputs_total(self, payslip, total):
        """Put ``total`` on the first input of the attachments (one input per attachment), the others at 0."""
        first_input, *other_inputs = payslip.input_line_ids.filtered(lambda l: l.code == self.attachement_type.code)
        first_input.amount = total
        for input_line in other_inputs:
            input_line.amount = 0

    @freeze_time('2027-01-01')
    def test_attachments_priority_a_eq_b(self):
        """Test two non-recurring attachments with same priority are paid pro-rata"""
        attachment_A, attachment_B = self.env['hr.salary.attachment'].create([
            {
                'employee_id': self.toto.id,
                'description': 'Non-recurring A 500',
                'salary_rule_id': self.attachement_type.id,
                'date_start': date(2027, 1, 1),
                'amount': 500,
                'is_recurring': False,
                'sequence': 10,
            },
            {
                'employee_id': self.toto.id,
                'description': 'Non-recurring B 1000',
                'salary_rule_id': self.attachement_type.id,
                'date_start': date(2027, 1, 1),
                'amount': 1000,
                'is_recurring': False,
                'sequence': 10,
            }
        ])

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.toto.id
        })
        payslip.compute_sheet()
        # Manually set the total amount to 600
        self._set_attachment_inputs_total(payslip, 600)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        payslip.action_payslip_paid()

        # As both have same priority, they are paid pro-rata according to their remaining amount
        # Remaining for A = 500, Remaining for B = 1000
        # Total remaining = 1500
        # Available amount = 600
        # A gets: 500/1500 * 600 = 200
        # B gets: 1000/1500 * 600 = 400
        self.assertEqual(attachment_A.paid_amount, 200)
        self.assertEqual(attachment_B.paid_amount, 400)
        self.assertEqual(attachment_A.remaining_amount, 300)
        self.assertEqual(attachment_B.remaining_amount, 600)

    @freeze_time('2027-01-01')
    def test_attachments_priority_a_gt_b(self):
        """Test two non-recurring attachments where A has higher priority than B"""
        attachment_A, attachment_B = self.env['hr.salary.attachment'].create([
            {
                'employee_id': self.toto.id,
                'description': 'Non-recurring A 500',
                'salary_rule_id': self.attachement_type.id,
                'date_start': date(2027, 1, 1),
                'amount': 500,
                'is_recurring': False,
                'sequence': 10,  # Higher priority (higher sequence number)
            },
            {
                'employee_id': self.toto.id,
                'description': 'Non-recurring B 1000',
                'salary_rule_id': self.attachement_type.id,
                'date_start': date(2027, 1, 1),
                'amount': 1000,
                'is_recurring': False,
                'sequence': 20,  # Lower priority
            }
        ])

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.toto.id
        })
        payslip.compute_sheet()
        self._set_attachment_inputs_total(payslip, 300)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        payslip.action_payslip_paid()

        # Higher priority attachment A gets paid first (all 300)
        # Lower priority attachment B gets the remaining 0
        self.assertEqual(attachment_A.paid_amount, 300)
        self.assertEqual(attachment_B.paid_amount, 0)

    @freeze_time('2027-01-01')
    def test_attachments_priority_a_gt_b_a_fully_paid(self):
        """Test priority where high-priority attachment is fully paid, remainder goes to low-priority"""
        attachment_A, attachment_B = self.env['hr.salary.attachment'].create([
            {
                'employee_id': self.toto.id,
                'description': 'Non-recurring A 300',
                'salary_rule_id': self.attachement_type.id,
                'date_start': date(2027, 1, 1),
                'amount': 300,
                'is_recurring': False,
                'sequence': 10,  # Higher priority
            },
            {
                'employee_id': self.toto.id,
                'description': 'Non-recurring B 1000',
                'salary_rule_id': self.attachement_type.id,
                'date_start': date(2027, 1, 1),
                'amount': 1000,
                'is_recurring': False,
                'sequence': 20,  # Lower priority
            }
        ])

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.toto.id
        })
        payslip.compute_sheet()
        self._set_attachment_inputs_total(payslip, 800)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        payslip.action_payslip_paid()

        # Higher priority A gets fully paid (300)
        # Lower priority B gets the remaining 500 (800 - 300)
        self.assertEqual(attachment_A.paid_amount, 300)
        self.assertEqual(attachment_A.remaining_amount, 0)
        self.assertEqual(attachment_A.state, '2_close')
        self.assertEqual(attachment_B.paid_amount, 500)
        self.assertEqual(attachment_B.remaining_amount, 500)
        self.assertEqual(attachment_B.state, '1_open')

    @freeze_time('2027-01-01')
    def test_attachments_priority_a_gt_b_eq_c(self):
        """Test three attachments where A has higher priority and B and C have equal priority"""
        attachment_A, attachment_B, attachment_C = self.env['hr.salary.attachment'].create([
            {
                'employee_id': self.toto.id,
                'description': 'Non-recurring A 400',
                'salary_rule_id': self.attachement_type.id,
                'date_start': date(2027, 1, 1),
                'amount': 400,
                'is_recurring': False,
                'sequence': 10,  # Higher priority
            },
            {
                'employee_id': self.toto.id,
                'description': 'Non-recurring B 800',
                'salary_rule_id': self.attachement_type.id,
                'date_start': date(2027, 1, 1),
                'amount': 800,
                'is_recurring': False,
                'sequence': 20,  # Lower priority (same as C)
            },
            {
                'employee_id': self.toto.id,
                'description': 'Non-recurring C 1200',
                'salary_rule_id': self.attachement_type.id,
                'date_start': date(2027, 1, 1),
                'amount': 1200,
                'is_recurring': False,
                'sequence': 20,  # Lower priority (same as B)
            }
        ])

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.toto.id
        })
        payslip.compute_sheet()
        self._set_attachment_inputs_total(payslip, 1000)
        payslip.compute_sheet()
        payslip.action_payslip_done()
        payslip.action_payslip_paid()

        # Higher priority A gets fully paid: 400
        # Remaining 600 is distributed pro-rata between B and C
        # Total B+C remaining = 800 + 1200 = 2000
        # B gets: 800/2000 * 600 = 240
        # C gets: 1200/2000 * 600 = 360
        self.assertEqual(attachment_A.paid_amount, 400)
        self.assertEqual(attachment_A.remaining_amount, 0)
        self.assertEqual(attachment_A.state, '2_close')
        self.assertEqual(attachment_B.paid_amount, 240)
        self.assertEqual(attachment_B.remaining_amount, 560)
        self.assertEqual(attachment_B.state, '1_open')
        self.assertEqual(attachment_C.paid_amount, 360)
        self.assertEqual(attachment_C.remaining_amount, 840)
        self.assertEqual(attachment_C.state, '1_open')

    @freeze_time('2027-01-01')
    def test_recurring_attachment_without_end_date(self):
        """Test recurring attachment without end date continues until manually closed"""
        attachment = self.env['hr.salary.attachment'].create({
            'employee_id': self.toto.id,
            'description': 'Recurring 500',
            'salary_rule_id': self.child_support_type.id,
            'date_start': date(2027, 1, 1),
            'amount': 500,
            'is_recurring': True,
        })

        # First payslip
        self.action_pay_payslip(
            self.toto,
            date(2027, 1, 1),
            date(2027, 1, 31)
        )
        self.assertEqual(attachment.paid_amount, 500)
        self.assertEqual(attachment.remaining_amount, 500)  # Resets for recurring
        self.assertEqual(attachment.state, '1_open')

        # Second payslip
        self.action_pay_payslip(
            self.toto,
            date(2027, 2, 1),
            date(2027, 2, 28)
        )
        self.assertEqual(attachment.paid_amount, 1000)
        self.assertEqual(attachment.remaining_amount, 500)
        self.assertEqual(attachment.state, '1_open')

        # Third payslip
        self.action_pay_payslip(
            self.toto,
            date(2027, 3, 1),
            date(2027, 3, 31)
        )
        self.assertEqual(attachment.paid_amount, 1500)
        self.assertEqual(attachment.remaining_amount, 500)
        self.assertEqual(attachment.state, '1_open')

        # Manually close it
        attachment.action_close()
        self.assertEqual(attachment.state, '2_close')

    @freeze_time('2027-01-01')
    def test_recurring_attachment_with_estimated_end_date(self):
        """Test recurring attachment with estimated end date stops after that date"""
        attachment = self.env['hr.salary.attachment'].create({
            'employee_id': self.toto.id,
            'description': 'Recurring 500 with end date',
            'salary_rule_id': self.child_support_type.id,
            'date_start': date(2027, 1, 1),
            'date_estimated_end': date(2027, 3, 31),
            'amount': 500,
            'is_recurring': True,
        })

        # January payslip
        self.action_pay_payslip(
            self.toto,
            date(2027, 1, 1),
            date(2027, 1, 31)
        )

        self.assertEqual(attachment.paid_amount, 500)
        self.assertEqual(attachment.remaining_amount, 500)
        self.assertEqual(attachment.state, '1_open')

        # February payslip
        self.action_pay_payslip(
            self.toto,
            date(2027, 2, 1),
            date(2027, 2, 28)
        )

        self.assertEqual(attachment.paid_amount, 1000)
        self.assertEqual(attachment.remaining_amount, 500)
        self.assertEqual(attachment.state, '1_open')

        # March payslip (last one within estimated end date)
        self.action_pay_payslip(
            self.toto,
            date(2027, 3, 1),
            date(2027, 3, 31)
        )

        self.assertEqual(attachment.paid_amount, 1500)
        self.assertEqual(attachment.remaining_amount, 500)
        self.assertEqual(attachment.state, '1_open')

        # April payslip (after estimated end date - should not be included)
        payslip4 = self.env['hr.payslip'].create({
            'employee_id': self.toto.id,
            'date_from': date(2027, 4, 1),
            'date_to': date(2027, 4, 30),
        })
        payslip4.compute_sheet()

        # The attachment should not be included in the payslip after the estimated end date
        self.assertNotIn(attachment, payslip4.salary_attachment_ids)

    @freeze_time('2027-01-01')
    def test_attachment_archived_employee(self):
        salary_attachment = self.env['hr.salary.attachment'].create({
            'employee_id': self.toto.id,
            'description': 'Attachment on archived employee',
            'salary_rule_id': self.attachement_type.id,
            'date_start': date(2027, 1, 1),
            'amount': 200,
        })

        # Archive employee
        self.toto.action_archive()
        self.assertFalse(self.toto.active)
        self.assertEqual(salary_attachment.employee_id, self.toto)
        self.assertEqual(salary_attachment.state, '2_close')  # Attachment should be closed

    def test_compute_salary_attachment_display_name(self):
        """Test the computed display name of salary attachments."""
        attachments = self.env['hr.salary.attachment'].create([
            {
                'employee_id': employee.id,
                'salary_rule_id': self.attachement_type.id,
                'amount': 200,
            }
            for employee in (self.toto, self.richard_emp)
        ])

        self.assertRecordValues(attachments, [
            {'display_name': f'{attachment.employee_id.display_name} {self.attachement_type.display_name}'}
            for attachment in attachments
        ])
