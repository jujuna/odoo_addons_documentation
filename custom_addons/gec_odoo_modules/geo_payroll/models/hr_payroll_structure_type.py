import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class HrPayrollStructureType(models.Model):
    _inherit = 'hr.payroll.structure.type'

    wage_type = fields.Selection(selection_add=[('daily', 'Daily Wage'), ('unit', 'Unit Wage')],
        ondelete={'daily': 'set monthly', 'unit': 'set monthly'})

    def _gec_set_missing_default_struct(self, structure_id):
        """Data hook: set default_struct_id only where empty, so a customer's choice survives upgrades."""
        self.filtered(lambda stype: not stype.default_struct_id).default_struct_id = structure_id

    @api.model
    def _gec_fix_foreign_default_work_entry_type(self):
        """Core picks the Time Type from the company country at creation: a later country change leaves a type its users cannot read."""
        # sudo: the foreign time type is hidden from the company's users by the hr.work.entry.type country restriction
        WorkEntryType = self.env['hr.work.entry.type'].sudo()
        company_countries = self.env['res.company'].sudo().search([]).country_id
        for stype in self.sudo().search([('default_work_entry_type_id.country_id', '!=', False)]):
            current = stype.default_work_entry_type_id
            if current.country_id == stype.country_id or (not stype.country_id and current.country_id in company_countries):
                continue
            new = (stype.country_id and WorkEntryType.search([('code', '=', current.code), ('country_id', '=', stype.country_id.id)], limit=1)
                or WorkEntryType.search([('code', '=', current.code), ('country_id', '=', False)], limit=1))
            if new:
                _logger.info("Structure type %s: Time Type %s replaced by %s", stype.id, current.id, new.id)
                stype.default_work_entry_type_id = new

    @api.model
    def _gec_retire_core_ge_structure(self):
        """Odoo's Georgian structure books income tax on an account Pay Salaries cannot pay: contracts never paid on its type, with a gross wage,
        no tax privilege, the standard company regime and no contract allowance move to our type; the rest stay on Odoo's type until someone
        sets them up by hand. Odoo keeps the pension choice on the contract, we keep it on the employee: only the current contract copies it."""
        core_type = self.env.ref('l10n_ge_hr_payroll.structure_type_employee_ge', raise_if_not_found=False)
        core_structure = self.env.ref('l10n_ge_hr_payroll.hr_payroll_structure_ge_employee_salary', raise_if_not_found=False)
        if not core_type or not core_structure:
            return
        Version = self.env['hr.version'].with_context(active_test=False)
        used = self.env['hr.payslip'].search([('struct_id.type_id', '=', core_type.id)]).version_id
        moved = Version.search([
            ('structure_type_id', '=', core_type.id),
            ('l10n_ge_net_salary', '=', False),
            ('l10n_ge_tax_privilege', '=', 'none'),
            ('company_id.l10n_ge_tax_regime', '=', 'standard'),
        ]) - used
        moved = moved.filtered(lambda version: not any(dict(version.payroll_properties).values()))
        current = moved.employee_id.current_version_id & moved
        current.filtered(lambda version: version.l10n_ge_pension_status == 'participant').employee_id.pension_fund_member = True
        for wage_type, versions in moved.grouped('wage_type').items():
            versions.structure_type_id = self.env.ref(f'geo_payroll.structure_type_geo_{wage_type}')
        if Version.search_count([('structure_type_id', '=', core_type.id)], limit=1):
            # Core gives a new contract the first type of its country: while Odoo's type stays, ours must come before it.
            core_type.sequence = max((self.search([('country_id', '=', core_type.country_id.id)]) - core_type).mapped('sequence')) + 1
        else:
            core_type.action_archive()
            core_structure.action_archive()

    @api.constrains('default_struct_id')
    def _check_benefits_type_stays_off_cycle(self):
        """Keep the default empty: benefits payslips must stay non-regular, outside the double-pay guards."""
        for kind in ('benefits', 'overtime'):
            structure_type = self.env.ref(f'geo_payroll.structure_type_geo_{kind}', raise_if_not_found=False)
            if structure_type and structure_type in self and structure_type.default_struct_id:
                raise ValidationError(self.env._("Leave the default structure of %(name)s empty: it is used only for separate payments, not for "
                    "regular salary.", name=structure_type.name))
