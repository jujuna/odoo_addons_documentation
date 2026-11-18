# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class BscPeriod(models.Model):
    """A shared reporting period that can be closed: it has a completion rate and its figures stop moving."""
    _name = 'bsc.period'
    _description = 'BSC Reporting Period'
    _order = 'date_from desc, id desc'

    name = fields.Char(required=True)
    scorecard_id = fields.Many2one(
        'bsc.scorecard', string='Scorecard', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='scorecard_id.company_id', store=True, index=True, readonly=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    state = fields.Selection(
        [('open', 'Open'),
         ('closed', 'Closed')],
        default='open', required=True)
    measurement_ids = fields.One2many('bsc.measurement', 'period_id', string='Measurements')
    measurement_count = fields.Integer(compute='_compute_completion')
    filled_count = fields.Integer(compute='_compute_completion')
    completion_rate = fields.Float(
        compute='_compute_completion', string='Completion (%)', digits=(16, 1))
    is_current = fields.Boolean(compute='_compute_is_current')

    _date_order = models.Constraint(
        'CHECK(date_from <= date_to)',
        'The period end date must not be before its start date.',
    )

    @api.depends('measurement_ids.actual_value_set', 'measurement_ids.kpi_id.active',
                 'measurement_ids.kpi_id.objective_id.active',
                 'measurement_ids.kpi_id.objective_id.assessment_mode')
    def _compute_completion(self):
        """Completion over the rows that still count (see ``_is_counted`` on the KPI)."""
        for period in self:
            rows = period.measurement_ids._filter_counted()
            total = len(rows)
            filled = len(rows.filtered('actual_value_set'))
            period.measurement_count = total
            period.filled_count = filled
            period.completion_rate = (filled / total * 100.0) if total else 0.0

    @api.depends('date_from', 'date_to')
    def _compute_is_current(self):
        today = fields.Date.context_today(self)
        for period in self:
            period.is_current = bool(
                period.date_from and period.date_to
                and period.date_from <= today <= period.date_to)

    @api.constrains('date_from', 'date_to', 'scorecard_id')
    def _check_no_overlap(self):
        for period in self:
            overlapping = self.search([
                ('id', '!=', period.id),
                ('scorecard_id', '=', period.scorecard_id.id),
                ('date_from', '<=', period.date_to),
                ('date_to', '>=', period.date_from),
            ], limit=1)
            if overlapping:
                raise ValidationError(_(
                    "Period '%(new)s' overlaps with '%(old)s'.",
                    new=period.name, old=overlapping.name))

    def action_prepare_measurements(self):
        """Create the empty rows the data owners fill in, so what is still missing is easy to see."""
        for period in self:
            if period.state == 'closed':
                raise UserError(_("Period '%s' is closed.", period.name))
            kpis = period.scorecard_id.objective_ids.kpi_ids.filtered(
                lambda k: k.active and k.data_source == 'manual')
            period._create_missing_measurements(kpis)
        return True

    def write(self, vals):
        """A closed period keeps its dates and scorecard; writing the same value is allowed."""
        for period in self.filtered(lambda p: p.state == 'closed'):
            if (('date_from' in vals and fields.Date.to_date(vals['date_from']) != period.date_from)
                    or ('date_to' in vals and fields.Date.to_date(vals['date_to']) != period.date_to)
                    or ('scorecard_id' in vals and vals['scorecard_id'] != period.scorecard_id.id)):
                raise UserError(_(
                    "Period '%s' is closed: its dates and scorecard cannot change.", period.name))
        return super().write(vals)

    def _create_missing_measurements(self, kpis):
        """Create the rows still missing; KPIs that no longer count get none."""
        self.ensure_one()
        kpis = kpis.filtered(lambda k: k._is_counted())
        existing = self.measurement_ids.mapped('kpi_id')
        previous_period = self.search([
            ('scorecard_id', '=', self.scorecard_id.id),
            ('date_from', '<', self.date_from),
        ], order='date_from desc', limit=1)
        values = []
        for kpi in kpis:
            if kpi in existing:
                continue
            previous = self.env['bsc.measurement']
            if previous_period:
                previous = self.env['bsc.measurement'].search([
                    ('kpi_id', '=', kpi.id),
                    ('period_id', '=', previous_period.id),
                ], limit=1)
            # Precedence: carried-over target, then the KPI default, then empty; all editable on the row.
            target = previous.target_value if previous and previous.target_value else 0.0
            values.append({
                'kpi_id': kpi.id,
                'period_id': self.id,
                'target_value': target or kpi.default_target,
            })
        if values:
            self.env['bsc.measurement'].create(values)
        return True

    def action_notify_owners(self):
        """Ask each data owner, once per period, for their figures.
        Idempotent for the daily cron: same type, deadline and subject (owner's language) means the same reminder."""
        activity_model = self.env['mail.activity']
        todo_type = self.env.ref('mail.mail_activity_data_todo')
        scorecard_model_id = self.env['ir.model']._get_id('bsc.scorecard')
        for period in self:
            pending = period.measurement_ids._filter_counted().filtered(
                lambda m: not m.actual_value_set)
            for owner in pending.mapped('kpi_id.owner_id'):
                owned = pending.filtered(lambda m, o=owner: m.kpi_id.owner_id == o)
                if not owned:
                    continue
                summary = period.with_context(lang=owner.lang or 'en_US').env._(
                    "Enter the figures for %s", period.name)
                already = activity_model.search_count([
                    ('res_model_id', '=', scorecard_model_id),
                    ('res_id', '=', period.scorecard_id.id),
                    ('user_id', '=', owner.id),
                    ('activity_type_id', '=', todo_type.id),
                    ('date_deadline', '=', period.date_to),
                    ('summary', '=', summary),
                ])
                if already:
                    continue
                period.scorecard_id.activity_schedule(
                    act_type_xmlid='mail.mail_activity_data_todo',
                    user_id=owner.id,
                    summary=summary,
                    note=_("Waiting for %(count)s measure(s): %(names)s",
                           count=len(owned),
                           names=", ".join(owned.mapped('kpi_id.name'))),
                    date_deadline=period.date_to,
                )
        return True

    def action_close(self, force=False):
        for period in self:
            if period.state == 'closed':
                continue
            missing = period.measurement_ids._filter_counted().filtered(
                lambda m: not m.actual_value_set)
            if missing and not force and not self.env.context.get('bsc_force_close'):
                raise UserError(_(
                    "%(count)s measure(s) are still empty in period '%(period)s':\n%(names)s\n\n"
                    "Use Close Anyway if this is intentional.",
                    count=len(missing), period=period.name,
                    names="\n".join(missing.mapped('kpi_id.name'))))
            period.measurement_ids._freeze_rules()
            period.state = 'closed'
            period._create_missing_ratings()
            # Score of the period being closed, not the one containing today.
            score = period.scorecard_id.with_context(bsc_period_id=period.id).score
            period.scorecard_id.message_post(body=_(
                "Period %(period)s closed. Completion %(rate)s%%, scorecard score %(score)s%%.",
                period=period.name,
                rate=round(period.completion_rate, 1),
                score=round(score, 1)))
            next_period = self.search([
                ('scorecard_id', '=', period.scorecard_id.id),
                ('date_from', '>', period.date_to),
            ], order='date_from', limit=1)
            if next_period and next_period.state == 'open':
                next_period.action_prepare_measurements()
        return True

    def _create_missing_ratings(self):
        """Keep the rating each qualitative objective has when its period closes.
        A period closed again after a reopen keeps the rating at the new close; one not yet started records none."""
        today = fields.Date.context_today(self)
        Rating = self.env['bsc.objective.rating']
        for period in self.filtered(lambda p: p.date_from <= today):
            existing = Rating.search([('period_id', '=', period.id)])
            for rating in existing.filtered(lambda r: r.objective_id.qualitative_status):
                objective = rating.objective_id
                if (rating.qualitative_status, rating.qualitative_note or False) != \
                        (objective.qualitative_status, objective.qualitative_note or False):
                    rating.write({'qualitative_status': objective.qualitative_status,
                                  'qualitative_note': objective.qualitative_note})
            rated = existing.objective_id
            objectives = period.scorecard_id.objective_ids.filtered(
                lambda o: o.active and o.assessment_mode == 'qualitative'
                and o.qualitative_status and o not in rated)
            Rating.create([{
                'objective_id': objective.id,
                'period_id': period.id,
                'qualitative_status': objective.qualitative_status,
                'qualitative_note': objective.qualitative_note,
            } for objective in objectives])

    def action_force_close(self):
        return self.with_context(bsc_force_close=True).action_close()

    def action_reopen(self):
        """Reopen a closed period; administrator only, always logged."""
        if not (self.env.su or self.env.user.has_group('bsc_strategy.group_bsc_admin')):
            raise UserError(_("Only a Balanced Scorecard administrator can reopen a period."))
        for period in self:
            period.state = 'open'
            period.scorecard_id.message_post(body=_(
                "Period %(period)s reopened by %(user)s.",
                period=period.name, user=self.env.user.display_name))
        return True

    def action_open_measurements(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Measurements - %s", self.name),
            'res_model': 'bsc.measurement',
            'view_mode': 'list,form',
            'domain': [('period_id', '=', self.id)],
            'context': {'default_period_id': self.id},
        }

    @api.model
    def _cron_prepare_and_notify(self):
        """Daily housekeeping: open rows exist, owners get asked once."""
        today = fields.Date.context_today(self)
        periods = self.search([
            ('state', '=', 'open'),
            ('scorecard_id.state', '=', 'active'),
            ('date_from', '<=', today),
        ])
        for period in periods:
            period.action_prepare_measurements()
        # Ask for figures inside the last week of a period.
        for period in periods:
            days_left = (period.date_to - today).days
            if 0 <= days_left <= 7:
                period.action_notify_owners()
        return True
