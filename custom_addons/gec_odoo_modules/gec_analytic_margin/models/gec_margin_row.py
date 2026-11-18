from odoo import models, fields, tools
from odoo.tools import SQL


class GecMarginRow(models.Model):
    """One ladder rung as a groupable dimension (pivots cannot group by measure columns).
    A real database view, not ``_table_query``: Postgres looks the relation up by name.
    Ids: ``component.id * 2`` and ``level.id * 2 + 1``, so a saved pivot stays valid."""
    _name = 'gec.margin.row'
    _description = 'Margin Statement Line'
    _auto = False
    _order = 'sequence, id'

    name = fields.Char(readonly=True, translate=True)
    code = fields.Char(readonly=True)
    sequence = fields.Integer(readonly=True)
    row_type = fields.Selection(
        [('component', 'Component'), ('level', 'Subtotal')],
        string='Line Type', readonly=True,
        help="A component line carries the amounts booked on its accounts. A "
             "subtotal line repeats those same amounts, once per level it "
             "belongs to — which is why the two must never be summed together.",
    )
    component_id = fields.Many2one('gec.margin.component', readonly=True)
    level_id = fields.Many2one('gec.margin.level', readonly=True)

    def init(self):
        # A level sits right under the last component it includes: components get sequence * 10, levels the same + 5.
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(SQL(
            """
            CREATE VIEW %s AS (
            SELECT gmc.id * 2 AS id,
                   gmc.name AS name,
                   gmc.code AS code,
                   gmc.sequence * 10 AS sequence,
                   'component' AS row_type,
                   gmc.id AS component_id,
                   NULL::integer AS level_id
              FROM gec_margin_component gmc
             WHERE gmc.active
             UNION ALL
            SELECT gml.id * 2 + 1,
                   gml.name,
                   gml.code,
                   COALESCE(MAX(gmc.sequence), gml.sequence) * 10 + 5,
                   'level',
                   NULL::integer,
                   gml.id
              FROM gec_margin_level gml
         LEFT JOIN gec_margin_level_component_rel rel ON rel.level_id = gml.id
         LEFT JOIN gec_margin_component gmc ON gmc.id = rel.component_id
                                           AND gmc.active
          GROUP BY gml.id
            )
            """,
            SQL.identifier(self._table),
        ))

    def _component_ids_by_row(self):
        """Which components each rung sums — the membership the report joins on."""
        return {
            row.id: (
                row.component_id.ids if row.row_type == 'component'
                else row.level_id.component_ids.ids
            )
            for row in self
        }
