from collections import defaultdict

from odoo import api, models
from odoo.exceptions import UserError
from odoo.tools import formatLang

from .tools import gec_lock_for_update


class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    @api.model_create_multi
    def create(self, vals_list):
        self._gec_drop_copied_benefit_inputs(vals_list)
        slips = super().create(vals_list)
        for slip in slips.filtered(lambda slip: slip.is_correction_payslip and not slip.edited):
            commands = slip._benefit_mirror_root_inputs()
            if commands:
                slip.update({'input_line_ids': commands})
        # A form-saved slip keeps the client input list (built without benefits): recompute with real ids.
        fresh = slips.filtered(lambda slip: slip.state == 'draft' and not slip.edited)
        if fresh:
            self.env.add_to_compute(fresh._fields['input_line_ids'], fresh)
        return slips

    def _gec_is_unedited_draft_base(self):
        self.ensure_one()
        return (
            self.state == 'draft'
            and not self.edited
            and not self.credit_note
            and not self.origin_payslip_id
            and bool(self.struct_id)
            and self.struct_id == self.struct_id.type_id.default_struct_id
        )

    def _gec_align_draft_base_structures(self):
        aligned = self.env['hr.payslip']
        for slip in self:
            default_structure = slip.version_id.sudo().structure_type_id.default_struct_id
            if slip._gec_is_unedited_draft_base() and default_structure and slip.struct_id != default_structure:
                slip.struct_id = default_structure
                aligned |= slip
        return aligned

    @api.depends('version_id')
    def _compute_struct_id(self):
        # Capture before super(): core fills only an empty structure, so an old default would stay.
        candidates = self.filtered(lambda slip: slip._gec_is_unedited_draft_base())
        super()._compute_struct_id()
        candidates._gec_align_draft_base_structures()

    def _gec_is_overtime(self):
        self.ensure_one()
        structure = self.env.ref('geo_payroll.structure_geo_overtime', raise_if_not_found=False)
        return bool(structure) and self.struct_id == structure

    def _gec_is_overtime_base(self):
        self.ensure_one()
        return self._gec_is_overtime() and not self.credit_note and not self.origin_payslip_id

    def _gec_is_regular_base(self):
        self.ensure_one()
        return self.is_regular and not self.credit_note and not self.origin_payslip_id

    def _gec_check_no_overlap(self):
        """Block overlapping base slips on one contract: one slip already pays all its versions."""
        for slip in self:
            if not slip._gec_is_regular_base() or not slip.version_id:
                continue
            gec_lock_for_update(slip.employee_id, allow_referencing=True)
            contract_key = slip.version_id.sudo()._get_version_lookup_key()
            others = self.env['hr.payslip'].sudo().search([
                ('id', '!=', slip.id),
                ('employee_id', '=', slip.employee_id.id),
                ('company_id', '=', slip.company_id.id),
                ('state', '!=', 'cancel'),
                ('credit_note', '=', False),
                ('origin_payslip_id', '=', False),
                ('date_from', '<=', slip.date_to),
                ('date_to', '>=', slip.date_from),
            ]).filtered(lambda other: other.is_regular and other.version_id
                        and other.version_id._get_version_lookup_key() == contract_key)
            if others:
                raise UserError(self.env._("%(employee)s already has a regular payslip for the same contract in this period (%(names)s): cancel one "
                    "of them so the base salary is not paid twice.", employee=slip.employee_id.name, names=', '.join(others.mapped('name'))))

    def _gec_mixed_pay_route_slips(self):
        """The payslip's structure computes every version, so a mixed route would misprice later days."""
        mixed = self.browse()
        for slip in self.filtered(lambda slip: slip._gec_is_regular_base() and slip.version_id):
            version = slip.version_id.sudo()
            contract_key = version._get_version_lookup_key()
            versions = version | slip.employee_id.sudo().version_ids.filtered(
                lambda v: v._get_version_lookup_key() == contract_key
                and slip.date_from <= v.date_version <= slip.date_to)
            if len({(v.structure_type_id, v._gec_uses_timesheet_hourly_base()) for v in versions}) > 1:
                mixed |= slip
        return mixed

    def _gec_short_fixed_period_slips(self):
        return self.filtered(lambda slip: slip._gec_is_regular_base() and slip.wage_type == 'monthly'
            and (slip.version_id.schedule_pay or slip.version_id.structure_type_id.default_schedule_pay)
            and slip.date_from + slip._get_schedule_timedelta() != slip.date_to)

    def _gec_money(self, amount):
        """Tooltip amount, rounded half-up like the payslip line totals."""
        return formatLang(self.env, amount, currency_obj=self.currency_id, rounding_method='HALF-UP')

    def compute_sheet(self):
        draft_slips = self.filtered(lambda slip: slip.state == 'draft')
        for slip in draft_slips._gec_align_draft_base_structures():
            slip.message_post(body=self.env._("Salary structure reset to %(structure)s, the default of the contract.",
                structure=slip.struct_id.display_name))
        edited_with_claims = draft_slips.filtered(lambda slip: slip.edited and slip.gec_settlement_ids.filtered('active_claim'))
        if edited_with_claims:
            raise UserError(self.env._("These edited payslips already contain work logs or timesheets and cannot be recomputed: %(names)s. "
                "Validate or cancel them.", names=', '.join(edited_with_claims.mapped('name'))))
        draft_slips._gec_release_stale_claims()
        draft_slips._gec_claim_work_logs()
        draft_slips._gec_claim_timesheets()
        draft_slips._gec_check_claims()
        return super().compute_sheet()

    def _get_localdict(self, work_entries=None):
        """Core pre-fills BASIC from attendance and skips a forced line's code, so GROSS would ignore the edit."""
        localdict = super()._get_localdict(work_entries)
        forced = self.env.context.get('force_payslip_line_overrides', {}).get('BASIC')
        if forced and 'amount' in forced and self.struct_id.country_code == 'GE':
            basic = self.struct_id.rule_ids.filtered(lambda rule: rule.code == 'BASIC' and not rule.category_ids)
            if basic:
                localdict['categories']['BASIC'] = self._get_payslip_line_total(forced['amount'], forced['quantity'], forced['rate'], basic)
        return localdict

    def _gec_check_overtime_payslips(self):
        allowed = {'WORKLOG_OT', 'GROSS', 'PENSION_EE', 'PIT', 'PENSION_ER', 'NET'}
        for slip in self.filtered(lambda slip: slip._gec_is_overtime()):
            if set(slip.line_ids.mapped('code')) - allowed or slip.input_line_ids:
                raise UserError(self.env._('An overtime payslip may contain only overtime, income tax, pension and net pay. Remove the extra lines '
                    'or inputs and recompute.'))
            if slip._gec_is_overtime_base() and not slip.gec_settlement_ids.filtered('active_claim'):
                raise UserError(self.env._('There is no approved unpaid overtime on this payslip.'))

    def _gec_validation_groups(self):
        """Slips of one person with the same start date share the yearly tax allowance, so go to consecutive groups."""
        groups = defaultdict(lambda: self.browse())
        placed = defaultdict(int)
        for slip in self.sorted(key=lambda slip: (slip.date_from, slip.id)):
            person = slip.employee_id.sudo().identification_id or slip.employee_id.id
            key = (person, slip.date_from)
            groups[placed[key]] |= slip
            placed[key] += 1
        return [groups[index] for index in sorted(groups)]

    def action_payslip_done(self):
        self._gec_check_one_entry_per_payslip()
        self._gec_check_correction_chains()
        self._gec_check_no_overlap()
        self._gec_check_claims()
        self._gec_check_lines_match_settlements()
        self._benefit_check_inputs_match_lines()
        self._gec_check_overtime_payslips()
        res = None
        # Lock every sibling employee record: the allowance is pooled per person across companies.
        gec_lock_for_update(self._gec_exemption_persons().sorted('id'), allow_referencing=True)
        for group in self._gec_validation_groups():
            for slip in group:
                slip._gec_check_current_exemption_tax()
            res = super(HrPayslip, group).action_payslip_done()
            group._benefit_record_consumption()
        self.filtered('origin_payslip_id')._gec_settle_correction_family()
        return res

    def _gec_check_not_paid(self):
        """Refuse to cancel or reopen paid payslips: core would drop the entry but keep the payment."""
        paid = self.filtered(lambda slip: slip.state == 'paid')
        if paid:
            raise UserError(self.env._("These payslips are already paid: %(names)s. Use Correct to change them, or Mark Unpaid first if the payment "
                "was reversed.", names=', '.join(paid.mapped('name'))))

    def action_payslip_cancel(self):
        """Cancel; refuse paid slips. The entry is released first so a reopened slip books a new one."""
        self._gec_check_not_paid()
        self._benefit_check_no_live_installments()
        self._gec_check_correction_balance_after_removal(self.env._('cancelled'))
        self._gec_release_journal_entries()
        res = super().action_payslip_cancel()
        self.gec_settlement_ids.filtered('active_claim')._release(self.env._('Payslip cancelled'))
        self._benefit_release_consumption()
        return res

    def _gec_prepare_reset_to_draft(self):
        """Realigns base slips before core's reset or refresh, keeping date_to; edited slips keep their structure."""
        for slip in self.filtered(lambda slip: slip._gec_is_regular_base() and not slip.edited):
            default_structure = slip.version_id.structure_type_id.default_struct_id
            if default_structure and slip.struct_id != default_structure:
                slip.write({'struct_id': default_structure.id, 'date_to': slip.date_to})

    def action_refresh_from_work_entries(self):
        """Realign base slips and refresh the benefit inputs with the lines; core would keep stale ones."""
        fresh = self.filtered(lambda slip: slip.state == 'draft' and not slip.edited)
        fresh._gec_prepare_reset_to_draft()
        if fresh:
            self.env.add_to_compute(fresh._fields['input_line_ids'], fresh)
        return super().action_refresh_from_work_entries()

    def action_payslip_draft(self):
        self._gec_check_not_paid()
        validated = self.filtered(lambda slip: slip.state == 'validated')
        validated._gec_check_correction_balance_after_removal(self.env._('reset to draft'))
        self.filtered(lambda slip: slip.state in ('validated', 'cancel'))._gec_release_journal_entries()
        self.filtered(lambda slip: slip.state == 'cancel')._gec_prepare_reset_to_draft()
        return super().action_payslip_draft()
