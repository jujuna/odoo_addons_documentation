# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .bsc_common import (
    PARAM_ACHIEVEMENT_CAP,
    DEFAULT_ACHIEVEMENT_CAP,
    achievement as compute_achievement,
    rag_status,
    trend as compute_trend,
)


class BscMeasurement(models.Model):
    """One KPI, one period, one figure.
    ``actual_value_set`` tells "not reported yet" from a reported zero, as a float cannot be empty."""
    _name = 'bsc.measurement'
    _description = 'BSC Measurement'
    _order = 'period_id, kpi_id'

    kpi_id = fields.Many2one(
        'bsc.kpi', string='KPI', required=True, ondelete='cascade', index=True)
    period_id = fields.Many2one(
        'bsc.period', string='Period', required=True, ondelete='cascade', index=True)
    objective_id = fields.Many2one(
        related='kpi_id.objective_id', store=True, index=True, readonly=True)
    perspective_id = fields.Many2one(
        related='kpi_id.perspective_id', store=True, readonly=True)
    scorecard_id = fields.Many2one(
        related='period_id.scorecard_id', store=True, index=True, readonly=True)
    company_id = fields.Many2one(
        related='period_id.company_id', store=True, index=True, readonly=True)
    owner_id = fields.Many2one(related='kpi_id.owner_id', store=True, readonly=True)
    uom_name = fields.Char(related='kpi_id.uom_name', readonly=True)
    direction = fields.Selection(related='kpi_id.direction', readonly=True)
    period_state = fields.Selection(
        related='period_id.state', readonly=True, string='Period Status')

    target_value = fields.Float(string='Target')
    actual_value = fields.Float(string='Actual')
    actual_value_set = fields.Boolean(
        string='Reported', copy=False,
        help="Set automatically as soon as an actual figure is written. Switch it on "
             "by hand to report a figure of exactly zero - typing 0 over the empty 0 "
             "changes nothing, so there would be nothing to save.")
    previous_value = fields.Float(
        compute='_compute_previous', string='Previous Actual', digits=(16, 2))
    has_previous = fields.Boolean(compute='_compute_previous')
    baseline_value = fields.Float(related='kpi_id.baseline_value', readonly=True)

    achievement = fields.Float(
        compute='_compute_achievement', store=True, string='Achievement (%)',
        digits=(16, 1))
    status = fields.Selection(
        [('green', 'On Track'),
         ('amber', 'At Risk'),
         ('red', 'Off Track'),
         ('no_data', 'No Data')],
        compute='_compute_achievement', store=True, string='Status')
    trend = fields.Selection(
        [('up', 'Up'),
         ('flat', 'Flat'),
         ('down', 'Down')],
        compute='_compute_trend',
        help="Direction of travel only. Up is not necessarily good.")
    comment = fields.Text(
        string='Variance Comment',
        help="Required when the status is off track. The number is not the point; "
             "the reason is.")
    entered_by_id = fields.Many2one('res.users', string='Reported By', readonly=True, copy=False)
    entry_date = fields.Datetime(string='Reported On', readonly=True, copy=False)
    rules_frozen = fields.Boolean(
        readonly=True, copy=False,
        help="Set when the period closes: the scoring rules below are then kept on "
             "the row, so editing the KPI later never rescores a closed period.")
    rule_target_min = fields.Float(string='Range Minimum', readonly=True, copy=False)
    rule_target_max = fields.Float(string='Range Maximum', readonly=True, copy=False)
    rule_threshold_green = fields.Float(string='Green From (%)', readonly=True, copy=False)
    rule_threshold_amber = fields.Float(string='Amber From (%)', readonly=True, copy=False)
    rule_cap = fields.Float(string='Achievement Cap (%)', readonly=True, copy=False)
    # Unused; declared so databases from the 20.0.1.7.0 line keep this column.
    target_value_set = fields.Boolean(string='Target Set', readonly=True, copy=False)
    state = fields.Selection(
        [('draft', 'Draft'),
         ('submitted', 'Submitted'),
         ('validated', 'Validated')],
        default='draft', required=True, copy=False)

    _kpi_period_uniq = models.Constraint(
        'unique(kpi_id, period_id)',
        'This KPI already has a measurement for that period.',
    )

    @api.depends('kpi_id.name', 'period_id.name')
    def _compute_display_name(self):
        for record in self:
            record.display_name = '%s / %s' % (
                record.kpi_id.name or '', record.period_id.name or '')

    @api.depends('actual_value', 'actual_value_set', 'target_value', 'rules_frozen',
                 'rule_target_min', 'rule_target_max', 'rule_threshold_green',
                 'rule_threshold_amber', 'rule_cap',
                 'kpi_id.direction', 'kpi_id.target_min', 'kpi_id.target_max',
                 'kpi_id.threshold_green', 'kpi_id.threshold_amber')
    def _compute_achievement(self):
        """Score a row with the rules kept on it once frozen, else the KPI's own."""
        cap = self.env['bsc.scorecard']._get_param(
            PARAM_ACHIEVEMENT_CAP, DEFAULT_ACHIEVEMENT_CAP)
        for record in self:
            if not record.actual_value_set:
                record.achievement = 0.0
                record.status = 'no_data'
                continue
            kpi = record.kpi_id
            if record.rules_frozen:
                target_min, target_max = record.rule_target_min, record.rule_target_max
                green, amber = record.rule_threshold_green, record.rule_threshold_amber
                row_cap = record.rule_cap
            else:
                target_min, target_max = kpi.target_min, kpi.target_max
                green, amber = kpi.threshold_green, kpi.threshold_amber
                row_cap = cap
            value = compute_achievement(
                kpi.direction, record.target_value, record.actual_value,
                target_min=target_min, target_max=target_max, cap=row_cap)
            record.achievement = value or 0.0
            record.status = rag_status(value, green, amber)

    @api.depends('kpi_id', 'period_id')
    def _compute_previous(self):
        for record in self:
            previous = record._previous_measurement()
            record.has_previous = bool(previous and previous.actual_value_set)
            record.previous_value = previous.actual_value if record.has_previous else 0.0

    @api.depends('actual_value', 'actual_value_set', 'previous_value', 'has_previous')
    def _compute_trend(self):
        for record in self:
            if not record.actual_value_set or not record.has_previous:
                record.trend = 'flat'
            else:
                record.trend = compute_trend(record.actual_value, record.previous_value)

    def _filter_counted(self):
        """The rows whose KPI still counts (see ``_is_counted`` on the KPI)."""
        return self.filtered(lambda m: m.kpi_id._is_counted())

    def _freeze_rules(self):
        """Keep the KPI's scoring rules and achievement cap on the rows of a closing period, once.
        Runs as superuser with the period lock bypassed, as the period is still open."""
        cap = self.env['bsc.scorecard']._get_param(
            PARAM_ACHIEVEMENT_CAP, DEFAULT_ACHIEVEMENT_CAP)
        rows = self.filtered(lambda m: not m.rules_frozen).sudo().with_context(
            bsc_bypass_period_lock=True)
        for kpi, kpi_rows in rows.grouped('kpi_id').items():
            kpi_rows.write({
                'rule_target_min': kpi.target_min,
                'rule_target_max': kpi.target_max,
                'rule_threshold_green': kpi.threshold_green,
                'rule_threshold_amber': kpi.threshold_amber,
                'rule_cap': cap,
                'rules_frozen': True,
            })

    @api.model
    def _bsc_freeze_closed_periods(self):
        """Freeze the rules on rows of periods closed before rules were kept.
        Called by data/bsc_freeze_closed.xml on every module update, as superuser; frozen rows are skipped."""
        self.search([
            ('period_id.state', '=', 'closed'),
            ('rules_frozen', '=', False),
        ])._freeze_rules()

    def _previous_measurement(self):
        """The same KPI in the closest earlier period of the same scorecard."""
        self.ensure_one()
        if not self.kpi_id or not self.period_id:
            return self.browse()
        previous_period = self.env['bsc.period'].search([
            ('scorecard_id', '=', self.period_id.scorecard_id.id),
            ('date_from', '<', self.period_id.date_from),
        ], order='date_from desc', limit=1)
        if not previous_period:
            return self.browse()
        return self.search([
            ('kpi_id', '=', self.kpi_id.id),
            ('period_id', '=', previous_period.id),
        ], limit=1)

    @api.onchange('actual_value')
    def _onchange_actual_value(self):
        """Show the status and the required comment while the figure is typed, before ``actual_value_set`` is saved."""
        for record in self:
            record.actual_value_set = bool(record.actual_value) or record._origin.actual_value_set

    @api.constrains('kpi_id', 'period_id')
    def _check_same_scorecard(self):
        for record in self:
            if record.kpi_id.scorecard_id != record.period_id.scorecard_id:
                raise ValidationError(_(
                    "'%(kpi)s' does not belong to the scorecard of period '%(period)s'.",
                    kpi=record.kpi_id.name, period=record.period_id.name))

    @api.constrains('status', 'comment')
    def _check_variance_comment(self):
        """A closed period is history: its rows are not asked for a comment any more."""
        for record in self.filtered(lambda m: m.period_id.state != 'closed'):
            if record.status == 'red' and not record.comment:
                raise ValidationError(_(
                    "'%s' is off track. Please record why before saving - a red figure "
                    "without an explanation cannot be acted upon.", record.kpi_id.name))

    def _assert_period_open(self):
        # Bypass only for superuser code (demo loader, rule freeze): a client can send the context key.
        if self.env.su and self.env.context.get('bsc_bypass_period_lock'):
            return
        closed = self.filtered(lambda m: m.period_id.state == 'closed')
        if closed:
            raise UserError(_(
                "Period '%s' is closed. Ask a Balanced Scorecard administrator to "
                "reopen it if a figure really must change.",
                closed[0].period_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'actual_value' in vals:
                vals.setdefault('actual_value_set', True)
                vals.setdefault('entered_by_id', self.env.uid)
                vals.setdefault('entry_date', fields.Datetime.now())
        records = super().create(vals_list)
        records._assert_period_open()
        return records

    # Target, KPI, period and audit fields are not the contributor's to change.
    _CONTRIBUTOR_FIELDS = {'actual_value', 'actual_value_set', 'comment', 'state',
                           'entered_by_id', 'entry_date'}
    _CONTRIBUTOR_STATES = {'draft', 'submitted'}

    def _check_contributor_write(self, vals):
        """Field-level rules the access rights cannot express.
        A contributor may update rows of their KPIs, but not move their target, validate their figure
or reword an approved one."""
        if self.env.su or self.env.user.has_group('bsc_strategy.group_bsc_manager'):
            return
        forbidden = set(vals) - self._CONTRIBUTOR_FIELDS
        if forbidden:
            raise AccessError(_(
                "Only a Balanced Scorecard manager can change %s on a figure.",
                ", ".join(sorted(self._fields[f].string for f in forbidden if f in self._fields))))
        if vals.get('entered_by_id') or vals.get('entry_date'):
            raise AccessError(_("Who entered a figure, and when, is recorded automatically."))
        if 'state' in vals and vals['state'] not in self._CONTRIBUTOR_STATES:
            raise AccessError(_("Only a Balanced Scorecard manager can validate a figure."))
        validated = self.filtered(lambda m: m.state == 'validated')
        if validated:
            raise AccessError(_(
                "'%s' has been validated. Ask a manager to change it.",
                validated[0].display_name))

    def write(self, vals):
        self._assert_period_open()
        self._check_contributor_write(vals)
        if vals.get('actual_value_set') and 'actual_value' not in vals:
            vals.setdefault('entered_by_id', self.env.uid)
            vals.setdefault('entry_date', fields.Datetime.now())
        elif 'actual_value_set' in vals and not vals['actual_value_set'] \
                and 'actual_value' not in vals:
            # Switching "Reported" off withdraws the figure, like Clear Figure.
            vals.update({'actual_value': 0.0, 'entered_by_id': False,
                         'entry_date': False, 'state': 'draft'})
            result = super().write(dict(vals, actual_value_set=False))
            if 'period_id' in vals:
                self._assert_period_open()
            return result
        if 'actual_value' in vals:
            vals.setdefault('actual_value_set', True)
            vals.setdefault('entered_by_id', self.env.uid)
            vals.setdefault('entry_date', fields.Datetime.now())
        result = super().write(vals)
        if 'period_id' in vals:
            self._assert_period_open()
        return result

    def unlink(self):
        self._assert_period_open()
        return super().unlink()

    def action_open_form(self):
        """Open the figure itself - read-only lists elsewhere link here."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    def action_submit(self):
        unfilled = self.filtered(lambda m: not m.actual_value_set)
        if unfilled:
            raise UserError(_(
                "Enter an actual figure first for: %s",
                ", ".join(unfilled.mapped('kpi_id.name'))))
        self.write({'state': 'submitted'})
        return True

    def action_validate(self):
        if not (self.env.su or self.env.user.has_group('bsc_strategy.group_bsc_manager')):
            raise AccessError(_("Only a Balanced Scorecard manager can validate a figure."))
        unfilled = self.filtered(lambda m: not m.actual_value_set)
        if unfilled:
            raise UserError(_(
                "Enter an actual figure first for: %s",
                ", ".join(unfilled.mapped('kpi_id.name'))))
        self.write({'state': 'validated'})
        return True

    def action_reset(self):
        """Clear a figure that was entered by mistake."""
        self.write({
            'actual_value': 0.0,
            'actual_value_set': False,
            'entered_by_id': False,
            'entry_date': False,
            'state': 'draft',
        })
        return True
