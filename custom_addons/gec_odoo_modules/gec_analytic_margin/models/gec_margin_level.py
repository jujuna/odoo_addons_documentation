from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

MODULE_UNINSTALL_FLAG = '_force_unlink'


class GecMarginLevelMixin(models.AbstractModel):
    """Marker for report models with one monetary column per ``gec.margin.level``, created and dropped as levels change.

    Same mechanism as ``analytic.plan.fields.mixin`` / ``_sync_plan_column``, so the ladder can be any depth."""
    _name = 'gec.margin.level.mixin'
    _description = 'Margin Level Columns'

    def _get_level_fnames(self):
        levels = self.env['gec.margin.level'].sudo().search([])
        return [
            fname for level in levels
            if (fname := level._column_name()) in self._fields
        ]


class GecMarginLevel(models.Model):
    """One rung of the margin ladder, defined by the components it includes (data, not code).

    Levels are cumulative by convention, not by constraint."""
    _name = 'gec.margin.level'
    _description = 'Margin Level'
    _order = 'sequence, id'

    name = fields.Char(
        required=True, translate=True,
        help="Shown as the measure name on the report, e.g. EBITDA.",
    )
    code = fields.Char(
        required=True,
        help="Stable technical identifier, e.g. ebitda.",
    )
    sequence = fields.Integer(default=10)
    component_ids = fields.Many2many(
        'gec.margin.component', 'gec_margin_level_component_rel',
        'level_id', 'component_id',
        string='Components',
        required=True,
        help="Amounts on accounts of these components are summed into this "
             "level. Everything else is ignored, which is how Finance Costs and "
             "Income Tax stay out of operating margin.",
    )
    description = fields.Char(
        compute='_compute_description', store=True,
        help="Human-readable definition, e.g. Revenue + Direct Cost + Personnel.",
    )
    column_name = fields.Char(compute='_compute_column_name')

    _code_uniq = models.Constraint(
        'UNIQUE(code)',
        'A margin level with this code already exists.',
    )

    @api.depends('component_ids.name', 'component_ids.sequence')
    def _compute_description(self):
        for level in self:
            level.description = " + ".join(
                level.component_ids.sorted('sequence').mapped('name')
            )

    def _compute_column_name(self):
        for level in self:
            level.column_name = level._column_name() if level.id else False

    @api.constrains('component_ids')
    def _check_components(self):
        for level in self:
            if not level.component_ids:
                raise ValidationError(_(
                    "Level %(name)s has no components, so it would always be "
                    "zero.", name=level.name,
                ))

    def _column_name(self):
        self.ensure_one()
        return f'x_level{self.id}_amount'

    def _sync_all_level_columns(self):
        model_names = self.env.registry.descendants(
            ['gec.margin.level.mixin'], '_inherit'
        ) - {'gec.margin.level.mixin'}
        for model_name in model_names:
            self._sync_level_column(model_name)

    def _sync_level_column(self, model_name):
        """Create or rename this level's column on ``model_name``."""
        IrModelFields = self.env['ir.model.fields'].sudo()
        for level in self:
            column = level._column_name()
            existing = IrModelFields.search([
                ('name', '=', column), ('model', '=', model_name),
            ])
            if existing:
                existing.field_description = level.name
                continue
            IrModelFields.with_context(update_custom_fields=True).create({
                'name': column,
                'field_description': level.name,
                'help': level.description,
                'state': 'manual',
                'model': model_name,
                'model_id': self.env['ir.model']._get_id(model_name),
                'ttype': 'monetary',
                'currency_field': 'currency_id',
                'readonly': True,
                'store': True,
            })

    def _drop_level_column(self):
        model_names = self.env.registry.descendants(
            ['gec.margin.level.mixin'], '_inherit'
        ) - {'gec.margin.level.mixin'}
        columns = [level._column_name() for level in self]
        fields_to_drop = self.env['ir.model.fields'].sudo().search([
            ('name', 'in', columns), ('model', 'in', list(model_names)),
        ])
        fields_to_drop.with_context(**{MODULE_UNINSTALL_FLAG: True}).unlink()

    def _signal_registry(self):
        if self.env.registry.ready:
            self.env.transaction.will_change_registry()

    @api.model_create_multi
    def create(self, vals_list):
        levels = super().create(vals_list)
        levels._sync_all_level_columns()
        # The report is a SQL view built from the level list: rebuild it before the new column is read,
        # but not while the registry loads (data import rebuilds it).
        self._signal_registry()
        return levels

    def write(self, vals):
        result = super().write(vals)
        if 'name' in vals or 'component_ids' in vals:
            self._sync_all_level_columns()
            self._signal_registry()
        return result

    def unlink(self):
        self._drop_level_column()
        result = super().unlink()
        self._signal_registry()
        return result
