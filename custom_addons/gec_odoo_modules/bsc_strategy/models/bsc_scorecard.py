# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .bsc_common import (
    computed_selection_search,
    PARAM_THRESHOLD_AMBER,
    PARAM_THRESHOLD_GREEN,
    DEFAULT_THRESHOLD_AMBER,
    DEFAULT_THRESHOLD_GREEN,
    rag_status,
    weighted_average,
)

FREQUENCY_MONTHS = {
    'monthly': 1,
    'quarterly': 3,
    'semiannual': 6,
    'annual': 12,
}

FREQUENCY_LABEL = {
    'monthly': 'M',
    'quarterly': 'Q',
    'semiannual': 'H',
    'annual': 'Y',
}


class BscScorecard(models.Model):
    """One organisation's (or unit's) strategy for one planning cycle."""
    _name = 'bsc.scorecard'
    _description = 'BSC Scorecard'
    _check_company_auto = True
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    date_from = fields.Date(string='Cycle Start', required=True, tracking=True)
    date_to = fields.Date(string='Cycle End', required=True, tracking=True)
    frequency = fields.Selection(
        [('monthly', 'Monthly'),
         ('quarterly', 'Quarterly'),
         ('semiannual', 'Semi-annual'),
         ('annual', 'Annual')],
        string='Review Frequency', default='quarterly', required=True,
        help="Drives the periods generated when the scorecard is activated.")
    state = fields.Selection(
        [('draft', 'Draft'),
         ('active', 'Active'),
         ('closed', 'Closed'),
         ('cancelled', 'Cancelled')],
        default='draft', required=True, tracking=True)
    responsible_id = fields.Many2one(
        'res.users', string='Strategy Owner', required=True,
        default=lambda self: self.env.user, tracking=True)
    parent_id = fields.Many2one(
        'bsc.scorecard', string='Parent Scorecard', ondelete='set null', check_company=True,
        help="Set this when the scorecard cascades from a higher-level one.")
    child_ids = fields.One2many('bsc.scorecard', 'parent_id', string='Cascaded Scorecards')
    vision = fields.Html(string='Vision')
    mission = fields.Html(string='Mission')

    objective_ids = fields.One2many('bsc.objective', 'scorecard_id', string='Objectives')
    initiative_ids = fields.One2many('bsc.initiative', 'scorecard_id', string='Initiatives')
    period_ids = fields.One2many('bsc.period', 'scorecard_id', string='Periods')
    weight_ids = fields.One2many(
        'bsc.scorecard.perspective', 'scorecard_id', string='Perspective Weights')
    review_ids = fields.One2many('bsc.review', 'scorecard_id', string='Reviews')

    objective_count = fields.Integer(compute='_compute_counts')
    kpi_count = fields.Integer(compute='_compute_counts')
    initiative_count = fields.Integer(compute='_compute_counts')

    current_period_id = fields.Many2one(
        'bsc.period', string='Current Period', compute='_compute_current_period')
    score = fields.Float(string='Score (%)', compute='_compute_score', digits=(16, 1))
    status = fields.Selection(
        [('green', 'On Track'),
         ('amber', 'At Risk'),
         ('red', 'Off Track'),
         ('no_data', 'No Data')],
        compute='_compute_score', search='_search_status')
    is_demo = fields.Boolean(
        string='Demo Data', readonly=True, copy=False,
        help="Created by Configuration > Demo Data and removed by it as well.")
    kpi_ids = fields.One2many(
        'bsc.kpi', 'scorecard_id', string='All KPIs', readonly=True)
    link_ids = fields.One2many(
        'bsc.objective.link', 'scorecard_id', string='Cause-Effect Links', readonly=True)
    link_count = fields.Integer(compute='_compute_counts')
    setup_checklist = fields.Html(
        compute='_compute_setup_checklist', sanitize=False,
        help="What is done and what is still missing, in the order the method "
             "wants it done.")
    setup_done = fields.Boolean(compute='_compute_setup_checklist')
    auto_create_review = fields.Boolean(
        string='Open the Review Automatically', default=True,
        help="When a period closes, create its strategy review as a draft with the "
             "score and the off-track objectives already frozen. The meeting still "
             "has to happen - but nobody has to remember to create the record.")

    def _search_status(self, operator, value):
        return computed_selection_search(self, 'status', operator, value)

    @api.depends('objective_ids', 'objective_ids.kpi_ids', 'initiative_ids', 'link_ids')
    def _compute_counts(self):
        for card in self:
            card.objective_count = len(card.objective_ids)
            card.kpi_count = len(card.objective_ids.kpi_ids)
            card.initiative_count = len(card.initiative_ids)
            card.link_count = len(card.link_ids)

    @api.depends('state', 'objective_ids', 'objective_ids.assessment_mode',
                 'objective_ids.kpi_ids', 'objective_ids.kpi_ids.default_target',
                 'objective_ids.kpi_ids.direction', 'objective_ids.perspective_id',
                 'link_ids', 'initiative_ids', 'period_ids.state')
    def _compute_setup_checklist(self):
        """Ordered setup to-do list: objectives, links, measures, work; each step names what is missing."""
        for card in self:
            steps = card._setup_steps()
            card.setup_done = all(step['done'] for step in steps if not step.get('optional'))
            card.setup_checklist = card._render_checklist(steps)

    def _setup_steps(self):
        self.ensure_one()
        objectives = self.objective_ids.filtered('active')
        kpi_objectives = objectives.filtered(lambda o: o.assessment_mode == 'kpi')
        kpis = objectives.kpi_ids.filtered('active')
        perspectives = self.env['bsc.perspective'].search([
            '|', ('company_id', '=', False), ('company_id', '=', self.company_id.id)])
        empty_perspectives = perspectives.filtered(
            lambda p: p not in objectives.perspective_id)
        no_kpi = kpi_objectives.filtered(lambda o: not o.kpi_ids)
        no_target = kpis.filtered(
            lambda k: k.direction != 'target_range' and not k.default_target
            and k.target_rule != 'empty')
        linked = self.link_ids.source_id | self.link_ids.target_id
        unlinked = objectives - linked
        no_initiative = objectives.filtered(lambda o: not o.initiative_ids)

        def names(records, limit=6):
            listed = records[:limit].mapped('name')
            more = len(records) - limit
            text = ", ".join(listed)
            return text + (_(" and %s more", more) if more > 0 else "")

        steps = [{
            'title': _("Strategic objectives in the perspectives"),
            'done': bool(objectives),
            'detail': (_("%s objective(s).", len(objectives)) if objectives
                       else _("No objectives yet - open the Objectives tab."))
            + ((" " + _("Perspectives with no objective yet: %s.", names(empty_perspectives)))
               if objectives and empty_perspectives else ""),
        }, {
            'title': _("Cause-effect links between objectives"),
            'done': bool(self.link_ids) and not unlinked,
            'optional': True,
            'detail': (_("%s link(s).", len(self.link_ids)) if self.link_ids
                       else _("None yet. Say which objective drives which."))
            + ((" " + _("Not connected yet: %s.", names(unlinked)))
               if self.link_ids and unlinked else ""),
        }, {
            'title': _("At least one KPI for every measured objective"),
            'done': bool(kpi_objectives) and not no_kpi,
            'detail': (_("Missing for: %s.", names(no_kpi)) if no_kpi
                       else _("%s KPI(s) defined.", len(kpis))),
        }, {
            'title': _("A target on every KPI"),
            'done': bool(kpis) and not no_target,
            'detail': (_("No target yet: %s. Without a target a reported figure "
                         "shows as No Data.", names(no_target)) if no_target
                       else _("Every KPI has a target.") if kpis else _("Add KPIs first.")),
        }, {
            'title': _("Initiatives behind the objectives"),
            'done': bool(objectives) and not no_initiative,
            'optional': True,
            'detail': (_("Nothing planned yet for: %s.", names(no_initiative))
                       if no_initiative else _("Every objective has an initiative.")),
        }, {
            'title': _("Activate the scorecard"),
            'done': self.state != 'draft',
            'detail': (_("Active. Periods were generated and figures can be entered "
                         "under Data Entry.") if self.state != 'draft'
                       else _("Press Activate once the steps above are done.")),
        }]
        return steps

    def _render_checklist(self, steps):
        from markupsafe import Markup, escape
        rows = []
        for index, step in enumerate(steps, 1):
            if step['done']:
                icon, tone = 'check_circle', 'text-success'
            elif step.get('optional'):
                icon, tone = 'radio_button_unchecked', 'text-muted'
            else:
                icon, tone = 'error', 'text-warning'
            optional = (Markup(' <span class="badge text-bg-light">%s</span>')
                        % _("optional")) if step.get('optional') else ''
            rows.append(Markup(
                '<li class="list-group-item d-flex gap-2 align-items-start py-2">'
                '<i class="oi %s mt-1" data-icon="%s" role="img"></i>'
                '<div><strong>%s. %s</strong>%s<div class="text-muted small">%s</div></div>'
                '</li>') % (tone, icon, index, step['title'], optional, step['detail']))
        return Markup('<ul class="list-group list-group-flush mb-0">%s</ul>') % Markup('').join(rows)

    def action_open_links(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Cause-Effect Links"),
            'res_model': 'bsc.objective.link',
            'view_mode': 'list,form',
            'domain': [('scorecard_id', '=', self.id)],
            'context': {'bsc_scorecard_id': self.id},
        }

    def action_open_data_entry(self):
        """Every figure of the open period(s), not only the user's own."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'bsc_strategy.action_bsc_data_entry')
        action['domain'] = [('scorecard_id', '=', self.id)]
        action['context'] = {'search_default_filter_open_period': 1}
        return action

    def action_open_dashboard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'bsc_dashboard',
            'name': _("Dashboard - %s", self.name),
            'params': {'scorecard_id': self.id},
        }

    @api.depends('period_ids', 'period_ids.date_from', 'period_ids.date_to', 'period_ids.state')
    @api.depends_context('bsc_period_id')
    def _compute_current_period(self):
        """The period every score is read for.
        The latest ended period while still open; else the one containing today, else the last past one, else the first.
        ``with_context(bsc_period_id=...)`` pins another one."""
        today = fields.Date.context_today(self)
        pinned = self.env.context.get('bsc_period_id')
        for card in self:
            periods = card.period_ids.sorted('date_from')
            if pinned and pinned in periods.ids:
                card.current_period_id = periods.filtered(lambda p: p.id == pinned)
                continue
            past = periods.filtered(lambda p: p.date_to < today)
            last_past = past[-1:]
            current = last_past if last_past and last_past.state == 'open' else periods.browse()
            if not current:
                current = periods.filtered(lambda p: p.date_from <= today <= p.date_to)
            if not current:
                current = past[-1:] if past else periods[:1]
            card.current_period_id = current[:1]

    @api.depends('weight_ids.weight', 'weight_ids.score',
                 'objective_ids.score', 'objective_ids.weight',
                 'objective_ids.perspective_id')
    @api.depends_context('bsc_period_id')
    def _compute_score(self):
        green = self._get_param(PARAM_THRESHOLD_GREEN, DEFAULT_THRESHOLD_GREEN)
        amber = self._get_param(PARAM_THRESHOLD_AMBER, DEFAULT_THRESHOLD_AMBER)
        for card in self:
            pairs = []
            for perspective in card.objective_ids.perspective_id:
                objectives = card.objective_ids.filtered(
                    lambda o, p=perspective: o.perspective_id == p)
                perspective_score = weighted_average(
                    [(o.weight, o.score if o.status != 'no_data' else None) for o in objectives])
                pairs.append((card._perspective_weight(perspective), perspective_score))
            value = weighted_average(pairs)
            card.score = value or 0.0
            card.status = rag_status(value, green, amber)

    def _get_param(self, key, default):
        """Read a numeric setting, falling back to the default; uses ``get_float`` when available."""
        params = self.env['ir.config_parameter'].sudo()
        if hasattr(params, 'get_float'):
            value = params.get_float(key, default=None)
            return default if value is None else value
        value = params.get_param(key)
        try:
            return float(value) if value else default
        except (TypeError, ValueError):
            return default

    def _perspective_weight(self, perspective):
        """Scorecard-level override, falling back to the perspective default."""
        self.ensure_one()
        line = self.weight_ids.filtered(lambda w, p=perspective: w.perspective_id == p)
        if line:
            return line[:1].weight
        return perspective.default_weight

    def get_perspective_summary(self):
        """One row per perspective, in strategy-map order; public because QWeb cannot call ``_`` methods."""
        self.ensure_one()
        rows = []
        for perspective in self.objective_ids.perspective_id.sorted('sequence'):
            objectives = self.objective_ids.filtered(
                lambda o, p=perspective: o.perspective_id == p)
            score = weighted_average(
                [(o.weight, o.score if o.status != 'no_data' else None) for o in objectives])
            rows.append({
                'name': perspective.name,
                'objective_count': len(objectives),
                'weight': self._perspective_weight(perspective),
                'score': score or 0.0,
                'has_data': score is not None,
            })
        return rows

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for card in self:
            if card.date_from and card.date_to and card.date_from > card.date_to:
                raise ValidationError(_("The cycle end date must be after the start date."))

    @api.constrains('parent_id')
    def _check_parent_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("A scorecard cannot be its own ancestor."))

    def action_activate(self):
        """Validate the design, generate the periods, open the first one.
        These checks are the only hard gate; weights, links and the approval flow stay optional."""
        today = fields.Date.context_today(self)
        for card in self:
            if card.state != 'draft':
                raise UserError(_("Only a draft scorecard can be activated."))
            problems = card._activation_problems()
            if problems:
                raise UserError(_(
                    "The scorecard cannot be activated yet:\n\n%s",
                    "\n".join("- %s" % problem for problem in problems)))
            card._generate_periods()
            card.state = 'active'
            card.message_post(body=_("Scorecard activated. %s period(s) generated.",
                                     len(card.period_ids)))
            # Rows for every started period, so an earlier period without rows cannot close as "complete".
            started = card.period_ids.filtered(lambda p: p.date_from <= today)
            for period in (started or card.period_ids.sorted('date_from')[:1]).sorted('date_from'):
                if period.state == 'open':
                    period.action_prepare_measurements()
        return True

    def _activation_problems(self):
        """Everything that blocks activation, as plain sentences."""
        self.ensure_one()
        problems = []
        objectives = self.objective_ids
        if not objectives:
            problems.append(_("Add at least one strategic objective."))
        no_kpi = objectives.filtered(
            lambda o: o.assessment_mode == 'kpi' and not o.kpi_ids)
        if no_kpi:
            problems.append(_(
                "These objectives have no KPI - add a measure or switch them to "
                "qualitative assessment: %s", ", ".join(no_kpi.mapped('name'))))
        missing_owner = objectives.kpi_ids.filtered(lambda k: not k.owner_id)
        if missing_owner:
            problems.append(_(
                "These KPIs have no data owner, so nobody would be asked for the "
                "figures: %s", ", ".join(missing_owner.mapped('name'))))
        return problems

    def action_close(self):
        for card in self:
            card.period_ids.filtered(lambda p: p.state == 'open').action_close(force=True)
            card.state = 'closed'
        return True

    def action_back_to_draft(self):
        """Delete the (empty) periods, back to draft; reactivation regenerates them.
        Runs as superuser after the write check; also deletes reminders due on a deleted period's end date,
