# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install_l10n', 'post_install', '-at_install')
class TestHrEmployee(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_ch = cls.env['res.company'].create({
            'name': 'Swiss Company',
            'country_id': cls.env.ref('base.ch').id,
            'currency_id': cls.env.ref('base.CHF').id,
        })
        cls.hr_manager = new_test_user(
            cls.env,
            login='swiss_hr_manager',
            groups='base.group_user,hr.group_hr_manager,base.group_partner_manager',
            name='Swiss HR Manager',
        )
        cls.hr_manager.write({
            'company_id': cls.company_ch.id,
            'company_ids': [Command.link(cls.company_ch.id)],
        })

    def test_non_payroll_hr_manager_can_create_swiss_employee(self):
        self.assertFalse(self.hr_manager.has_group('hr_payroll.group_hr_payroll_user'))

        employee = self.env['hr.employee'].with_user(self.hr_manager).with_company(self.company_ch).create({
            'name': 'Swiss Employee',
            'company_id': self.company_ch.id,
        })

        self.assertEqual(employee.company_id, self.company_ch)

    def test_certificate_default_only_for_swiss_companies(self):
        """The Swiss certificate levels only exist for the Swiss companies: the default must not be given
        to the employees of the other companies."""
        company_be = self.env['res.company'].create({
            'name': 'Belgian Company',
            'country_id': self.env.ref('base.be').id,
        })
        swiss_employee, belgian_employee = (
            self.env['hr.employee'].with_company(company).create({'name': 'Employee', 'company_id': company.id})
            for company in (self.company_ch, company_be)
        )
        self.assertEqual(swiss_employee.certificate, 'mandatorySchoolOnly')
        self.assertFalse(belgian_employee.certificate)
