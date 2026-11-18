import re
from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .rs_cit_declaration import RECOVERY_ROWS


class RsCitTaxedItem(models.Model):
    """An amount taxed on line 18.1.1, 18.1.3, 18.1.4, 18.2 or 18.3 whose tax comes back (line 27.1 or 27.2)
    when the money returns: a loan repaid, an advance settled, a security or share sold."""
    _name = 'rs.cit.taxed.item'
    _description = 'rs.ge Profit Tax Taxed Item'
    _order = 'date, id'

    declaration_id = fields.Many2one('rs.cit.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    cell_id = fields.Many2one('rs.cit.cell', string='Row', required=True, ondelete='restrict')
    code = fields.Char(related='cell_id.code')
    move_line_id = fields.Many2one('account.move.line', string='Journal Item', required=True, ondelete='cascade')
    date = fields.Date(related='move_line_id.date', store=True)
    account_id = fields.Many2one(related='move_line_id.account_id', store=True)
    partner_id = fields.Many2one('res.partner', compute='_compute_partner_id', store=True)
    amount = fields.Monetary(string='Taxed Amount', required=True)
    recovery_ids = fields.One2many('rs.cit.recovery', 'taxed_item_id', string='Money Back')
    recovered = fields.Monetary(compute='_compute_recovered', string='Recovered',
                                help="Money back counted by confirmed declarations.")
    remaining = fields.Monetary(compute='_compute_recovered', string='Remaining')
    state = fields.Selection(related='declaration_id.state', string='Declaration Status')

    @api.depends('move_line_id.partner_id')
    def _compute_partner_id(self):
        for taxed in self:
            taxed.partner_id = taxed.move_line_id.partner_id.commercial_partner_id

    @api.depends('amount', 'recovery_ids.amount', 'recovery_ids.declaration_id.state')
    def _compute_recovered(self):
        for taxed in self:
            taxed.recovered = sum(taxed.recovery_ids.filtered(
                lambda r: r.declaration_id._is_latest_confirmed()).mapped('amount'))
            taxed.remaining = taxed.amount - taxed.recovered

    def _counts_for(self, declaration):
        """Whether money back in ``declaration`` may be counted against this item: taxed by it, or by the
        latest confirmed version of an earlier month."""
        self.ensure_one()
        source = self.declaration_id
        if source == declaration:
            return True
        return source.date_from < declaration.date_from and source._is_latest_confirmed()

    def _available_for(self, declaration):
        """Taxed amount not yet recovered by the latest confirmed declarations of months before ``declaration``."""
        self.ensure_one()
        used = self.recovery_ids.filtered(lambda r: r.declaration_id.date_from < declaration.date_from
                                          and r.declaration_id._is_latest_confirmed())
        return self.amount - sum(used.mapped('amount'))


class RsCitRecovery(models.Model):
    """Money back this declaration counts on line 27.1 or 27.2 against one taxed item (annex 1.2)."""
    _name = 'rs.cit.recovery'
    _description = 'rs.ge Profit Tax Recovery'
    _order = 'id'

    declaration_id = fields.Many2one('rs.cit.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    taxed_item_id = fields.Many2one('rs.cit.taxed.item', required=True, ondelete='cascade', index=True)
    move_line_id = fields.Many2one('account.move.line', string='Money Back', required=True, ondelete='cascade')
    amount = fields.Monetary(required=True, help="Annex 1.2 column 3.")
    taxed_period = fields.Char(compute='_compute_taxed_period', string='Taxed In', help="Annex 1.2 column 1.")
    taxed_code = fields.Char(related='taxed_item_id.code', string='Taxed On Line', help="Annex 1.2 column 2.")
    code = fields.Char(compute='_compute_code', store=True, string='Line')

    @api.depends('taxed_item_id.declaration_id.date_from')
    def _compute_taxed_period(self):
        for recovery in self:
            month = recovery.taxed_item_id.declaration_id.date_from
            recovery.taxed_period = month.strftime('%m/%Y') if month else False

    @api.depends('taxed_item_id.cell_id.code')
    def _compute_code(self):
        for recovery in self:
            recovery.code = RECOVERY_ROWS.get(recovery.taxed_item_id.cell_id.code)


# Annexes 1.1 and 1.4 part I: the month typed, then line 25.1/25.3 and 16.1.1/16.1.2 of that month's declaration.
PERIOD_ROWS = {'1.1': ('25.1', '16.1.1'), '1.4': ('25.3', '16.1.2')}


def parse_month(text):
    """First day of the month written as 10/2026, 10.2026 or 2026/10; None when it is not a month."""
    numbers = re.findall(r'\d+', text or '')
    if len(numbers) != 2:
        return None
    first, second = (int(number) for number in numbers)
    month, year = (first, second) if first <= 12 and second > 12 else (second, first)
    return date(year, month, 1) if 1 <= month <= 12 and year > 1900 else None


class RsCitAnnexLine(models.Model):
    """One row of a declaration annex with repeating rows: 1.1 and 1.4 part I, 1.5, 1.6, 3 and 4."""
    _name = 'rs.cit.annex.line'
    _description = 'rs.ge Profit Tax Annex Line'
    _order = 'annex, sequence, id'

    declaration_id = fields.Many2one('rs.cit.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    annex = fields.Selection([
        ('1.1', 'Annex 1.1'), ('1.4', 'Annex 1.4'), ('1.5', 'Annex 1.5'), ('1.6', 'Annex 1.6'),
        ('3', 'Annex 3'), ('4', 'Annex 4'),
    ], required=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(help="1.1/1.4: month/year. 1.5: tax demand number. 1.6: calendar year. 3: balance. 4: contract.")
    date = fields.Date(help="1.5: tax demand date. 4: start date of the transaction.")
    partner_id = fields.Many2one('res.partner', string='Related Person', help="Annex 4 columns 1-3.")
    partner_vat = fields.Char(related='partner_id.vat', string='Identification Number')
    partner_country_id = fields.Many2one(related='partner_id.country_id', string='Residency')
    relation = fields.Selection([
        ('direct', 'Owns more than 50% directly'),
        ('indirect', 'Owns more than 50% indirectly'),
        ('control', 'Practical control of business decisions'),
        ('preferential', 'Resident of a preferential tax country'),
        ('pe', 'Permanent establishment'),
    ], string='Relation', help="Annex 4 column 4.")
    operation = fields.Selection([
        ('goods', 'Goods or services supplied or bought'),
        ('assets', 'Tangible or intangible assets supplied or bought'),
        ('loan', 'Loan received or given'),
        ('interest', 'Interest income or expense'),
        ('guarantee', 'Guarantee received or given'),
        ('financial', 'Other financial operation'),
        ('royalty', 'Royalty'),
        ('restructuring', 'Business restructuring'),
        ('other', 'Other controlled transaction'),
    ], string='Transaction Type', help="Annex 4 column 5.")
    documentation = fields.Selection([
        ('yes', 'I have it'), ('no', "I don't have it"), ('preparing', 'Being prepared'), ('planned', 'Planned'),
    ], string='Documentation', help="Annex 4 column 10.")
    operation_currency_id = fields.Many2one('res.currency', string='Transaction Currency', help="Annex 4 columns 6 and 8.")
    amount1 = fields.Float(digits='Account', help="1.1/1.4: line 25.1/25.3 amount. 1.5: taxed amount. "
                                                  "1.6: net profit. 3: opening balance. 4: volume in currency.")
    amount2 = fields.Float(digits='Account', help="1.1/1.4: line 16.1.1/16.1.2 amount. 1.6: dividend. "
                                                  "3: increase. 4: volume in GEL.")
    amount3 = fields.Float(digits='Account', help="1.6: expenses in Georgia. 3: of which revaluation. "
                                                  "4: balance owed at year end, in currency.")
    amount4 = fields.Float(digits='Account', help="3: decrease.")
    amount5 = fields.Float(digits='Account', help="3: of which revaluation.")
    amount6 = fields.Float(digits='Account', help="3: closing balance.")
    manual = fields.Boolean(help="Annex 3: typed by the accountant, so Recalculate leaves this row alone.")
    result1 = fields.Float(compute='_compute_results', digits='Account', string='Reduction',
                           help="Annex 1.6 column 5: expenses x dividend / net profit.")
    result2 = fields.Float(compute='_compute_results', digits='Account', string='Taxable Distribution',
                           help="Annex 1.6 column 6: dividend less the reduction; line 16.1.3.")

    @api.depends('annex', 'amount1', 'amount2', 'amount3')
    def _compute_results(self):
        for line in self:
            reduction = 0.0
            if line.annex == '1.6' and line.amount1 > 0:
                reduction = min(line.amount2, line.amount3 * line.amount2 / line.amount1)
            line.result1 = reduction
            line.result2 = line.amount2 - reduction if line.annex == '1.6' else 0.0

    def _check_draft(self):
        if self.declaration_id.filtered(lambda d: d.state == 'confirmed'):
            raise UserError(_("A confirmed declaration cannot be changed. Set it back to draft first."))

    @api.model
    def _period_amounts(self, annex, name, declaration):
        """Annexes 1.1 and 1.4 part I columns 2 and 3, read from the latest confirmed declaration of the month
        typed in column 1, as rs.ge fills them."""
        month = parse_month(name)
        if annex not in PERIOD_ROWS or not month or not declaration:
            return {}
        sources = self.env['rs.cit.declaration'].search([
            ('company_id', '=', declaration.company_id.id), ('date_from', '=', month), ('state', '=', 'confirmed')])
        source = sources.filtered(lambda d: d._is_latest_confirmed())[:1]
        amounts = {line.code: line.amount for line in source.line_ids}
        credit, taxable = PERIOD_ROWS[annex]
        return {'amount1': amounts.get(credit, 0.0), 'amount2': amounts.get(taxable, 0.0)}

    @api.onchange('name')
    def _onchange_name_period(self):
        for line in self.filtered(lambda l: l.annex in PERIOD_ROWS):
            line.update(self._period_amounts(line.annex, line.name, line.declaration_id) or
                        {'amount1': 0.0, 'amount2': 0.0})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('annex') in PERIOD_ROWS:
                declaration = self.env['rs.cit.declaration'].browse(vals.get('declaration_id'))
                vals.update(self._period_amounts(vals['annex'], vals.get('name'), declaration))
        lines = super().create(vals_list)
        lines._check_draft()
        lines.filtered(lambda l: l.annex != '3').declaration_id._compute_formulas()
        return lines

    def write(self, vals):
        self._check_draft()
        typed = {'amount1', 'amount2', 'amount3', 'amount4', 'amount5'} & set(vals)
        if typed and not self.env.context.get('gec_cit_auto'):
            vals = dict(vals, manual=True)
        result = super().write(vals)
        if typed:
            for line in self.filtered(lambda l: l.annex == '3'):
                # Closing balance = opening + increase - decrease, as rs.ge computes it.
                super(RsCitAnnexLine, line).write({'amount6': line.amount1 + line.amount2 - line.amount4})
        if 'name' in vals:
            for line in self.filtered(lambda l: l.annex in PERIOD_ROWS):
                amounts = self._period_amounts(line.annex, line.name, line.declaration_id)
                if amounts:
                    super(RsCitAnnexLine, line).write(amounts)
        self.filtered(lambda l: l.annex != '3').declaration_id._compute_formulas()
        return result

    def unlink(self):
        self._check_draft()
        declarations = self.filtered(lambda l: l.annex != '3').declaration_id
        result = super().unlink()
        declarations.exists()._compute_formulas()
        return result