only the KPI owners' and the responsible's."""
        for card in self:
            card.check_access('write')
            periods = card.sudo().period_ids
            if periods.measurement_ids.filtered('actual_value_set'):
                raise UserError(_(
                    "This scorecard already holds measured data and cannot go back to draft."))
            if (periods.filtered(lambda p: p.state == 'closed')
                    or self.env['bsc.review'].sudo().search_count(
                        [('period_id', 'in', periods.ids)])):
                raise UserError(_(
                    "This scorecard already has a closed period or a strategy review "
                    "and cannot go back to draft."))
            todo = self.env.ref('mail.mail_activity_data_todo')
            deadlines = set(periods.mapped('date_to'))
            reminded = (card.sudo().with_context(active_test=False).kpi_ids.owner_id
                        | card.responsible_id)
            card.sudo().activity_ids.filtered(
                lambda a: a.activity_type_id == todo and a.date_deadline in deadlines
                and a.user_id in reminded).unlink()
            periods.unlink()
            card.state = 'draft'
        return True

    def _generate_periods(self):
        """Create the reporting periods for the whole cycle."""
        self.ensure_one()
        months = FREQUENCY_MONTHS[self.frequency]
        label = FREQUENCY_LABEL[self.frequency]
        existing = {(p.date_from, p.date_to) for p in self.period_ids}
        values = []
        start = self.date_from
        position = 0
        while start <= self.date_to:
            end = start + relativedelta(months=months, days=-1)
            if end > self.date_to:
                end = self.date_to
            if (start, end) not in existing:
                if self.frequency == 'annual':
                    name = str(start.year)
                elif self.frequency == 'monthly':
                    name = '%s-%02d' % (start.year, start.month)
                elif start.day == 1 and (start.month - 1) % months == 0:
                    name = '%s-%s%s' % (start.year, label, (start.month - 1) // months + 1)
                else:
                    name = '%s-%s%s' % (start.year, label, position % (12 // months) + 1)
                values.append({
                    'name': name,
                    'scorecard_id': self.id,
                    'date_from': start,
                    'date_to': end,
                })
            start = end + relativedelta(days=1)
            position += 1
        if values:
            self.env['bsc.period'].create(values)
        return True

    def action_duplicate_to_new_cycle(self):
        """Copy only the design into a new cycle: objectives, KPIs, perspective weights, strategy map.
        Measurements, periods, reviews and initiatives stay with the old cycle; links are rebuilt old-to-new."""
        self.ensure_one()
        new_card = self.copy({
            'name': _("%s (copy)", self.name),
            'state': 'draft',
        })
        mapping = {}
        for objective in self.objective_ids:
            mapping[objective.id] = objective.copy({'scorecard_id': new_card.id}).id
        for link in self.objective_ids.link_out_ids:
            if link.source_id.id in mapping and link.target_id.id in mapping:
                link.copy({
                    'source_id': mapping[link.source_id.id],
                    'target_id': mapping[link.target_id.id],
                })
        for line in self.weight_ids:
            line.copy({'scorecard_id': new_card.id})
        new_card.message_post(body=_("Copied from %s.", self.name))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'bsc.scorecard',
            'res_id': new_card.id,
            'view_mode': 'form',
        }

    def action_open_objectives(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Objectives"),
            'res_model': 'bsc.objective',
            'view_mode': 'kanban,list,form',
            'domain': [('scorecard_id', '=', self.id)],
            'context': {'default_scorecard_id': self.id},
        }

    def action_open_kpis(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Key Performance Indicators"),
            'res_model': 'bsc.kpi',
            'view_mode': 'list,form',
            'domain': [('scorecard_id', '=', self.id)],
        }

    def action_open_initiatives(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Initiatives"),
            'res_model': 'bsc.initiative',
            'view_mode': 'kanban,list,form',
            'domain': [('scorecard_id', '=', self.id)],
            'context': {'default_scorecard_id': self.id},
        }


class BscScorecardPerspective(models.Model):
    """Per-scorecard weight (and resulting score) of a perspective."""
    _name = 'bsc.scorecard.perspective'
    _description = 'BSC Scorecard Perspective Weight'
    _order = 'sequence, id'
    _check_company_auto = True

    scorecard_id = fields.Many2one(
        'bsc.scorecard', required=True, ondelete='cascade', index=True)
    perspective_id = fields.Many2one(
        'bsc.perspective', required=True, ondelete='cascade', check_company=True)
    sequence = fields.Integer(related='perspective_id.sequence', store=True)
    weight = fields.Float(string='Weight (%)', default=25.0)
    company_id = fields.Many2one(related='scorecard_id.company_id', store=True, index=True)
    score = fields.Float(string='Score (%)', compute='_compute_score', digits=(16, 1))
    objective_count = fields.Integer(compute='_compute_score')

    _scorecard_perspective_uniq = models.Constraint(
        'unique(scorecard_id, perspective_id)',
        'A perspective can only be weighted once per scorecard.',
    )

    @api.depends('scorecard_id.objective_ids.score',
                 'scorecard_id.objective_ids.weight',
                 'scorecard_id.objective_ids.perspective_id')
    @api.depends_context('bsc_period_id')
    def _compute_score(self):
        for line in self:
            objectives = line.scorecard_id.objective_ids.filtered(
                lambda o, l=line: o.perspective_id == l.perspective_id)
            line.objective_count = len(objectives)
            value = weighted_average(
                [(o.weight, o.score if o.status != 'no_data' else None) for o in objectives])
            line.score = value or 0.0
