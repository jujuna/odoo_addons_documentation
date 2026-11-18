from collections import defaultdict

from odoo import Command, models
from odoo.addons.geo_payroll.models.account_chart_template import STRUCTS
from odoo.tools import float_compare, float_is_zero


class RsForm30DeclarationSalary(models.Model):
    _inherit = 'rs.form30.declaration'

    def _rs_form30_salary_figures(self, slip):
        totals = defaultdict(float)
        for line in slip.line_ids:
            totals[line.code] += line.total
        advance = sum(slip.input_line_ids.filtered(lambda inp: inp.code == 'ADVANCE_PAY').mapped('amount'))
        return {
            'amount': totals['GROSS'] + advance,
            'tax': -totals['PIT'] + totals['ADV_PIT_PRE'],
            'pension': -totals['PENSION_EE'] + totals['ADV_PEE_PRE'],
            'advance': advance,
        }

    def _rs_form30_salary_settlement(self, candidates, families):
        """Family partials are payroll netting, not cash; a paid slip without partials uses its paid date."""
        rounding = self.currency_id.rounding
        net_lines = {slip: slip._rs_form30_net_lines() for slip in candidates}
        parts = self.env['account.move.line'].concat(net_lines.values())._rs_form30_cash_parts()
        result = {}
        for family in families.values():
            family_moves = family.move_id
            for slip in family & candidates:
                items = [parts.get(line, {}) for line in net_lines[slip]]
                cash = [part for item in items for part in item.get('cash', [])]
                other = [part for item in items for part in item.get('other', []) if part['move'] not in family_moves]
                # sudo: the accountant may lack access to the partials of payroll entry lines
                lines = net_lines[slip].sudo()
                fallback = False
                if (slip.state == 'paid' and slip.paid_date
                        and not lines.matched_debit_ids and not lines.matched_credit_ids
                        and float_compare(slip.net_wage, 0.0, precision_rounding=rounding) > 0):
                    fallback = slip.paid_date
                result[slip] = {
                    'net_lines': net_lines[slip],
                    'cash': cash,
                    'other': other,
                    'fallback': fallback,
                    'dates': [part['date'] for part in cash] + ([fallback] if fallback else []),
                    'entry_date': slip.move_id.date if slip.move_id.state == 'posted' else False,
                }
        return result

    def _rs_form30_salary_plans(self, candidates, families, settlement, declared):
        """Per correction family the final slip is declared by the months its cash paid it; once filed, only the difference."""
        def in_month(day):
            return self.date_from <= day <= self.date_to

        rounding = self.currency_id.rounding
        plans = []
        draft_rows = self.env['rs.form30.line'].search([
            ('company_id', '=', self.company_id.id),
            ('declaration_id.state', '!=', 'exported'),
            ('declaration_id.date_from', '<', self.date_from),
            ('payslip_id', 'in', candidates.ids),
        ])
        drafted = {line.payslip_id.id: line.declaration_id for line in draft_rows}
        for root, family in families.items():
            members = family & candidates
            corrections = members.filtered(lambda slip: slip.origin_payslip_id and settlement[slip]['entry_date'])
            final = (corrections - corrections.origin_payslip_id).sorted('id')[-1:] or root
            if final not in members:
                continue
            if final == root and root.id in declared['payslip_filed']:
                refunds = family.filtered(lambda slip: slip.is_refund_payslip and slip.state in ('validated', 'paid') and slip.move_id)
                for refund in refunds.filtered(lambda slip: in_month(slip.move_id.date)):
                    declared['warnings'].append("Correction %s changes figures already declared for %s: correct that declaration, then generate "
                        "this month again." % (refund.name, root.employee_id.name))
            item = settlement[final]
            label = f"{final.employee_id.name} ({final.name})"
            source = self._rs_form30_source(root)
            plan = {
                'slip': final,
                'root': root,
                'kind': False,
                'date': False,
                'parts': [],
                'shares': False,
                'other': any(settlement[slip]['other'] for slip in members),
            }
            if final != root:
                shares, parts, cash = (1.0, 1.0), [], []
                if float_compare(final.net_wage, 0.0, precision_rounding=rounding) > 0:
                    cash = self._rs_form30_salary_family_cash(members, settlement)
                    parts, share_before, share_through = self._rs_form30_month_share(cash, final.net_wage, declared, label, source)
                    shares = (share_before, share_through)
                parts = parts if shares[1] > shares[0] else []
                date = max((part['date'] for part in parts), default=item['entry_date'])
                if root.id in declared['payslip_filed']:
                    if parts or (item['entry_date'] and in_month(item['entry_date'])):
                        unfiled = [part for part in cash if part['date'] < self.date_from
                            and not self._rs_form30_part_declaration(part, declared, source)
                            and (part['payment'] or part['statement_line'] or part['offset'] or ('payslip', root.id) not in declared['sources'])]
                        if unfiled:
                            declared['warnings'].append("Correction %s: export the declaration of %s first, then generate this month again." % (
                                final.name, min(part['date'] for part in unfiled).strftime('%Y/%m')))
                        else:
                            plans.append(dict(plan, kind='filed', date=date, parts=parts, shares=shares))
                else:
                    if parts:
                        plans.append(dict(plan, kind='share', date=date, parts=parts, shares=shares))
                    stale = next((drafted[slip.id] for slip in members - final if slip.id in drafted), None)
                    if stale:
                        declared['warnings'].append("Correction %s: generate the declaration of %s again before exporting it." % (
                            final.name, stale.date_from.strftime('%Y/%m')))
            elif any(in_month(part['date']) for part in item['cash']):
                parts, share_before, share_through = self._rs_form30_month_share(
                    item['cash'], -sum(item['net_lines'].mapped('balance')), declared, label, source)
                if share_through - share_before > 0:
                    plans.append(dict(plan, kind='share', date=max(part['date'] for part in parts), parts=parts,
                        shares=(share_before, share_through)))
            elif item['fallback'] and in_month(item['fallback']):
                plans.append(dict(plan, kind='fallback', date=item['fallback']))
            elif (float_compare(final.net_wage, 0.0, precision_rounding=rounding) <= 0 and item['entry_date'] and in_month(item['entry_date'])):
                plans.append(dict(plan, kind='zero', date=item['entry_date']))
        return plans

    def _rs_form30_salary_family_cash(self, members, settlement):
        """A slip paid without a matched payment counts as cash on its paid date."""
        cash = [part for slip in members for part in settlement[slip]['cash']]
        cash += [{
            'amount': slip.net_wage,
            'date': settlement[slip]['fallback'],
            'kind': 'fallback',
            'payment': self.env['account.payment'],
            'statement_line': self.env['account.bank.statement.line'],
            'matched': True,
            'withheld_at_payment': False,
            'offset': self.env['account.move'],
        } for slip in members if settlement[slip]['fallback']]
        return cash

    def _rs_form30_salary_families(self):
        """Return (candidates, {root: family})."""
        # sudo: the accountant filing the declaration usually has no payroll access
        geo_types = self.env['account.chart.template'].sudo()._gec_structures(STRUCTS + ('benefits', 'overtime')).type_id
        candidates = self.env['hr.payslip'].sudo().search([
            ('company_id', '=', self.company_id.id),
            ('struct_id.type_id', 'in', geo_types.ids),
            ('state', 'in', ('validated', 'paid')),
            ('credit_note', '=', False),
            ('is_refund_payslip', '=', False),
        ], order='date_from, id')
        roots = list(dict.fromkeys(slip._rs_form30_family_root() for slip in candidates))
        grouped = self.env['hr.payslip'].sudo().concat(roots)._rs_form30_family().grouped(lambda slip: slip._rs_form30_family_root())
        families = {root: grouped[root] for root in roots}
        return candidates, families

    def _rs_form30_salary_add_unpaid(self, candidates, settlement, result):
        """A slip with only rejected, canceled or draft payments counts as unpaid."""
        rounding = self.currency_id.rounding
        for slip in candidates:
            item = settlement[slip]
            lines = item['net_lines']
            if (lines and not float_is_zero(sum(lines.mapped('amount_residual')), precision_rounding=rounding)
                    and not any(day <= self.date_to for day in item['dates'])
                    and item['entry_date'] and item['entry_date'] <= self.date_to):
                result['unpaid'] |= slip.move_id
            elif (lines and item['entry_date'] and item['entry_date'] <= self.date_to
                    and not any(part['date'] <= self.date_to for part in item['cash'])
                    and lines.matched_debit_ids.debit_move_id.payment_id.filtered(
                        lambda payment: payment.state in ('rejected', 'canceled', 'draft'))):
                result['unpaid'] |= slip.move_id

    def _rs_form30_salary_data(self, declared):
        self.ensure_one()
        candidates, families = self._rs_form30_salary_families()
        settlement = self._rs_form30_salary_settlement(candidates, families)
        Move = self.env['account.move']
        result = {'lines': [], 'unpaid': Move, 'warnings': []}
        self._rs_form30_salary_add_unpaid(candidates, settlement, result)
        plans = self._rs_form30_salary_plans(candidates, families, settlement, declared)
        salary_type = self.env.ref('gec_income_tax_report.income_type_1')
        Line = self.env['rs.form30.line']
        for plan in plans:
            slip, root = plan['slip'], plan['root']
            figures = self._rs_form30_salary_figures(slip)
            amount, tax, pension = figures['amount'], figures['tax'], figures['pension']
            if plan['kind'] == 'filed':
                filed = declared['payslip_filed'][root.id]
                diffs = [float_compare(value - done, 0.0, precision_rounding=0.01) for value, done in zip((amount, tax, pension), filed)]
                if -1 not in diffs and plan['parts']:
                    amount, tax, pension = [max(0.0, self.currency_id.round(value * plan['shares'][1]) - done)
                        for value, done in zip((amount, tax, pension), filed)]
                    lost = float_compare(amount, 0.0, precision_rounding=0.01) <= 0 and any(
                        float_compare(value, 0.0, precision_rounding=0.01) > 0 for value in (tax, pension))
                else:
                    lost = -1 in diffs or (1 in diffs and not plan['parts'] and plan['shares'][1] >= 1)
                if lost:
                    result['warnings'].append("Correction %s changes figures already declared for %s: correct that declaration, then generate "
                        "this month again." % (slip.name, slip.employee_id.name))
                if lost or not plan['parts']:
                    continue
            elif plan['shares']:
                amount, tax, pension = self._rs_form30_month_amounts([amount, tax, pension], *plan['shares'])
            if float_compare(amount, 0.0, precision_rounding=0.01) <= 0:
                continue
            employee = slip.employee_id
            partner = employee.work_contact_id
            version = slip.version_id
            warnings = []
            rate = slip._rule_parameter('gec_ge_pit_rate')
            relief = 0.0
            identification = Line._clean_identification(version.identification_id)
            if not identification and partner.vat:
                identification = Line._clean_identification(partner.vat)
                warnings.append("Employee ID taken from the work contact Tax ID, verify it.")
            if slip._gec_exemption_remaining():
                relief = max(0.0, self.currency_id.round(amount - pension - tax * 100 / rate))
                warnings.append("Relief derived from the withheld tax, verify on the portal.")
            classification, classification_warnings = self._recipient_classification(
                partner, plan['date'], salary=True, nationality=version.country_id, usage='salary')
            warnings.extend(classification_warnings)
            if plan['kind'] == 'fallback' or any(part['kind'] == 'fallback' for part in plan['parts']):
                warnings.append("No payment matched, date taken from the payslip.")
            if plan['kind'] == 'zero':
                warnings.append("Zero net pay: the row is dated on the payslip entry.")
            warnings.extend(self._rs_form30_settlement_warnings(plan['parts'], plan['other']))
            if slip.edited:
                warnings.append("Payslip lines were edited manually.")
            if figures['advance'] > 0:
                warnings.append("Includes an advance: confirm the month.")
            if plan['kind'] == 'filed':
                warnings.append("Corrected by %s after earlier months were filed: the row holds the difference to what was filed." % slip.name)
            elif slip != root:
                warnings.append("Corrected by %s: figures follow the corrected payslip, split by the months its net was paid." % slip.name)
            elif families[root].filtered(lambda refund: refund.is_refund_payslip and refund.state in ('validated', 'paid')):
                warnings.append("Reversed after payment: correct the declaration.")
            first_name, last_name = Line._split_name(employee.legal_name or employee.name, is_company=False)
            result['lines'].append({
                **classification,
                'source': 'payslip',
                'payslip_id': slip.id,
                'partner_id': partner.id,
                'identification': identification,
                'first_name': first_name,
                'last_name': last_name,
                'address': ' '.join(filter(None, [version.private_street, version.private_street2, version.private_city])),
                'income_type_id': salary_type.id,
                'amount': amount,
                'other_relief': relief,
                'date': plan['date'],
                'rate': rate,
                'autonomous_republic': version.work_location_id.rs_form30_autonomous_republic,
                'pension_amount': pension,
                'tax_amount': tax,
                'settlement_payment_ids': [Command.set(sorted({pid for part in plan['parts'] for pid in part['payment'].ids}))],
                'settlement_statement_line_ids': [Command.set(sorted({sid for part in plan['parts'] for sid in part['statement_line'].ids}))],
                'settlement_move_ids': [Command.set(sorted({mid for part in plan['parts'] for mid in part['offset'].ids}))],
                'warning': ' '.join(warnings),
                'issue_level': self._rs_form30_issue_level(warnings),
            })
        result['warnings'] = list(dict.fromkeys(result['warnings']))
        return result
