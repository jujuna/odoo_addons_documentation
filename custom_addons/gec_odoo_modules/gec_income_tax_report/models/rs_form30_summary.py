from odoo import api, fields, models

from .rs_form30_declaration import _refuse_exported_rows


class RsForm30SummaryCell(models.Model):
    """One labelled cell of the declaration's main part, as the portal lays it out."""
    _name = 'rs.form30.summary.cell'
    _description = 'rs.ge Form 30 Main Part Cell'
    _order = 'sequence, id'

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    note = fields.Char(help="Right-hand half of a split row, e.g. the rate of an article 134 sub-point.")
    sequence = fields.Integer(default=10)
    computed = fields.Boolean(help="The portal calculates this cell from the annexes; it is never typed in.")
    proposed = fields.Boolean(help="Typed on the portal; Odoo proposes it from its own records and refreshes it until the accountant overwrites it.")
    is_boolean = fields.Boolean(help="Rendered as a checkbox on the portal, not an amount.")
    is_section = fields.Boolean(help="A heading row that carries no value.")

    _code_uniq = models.Constraint('UNIQUE(code)', 'Main part cell code must be unique.')


class RsForm30SummaryLine(models.Model):
    _name = 'rs.form30.summary.line'
    _description = 'rs.ge Form 30 Main Part Value'
    _order = 'sequence, id'

    declaration_id = fields.Many2one('rs.form30.declaration', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='declaration_id.company_id', store=True)
    currency_id = fields.Many2one(related='declaration_id.currency_id')
    cell_id = fields.Many2one('rs.form30.summary.cell', required=True, ondelete='cascade')
    sequence = fields.Integer(related='cell_id.sequence', store=True)
    code = fields.Char(related='cell_id.code')
    name = fields.Char(related='cell_id.name')
    note = fields.Char(related='cell_id.note')
    computed = fields.Boolean(related='cell_id.computed')
    proposed = fields.Boolean(related='cell_id.proposed')
    is_boolean = fields.Boolean(related='cell_id.is_boolean')
    is_section = fields.Boolean(related='cell_id.is_section')
    value = fields.Float()
    value_bool = fields.Boolean()
    proposed_value = fields.Float(help="What Odoo last proposed; the value is refreshed only while it still equals this.")

    def write(self, vals):
        _refuse_exported_rows(self)
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_exported(self):
        _refuse_exported_rows(self)
