from odoo import api, models
from odoo.exceptions import UserError


class HrPayslipRun(models.Model):
    _inherit = 'hr.payslip.run'

    def _gec_is_overtime_run(self, structure_id=None):
        structure = self.env.ref('geo_payroll.structure_geo_overtime', raise_if_not_found=False)
        return bool(structure) and (structure_id or self.structure_id.id) == structure.id

    def _get_valid_versions(self, date_start=None, date_end=None, structure_id=None, company_id=None, employee_type_ids=None, employee_ids=None):
        """Core keeps only versions of the structure's type, which no employee has for GEO Overtime."""
        if not self._gec_is_overtime_run(structure_id):
            return super()._get_valid_versions(date_start=date_start, date_end=date_end, structure_id=structure_id, company_id=company_id,
                employee_type_ids=employee_type_ids, employee_ids=employee_ids)
        company = company_id or self.company_id.id
        domain = [
            ('company_id', '=', company),
            ('employee_id.company_id', '=', company),
            ('type', '=', 'overtime'),
            ('state', '=', 'approved'),
            ('date', '<=', date_end or self.date_end),
            ('version_id.overtime_pay_mode', '=', 'separate'),
            ('settlement_ids', 'not any', [('active_claim', '=', True)]),
        ]
        if employee_ids:
            domain.append(('employee_id', 'in', employee_ids))
        logs = self.env['hr.employee.work.log'].search(domain, order='date desc, id desc')
        return self.env['hr.version'].browse([employee_logs[0].version_id.id for employee_logs in logs.grouped('employee_id').values()])

    def _generate_payslips(self, versions=None):
        """A slip that claims nothing (paid elsewhere meanwhile) is removed instead of raising."""
        self.ensure_one()
        if not self._gec_is_overtime_run():
            return super()._generate_payslips(versions=versions)
        if not self.version_ids:
            raise UserError(self.env._("No approved unpaid overtime was found for the selected employees: approve their overtime work logs and "
                "check that Overtime Payment on their contract is Separate Payslip."))
        candidate_versions = self.version_ids if versions is None else versions & self.version_ids
        slips = self.env['hr.payslip'].with_context(tracking_disable=True).create([{
            'name': self.env._('Overtime Payslip'),
            'employee_id': version.employee_id.id,
            'version_id': version.id,
            'company_id': self.company_id.id,
            'date_from': self.date_start,
            'date_to': self.date_end,
            'struct_id': self.structure_id.id,
            'payslip_run_id': self.id,
        } for version in candidate_versions - self.slip_ids.version_id])
        slips._compute_name()
        slips.compute_sheet()
        empty = slips.filtered(lambda slip: not slip.gec_settlement_ids.filtered('active_claim'))
        empty.unlink()
        return slips - empty

    def action_draft(self):
        """Reset a safe run: realign base slips first and release entries so validation books new ones."""
        for run in self:
            run.slip_ids._gec_check_correction_balance_after_removal(self.env._('reset to draft'))
        reopened = self.slip_ids.filtered(lambda slip: slip.state != 'draft')
        reopened._gec_prepare_reset_to_draft()
        res = super().action_draft()
        reopened._gec_release_journal_entries()
        return res

    @api.ondelete(at_uninstall=False)
    def _gec_release_run_settlements(self):
        settlements = self.slip_ids.gec_settlement_ids.filtered('active_claim')
        if settlements:
            settlements._release(self.env._('Pay run deleted'))
