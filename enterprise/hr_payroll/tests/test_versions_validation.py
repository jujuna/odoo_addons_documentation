from datetime import date, datetime

from odoo.tests import Form, tagged
from odoo.exceptions import ValidationError
from .common import TestPayslipBase


@tagged('-at_install', 'post_install')
class TestVersionsValidation(TestPayslipBase):

    def test_01_archive_version_with_draft_payslip_allowed(self):
        version = self.env['hr.version'].create({
            'name': 'Active Version',
            'employee_id': self.richard_emp.id,
            'date_start': datetime(2025, 1, 1),
            'date_end': datetime(2025, 1, 31),
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.richard_emp.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'state': 'draft',
        })
        self.assertEqual(payslip.state, 'draft')

        version.write({'active': False})
        self.assertFalse(version.active)

    def test_02_archive_version_with_validated_payslip(self):
        version = self.richard_emp.create_version({
            'name': "Active Version",
            'date_version': '2025-01-01',
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.richard_emp.id,
            'version_id': version.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'state': 'draft',
        })
        payslip.action_validate()

        with self.assertRaises(ValidationError, msg="Should prevent archive version with validated payslip."):
            version.write({'active': False})

        payslip.action_payslip_draft()
        version.write({'active': False})

    def test_03_delete_version_with_validated_payslip(self):
        version = self.richard_emp.create_version({
            'name': "Active Version",
            'date_version': '2025-01-01',
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.richard_emp.id,
            'version_id': version.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 31),
            'state': 'draft',
        })
        payslip.action_validate()

        with self.assertRaises(ValidationError, msg="Should prevent delete version with validated payslip."):
            version.unlink()

    def test_04_validate_payslip_linked_to_archived_version(self):
        version = self.richard_emp.create_version({
            'name': "Archived Version",
            'date_version': '2025-01-01',
            'active': False,
        })

        payslip = self.env['hr.payslip'].create({
            'employee_id': self.richard_emp.id,
            'version_id': version.id,
            'date_from': date(2025, 1, 1),
            'date_to': date(2025, 1, 30),
            'state': 'draft',
        })

        with self.assertRaises(ValidationError, msg="Should prevent validate payslip with archived version."):
            payslip.action_validate()

        version.active = True
        payslip.action_validate()

    def test_05_new_payslip_ignores_archived_version(self):
        """ The version of a new payslip, in the form, is the active version of its period: an archived
        version replacing it during the previous month is ignored. """
        employee = self.env['hr.employee'].create({
            'name': 'Archived Version Employee',
            'date_version': date(2025, 10, 1),
            'contract_date_start': date(2025, 10, 1),
            'wage': 3000,
            'structure_type_id': self.structure_type.id,
        })
        new_salary_version = employee.create_version({'date_version': date(2026, 10, 1), 'wage': 3500})
        employee.create_version({'date_version': date(2026, 10, 15), 'wage': 4000}).action_archive()

        payslip_form = Form(self.env['hr.payslip'].with_context(
            default_employee_id=employee.id,
            default_date_from=date(2026, 11, 1),
        ))
        self.assertEqual(payslip_form.version_id, new_salary_version)
        self.assertEqual(payslip_form.allowed_version_ids[:], new_salary_version)
