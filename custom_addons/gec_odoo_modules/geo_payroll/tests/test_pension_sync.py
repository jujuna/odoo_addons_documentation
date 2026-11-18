from .common import GeoPayrollCase


class TestPensionSync(GeoPayrollCase):

    def _employee_with_contact(self):
        employee = self._make_employee('fixed')
        self.assertTrue(employee.work_contact_id)
        return employee

    def test_employee_write_pushes_to_partner(self):
        employee = self._employee_with_contact()
        employee.pension_fund_member = True
        self.assertTrue(employee.work_contact_id.pension_fund_member)
        employee.pension_fund_member = False
        self.assertFalse(employee.work_contact_id.pension_fund_member)

    def test_partner_write_pushes_to_employee(self):
        employee = self._employee_with_contact()
        employee.work_contact_id.pension_fund_member = True
        self.assertTrue(employee.pension_fund_member)
        employee.work_contact_id.pension_fund_member = False
        self.assertFalse(employee.pension_fund_member)

    def test_create_with_flag_pushes_to_new_contact(self):
        employee = self.env['hr.employee'].create({
            'name': 'Pension Member',
            'company_id': self.company.id,
            'pension_fund_member': True,
        })
        self.assertTrue(employee.work_contact_id)
        self.assertTrue(employee.work_contact_id.pension_fund_member)

    def test_relink_pulls_partner_value(self):
        employee = self._employee_with_contact()
        partner = self.env['res.partner'].create({'name': 'Existing Member', 'pension_fund_member': True})
        employee.work_contact_id = partner
        self.assertTrue(employee.pension_fund_member)

    def test_partner_shared_by_two_employees(self):
        first = self._employee_with_contact()
        second = self._make_employee('fixed')
        second.work_contact_id = first.work_contact_id
        first.pension_fund_member = True
        self.assertTrue(second.pension_fund_member)
