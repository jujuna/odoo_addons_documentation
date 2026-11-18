from odoo import models, fields, api
from odoo.fields import Domain
from odoo.tools import SQL


class AccountAccount(models.Model):
    _inherit = 'account.account'

    gec_margin_component_id = fields.Many2one(
        'gec.margin.component',
        string='Margin Component',
        ondelete='restrict',
        index='btree_not_null',
        help="Which P&L component this account belongs to, and therefore which "
             "margin levels it reaches.\n\n"
             "Usually left empty: classification rules derive it from the "
             "account type and code prefix. Set it here only to override a rule "
             "for a single account — an explicit value always wins.",
    )
    gec_revenue_stream_id = fields.Many2one(
        'gec.revenue.stream', string='Revenue Stream', ondelete='restrict',
        help="What kind of revenue this income account carries — license, "
             "maintenance, services. Changes no figure on the P&L; it feeds the "
             "revenue mix and the recurring share of revenue. A stream on the "
             "analytic account (a product line, say) takes precedence.",
    )
    gec_margin_component_effective_id = fields.Many2one(
        'gec.margin.component',
        string='Component (effective)',
        compute='_compute_gec_margin_component_effective_id',
        search='_search_gec_margin_component_effective_id',
        help="What the account actually resolves to: the explicit value if set, "
             "otherwise whatever the classification rules make of it. This is "
             "what the report uses.",
    )

    # The resolution logic lives only in gec.margin.classification.rule._component_sql;
    # domains reuse it so reports and filters always agree.
    @api.model
    def _gec_component_domain_by_id(self, component_id):
        Rule = self.env['gec.margin.classification.rule']
        # Odoo 20 passes to_sql a single TableSQL.
        return Domain.custom(to_sql=lambda table: SQL(
            "%s = %s", Rule._component_sql(table._alias), component_id,
        ))

    @api.model
    def _gec_component_domain(self, code):
        """Domain selecting accounts that resolve to the component ``code``."""
        component = self.env['gec.margin.component'].search(
            [('code', '=', code)], limit=1,
        )
        if not component:
            return Domain('id', '=', False)
        return self._gec_component_domain_by_id(component.id)

    def _compute_gec_margin_component_effective_id(self):
        remaining = self
        for component in self.env['gec.margin.component'].search([]):
            if not remaining:
                break
            matching = remaining.filtered(lambda a: a.gec_margin_component_id == component)
            unset = remaining.filtered(lambda a: not a.gec_margin_component_id)
            if unset:
                matching |= self.search(Domain.AND([
                    Domain('id', 'in', unset.ids),
                    self._gec_component_domain_by_id(component.id),
                ]))
            matching.gec_margin_component_effective_id = component
            remaining -= matching
        remaining.gec_margin_component_effective_id = False

    def _search_gec_margin_component_effective_id(self, operator, value):
        # Odoo 20 turns '='/'!=' into 'in'/'not in' with an OrderedSet; a direct call may pass a scalar.
        if operator not in ('in', 'not in', '=', '!='):
            return NotImplemented
        negate = operator in ('not in', '!=')
        values = list(value) if isinstance(value, (list, tuple, set, frozenset)) or (
            hasattr(value, '__iter__') and not isinstance(value, str)
        ) else [value]

        Component = self.env['gec.margin.component']
        components = Component.browse([
            v for v in values if isinstance(v, int) and not isinstance(v, bool) and v
        ])
        for name in (v for v in values if isinstance(v, str)):
            components |= Component.search([('display_name', '=', name)])

        domains = [self._gec_component_domain_by_id(c.id) for c in components]
        if any(v is False for v in values):
            Rule = self.env['gec.margin.classification.rule']
            domains.append(Domain.custom(to_sql=lambda table: SQL(
                "%s IS NULL", Rule._component_sql(table._alias),
            )))
        domain = Domain.OR(domains) if domains else Domain.FALSE
        return ~domain if negate else domain

    @api.model
    def _gec_component_sql(self, alias):
        """SQL resolving an ``account_account`` row to a component id."""
        return self.env['gec.margin.classification.rule']._component_sql(alias)
