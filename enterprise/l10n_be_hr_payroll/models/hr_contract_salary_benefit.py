from odoo import api, fields, models
from odoo.exceptions import UserError


class HrContractSalaryBenefit(models.Model):
    _inherit = 'hr.contract.salary.benefit'

    l10n_be_joint_committee_ids = fields.Many2many(
        comodel_name='l10n.be.joint.committee',
        string="Joint Committees",
        help="The benefit is activated with the first of these joint committees, and archived with the last one.",
        context={'active_test': False},
    )
    l10n_be_excluded_joint_committee_ids = fields.Many2many(
        comodel_name='l10n.be.joint.committee',
        relation='hr_contract_salary_benefit_excluded_joint_committee_rel',
        string="Excluded Joint Committees",
        help="List all joint committees where the benefit rule should not be applied",
        context={'active_test': False},
    )

    def _is_available_for_joint_committee(self, joint_committee):
        self.ensure_one()
        return (
            (not self.l10n_be_joint_committee_ids or (
                joint_committee and joint_committee.is_descendant_of(self.l10n_be_joint_committee_ids)
            ))
            and not (
                joint_committee
                and joint_committee.is_descendant_of(self.l10n_be_excluded_joint_committee_ids)
            )
        )

    def _l10n_be_get_onss_values(self, benefits_by_version):
        """ Monthly amount subject to ONSS of the benefits of each version: the total of their salary rules of the
        ONSS_BASE category, computed on a payslip simulation by version, all created together.

        :param benefits_by_version: {hr.version: hr.contract.salary.benefit}
        :return: {hr.version: {benefit: amount}}
        """
        onss_category = self.env.ref('l10n_be_hr_payroll.ONSS_BASE')
        rules_by_benefit = {
            benefit: benefit.salary_rule_ids.filtered(lambda rule: onss_category in rule.category_ids)
            for benefit in self.browse().union(benefits_by_version.values())
        }
        today = fields.Date.today()
        Payslip = self.env['hr.payslip'].with_context(salary_simulation=True)
        simulations = {}  # {payslip: (version, available benefits, rules)}
        for version, benefits in benefits_by_version.items():
            available_benefits = benefits.filtered(
                lambda benefit: benefit._is_available_for_joint_committee(version.l10n_be_joint_committee_id))
            rules = self.env['hr.salary.rule'].union(rules_by_benefit[benefit] for benefit in available_benefits)
            if rules:
                simulations[Payslip.new({
                    'name': 'Draft',
                    'employee_id': version.employee_id.id,
                    'version_id': version.id,
                    'company_id': version.company_id.id or self.env.company.id,
                    'date_from': fields.Date.start_of(today, 'month'),
                    'date_to': fields.Date.end_of(today, 'month'),
                })] = (version, available_benefits, rules.sorted('sequence'))
        # created together: the versions, employees and companies of the simulations are prefetched at once
        payslips = Payslip.concat(simulations)

        result = {version: dict.fromkeys(benefits, 0.0) for version, benefits in benefits_by_version.items()}
        for payslip in payslips:
            version, available_benefits, rules = simulations[payslip]
            localdict = payslip._get_localdict()
            for rule in rules:
                localdict.update(result=None, result_qty=1.0, result_rate=100, explanation_info={})
                if not rule._satisfy_condition(localdict):
                    continue
                amount, qty, rate, _explanation_info = rule.with_context(salary_simulation=True)._compute_rule(localdict)
                tot_rule = payslip._get_payslip_line_total(amount, qty, rate, rule)
                localdict[rule.code] = tot_rule
                localdict['result_rules'][rule.code] = {
                    'total': tot_rule,
                    'amount': amount,
                    'quantity': qty,
                    'rate': rate,
                    'ytd': tot_rule,
                }
                if rule.category_ids:
                    localdict = rule.category_ids._sum_salary_rule_category(localdict, tot_rule)
            for benefit in available_benefits:
                result[version][benefit] = sum(
                    localdict['result_rules'].get(rule.code, {}).get('total', 0.0)
                    for rule in rules_by_benefit[benefit]
                )
        return result

    def write(self, vals):
        exclusive_benefits = self.browse()
        if 'active' in vals:
            exclusive_benefits = self._l10n_be_get_loss_on_commission_pto_benefits()
            if vals['active'] and len(self & exclusive_benefits) > 1:
                raise UserError(self.env._("Loss on commission on paid time off can only be compensated in one way."))
        res = super().write(vals)
        if self & exclusive_benefits:
            if vals['active']:
                # Restoring one of the benefits archives the other one
                (exclusive_benefits - self).filtered('active').active = False
            elif not any(exclusive_benefits.mapped('active')):
                raise UserError(self.env._(
                    "Loss on commission on paid time off must be compensated in one way. "
                    "Restore the other benefit instead."))
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_loss_on_commission_pto(self):
        if self & self._l10n_be_get_loss_on_commission_pto_benefits():
            raise UserError(self.env._(
                "The benefits choosing how the loss on commission on paid time off is compensated cannot be deleted. "
                "Restore the other one to archive it."))

    def _l10n_be_get_loss_on_commission_pto_benefits(self):
        benefits = self.browse()
        for xmlid in (
            'l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_monthly',
            'l10n_be_hr_payroll.l10n_be_loss_on_commission_pto_double_holiday',
        ):
            benefits |= self.env.ref(xmlid, raise_if_not_found=False) or self.browse()
        return benefits
