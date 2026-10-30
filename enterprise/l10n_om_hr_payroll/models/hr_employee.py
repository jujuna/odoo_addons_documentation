from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    l10n_om_employee_is_eos_eligible = fields.Boolean(readonly=False, related="version_id.l10n_om_employee_is_eos_eligible", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_om_employee_old_age_disability_death_insurance_percentage = fields.Float(readonly=False, related="version_id.l10n_om_employee_old_age_disability_death_insurance_percentage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_om_employee_work_injury_insurance_percentage = fields.Float(readonly=False, related="version_id.l10n_om_employee_work_injury_insurance_percentage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_om_employee_unemployment_insurance_percentage = fields.Float(readonly=False, related="version_id.l10n_om_employee_unemployment_insurance_percentage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_om_employee_sick_leave_insurance_percentage = fields.Float(readonly=False, related="version_id.l10n_om_employee_sick_leave_insurance_percentage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_om_employee_maternity_leave_insurance_percentage = fields.Float(readonly=False, related="version_id.l10n_om_employee_maternity_leave_insurance_percentage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_om_company_old_age_disability_death_insurance_percentage = fields.Float(readonly=False, related="version_id.l10n_om_company_old_age_disability_death_insurance_percentage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_om_company_work_injury_insurance_percentage = fields.Float(readonly=False, related="version_id.l10n_om_company_work_injury_insurance_percentage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_om_company_unemployment_insurance_percentage = fields.Float(readonly=False, related="version_id.l10n_om_company_unemployment_insurance_percentage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_om_company_sick_leave_insurance_percentage = fields.Float(readonly=False, related="version_id.l10n_om_company_sick_leave_insurance_percentage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_om_company_maternity_leave_insurance_percentage = fields.Float(readonly=False, related="version_id.l10n_om_company_maternity_leave_insurance_percentage", inherited=True, groups="hr_payroll.group_hr_payroll_user")
    l10n_om_remaining_annual_leave_balance = fields.Float(compute="_compute_l10n_om_remaining_annual_leave_balance", groups="hr_payroll.group_hr_payroll_user")
    l10n_om_identification_type = fields.Selection(readonly=False, related="version_id.l10n_om_identification_type", inherited=True, groups="hr_payroll.group_hr_payroll_user")

    def _compute_l10n_om_remaining_annual_leave_balance(self):
        om_employees = self.filtered(lambda e: e.company_country_code == 'OM')
        for employee in (self - om_employees):
            employee.l10n_om_remaining_annual_leave_balance = 0

        emp_per_company_and_date = om_employees.grouped(
            lambda e: (e.company_id, e.departure_date)
        )
        allocation_data_per_employee = {}
        for (company, departure_date), employees in emp_per_company_and_date.items():
            work_entry_type = company.l10n_om_annual_work_entry_type_id
            if not work_entry_type:
                continue
            allocation_data_per_employee.update(
                work_entry_type.get_allocation_data(employees, target_date=departure_date)
            )

        for employee in om_employees:
            employee_allocation_data = allocation_data_per_employee.get(employee, False)
            employee.l10n_om_remaining_annual_leave_balance = (
                employee_allocation_data[0][1]['remaining_leaves'] if employee_allocation_data else 0
        )
