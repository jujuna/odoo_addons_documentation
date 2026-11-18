# -*- coding: utf-8 -*-
"""Manager dashboard: one payload per scorecard and period, built server-side, period pinned via ``bsc_period_id``.
"""
from odoo import _, api, fields, models

from .bsc_common import (
    DEFAULT_THRESHOLD_AMBER,
    DEFAULT_THRESHOLD_GREEN,
    PARAM_THRESHOLD_AMBER,
    PARAM_THRESHOLD_GREEN,
    rag_status,
)


class BscScorecardDashboard(models.Model):
    _inherit = 'bsc.scorecard'

    @api.model
    def get_dashboard_data(self, scorecard_id=False, period_id=False):
        cards = self.search([('state', 'in', ('active', 'closed', 'draft'))])
        cards = cards.sorted(key=lambda c: (
            {'active': 0, 'closed': 1, 'draft': 2}.get(c.state, 3), -(c.date_from.toordinal() if c.date_from else 0)))
        result = {
            'scorecards': [{'id': c.id, 'name': c.name, 'state': c.state,
                            'is_demo': c.is_demo} for c in cards],
            'scorecard': False,
        }
        card = cards.filtered(lambda c: c.id == scorecard_id)[:1] or cards[:1]
        if not card:
            return result
        periods = card.period_ids.sorted('date_from')
        period = periods.filtered(lambda p: p.id == period_id)[:1] or card.current_period_id
        result.update(card._dashboard_payload(period, periods))
        return result

    def _dashboard_payload(self, period, periods):
        self.ensure_one()
        status_labels = dict(self._fields['status']._description_selection(self.env))
        state_labels = dict(self._fields['state']._description_selection(self.env))
        green = self._get_param(PARAM_THRESHOLD_GREEN, DEFAULT_THRESHOLD_GREEN)
        amber = self._get_param(PARAM_THRESHOLD_AMBER, DEFAULT_THRESHOLD_AMBER)
        today = fields.Date.context_today(self)
        card = self.with_context(bsc_period_id=period.id) if period else self

        payload = {
            'scorecard': {
                'id': self.id,
                'name': self.name,
                'state': self.state,
                'state_label': state_labels.get(self.state, ''),
                'is_demo': self.is_demo,
                'owner': self.responsible_id.display_name or '',
                'date_from': fields.Date.to_string(self.date_from),
                'date_to': fields.Date.to_string(self.date_to),
                'score': round(card.score, 1),
                'status': card.status,
                'status_label': status_labels.get(card.status, ''),
            },
            'periods': [{
                'id': p.id, 'name': p.name, 'state': p.state, 'is_current': p.is_current,
            } for p in periods],
            'period': False,
            'currency': self.currency_id.symbol or '',
            'thresholds': {'green': green, 'amber': amber},
            'can_manage': self.env.user.has_group('bsc_strategy.group_bsc_manager'),
        }
        if period:
            payload['period'] = {
                'id': period.id,
                'name': period.name,
                'state': period.state,
                'date_from': fields.Date.to_string(period.date_from),
                'date_to': fields.Date.to_string(period.date_to),
                'completion': round(period.completion_rate, 1),
                'filled': period.filled_count,
                'expected': period.measurement_count,
                'started': period.date_from <= today,
                'days_left': (period.date_to - today).days if period.state == 'open' else None,
            }

        perspectives = []
        for perspective in card.objective_ids.filtered('active').perspective_id.sorted(
                key=lambda p: p.sequence, reverse=True):
            row = card._map_perspective(perspective, card.objective_ids.filtered('active'))
            status = rag_status(row['score'] if row['has_data'] else None, green, amber)
            row.update({'status': status, 'status_label': status_labels.get(status, '')})
            perspectives.append(row)
        payload['perspectives'] = perspectives

        objectives = card.objective_ids.filtered('active').sorted(
            key=lambda o: (-o.perspective_id.sequence, o.sequence, o.id))
        payload['objectives'] = [{
            'id': o.id,
            'code': o.code or '',
            'name': o.name,
            'perspective': o.perspective_id.name,
            'owner': o.owner_id.display_name or '',
            'score': round(o.score, 1),
            'status': o.status,
            'status_label': status_labels.get(o.status, ''),
            'kpi_count': o.kpi_count,
            'qualitative': o.assessment_mode == 'qualitative',
            'live_initiatives': len(o.initiative_ids.filtered(
                lambda i: i.state in ('approved', 'in_progress'))),
        } for o in objectives]

        rows = period.measurement_ids._filter_counted() if period else \
            self.env['bsc.measurement']
        trend_labels = dict(rows._fields['trend']._description_selection(self.env))
        automated = 'auto_needs_attention' in rows._fields
        payload['kpis'] = [{
            'id': m.id,
            'kpi_id': m.kpi_id.id,
            'name': m.kpi_id.name,
            'objective': m.objective_id.code or m.objective_id.name,
            'objective_name': m.objective_id.name,
            'perspective': m.perspective_id.name,
            'unit': m.uom_name or '',
            'target': m.target_value,
            'actual': m.actual_value,
            'reported': m.actual_value_set,
            'previous': m.previous_value if m.has_previous else None,
            'achievement': round(m.achievement, 1),
            'status': m.status,
            'status_label': status_labels.get(m.status, ''),
            'trend': m.trend,
            'trend_label': trend_labels.get(m.trend, ''),
            'comment': m.comment or '',
            'owner': m.owner_id.display_name or '',
            'state': m.state,
            'direction': m.direction,
        } for m in rows.sorted(key=lambda m: (-m.perspective_id.sequence,
                                              m.objective_id.sequence, m.kpi_id.sequence))]
        payload['kpi_counts'] = {
            status: len(rows.filtered(lambda m, s=status: m.status == s))
            for status in ('green', 'amber', 'red', 'no_data')
        }

        trend = []
        rated_periods = self.env['bsc.objective.rating'].search(
            [('period_id', 'in', periods.ids)]).period_id
        for p in periods:
            if period and p.date_from > period.date_from:
                break
            scored = self.with_context(bsc_period_id=p.id)
            has_data = bool(p.filled_count) or p in rated_periods
            trend.append({
                'id': p.id,
                'name': p.name,
                'score': round(scored.score, 1) if has_data else None,
                'status': scored.status if has_data else 'no_data',
                'completion': round(p.completion_rate, 1),
                'state': p.state,
            })
        payload['trend'] = trend

        missing = rows.filtered(lambda m: not m.actual_value_set)
        by_owner = {}
        for m in missing:
            by_owner.setdefault(m.owner_id, []).append(m.kpi_id.name)
        live_states = ('approved', 'in_progress')
        initiatives = self.initiative_ids.filtered('active')
        red_objectives = objectives.filtered(lambda o: o.status == 'red')
        payload['attention'] = {
            'missing_total': len(missing),
            'missing_by_owner': [{
                'id': owner.id,
                'owner': owner.display_name or _("Nobody"),
                'count': len(names),
                'kpis': names,
            } for owner, names in sorted(by_owner.items(), key=lambda item: -len(item[1]))],
            'red_without_comment': [{
                'id': m.id, 'name': m.kpi_id.name,
            } for m in rows.filtered(lambda m: m.status == 'red' and not m.comment)],
            'held': [{
                'id': m.id, 'name': m.kpi_id.name,
            } for m in (rows.filtered('auto_needs_attention') if automated else rows.browse())],
            'red_without_action': [{
                'id': o.id, 'code': o.code or '', 'name': o.name,
            } for o in red_objectives.filtered(
                lambda o: not o.initiative_ids.filtered(lambda i: i.state in live_states))],
            'overdue': [{
                'id': i.id, 'name': i.name, 'owner': i.owner_id.display_name or '',
                'date_end': fields.Date.to_string(i.date_end),
                'days': (today - i.date_end).days,
            } for i in initiatives.filtered(
                lambda i: i.state in live_states and i.date_end and i.date_end < today)],
            'over_budget': [{
                'id': i.id, 'name': i.name,
                'planned': i.budget_planned, 'actual': i.budget_actual,
            } for i in initiatives.filtered(
                lambda i: i.budget_planned and i.budget_actual > i.budget_planned)],
        }

        stage_labels = dict(initiatives._fields['state']._description_selection(self.env))
        live = initiatives.filtered(lambda i: i.state in live_states)
        payload['initiatives'] = {
            'counts': {state: len(initiatives.filtered(lambda i, s=state: i.state == s))
                       for state in ('proposed', 'approved', 'in_progress', 'done', 'cancelled')},
            'budget_planned': sum(initiatives.filtered(
                lambda i: i.state != 'cancelled').mapped('budget_planned')),
            'budget_actual': sum(initiatives.mapped('budget_actual')),
            'average_progress': round(sum(live.mapped('progress')) / len(live), 0) if live else 0,
            'items': [{
                'id': i.id,
                'name': i.name,
                'state': i.state,
                'state_label': stage_labels.get(i.state, ''),
                'stage': i.stage_id.name or '',
                'owner': i.owner_id.display_name or '',
                'progress': round(i.progress, 0),
                'date_end': fields.Date.to_string(i.date_end) if i.date_end else '',
                'overdue': bool(i.state in live_states and i.date_end and i.date_end < today),
                'planned': i.budget_planned,
                'actual': i.budget_actual,
                'objectives': ", ".join(o.code or o.name for o in i.objective_ids),
            } for i in initiatives.sorted(key=lambda i: (
                i.state not in live_states, i.state == 'done', i.state == 'cancelled',
                -int(i.priority or '0'), i.date_end or today))],
        }

        review = self.review_ids.filtered(lambda r: period and r.period_id == period)[:1]
        payload['review'] = {
            'id': review.id,
            'name': review.name,
            'state': review.state,
            'decided': bool(review.decisions),
        } if review else False

        links = self.link_ids
        payload['links'] = {
            'total': len(links),
            'validated': len(links.filtered('validated')),
        }
        return payload

    def action_print_board_pack(self, period_id=False):
        """The board pack for a chosen period, not only the current one."""
        self.ensure_one()
        report = self.env.ref('bsc_strategy.action_report_bsc_board')
        if period_id and period_id in self.period_ids.ids:
            report = report.with_context(bsc_period_id=period_id)
        return report.report_action(self)


class BscPeriodDashboard(models.Model):
    _inherit = 'bsc.period'

    def action_open_review(self):
        """Open this period's review, creating and preparing it if needed; it does not wait for the close."""
        self.ensure_one()
        Review = self.env['bsc.review']
        review = Review.search([('scorecard_id', '=', self.scorecard_id.id),
                                ('period_id', '=', self.id)], limit=1)
        if not review:
            review = Review.create({
                'scorecard_id': self.scorecard_id.id,
                'period_id': self.id,
            })
            review.action_prepare()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'bsc.review',
            'res_id': review.id,
            'views': [[False, 'form']],
            'target': 'current',
        }
