from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools import SQL


class GecMarginComponent(models.Model):
    """A line of this company's P&L; the conventional set ships as data, which a company may delete or replace."""
    _name = 'gec.margin.component'
    _description = 'Margin Component'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        help="Stable technical identifier, used by classification rules and by "
             "allocation rules. Changing it after accounts are classified will "
             "not break anything, but keep it meaningful.",
    )
    sequence = fields.Integer(
        default=10,
        help="Order in the P&L, from revenue downwards.",
    )
    active = fields.Boolean(default=True)
    nature = fields.Selection(
        [
            ('revenue', 'Money in'),
            ('cost', 'Money out'),
            ('excluded', 'Outside the P&L'),
        ],
        required=True, default='cost',
        help="Decides which side of the report the amount lands on. "
             "'Outside the P&L' keeps balance-sheet accounts out of every "
             "margin level.",
    )
    cost_level = fields.Selection(
        [('unit', 'Unit level — one per item'),
         ('batch', 'Batch level — one per run or order'),
         ('product', 'Product level — sustains a product or service line'),
         ('facility', 'Facility level — sustains the business itself')],
        string='Cost Level', default='product', required=True,
        help="Cooper and Kaplan's cost hierarchy: what makes this cost happen.\n\n"
             "Unit, batch and product level costs are caused by something a cost "
             "object does, so a driver can honestly connect them.\n\n"
             "Facility level costs — rent, the board, the annual audit — are "
             "caused by the business existing. Nothing a product does makes them "
             "go up or down, so no driver is honest and they are never allocated. "
             "They stay visible as their own figure below the margin ladder.\n\n"
             "Spreading facility cost by revenue is the classic way to make the "
             "best-selling product look unprofitable, and the usual reason a "
             "costing model stops being trusted.",
    )
    allocatable = fields.Boolean(
        default=False,
        help="Whether an allocation rule may take cost from this component. "
             "True for Personnel and Overhead — costs that belong to several "
             "cost objects. False for Income Tax and Finance Costs, which "
             "cannot be meaningfully attributed to a product line.",
    )
    is_function = fields.Boolean(
        string='Function Line',
        help="A line of the P&L by function — Cost of Sales, R&D, Sales & "
             "Marketing, G&A. Cost centres and activities name one of these, and "
             "a company reporting by function reads its costs under them. No GL "
             "account is classified here directly.",
    )
    function_reclassify = fields.Boolean(
        string='Regroup by Function',
        help="In a company reporting by function, cost on this line is moved to "
             "the function its activity or cost centre names. True for Personnel "
             "and Overhead — the pooled costs whose job is not in the account "
             "name. Left off for Direct Cost, Depreciation, Finance and Tax, "
             "which read the same either way: the benchmark's EBITDA is before "
             "depreciation whatever department the asset sits in.",
    )
    level_ids = fields.Many2many(
        'gec.margin.level', 'gec_margin_level_component_rel',
        'component_id', 'level_id',
        string='Appears in Levels',
    )

    @api.onchange('cost_level')
    def _onchange_cost_level_facility(self):
        if self.cost_level == 'facility':
            self.allocatable = False

    @api.constrains('cost_level', 'allocatable')
    def _check_facility_is_not_allocatable(self):
        """The facility level is never driven: ticking Allocatable on it is an error, not silently reverted."""
        for component in self:
            if component.cost_level == 'facility' and component.allocatable:
                raise ValidationError(_(
                    "%(name)s is facility level, so it cannot be allocatable. "
                    "Nothing a product does makes rent go up or down — there is "
                    "no honest driver. Either lower the cost level, or leave it "
                    "unallocated and read it below the margin ladder.",
                    name=component.name,
                ))
    classification_rule_ids = fields.One2many(
        'gec.margin.classification.rule', 'component_id',
        string='Classification Rules',
    )
    account_count = fields.Integer(
        compute='_compute_account_count', string='Accounts',
    )

    _code_uniq = models.Constraint(
        'UNIQUE(code)',
        'A margin component with this code already exists.',
    )

    @api.depends('code')
    def _compute_account_count(self):
        counts = dict(self.env['account.account']._read_group(
            domain=[('gec_margin_component_id', 'in', self.ids)],
            groupby=['gec_margin_component_id'],
            aggregates=['__count'],
        ))
        for component in self:
            component.account_count = counts.get(component, 0)

    @api.constrains('nature', 'is_function', 'function_reclassify')
    def _check_function(self):
        for component in self:
            if component.is_function and component.nature != 'cost':
                raise ValidationError(_(
                    "%(name)s is a function line, so it must be a cost: only "
                    "costs are regrouped by function.", name=component.name,
                ))
            if component.is_function and component.function_reclassify:
                raise ValidationError(_(
                    "%(name)s is itself a function line and cannot be regrouped "
                    "into another one.", name=component.name,
                ))

    @api.constrains('nature', 'allocatable')
    def _check_allocatable(self):
        for component in self:
            if component.allocatable and component.nature != 'cost':
                raise ValidationError(_(
                    "%(name)s cannot be allocatable: only costs are allocated.",
                    name=component.name,
                ))

    def action_view_accounts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Accounts — %(name)s", name=self.name),
            'res_model': 'account.account',
            'view_mode': 'list,form',
            'domain': [('gec_margin_component_id', '=', self.id)],
        }

    def action_gec_open_all_rules(self):
        """Every classification rule in the order tried; the first match wins across all components,
        so precedence shows only in the flat list."""
        return self.env['ir.actions.actions']._for_xml_id(
            'gec_analytic_margin.action_gec_margin_classification_rule')


