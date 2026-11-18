# -*- coding: utf-8 -*-
"""The strategy map: everything it needs in one call, built server-side as the scores are computed, not stored.
"""
from odoo import _, api, fields, models
from .bsc_common import weighted_average


class BscScorecardMap(models.Model):
    _inherit = 'bsc.scorecard'

    @api.model
    def get_map_scorecards(self, scorecard_id=False):
        """The scorecards worth drawing, active ones first; the requested one is always listed, even when empty."""
        cards = self.search([('objective_ids', '!=', False)])
        if scorecard_id:
            cards |= self.search([('id', '=', scorecard_id)])
        cards = cards.sorted(key=lambda c: (c.state != 'active', -(c.id or 0)))
        state_labels = dict(self._fields['state']._description_selection(self.env))
        return [{'id': c.id, 'name': c.name, 'state': c.state,
                 'state_label': state_labels.get(c.state, '')} for c in cards]

    def get_strategy_map(self):
        """Perspectives as layers, objectives as cards, links as arrows.
        ``can_manage`` tells the client whether the user may validate links."""
        self.ensure_one()
        status_labels = dict(
            self._fields['status']._description_selection(self.env))
        strength_labels = dict(
            self.env['bsc.objective.link']._fields['strength']
            ._description_selection(self.env))

        objectives = self.objective_ids.filtered('active')
        # Highest sequence first: the map is drawn top-down but read bottom-up.
        perspectives = objectives.perspective_id.sorted(
            key=lambda p: p.sequence, reverse=True)

        period = self.current_period_id
        return {
            'can_manage': self.env['bsc.objective.link'].has_access('write'),
            'scorecard': {
                'id': self.id,
                'name': self.name,
                'state': self.state,
                'score': round(self.score, 1),
                'status': self.status,
                'status_label': status_labels.get(self.status, ''),
                'period': period.name if period else '',
                'completion': round(period.completion_rate, 1) if period else 0.0,
            },
            'perspectives': [
                self._map_perspective(perspective, objectives)
                for perspective in perspectives
            ],
            'objectives': [{
                'id': objective.id,
                'name': objective.name,
                'code': objective.code or '',
                'perspective_id': objective.perspective_id.id,
                'score': round(objective.score, 1),
                'status': objective.status,
                'status_label': status_labels.get(objective.status, ''),
                'weight': round(objective.weight, 1),
                'owner': objective.owner_id.display_name or '',
                'kpi_count': objective.kpi_count,
                'initiative_count': objective.initiative_count,
                'qualitative': objective.assessment_mode == 'qualitative',
            } for objective in objectives],
            'links': [{
                'id': link.id,
                'source_id': link.source_id.id,
                'target_id': link.target_id.id,
                'hypothesis': link.hypothesis or '',
                'strength': link.strength,
                'strength_label': strength_labels.get(link.strength, ''),
                'validated': link.validated,
            } for link in objectives.link_out_ids],
        }

    def _map_perspective(self, perspective, objectives):
        """Perspective row for the map, scored the same way the core rolls up."""
        self.ensure_one()
        inside = objectives.filtered(
            lambda o, p=perspective: o.perspective_id == p)
        score = weighted_average(
            [(o.weight, o.score if o.status != 'no_data' else None) for o in inside])
        return {
            'id': perspective.id,
            'name': perspective.name,
            'sequence': perspective.sequence,
            'weight': round(self._perspective_weight(perspective), 1),
            'objective_count': len(inside),
            'score': round(score, 1) if score is not None else 0.0,
            'has_data': score is not None,
            'bar': min(100.0, max(0.0, round(score, 1))) if score is not None else 0.0,
        }

    def action_open_strategy_map(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'bsc_strategy_map',
            'name': _("Strategy Map - %s", self.name),
            'params': {'scorecard_id': self.id},
            'context': {'default_scorecard_id': self.id},
        }


