from datetime import date

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_date


class HrPayrollSalaryIncrease(models.TransientModel):
    _inherit = 'hr.payroll.salary.increase'

    type = fields.Selection(string="Type", selection=[('manual', 'Manual'), ('legal', 'Legal Indexation')], default='manual', required=True)
    year = fields.Char(string="Year", required=True, default=lambda self: str(fields.Date.context_today(self).year))
    rate = fields.Float(string="Rate (%)", required=True, compute="_compute_rate")
    legal_indexation_available = fields.Boolean(
        string="Legal Indexation Available",
        compute="_compute_legal_indexation_available",
    )
    legal_indexation_warning = fields.Char(string="Legal Indexation Warning", compute="_compute_legal_indexation_available")
    country_code = fields.Char(related='company_id.country_id.code', readonly=True)

    @api.depends('employee_ids', 'year')
    def _compute_legal_indexation_available(self):
        for record in self:
            if not record.employee_ids or not record.year or not record.year.isdigit():
                record.legal_indexation_available = False
                record.legal_indexation_warning = self.env._("Please select employees and year to check legal indexation availability.")
                continue
            if any(not employee.l10n_be_egov3_code for employee in record.employee_ids):
                record.legal_indexation_available = False
                record.legal_indexation_warning = self.env._("The following employees do not have a Joint Committee assigned: %s", ", ".join(employee.name for employee in record.employee_ids if not employee.l10n_be_egov3_code))
                continue
            egov3_codes = set(filter(None, record.employee_ids.mapped('l10n_be_egov3_code')))
            if len(egov3_codes) > 1:
                record.legal_indexation_available = False
                record.legal_indexation_warning = self.env._("The following employees are assigned to different Joint Committees: %s", ", ".join(record.employee_ids.mapped('name')))
                continue
            egov3_code = next(iter(egov3_codes))
            rule_parameter = self.env["hr.rule.parameter"]._get_parameter_from_code(
                "l10n_be_legal_index",
                date=date(int(record.year), 1, 1),
                raise_if_not_found=False,
            )
            record.legal_indexation_available = bool(
                rule_parameter and rule_parameter.get(egov3_code),
            )
            record.legal_indexation_warning = (
                self.env._(
                    "The selected employees do not belong to a Joint Committee eligible for legal indexation: %s",
                    ", ".join(record.employee_ids.mapped("name")),
                )
                if not record.legal_indexation_available
                else ""
            )

    @api.onchange('employee_ids', 'year')
    def _onchange_legal_indexation_availability(self):
        if not self.legal_indexation_available:
            self.type = 'manual'

    @api.onchange('type', 'year')
    def _onchange_type_year(self):
        if self.type == 'legal' and self.year and self.year.isdigit():
            self.increase_date = date(int(self.year), 1, 1)

    @api.depends('type', 'year', 'employee_ids')
    def _compute_rate(self):
        for record in self:
            record.rate = 0.0
            if record.type != 'legal' or not record.year or not record.year.isdigit():
                continue
            rule_parameter = self.env["hr.rule.parameter"]._get_parameter_from_code(
                "l10n_be_legal_index", date=date(int(record.year), 1, 1), raise_if_not_found=False,
            )
            egov3_code = record.employee_ids[:1].l10n_be_egov3_code
            if rule_parameter and egov3_code and rule_parameter.get(egov3_code):
                record.rate = rule_parameter[egov3_code][0]

    def _indexation_issues_check(self):
        if self.type == 'manual':
            return super()._indexation_issues_check()
        if len(set(self.employee_ids.mapped('l10n_be_egov3_code'))) > 1:
            raise UserError(self.env._("All selected employees must have the same joint committee for legal indexation."))

    def _index_wage(self, employee, base_version):
        self.ensure_one()
        wage_field = base_version._get_contract_wage_field()
        if self.type == 'manual':
            super()._index_wage(employee, base_version)
            return

        legal_index = self._get_legal_indexed_wage(base_version)
        if not legal_index:
            return
        new_wage, capped_amount = legal_index

        if base_version.date_version != self.increase_date:
            employee.create_version({
                'date_version': self.increase_date,
                wage_field: new_wage,
                'l10n_be_capped_amount': capped_amount or False,
            })
        else:
            base_version[wage_field] = new_wage
            base_version.l10n_be_capped_amount = capped_amount

    def _get_legal_indexed_wage(self, version):
        """ Returns the legally indexed wage of the version and the part of its wage above the cap, or None when
            the version isn't concerned by a legal indexation. """
        self.ensure_one()
        rule_parameters = self.env["hr.rule.parameter"]._get_parameter_from_code(
            "l10n_be_legal_index", date=date(int(self.year), 1, 1), raise_if_not_found=False,
        )
        if not rule_parameters or not rule_parameters.get(version.l10n_be_egov3_code):
            return None
        rate, cap = rule_parameters.get(version.l10n_be_egov3_code)
        # Convert the wage to monthly equivalent salary (for hourly/daily paid employees  and part-timers)
        reference_wage = version._l10n_be_get_monthly_wage(int(self.year))
        # The cap applies to a full-time reference wage: a part-time wage is converted to a full-time one (Q/S),
        # and the increase computed on it is prorated back to the part-time
        work_time_rate = version.work_time_rate or 1.0
        full_time_wage = reference_wage / work_time_rate
        capped_amount = max(full_time_wage - (cap or full_time_wage), 0) * work_time_rate
        new_reference_wage = reference_wage + self._compute_increase_amount(full_time_wage, cap, rate) * work_time_rate
        new_wage = version._get_wage_from_reference_salary(int(self.year), new_reference_wage)
        return new_wage, capped_amount

    def _index_future_versions(self, future_versions):
        self.ensure_one()
        if self.type != 'legal':
            super()._index_future_versions(future_versions)
            return
        for version in future_versions:
            legal_index = self._get_legal_indexed_wage(version)
            if not legal_index:
                continue
            new_wage, capped_amount = legal_index
            version[version._get_contract_wage_field()] = new_wage
            version.l10n_be_capped_amount = capped_amount

    def _generate_indexation_message(self, future_affected_versions):
        if self.type == 'manual':
            return super()._generate_indexation_message(future_affected_versions)

        egov3_code = self.employee_ids[:1].l10n_be_egov3_code
        rule_parameters = self.env['hr.rule.parameter']._get_parameter_from_code(
            'l10n_be_legal_index',
            date=date(int(self.year), 1, 1),
            raise_if_not_found=False,
        )
        params = rule_parameters.get(egov3_code) if rule_parameters and egov3_code else None
        rate, cap = params if params else (0.0, False)
        message_body = self.env._(
            'Wage legally indexed by %(percentage).2f%%%(capped)s starting from %(increase_date)s on %(date)s.',
            percentage=rate * 100,
            capped=self.env._(' (capped at %(cap)s)', cap=self.currency_id.format(cap)) if cap else '',
            increase_date=format_date(self.env, fields.Date.to_date(f"{self.year}-01-01")),
            date=format_date(self.env, fields.Date.today()),
        )
        if future_affected_versions:
            message_body += Markup("<br/><b>%s</b><ul>") % self.env._("Impacted Employee Records:")
            for v in future_affected_versions:
                message_body += Markup("<li><b>%s</b></li>") % v.display_name
            message_body += Markup("</ul>")
        return message_body

    def _compute_increase_amount(self, current_wage, cap, rate):
        self.ensure_one()
        # the first 2% of the index only apply to the capped reference wage, the index above 2% to the whole wage
        if cap and current_wage > cap:
            return (cap * min(rate, 0.02)) + (current_wage * max(rate - 0.02, 0))
        return current_wage * rate