class GecMarginClassificationRule(models.Model):
    """How an account gets its component without tagging; rules are tried in sequence, first match wins,
    and a code prefix classifies every company's chart at once."""
    _name = 'gec.margin.classification.rule'
    _description = 'Margin Component Classification Rule'
    _order = 'sequence, id'

    name = fields.Char(compute='_compute_name', store=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    component_id = fields.Many2one(
        'gec.margin.component', required=True, ondelete='cascade',
    )
    code_prefix = fields.Char(
        help="Match accounts whose code starts with this, e.g. 741. "
             "Leave empty to match on account type alone.",
    )
    account_type = fields.Selection(
        selection=lambda self: self.env['account.account']._fields['account_type'].selection,
        help="Match accounts of this type. Leave empty to match on code prefix "
             "alone. Setting both requires the account to satisfy both.",
    )
    company_ids = fields.Many2many(
        'res.company',
        string='Companies',
        help="Restrict the rule to these companies. Leave empty to apply it "
             "everywhere — usually what you want, since a code prefix means "
             "the same thing in every company's chart.",
    )

    @api.depends('component_id', 'code_prefix', 'account_type')
    def _compute_name(self):
        for rule in self:
            criteria = []
            if rule.code_prefix:
                criteria.append(_("code %s…", rule.code_prefix))
            if rule.account_type:
                criteria.append(dict(
                    self.env['account.account']._fields['account_type'].selection
                ).get(rule.account_type, rule.account_type))
            rule.name = "%s → %s" % (
                " + ".join(criteria) or _("everything"),
                rule.component_id.name or '',
            )

    @api.constrains('code_prefix', 'account_type')
    def _check_has_criteria(self):
        for rule in self:
            if not rule.code_prefix and not rule.account_type:
                raise ValidationError(_(
                    "A classification rule needs a code prefix, an account "
                    "type, or both — otherwise it would claim every account."
                ))

    @staticmethod
    def _code_prefix_domain(prefix):
        """Match a code prefix in any company's chart: ``account.account.code`` is company-dependent
        and its search only sees the active company's ``code_store``."""
        # Odoo 20 passes to_sql a single TableSQL.
        return Domain.custom(to_sql=lambda table: SQL(
            "EXISTS (SELECT 1 FROM jsonb_each_text(%(store)s) AS c(k, v)"
            " WHERE v LIKE %(pattern)s)",
            store=SQL("%s.code_store", SQL.identifier(table._alias)),
            pattern=f'{prefix}%',
        ))

    def _get_account_domain(self):
        """Domain on account.account for the accounts this rule claims."""
        self.ensure_one()
        domain = Domain.TRUE
        if self.account_type:
            domain &= Domain('account_type', '=', self.account_type)
        if self.code_prefix:
            domain &= self._code_prefix_domain(self.code_prefix)
        if self.company_ids:
            domain &= Domain('company_ids', 'in', self.company_ids.ids)
        return domain

    @api.model
    def _apply_all(self, accounts=None):
        """Classify accounts that have no component set by hand; explicit values are never reverted."""
        Account = self.env['account.account']
        accounts = accounts if accounts is not None else Account.search([])
        unset = accounts.filtered(lambda a: not a.gec_margin_component_id)
        if not unset:
            return 0
        touched = Account
        # Reverse order so the lowest sequence is written last and wins; search(), not filtered_domain(),
        # as a prefix rule has a raw-SQL condition.
        for rule in self.search([], order='sequence desc, id desc'):
            matching = Account.search(Domain.AND([
                rule._get_account_domain(),
                Domain('id', 'in', unset.ids),
            ]))
            if matching:
                matching.gec_margin_component_id = rule.component_id
                touched |= matching
        return len(touched)

    def action_apply_now(self):
        count = self._apply_all()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if count else 'warning',
                'message': _("%(count)s accounts classified.", count=count)
                if count else _("No unclassified account matched a rule."),
                'sticky': False,
            },
        }

    @api.model
    def _component_sql(self, alias):
        """SQL resolving an ``account_account`` row to a component id: the explicit column first,
        then the rules in sequence, as in :meth:`_apply_all`."""
        branches = []
        for rule in self.search([]):
            conditions = []
            if rule.account_type:
                conditions.append(SQL(
                    "%s.account_type = %s", SQL.identifier(alias), rule.account_type,
                ))
            if rule.code_prefix:
                conditions.append(SQL(
                    # code is company-dependent jsonb; any company's code matching the prefix classifies the account.
                    "EXISTS (SELECT 1 FROM jsonb_each_text(%s.code_store) AS c(k, v)"
                    " WHERE v LIKE %s)",
                    SQL.identifier(alias), f'{rule.code_prefix}%',
                ))
            if not conditions:
                continue
            if rule.company_ids:
                # Same restriction as _get_account_domain, so the report and the Apply button agree.
                company_field = self.env['account.account']._fields['company_ids']
                conditions.append(SQL(
                    "EXISTS (SELECT 1 FROM %(rel)s r WHERE r.%(col1)s = %(alias)s.id"
                    " AND r.%(col2)s IN %(companies)s)",
                    rel=SQL.identifier(company_field.relation),
                    col1=SQL.identifier(company_field.column1),
                    col2=SQL.identifier(company_field.column2),
                    alias=SQL.identifier(alias),
                    companies=tuple(rule.company_ids.ids),
                ))
            branches.append(SQL(
                "WHEN %s THEN %s",
                SQL(" AND ").join(conditions),
                rule.component_id.id,
            ))
        if not branches:
            return SQL("%s.gec_margin_component_id", SQL.identifier(alias))
        return SQL(
            "COALESCE(%(explicit)s, CASE %(branches)s ELSE NULL END)",
            explicit=SQL("%s.gec_margin_component_id", SQL.identifier(alias)),
            branches=SQL(" ").join(branches),
        )
