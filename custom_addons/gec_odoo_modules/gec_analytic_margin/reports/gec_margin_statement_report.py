from odoo import models, fields
from odoo.tools import SQL


class GecMarginStatementReport(models.Model):
    """``gec.margin.report`` transposed: ladder on the rows, plans across the top.
    A separate model: an amount on a component also belongs to each rung that includes it, so it returns
    once per rung; ``is_component_row`` keeps the grand total right, like ``is_primary_plan``."""
    _name = 'gec.margin.statement.report'
    _inherit = 'gec.margin.report'
    _description = 'Analytic Margin Statement'
    _auto = False
    _order = 'plan_sequence, row_sequence, date desc, id desc'

    margin_row_id = fields.Many2one(
        'gec.margin.row', string='Statement Line', readonly=True,
        help="Which rung of the margin ladder this amount is reported on. An "
             "amount appears once per rung it belongs to.",
    )
    row_sequence = fields.Integer(string='Line Order', readonly=True)
    is_component_row = fields.Boolean(
        string='Component Line', readonly=True,
        help="True on the rows that carry an amount once — the component lines. "
             "The subtotal lines (Gross Margin, EBITDA…) repeat those same "
             "amounts, so a total taken across every line counts them several "
             "times. Filter on this whenever you need the figures to add up.",
    )

    def _statement_rows(self):
        return self.env['gec.margin.row'].sudo().search([])

    def _id_slots(self):
        # One slot per rung, plus one for an amount on no rung (unclassified account, or no GL account).
        return len(self._statement_rows()) + 1

    def _id_slot_sql(self):
        return SQL("COALESCE(rw.row_slot, %s)", len(self._statement_rows()))

    def _extra_columns(self, alias):
        # COALESCE to TRUE so an amount on no rung is still counted once and Net reconciles.
        return SQL(
            """,
                   rw.row_id AS margin_row_id,
                   rw.row_seq AS row_sequence,
                   COALESCE(rw.is_component_row, TRUE) AS is_component_row
            """
        )

    def _extra_joins(self, alias):
        """Explode the row over every rung its component belongs to; LEFT JOIN keeps unclassified amounts."""
        rows = self._statement_rows()
        members = rows._component_ids_by_row()
        values = SQL(', ').join(
            SQL(
                "(%(slot)s::integer, %(row_id)s::integer, %(seq)s::integer, "
                "%(is_component)s::boolean, %(members)s::integer[])",
                slot=slot,
                row_id=row.id,
                seq=row.sequence,
                is_component=row.row_type == 'component',
                members=members[row.id] or [0],
            )
            for slot, row in enumerate(rows)
        )
        if not rows:
            return SQL("")
        return SQL(
            """
       LEFT JOIN LATERAL (
                 SELECT *
                   FROM (VALUES %(values)s)
                     AS r(row_slot, row_id, row_seq, is_component_row, members)
                  WHERE gmc.id = ANY(r.members)
                 ) rw ON TRUE
            """,
            values=values,
        )