class BscObjectiveLinkMap(models.Model):
    _inherit = 'bsc.objective.link'

    def action_toggle_validated_from_map(self, validated=None):
        """Tick a hypothesis off from the map itself.
        The client sends the wanted value, so a second click on a stale screen writes and posts nothing;
without ``validated`` the flag is flipped."""
        self.ensure_one()
        target = (not self.validated) if validated is None else bool(validated)
        if target != self.validated:
            self.validated = target
            self.scorecard_id.message_post(body=_(
                "Cause-effect link '%(link)s' marked as %(state)s by %(user)s.",
                link=self.display_name,
                state=_("validated with data") if self.validated else _("not yet validated"),
                user=self.env.user.display_name))
        return self.validated


class BscObjectiveDetail(models.Model):
    """What the inspector panel shows when a card is clicked; fetched on demand to keep the map payload small."""
    _inherit = 'bsc.objective'

    def get_map_detail(self):
        self.ensure_one()
        Measurement = self.env['bsc.measurement']
        status_labels = dict(self._fields['status']._description_selection(self.env))
        trend_labels = dict(
            Measurement._fields['trend']._description_selection(self.env))
        # Capability check: the automation fields may be absent.
        automated = 'is_automated' in Measurement._fields
        period = self.scorecard_id.current_period_id

        kpis = []
        for kpi in self.kpi_ids.filtered('active'):
            measurement = kpi.current_measurement_id
            kpis.append({
                'id': kpi.id,
                'name': kpi.name,
                'uom': kpi.uom_name or '',
                'direction': kpi.direction,
                'weight': round(kpi.weight, 1),
                'owner': kpi.owner_id.display_name or '',
                'target': round(kpi.current_target, 2),
                'actual': round(kpi.current_actual, 2),
                'achievement': round(kpi.current_achievement, 1),
                'status': kpi.current_status,
                'status_label': status_labels.get(kpi.current_status, ''),
                'reported': bool(measurement and measurement.actual_value_set),
                'trend': measurement.trend if measurement else 'flat',
                'trend_label': trend_labels.get(
                    measurement.trend if measurement else 'flat', ''),
                'comment': (measurement.comment or '') if measurement else '',
                'is_automated': bool(
                    automated and measurement and measurement.is_automated),
                'auto_state': (measurement.auto_state or '') if (
                    automated and measurement) else '',
                'auto_message': (measurement.auto_message or '') if (
                    automated and measurement) else '',
            })

        def link_row(link, other):
            return {
                'id': link.id,
                'other_id': other.id,
                'other_code': other.code or '',
                'other_name': other.name,
                'other_status': other.status,
                'hypothesis': link.hypothesis or '',
                'strength': link.strength,
                'validated': link.validated,
            }

        return {
            'type': 'objective',
            'id': self.id,
            'name': self.name,
            'code': self.code or '',
            'perspective': self.perspective_id.name,
            'owner': self.owner_id.display_name or '',
            'weight': round(self.weight, 1),
            'score': round(self.score, 1),
            'status': self.status,
            'status_label': status_labels.get(self.status, ''),
            'qualitative': self.assessment_mode == 'qualitative',
            'qualitative_note': self.qualitative_note or '',
            'description': self.description or '',
            'period': period.name if period else '',
            'kpis': kpis,
            'driven_by': [link_row(link, link.source_id) for link in self.link_in_ids],
            'drives': [link_row(link, link.target_id) for link in self.link_out_ids],
            'initiatives': [
                self._map_initiative(initiative)
                for initiative in self.initiative_ids.sorted(
                    key=lambda i: (i.state == 'done', i.state == 'cancelled',
                                   -int(i.priority or '0')))
            ],
            'initiative_summary': self._map_initiative_summary(),
            'currency': self.scorecard_id.currency_id.symbol or '',
        }

    def _map_initiative(self, initiative):
        """One initiative as the panel needs it: budget, owner, dates and execution project.
        Project and task names are read with sudo, labels only, so a private project cannot break the panel."""
        self.ensure_one()
        state_labels = dict(
            initiative._fields['state']._description_selection(self.env))
        priority_labels = dict(
            initiative._fields['priority']._description_selection(self.env))
        values = {
            'id': initiative.id,
            'name': initiative.name,
            'stage': initiative.stage_id.name or '',
            'state': initiative.state or '',
            'state_label': state_labels.get(initiative.state, ''),
            'priority': initiative.priority,
            'priority_label': priority_labels.get(initiative.priority, ''),
            'progress': round(initiative.progress, 0),
            'owner': initiative.owner_id.display_name or '',
            'budget_planned': round(initiative.budget_planned, 0),
            'budget_actual': round(initiative.budget_actual, 0),
            'budget_over': initiative.budget_actual > initiative.budget_planned > 0.0,
            'expected_impact': initiative.expected_impact or '',
            'date_start': (initiative.date_start and
                           fields.Date.to_string(initiative.date_start)) or '',
            'date_end': (initiative.date_end and
                         fields.Date.to_string(initiative.date_end)) or '',
            'overdue': bool(
                initiative.date_end
                and initiative.date_end < fields.Date.context_today(self)
                and initiative.state in ('approved', 'in_progress')),
            'project': '',
            'project_id': False,
            'task': '',
            'task_id': False,
            'task_state': '',
            'task_count': 0,
            'task_done_count': 0,
            'project_progress': 0,
            'tracks_project': False,
            'needs_execution': False,
        }
        # Capability check: the project fields may be absent.
        if 'project_id' in initiative._fields:
            project, task = initiative.project_id, initiative.task_id
            values.update({
                'project': project.sudo().display_name or '',
                'project_id': project.id or False,
                'task': task.sudo().display_name or '',
                'task_id': task.id or False,
                'task_state': self._task_state_label(task.sudo()),
                'task_count': initiative.task_count or 0,
                'task_done_count': initiative.task_done_count or 0,
                'project_progress': round(initiative.project_progress, 0),
                'tracks_project': bool(
                    initiative.use_project_progress and (project or task)),
                # Work started with nothing behind it is the gap worth showing; the chatter only hints at it.
                'needs_execution': bool(
                    initiative.state == 'in_progress' and not project and not task),
            })
        return values

    def _task_state_label(self, task):
        """Read the label from the field selection, not a hardcoded text."""
        if not task:
            return ''
        labels = dict(task._fields['state']._description_selection(self.env))
        return labels.get(task.state, task.state or '')

    def _map_initiative_summary(self):
        """The one line that answers 'is anything being done about this?'"""
        self.ensure_one()
        initiatives = self.initiative_ids
        live = initiatives.filtered(lambda i: i.state in ('approved', 'in_progress'))
        return {
            'count': len(initiatives),
            'live': len(live),
            'proposed': len(initiatives.filtered(lambda i: i.state == 'proposed')),
            'done': len(initiatives.filtered(lambda i: i.state == 'done')),
            'overdue': len(live.filtered(
                lambda i: i.date_end and i.date_end < fields.Date.context_today(self))),
            'budget_planned': round(sum(initiatives.mapped('budget_planned')), 0),
            'budget_actual': round(sum(initiatives.mapped('budget_actual')), 0),
            'progress': round(
                sum(live.mapped('progress')) / len(live), 0) if live else 0,
        }


class BscObjectiveLinkDetail(models.Model):
    _inherit = 'bsc.objective.link'

    def get_map_detail(self):
        self.ensure_one()
        status_labels = dict(
            self.env['bsc.objective']._fields['status']
            ._description_selection(self.env))
        strength_labels = dict(
            self._fields['strength']._description_selection(self.env))

        def end(objective):
            return {
                'id': objective.id,
                'code': objective.code or '',
                'name': objective.name,
                'perspective': objective.perspective_id.name,
                'score': round(objective.score, 1),
                'status': objective.status,
                'status_label': status_labels.get(objective.status, ''),
            }

        return {
            'type': 'link',
            'id': self.id,
            'hypothesis': self.hypothesis or '',
            'strength': self.strength,
            'strength_label': strength_labels.get(self.strength, ''),
            'validated': self.validated,
            'validation_note': self.validation_note or '',
            'source': end(self.source_id),
            'target': end(self.target_id),
        }
