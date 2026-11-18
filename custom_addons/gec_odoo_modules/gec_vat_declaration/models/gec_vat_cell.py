from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools import float_compare

from .gec_vat_declaration import AUDIT_CODES, COLUMN4_SOURCE, FIXED_ASSET_SOURCE, MARGIN_CODES, ODOO_SOURCE, list_action, round_2

TABS = [
    ('1', 'A I - Taxable Operations'),
    ('2', 'A II - Reverse Charge VAT'),
    ('3', 'A III - Creditable VAT'),
    ('16', 'Part III - VAT Calculation'),
    ('17', 'III-19⁶ - Margin Scheme'),
]


class GecVatCell(models.Model):
    """One labelled cell of a VAT declaration cell tab, as the rs.ge portal lays it out."""
    _name = 'gec.vat.cell'
    _description = 'VAT Declaration Cell'
    _order = 'sequence, id'

    code = fields.Char(required=True, help="Portal input id without the control_ prefix, e.g. 355_1 or 358_17.")
    tab = fields.Selection(TABS, required=True)
    row = fields.Char(help="Row number as the portal prints it, e.g. 1, 1¹, 14³.")
    line = fields.Char(help="Portal row key inside the tab, e.g. 1, 1_1, 13_1, 6_7. The cells of one row share it.")
    line_label = fields.Char(help="Row number as printed on the grid, e.g. (1¹) or (6) / (7); empty for an unnumbered row.")
    slot = fields.Integer(help="Value column of the portal row the cell sits in: 1, 2 or 3.")
    name = fields.Char(required=True)
    column = fields.Selection([
        ('base', 'Base'),
        ('vat', 'VAT'),
        ('total', 'Total'),
        ('goods', 'Goods and Services'),
        ('fixed_assets', 'Fixed Assets'),
        ('amount', 'Amount'),
        ('purchase_price', 'Purchase Price'),
        ('sale_price', 'Sale Price'),
    ])
    note = fields.Text(help="The portal tooltip of the cell.")
    formula = fields.Char(help="The portal formula of a locked cell, in portal row and column numbers.")
    computed = fields.Boolean(help="Locked on the portal: calculated from other cells, never typed.")
    proposed = fields.Boolean(help="Editable on the portal; Odoo proposes it from its own report or from other cells and refreshes it until "
        "the accountant overwrites it. A cell that is neither computed nor proposed is typed.")
    december_only = fields.Boolean(help="Locked on the portal except in the December declaration, where it is typed.")
    sequence = fields.Integer(default=10)

    _code_uniq = models.Constraint('UNIQUE(code)', 'The VAT declaration cell code must be unique.')


class GecVatDeclarationLine(models.Model):
    _name = 'gec.vat.declaration.line'
    _inherit = 'gec.vat.declaration.row'
    _description = 'VAT Declaration Cell Value'
    _order = 'sequence, id'

    declaration_id = fields.Many2one('gec.vat.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    cell_id = fields.Many2one('gec.vat.cell', required=True, ondelete='restrict')
    sequence = fields.Integer(related='cell_id.sequence', store=True)
    tab = fields.Selection(related='cell_id.tab', store=True)
    code = fields.Char(related='cell_id.code')
    row = fields.Char(related='cell_id.row')
    line = fields.Char(related='cell_id.line')
    line_label = fields.Char(related='cell_id.line_label')
    slot = fields.Integer(related='cell_id.slot')
    name = fields.Char(related='cell_id.name')
    column = fields.Selection(related='cell_id.column')
    note = fields.Text(related='cell_id.note')
    formula = fields.Char(related='cell_id.formula')
    computed = fields.Boolean(related='cell_id.computed')
    proposed = fields.Boolean(related='cell_id.proposed')
    december_only = fields.Boolean(related='cell_id.december_only')
    locked = fields.Boolean(compute='_compute_locked')
    auditable = fields.Boolean(compute='_compute_auditable')
    value = fields.Float()
    proposed_value = fields.Float(help="What Odoo last proposed; the value is refreshed only while it still equals this.")
    odoo_value = fields.Float(string="Odoo", help="Odoo's own figure for this cell, from the VAT report at the last Generate.")

    @api.depends('computed', 'december_only', 'declaration_id.date_from')
    def _compute_locked(self):
        """A computed cell is locked, except the December-only cells in a December declaration."""
        for line in self:
            december = bool(line.declaration_id.date_from) and line.declaration_id.date_from.month == 12
            line.locked = line.computed and not (line.december_only and december)

    @api.depends('code')
    def _compute_auditable(self):
        for line in self:
            line.auditable = line.code in AUDIT_CODES

    def action_gec_audit(self):
        """List what makes up Odoo's figure for this cell: core's audit of the VAT report for report cells."""
        self.ensure_one()
        self.check_access('read')
        declaration = self.declaration_id
        name = '%s · %s' % (self.name, dict(self._fields['column']._description_selection(self.env))[self.column])
        if self.code in MARGIN_CODES:
            return list_action(declaration._gec_margin_scan()[2][self.code], name)
        Line = self.env['account.move.line'].sudo()  # unreadable branch lines: only their ids and balance are used
        if self.code in FIXED_ASSET_SOURCE:
            items = Line.browse(declaration._gec_fixed_asset_tax_lines().get(self.code, (0.0, []))[1])
            if float_compare(self.value, round_2(sum(items.mapped('balance'))), precision_rounding=0.01) != 0:
                name = self.env._("%s (the tax items differ from the cell: shared with other lines, capped, typed or changed since Generate)", name)
            return list_action(items, name)
        total_code, fixed_code = COLUMN4_SOURCE.get(self.code, (self.code, False))
        line_code, label = ODOO_SOURCE[total_code]
        report, options = declaration._gec_report_options()
        report_line = report.line_ids.filtered(lambda line: line.code == line_code)
        report_line.ensure_one()
        action = report.action_audit_cell(options, {
            'report_line_id': report_line.id,
            'expression_label': label,
            'column_group_index': 0,
            'calling_line_dict_id': report._get_generic_line_id('account.report.line', report_line.id),
        })
        domain = Domain(action['domain'])
        if action['res_model'] != 'account.move.line':
            domain &= Domain('company_id', 'in', report.get_report_company_ids(options))
        action['name'] = name
        if fixed_code:
            items = Line.browse(declaration._gec_fixed_asset_tax_lines().get(fixed_code, (0.0, []))[1])
            column5 = declaration.line_ids.filtered(lambda line: line.code == fixed_code)
            if float_compare(column5.value, round_2(sum(items.mapped('balance'))), precision_rounding=0.01) == 0:
                domain &= Domain('id', 'not in', items.ids)
            else:
                action['name'] = self.env._("%s (column 5 differs from its tax items: the whole row)", name)
        action['domain'] = domain
        return action
