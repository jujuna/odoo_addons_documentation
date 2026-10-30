import ast
from datetime import date

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_round
from odoo.tools.safe_eval import safe_eval
from odoo.addons.l10n_be_hr_payroll.models.utils import to_eurocent


class L10n_Be281_Mapping(models.Model):
    _name = "l10n.be.281.mapping"
    _description = "HR Payroll 281.XX Declaration Mapping"

    date_from = fields.Date(string="From Date", required=True)
    date_to = fields.Date(string="To Date")
    tag = fields.Char(string="Tag", required=True)
    evaluation_type = fields.Selection(
        [
            ("salary_rule", "Salary Rule"),
            ("python", "Python"),
            ("control", "Control"),
        ],
        string="Evaluation Type",
        required=True,
    )
    salary_rule_ids = fields.Many2many(
        'hr.salary.rule', 'l10n_be_281_mapping_salary_rule_rel',
        string="Salary Rules", domain=[('country_code', '=', 'BE')], ondelete='restrict', context={'active_test': False})
    control_mapping_ids = fields.Many2many(
        'l10n.be.281.mapping', 'l10n_be_281_mapping_control_rel',
        'mapping_id', 'control_mapping_id', string="Control Rows", ondelete='restrict')
    controlled_by_mapping_ids = fields.Many2many(
        'l10n.be.281.mapping', 'l10n_be_281_mapping_control_rel',
        'control_mapping_id', 'mapping_id', string="Controlled By")
    evaluation_value = fields.Text(string="Evaluation Value")
    is_monetary = fields.Boolean(
        string="Monetary",
        help="The result is an amount or a number of hours, declared in hundredths in the XML files.")
    skip_if_falsy = fields.Boolean(string="Skip If Falsy")
    declaration_code = fields.Selection(
        [
            ("273S", "273S"),
            ("274.10", "274.10"),
            ("274.13", "274.13"),
            ("274.18", "274.18"),
            ("274.20", "274.20"),
            ("274.30", "274.30"),
            ("281.10", "281.10"),
            ("281.13", "281.13"),
            ("281.18", "281.18"),
            ("281.20", "281.20"),
            ("281.30", "281.30"),
            ("281.45", "281.45"),
        ],
        string="Declaration Code",
        required=True,
    )

    _date_range = models.Constraint(
        "CHECK(date_to IS NULL OR date_to >= date_from)",
        "The mapping end date must be on or after its start date.",
    )

    @api.onchange('evaluation_type')
    def _onchange_evaluation_type(self):
        for mapping in self:
            if mapping.evaluation_type != 'python':
                mapping.evaluation_value = False
                mapping.is_monetary = False
            if mapping.evaluation_type != 'salary_rule':
                mapping.salary_rule_ids = [Command.clear()]
            if mapping.evaluation_type != 'control':
                mapping.control_mapping_ids = [Command.clear()]

    def write(self, vals):
        if 'evaluation_type' in vals:
            # The fields of the previous evaluation type don't apply anymore, as in _onchange_evaluation_type: a row
            # of the data may change of evaluation type
            if vals['evaluation_type'] != 'python':
                vals.setdefault('evaluation_value', False)
                vals.setdefault('is_monetary', False)
            if vals['evaluation_type'] != 'salary_rule':
                vals.setdefault('salary_rule_ids', [Command.clear()])
            if vals['evaluation_type'] != 'control':
                vals.setdefault('control_mapping_ids', [Command.clear()])
        return super().write(vals)

    @api.constrains('evaluation_type', 'salary_rule_ids', 'control_mapping_ids', 'controlled_by_mapping_ids', 'evaluation_value')
    def _check_evaluation_type_consistency(self):
        for mapping in self:
            evaluation_type = mapping.evaluation_type
            if evaluation_type == 'salary_rule':
                if not mapping.salary_rule_ids:
                    raise ValidationError(self.env._(
                        "Mapping row %(tag)s must have at least one salary rule.", tag=mapping.tag,
                    ))
                if mapping.control_mapping_ids or mapping.evaluation_value:
                    raise ValidationError(self.env._(
                        "Mapping row %(tag)s is a Salary Rule row and can't have control links or a python expression.",
                        tag=mapping.tag,
                    ))
            elif evaluation_type == 'control':
                if not mapping.control_mapping_ids:
                    raise ValidationError(self.env._(
                        "Mapping row %(tag)s must have at least one control target.", tag=mapping.tag,
                    ))
                if mapping.salary_rule_ids or mapping.evaluation_value:
                    raise ValidationError(self.env._(
                        "Mapping row %(tag)s is a Control row and can't have salary rules or a python expression.",
                        tag=mapping.tag,
                    ))
            elif evaluation_type == 'python':
                if not mapping.evaluation_value:
                    raise ValidationError(self.env._(
                        "Mapping row %(tag)s must have a python expression.", tag=mapping.tag,
                    ))
                if mapping.control_mapping_ids or mapping.salary_rule_ids:
                    raise ValidationError(self.env._(
                        "Mapping row %(tag)s is a Python row and can't have control links or salary rules.", tag=mapping.tag,
                    ))

    @api.constrains('control_mapping_ids', 'controlled_by_mapping_ids')
    def _check_control_cycle(self):
        for mapping in self:
            reached = mapping.control_mapping_ids
            seen = self.browse()
            while reached:
                if mapping in reached:
                    raise ValidationError(self.env._(
                        "Mapping row %(tag)s creates a cycle through its control rows.", tag=mapping.tag,
                    ))
                seen |= reached
                reached = reached.control_mapping_ids - seen

    @api.constrains('salary_rule_ids')
    def _check_salary_rule_country(self):
        for mapping in self:
            if any(rule.country_code != 'BE' for rule in mapping.salary_rule_ids):
                raise ValidationError(self.env._(
                    "Mapping row %(tag)s can only link to Belgian salary rules.", tag=mapping.tag,
                ))

    @api.constrains('control_mapping_ids', 'controlled_by_mapping_ids', 'declaration_code')
    def _check_control_declaration_code(self):
        # Checked both ways, so it also catches a target's own declaration_code changing later.
        for mapping in self:
            for target in mapping.control_mapping_ids:
                if target.declaration_code != mapping.declaration_code:
                    raise ValidationError(self.env._(
                        "Mapping row %(tag)s can only control rows from the same declaration.",
                        tag=mapping.tag,
                    ))
            for controller in mapping.controlled_by_mapping_ids:
                if controller.declaration_code != mapping.declaration_code:
                    raise ValidationError(self.env._(
                        "Mapping row %(tag)s can only be controlled by rows from the same declaration.",
                        tag=mapping.tag,
                    ))

    @api.constrains('declaration_code', 'evaluation_type')
    def _check_273s_evaluation_type(self):
        # 273S sums raw codes directly; it never calls _evaluate on the mapping row.
        # python/control would be silently ignored or read as an empty code list.
        for mapping in self:
            if mapping.declaration_code == '273S' and mapping.evaluation_type != 'salary_rule':
                raise ValidationError(self.env._(
                    "273S mapping row %(tag)s must use the Salary Rule evaluation type.", tag=mapping.tag,
                ))

    @api.constrains('date_from', 'date_to')
    def _check_calendar_year_dates(self):
        for mapping in self:
            if mapping.date_from and (mapping.date_from.month, mapping.date_from.day) != (1, 1):
                raise ValidationError(self.env._("A mapping must start on January 1."))
            if mapping.date_to and (mapping.date_to.month, mapping.date_to.day) != (12, 31):
                raise ValidationError(self.env._("A mapping must end on December 31."))

    @api.constrains('declaration_code', 'tag', 'date_from', 'date_to')
    def _check_date_range_overlap(self):
        for mapping in self:
            domain = [
                ('id', '!=', mapping.id),
                ('declaration_code', '=', mapping.declaration_code),
                ('tag', '=', mapping.tag),
                '|', ('date_to', '=', False), ('date_to', '>=', mapping.date_from),
            ]
            if mapping.date_to:
                domain.append(('date_from', '<=', mapping.date_to))
            if mapping.search_count(domain, limit=1):
                raise ValidationError(self.env._(
                    "The year range for tag %(tag)s overlaps another %(declaration)s mapping.",
                    tag=mapping.tag, declaration=mapping.declaration_code,
                ))

    @api.depends('declaration_code', 'tag', 'date_from', 'date_to')
    def _compute_display_name(self):
        for mapping in self:
            date_range = f"{mapping.date_from} - {mapping.date_to}" if mapping.date_to else f"{mapping.date_from}+"
            mapping.display_name = f"{mapping.declaration_code} {mapping.tag} ({date_range})"

    def _get_codes(self):
        salary_mappings = self.filtered(lambda mapping: mapping.evaluation_type == 'salary_rule')
        # Archived rules still contribute to declarations for past payslips.
        codes = salary_mappings.with_context(active_test=False).salary_rule_ids.mapped('code')
        return list(dict.fromkeys(codes))

    def _tag_domain(self, declaration_code, tag, year):
        return [
            ('declaration_code', '=', declaration_code),
            ('tag', '=', tag),
            ('date_from', '<=', date(int(year), 1, 1)),
            '|', ('date_to', '=', False), ('date_to', '>=', date(int(year), 12, 31)),
        ]

    def _search_for_tag(self, declaration_code, tag, year):
        mappings = self.search(self._tag_domain(declaration_code, tag, year))
        if not mappings:
            raise UserError(self.env._(
                "No l10n.be.281.mapping row found for %(declaration)s tag %(tag)s and year %(year)s.",
                declaration=declaration_code, tag=tag, year=year,
            ))
        if len(mappings) > 1:
            raise UserError(self.env._(
                "Multiple l10n.be.281.mapping rows match %(declaration)s tag %(tag)s for year %(year)s; their year ranges overlap.",
                declaration=declaration_code, tag=tag, year=year,
            ))
        return mappings

    def _get_codes_for_tag(self, declaration_code, tag, year):
        if not self.search_count(self._tag_domain(declaration_code, tag, year)):
            return []
        return self._search_for_tag(declaration_code, tag, year)._get_codes()

    def _get_localdict(self, line_values, **kwargs):
        localdict = {
            "float_round": float_round,
            "_to_eurocent": self._to_eurocent,
            "mapped_total": dict(line_values),
        }
        localdict.update(kwargs)
        return localdict

    def _to_eurocent(self, amount):
        # Convert amount to eurocents if context requires it.
        return to_eurocent(amount) if self.env.context.get('round_281') else float(amount)

    def _get_evaluation_plan(self):
        """Prepare _evaluate_batch once for all the employees of a declaration.

        Most python rows are constants (``result = 0``) or read a single total (``result = mapped_total['X']``):
        they are evaluated without safe_eval, which compiles and checks the expression at each call. The control
        rows are ordered so that the rows they total are computed first.
        """
        plan = []
        for mapping_line in self.filtered(lambda mapping_line: mapping_line.evaluation_type != 'control'):
            if mapping_line.evaluation_type == 'salary_rule':
                kind, data = 'salary_rule', mapping_line._get_codes()
            else:
                kind, data = mapping_line._get_python_shortcut()
            plan.append((mapping_line, mapping_line.tag, mapping_line.is_monetary, kind, data))
        computed_tags = {step[1] for step in plan}
        # A control row may total other control rows, so resolve them from the inside out.
        pending_lines = self.filtered(lambda mapping_line: mapping_line.evaluation_type == 'control')
        while pending_lines:
            ready_lines = pending_lines.filtered(
                lambda mapping_line: all(target.tag in computed_tags for target in mapping_line.control_mapping_ids)
            )
            if not ready_lines:
                raise UserError(self.env._(
                    "The l10n.be.281 mapping control rows %(tags)s could not be resolved.",
                    tags=', '.join(pending_lines.mapped('tag')),
                ))
            plan.extend(
                (mapping_line, mapping_line.tag, mapping_line.is_monetary, 'control', mapping_line.control_mapping_ids.mapped('tag'))
                for mapping_line in ready_lines
            )
            computed_tags.update(ready_lines.mapped('tag'))
            pending_lines -= ready_lines
        return plan

    def _get_python_shortcut(self):
        self.ensure_one()
        try:
            statements = ast.parse(self.evaluation_value.strip()).body
        except SyntaxError:
            return 'python', None
        if len(statements) != 1 or not isinstance(statements[0], ast.Assign) or len(statements[0].targets) != 1 \
                or not isinstance(statements[0].targets[0], ast.Name) or statements[0].targets[0].id != 'result':
            return 'python', None
        value = statements[0].value
        if isinstance(value, ast.Subscript) and isinstance(value.value, ast.Name) and value.value.id == 'mapped_total' \
                and isinstance(value.slice, ast.Constant) and isinstance(value.slice.value, str):
            return 'mapped_total', value.slice.value
        try:
            return 'constant', ast.literal_eval(value)
        except (ValueError, TypeError, SyntaxError):
            return 'python', None

    def _evaluate_batch(self, localdict, plan=None):
        computed = {}
        for mapping_line, tag, is_monetary, kind, data in plan or self._get_evaluation_plan():
            if kind == 'python':
                computed[tag] = mapping_line._evaluate_python(localdict)
            elif kind == 'salary_rule':
                total = sum(localdict['mapped_total'].get(code, 0) for code in data)
                computed[tag] = localdict['_to_eurocent'](round(total, 2))
            elif kind == 'control':
                computed[tag] = sum(computed[control_tag] for control_tag in data)
            else:
                if kind == 'constant':
                    result = data
                else:
                    try:
                        result = localdict['mapped_total'][data]
                    except KeyError as e:
                        raise UserError(self.env._(
                            "l10n.be.281.mapping row %(tag)s failed to evaluate %(expr)s: %(error)s",
                            tag=tag, expr=mapping_line.evaluation_value, error=e,
                        )) from e
                computed[tag] = localdict['_to_eurocent'](round(result, 2)) if is_monetary else result
        return computed

    def _evaluate(self, localdict, computed):
        # One row, as evaluated with the others in _evaluate_batch. A control row totals the computed rows.
        # The localdict's _to_eurocent sets the unit, so each declaration keeps its own.
        self.ensure_one()
        if self.evaluation_type == 'control':
            return self._evaluate_control(computed)
        return self._evaluate_batch(localdict)[self.tag]

    def _evaluate_python(self, localdict):
        localdict.pop('result', None)
        try:
            # PY001: evaluation_value is writable only by group_hr_payroll_manager.
            # That's the same trust level as hr.salary.rule's condition_python/amount_python_compute.
            # The 274 also runs it as superuser, in its stored line compute.
            safe_eval(self.evaluation_value, localdict, mode='exec')
        except Exception as e:
            raise UserError(self.env._(
                "l10n.be.281.mapping row %(tag)s failed to evaluate %(expr)s: %(error)s",
                tag=self.tag, expr=self.evaluation_value, error=e,
            )) from e
        if 'result' not in localdict:
            raise UserError(self.env._(
                "l10n.be.281.mapping row %(tag)s: python evaluation_value must assign a 'result' variable.",
                tag=self.tag,
            ))
        result = localdict['result']
        return localdict['_to_eurocent'](round(result, 2)) if self.is_monetary else result

    def _evaluate_control(self, computed):
        total = 0
        for target in self.control_mapping_ids:
            try:
                total += computed[target.tag]
            except KeyError as e:
                raise UserError(self.env._(
                    "l10n.be.281.mapping control row %(tag)s references unknown or not-yet-computed tag %(missing)s.",
                    tag=self.tag, missing=e.args[0],
                )) from e
        return total
