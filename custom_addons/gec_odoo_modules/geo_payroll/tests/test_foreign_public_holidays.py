from odoo.tests import TransactionCase, tagged

from odoo.addons.geo_payroll.models.resource_calendar_leaves import FOREIGN_PUBLIC_HOLIDAYS_KEY


@tagged('post_install', '-at_install', 'geo_payroll')
class TestForeignPublicHolidays(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_bool(FOREIGN_PUBLIC_HOLIDAYS_KEY, False)
        Company = cls.env['res.company']
        cls.ge = cls.env.ref('base.ge')
        cls.ge_company = Company.create({'name': 'Holiday GE', 'country_id': cls.ge.id})
        cls.us_company = Company.create({'name': 'Holiday US', 'country_id': cls.env.ref('base.us').id})
        cls.us_other = Company.create({'name': 'Holiday US 2', 'country_id': cls.env.ref('base.us').id})
        cls.no_country_company = Company.create({'name': 'Holiday No Country'})
        cls.us_type = cls.env.ref('hr_work_entry.us_work_entry_type_public_holiday')
        cls.ge_type = cls.env.ref('hr_work_entry.ge_work_entry_type_public_holiday')
        cls.generic_type = cls.env.ref('hr_work_entry.generic_work_entry_type_public_holiday')

    def _holiday(self, company, work_entry_type, day='2027-01-04', **values):
        leave = self.env['resource.calendar.leaves'].create({
            'name': 'Holiday',
            'company_id': company.id,
            'calendar_id': False,
            'date_from': f'{day} 00:00:00',
            'date_to': f'{day} 23:59:59',
            'work_entry_type_id': work_entry_type.id,
            **values,
        })
        self.assertEqual(leave.work_entry_type_id, work_entry_type)
        return leave

    def _remove(self, companies=None):
        self.env['resource.calendar.leaves']._gec_remove_foreign_public_holidays(companies)

    def test_foreign_type_removed_own_and_generic_stay(self):
        foreign = self._holiday(self.ge_company, self.us_type)
        own = self._holiday(self.ge_company, self.ge_type, day='2027-01-05')
        generic = self._holiday(self.ge_company, self.generic_type, day='2027-01-06')
        self._remove()
        self.assertFalse(foreign.exists())
        self.assertTrue(own.exists() and generic.exists())

    def test_other_company_own_country_stays(self):
        leave = self._holiday(self.us_company, self.us_type)
        self._remove()
        self.assertTrue(leave.exists())

    def test_company_without_country_stays(self):
        leave = self._holiday(self.no_country_company, self.us_type)
        self._remove()
        self.assertTrue(leave.exists())

    def test_employee_leave_stays(self):
        resource = self.env['resource.resource'].create({'name': 'Holiday Employee', 'company_id': self.ge_company.id})
        leave = self._holiday(self.ge_company, self.us_type, resource_id=resource.id, calendar_id=resource.calendar_id.id)
        self._remove()
        self.assertTrue(leave.exists())

    def test_scoped_to_given_companies(self):
        leave = self._holiday(self.ge_company, self.us_type)
        self._remove(self.us_company)
        self.assertTrue(leave.exists())
        self._remove(self.ge_company)
        self.assertFalse(leave.exists())

    def test_country_change_removes_old_country_holidays(self):
        leave = self._holiday(self.us_company, self.us_type)
        other = self._holiday(self.us_other, self.us_type)
        self.us_company.write({'country_id': self.ge.id})
        self.assertFalse(leave.exists())
        self.assertTrue(other.exists())

    def test_partner_country_change_removes_old_country_holidays(self):
        leave = self._holiday(self.us_company, self.us_type)
        self.us_company.partner_id.country_id = self.ge
        self.assertFalse(leave.exists())

    def test_second_call_removes_nothing(self):
        leave = self._holiday(self.ge_company, self.us_type)
        own = self._holiday(self.ge_company, self.ge_type, day='2027-01-05')
        self._remove()
        self._remove()
        self.assertFalse(leave.exists())
        self.assertTrue(own.exists())

    def test_structure_type_foreign_time_type_replaced(self):
        us_attendance = self.env.ref('hr_work_entry.us_work_entry_type_attendance')
        ge_attendance = self.env['hr.work.entry.type'].search([('code', '=', us_attendance.code), ('country_id', '=', self.ge.id)], limit=1)
        StructureType = self.env['hr.payroll.structure.type']
        ge_type = StructureType.create({'name': 'GE type', 'country_id': self.ge.id, 'default_work_entry_type_id': us_attendance.id})
        us_type = StructureType.create({'name': 'US type', 'country_id': self.env.ref('base.us').id, 'default_work_entry_type_id': us_attendance.id})
        StructureType._gec_fix_foreign_default_work_entry_type()
        self.assertEqual(ge_type.default_work_entry_type_id, ge_attendance)
        self.assertEqual(us_type.default_work_entry_type_id, us_attendance)
