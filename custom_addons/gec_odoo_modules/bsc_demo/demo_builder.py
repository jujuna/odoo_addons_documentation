# -*- coding: utf-8 -*-
"""Builds one worked scorecard and runs it: every quarter before today's is filled in and closed.
The quarter containing today is live, half-collected; in January to March the demo runs the previous year (Q4 live)."""
import logging
from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from odoo import fields

_logger = logging.getLogger(__name__)

SCORECARD_NAME = "Growth and Delivery %s"

# Per-KPI figures by quarter: (target, actual, variance comment); target ``None`` keeps the rule's proposal.
FIGURES = {
    'revenue':      {1: (500000, 480000, ''), 2: (550000, 505000, ''),
                     3: (560000, 470000, "Two large renewals slipped after the "
                                         "delivery delays. Both are still expected."),
                     4: (580000, 450000, "Renewals still waiting on delivery dates.")},
    'recurring':    {1: (30, 28, ''), 2: (32, 33, ''), 3: (34, 33, ''), 4: (35, 34, '')},
    'margin':       {1: (38, 37, ''), 2: (38, 35.5, ''), 3: (39, 34, ''), 4: (39, 33.5, '')},
    'retention':    {1: (90, 88, ''), 2: (90, 84, ''), 3: (91, 79, ''), 4: (91, 78, '')},
    'churn':        {1: (5, 4, ''),
                     2: (5, 7, "Three accounts left citing late delivery. Same root "
                               "cause as P1."),
                     3: (4, 9, "Churn is now tracking delivery performance almost "
                               "exactly. This is the chain the map predicted."),
                     4: (4, 9, "No improvement until delivery recovers.")},
    'delivery_days': {1: (10, 11, ''),
                      2: (10, 13, "Two senior engineers left and were not replaced "
                                  "for two months."),
                      3: (9, 15, "Still deteriorating. The process redesign "
                                 "initiative is behind schedule."),
                      4: (9, 14, "First small improvement since the backfill hires.")},
    'on_time':      {1: (95, 92, ''), 2: (95, 84, ''), 3: (95, 76, ''), 4: (95, 79, '')},
    'rework':       {1: (4, 3.5, ''),
                     2: (4, 5.2, "Rework rose with the workload per engineer."),
                     3: (3.5, 6.0, "Root cause unchanged: too few reviewers."),
                     4: (3.5, 5.6, "Slightly better with the new reviewers.")},
    'satisfaction': {1: (8.0, 8.2, ''), 2: (8.0, 7.6, ''), 3: (8.0, 7.3, ''),
                     4: (8.0, 7.2, '')},
    'consultants':  {1: (10, 9, ''), 2: (10, 11, ''), 3: (11, 12, ''), 4: (12, 12, '')},
}

# In the live quarter these KPIs are not reported yet and their targets come from the target rule.
LIVE_UNREPORTED = ('recurring', 'satisfaction')
LIVE_RULE_TARGETS = ('revenue', 'consultants')

# Targets of the automated KPIs; the actual comes from the source.
AUTO_TARGETS = {'new_customers': {1: 10, 2: 12, 3: 14, 4: 16}}
# Live quarter only: the source that matches nothing.
LIVE_AUTO_TARGETS = {'escalations': 20}

# Demo partners per quarter; the live quarter is far out of line, to show the deviation guard
# (it compares only ended quarters, so the jump is held only if the quarter has already ended).
PARTNERS_PER_QUARTER = {1: 12, 2: 15, 3: 17, 4: 18}
LIVE_PARTNERS = 40


def build_demo(env, today=None):
    today = today or fields.Date.context_today(env['bsc.scorecard'])
    current_quarter = (today.month - 1) // 3 + 1
    if current_quarter == 1:
        year, live = today.year - 1, 4
    else:
        year, live = today.year, current_quarter
    name = SCORECARD_NAME % year
    if env['bsc.scorecard'].search_count([('name', '=', name)]):
        _logger.info("BSC demo already present, skipping.")
        return

    builder = _DemoBuilder(env, year, name, live, today)
    builder.run()
    _logger.info("BSC demo built: %s (live quarter Q%s)", name, live)


class _DemoBuilder:

    def __init__(self, env, year, name, live, today):
        self.env = env
        self.year = year
        self.name = name
        self.live = live
        self.today = today
        # The install runs as OdooBot; a person must own the strategy.
        self.user = env.ref('base.user_admin', raise_if_not_found=False) or env.user
        self.company = env.company
        self.objectives = {}
        self.kpis = {}
        self.periods = {}

    @property
    def closed_quarters(self):
        return list(range(1, self.live))

    def run(self):
        self._make_partners()
        self._make_sources()
        self._make_scorecard()
        self._make_objectives()
        self._make_links()
        self._make_kpis()
        self._make_initiatives()
        self._activate()
        for quarter in self.closed_quarters:
            self._run_quarter(quarter, close=True)
        self._run_quarter(self.live, close=False)
        self._write_reviews()

    def _quarter_start(self, quarter):
        return date(self.year, quarter * 3 - 2, 1)

    def _make_partners(self):
        """Partners backdated into each quarter, so the counts differ per period."""
        Partner = self.env['res.partner']
        for quarter in range(1, self.live + 1):
            count = LIVE_PARTNERS if quarter == self.live else PARTNERS_PER_QUARTER[quarter]
            created = Partner.create([{
                'name': "Demo customer %s-Q%s-%s" % (self.year, quarter, index + 1),
                'ref': 'BSC-DEMO',
                'is_company': True,
            } for index in range(count)])
            # Mid-quarter for closed quarters; the first day for the live one, never in the future.
            start = self._quarter_start(quarter)
            day = start if quarter == self.live else start + relativedelta(months=1, days=14)
            stamp = datetime(day.year, day.month, day.day, 0, 30, 0)
            # create_date is readonly in the ORM.
            self.env.cr.execute(
                "UPDATE res_partner SET create_date = %s WHERE id IN %s",
                (stamp, tuple(created.ids)))
        Partner.invalidate_model(['create_date'])

    def _make_sources(self):
        Source = self.env['bsc.kpi.source']
        # Sources pick model and fields from dropdowns; the technical names follow.
        partner_model = self.env['ir.model']._get('res.partner')
        Field = self.env['ir.model.fields']
        create_date = Field._get('res.partner', 'create_date')
        self.source_customers = Source.create({
            'name': "New customers (demo)",
            'description': "Counts demo partners created inside the period. Real "
                           "deployments would filter on customer_rank.",
            'model_id': partner_model.id,
            'domain': "[('ref', '=', 'BSC-DEMO')]",
            'aggregate': 'count',
            'date_field_id': create_date.id,
            'uom_hint': 'customers',
        })
        # Matches nothing on purpose: shows a silently broken filter leaving the cell empty.
        self.source_escalations = Source.create({
            'name': "Escalations logged (demo - matches nothing)",
            'description': "Points at a tag that does not exist, to demonstrate that "
                           "an empty result set is reported as no data and never as a "
                           "zero.",
            'model_id': partner_model.id,
            'domain': "[('ref', '=', 'BSC-NO-SUCH-TAG')]",
            'aggregate': 'sum',
            'value_field_id': Field._get('res.partner', 'color').id,
            'date_field_id': create_date.id,
            'uom_hint': 'escalations',
        })

    def _make_scorecard(self):
        self.scorecard = self.env['bsc.scorecard'].create({
            'name': self.name,
            'company_id': self.company.id,
            'date_from': date(self.year, 1, 1),
            'date_to': date(self.year, 12, 31),
            'frequency': 'quarterly',
            'responsible_id': self.user.id,
            'vision': "<p>To be the delivery partner our clients keep, not the one "
                      "they compare.</p>",
            'mission': "<p>We deliver the work on the date we promised, at a margin "
                       "that lets us keep the people who do it.</p>",
        })
        weights = {'financial': 40, 'customer': 30, 'process': 20, 'learning': 10}
        for code, weight in weights.items():
            self.env['bsc.scorecard.perspective'].create({
                'scorecard_id': self.scorecard.id,
                'perspective_id': self.env.ref(
                    'bsc_strategy.perspective_%s' % code).id,
                'weight': weight,
            })

    def _objective(self, key, code, perspective, name, weight, **extra):
        values = {
            'name': name,
            'code': code,
            'scorecard_id': self.scorecard.id,
            'perspective_id': self.env.ref(
                'bsc_strategy.perspective_%s' % perspective).id,
            'owner_id': self.user.id,
            'weight': weight,
        }
        values.update(extra)
        self.objectives[key] = self.env['bsc.objective'].create(values)

    def _make_objectives(self):
        self._objective('revenue', 'F1', 'financial',
                        "Grow revenue by 25%", 60,
                        description="Measured on invoiced revenue, not signed orders.")
        self._objective('margin', 'F2', 'financial',
                        "Protect the gross margin", 40)
        self._objective('retention', 'C1', 'customer',
                        "Keep the customers we have", 60,
                        description="Retention is cheaper than acquisition, and our "
                                    "churn is a symptom of delivery, not of price.")
        self._objective('acquisition', 'C2', 'customer',
                        "Win new customers", 40)
        self._objective('delivery', 'P1', 'process',
                        "Deliver on the promised date", 60)
        self._objective('quality', 'P2', 'process',
                        "Cut rework", 40)
        self._objective('capability', 'L1', 'learning',
                        "Build senior delivery capability", 60)
        self._objective('engagement', 'L2', 'learning',
                        "Keep the team engaged and staying", 40,
                        assessment_mode='qualitative',
                        qualitative_status='amber',
                        qualitative_note="Two senior departures this year. The pulse "
                                         "survey has recovered but the team is "
                                         "still short-handed.")

    def _make_links(self):
        links = [
            ('capability', 'delivery', 'strong',
             "Senior engineers hit promised dates more often than junior ones. "
             "The late projects this year were all junior-led."),
            ('capability', 'quality', 'medium',
             "More experienced reviewers should mean less rework."),
            ('engagement', 'quality', 'medium',
             "An engaged team catches its own mistakes."),
            ('delivery', 'retention', 'strong',
             "Customers who receive late deliveries churn. Every churned account "
             "this year cited delivery dates."),
            ('quality', 'retention', 'medium',
             "Rework erodes trust even when the final date is met."),
            ('delivery', 'acquisition', 'weak',
             "References from happy clients bring new ones."),
            ('retention', 'revenue', 'strong',
             "Retained accounts renew at a higher value."),
            ('acquisition', 'revenue', 'strong',
             "New logos add revenue, with a lag that is not yet known."),
            ('retention', 'margin', 'medium',
             "Existing accounts cost less to serve."),
        ]
        for source, target, strength, hypothesis in links:
            self.env['bsc.objective.link'].create({
                'source_id': self.objectives[source].id,
                'target_id': self.objectives[target].id,
                'strength': strength,
                'hypothesis': hypothesis,
            })

    def _kpi(self, key, objective, name, **extra):
        values = {
            'name': name,
            'objective_id': self.objectives[objective].id,
            'owner_id': self.user.id,
        }
        values.update(extra)
        self.kpis[key] = self.env['bsc.kpi'].create(values)

    def _make_kpis(self):
        self._kpi('revenue', 'revenue', "Invoiced revenue", weight=70,
                  uom_name='GEL', direction='higher_better', baseline_value=450000,
                  # Target rule: next quarter is last quarter plus 10%.
                  target_rule='previous_growth', target_growth=10.0,
                  description="Posted customer invoices, net of tax, in the period.")
        self._kpi('recurring', 'revenue', "Recurring revenue share", weight=30,
                  uom_name='%', direction='higher_better')
        self._kpi('margin', 'margin', "Gross margin", uom_name='%',
                  direction='higher_better', baseline_value=36)
        self._kpi('retention', 'retention', "Customer retention rate", weight=50,
                  uom_name='%', direction='higher_better')
        self._kpi('churn', 'retention', "Accounts churned", weight=30,
                  uom_name='accounts', direction='lower_better',
                  description="Lower is better, and zero is a real result - which is "
                              "exactly the case a naive scorecard divides by.")
        self._kpi('new_customers', 'acquisition', "New customers", uom_name='customers',
                  direction='higher_better', data_source='odoo',
                  source_id=self.source_customers.id)
        self._kpi('delivery_days', 'delivery', "Average delivery time", weight=50,
                  uom_name='days', direction='lower_better', baseline_value=12)
        self._kpi('on_time', 'delivery', "On-time delivery", weight=50,
                  uom_name='%', direction='higher_better')
        self._kpi('rework', 'quality', "Rework rate", weight=70, uom_name='%',
                  direction='lower_better')
        self._kpi('escalations', 'quality', "Escalations logged", weight=30,
                  uom_name='escalations', direction='lower_better',
                  data_source='odoo', source_id=self.source_escalations.id)
        self._kpi('satisfaction', 'retention', "Satisfaction score",
                  uom_name='/10', direction='target_range',
                  target_min=7.5, target_max=9.0, weight=20,
                  description="Below 7.5 is a problem. Above 9 usually means the "
                              "sample is too small to believe.")
        self._kpi('consultants', 'capability', "Certified senior consultants",
                  uom_name='people', direction='higher_better', baseline_value=8,
                  target_rule='baseline_growth', target_growth=25.0)

    def _make_initiatives(self):
        Initiative = self.env['bsc.initiative']
        self.initiatives = {}

        def stage(xmlid):
            return self.env.ref('bsc_strategy.initiative_stage_%s' % xmlid)

        self.initiatives['redesign'] = Initiative.create({
            'name': "Redesign the delivery process",
            'scorecard_id': self.scorecard.id,
            'objective_ids': [(6, 0, [self.objectives['delivery'].id,
                                      self.objectives['quality'].id])],
            'owner_id': self.user.id,
            'priority': '3',
            'date_start': date(self.year, 4, 1),
            'date_end': date(self.year, 11, 30),
            'budget_planned': 60000,
            'budget_actual': 27500,
            'progress': 45,
            'expected_impact': "Average delivery time back under 10 days by Q4, and "
                               "on-time delivery above 90%.",
            'impact_kpi_ids': [(6, 0, [self.kpis['delivery_days'].id,
                                       self.kpis['on_time'].id])],
        })
        self.initiatives['redesign'].stage_id = stage('approved')
        self.initiatives['redesign'].stage_id = stage('in_progress')

        self.initiatives['certification'] = Initiative.create({
            'name': "Senior consultant certification programme",
            'scorecard_id': self.scorecard.id,
            'objective_ids': [(6, 0, [self.objectives['capability'].id])],
            'owner_id': self.user.id,
            'priority': '2',
            'date_start': date(self.year, 2, 1),
            'date_end': date(self.year, 12, 31),
            'budget_planned': 25000,
            'budget_actual': 18000,
            'progress': 70,
            'expected_impact': "Four more certified consultants by year end.",
        })
        self.initiatives['certification'].stage_id = stage('approved')
        self.initiatives['certification'].stage_id = stage('in_progress')

        self.initiatives['key_accounts'] = Initiative.create({
            'name': "Key account programme",
            'scorecard_id': self.scorecard.id,
            'objective_ids': [(6, 0, [self.objectives['retention'].id])],
            'owner_id': self.user.id,
            'priority': '1',
            'expected_impact': "A named owner for each of the top 20 accounts.",
        })

        self.initiatives['crm'] = Initiative.create({
            'name': "CRM data cleanup",
            'scorecard_id': self.scorecard.id,
            'objective_ids': [(6, 0, [self.objectives['acquisition'].id])],
            'owner_id': self.user.id,
            'date_start': date(self.year, 1, 15),
            'date_end': date(self.year, 3, 31),
            'budget_planned': 8000,
            'budget_actual': 7200,
            'expected_impact': "Trustworthy new-customer counts.",
            'result_summary': "Done. Duplicate accounts merged and the new-customer "
                              "figure is now taken straight from the database.",
        })
        self.initiatives['crm'].stage_id = stage('approved')
        self.initiatives['crm'].stage_id = stage('done')

    def _activate(self):
        self.scorecard.action_activate()
        for period in self.scorecard.period_ids:
            quarter = (period.date_from.month - 1) // 3 + 1
            self.periods[quarter] = period
        # Drop the live quarter's rows so they are recreated after the earlier quarters hold history.
        # Uses the builder's live quarter, not ``current_period_id`` (the latest ended open period).
        self.periods[self.live].measurement_ids.unlink()

    def _run_quarter(self, quarter, close):
        period = self.periods[quarter]
        period.action_prepare_measurements()
        self._fill(period, quarter)
        self._refresh_automated(period, quarter)
        if close:
            period.action_close(force=True)

    def _fill(self, period, quarter):
        live = quarter == self.live
        for key, by_quarter in FIGURES.items():
            target, actual, comment = by_quarter[quarter]
            if live and key in LIVE_UNREPORTED:
                actual, comment = None, ''
            if live and key in LIVE_RULE_TARGETS:
                target = None
            measurement = period.measurement_ids.filtered(
                lambda m, k=key: m.kpi_id == self.kpis[k])
            if not measurement:
                continue
            values = {}
            if target is not None:
                values['target_value'] = target
            if actual is not None:
                values['actual_value'] = actual
            if comment:
                values['comment'] = comment
            if values:
                measurement.write(values)
                if actual is not None and not live:
                    measurement.action_submit()
                    measurement.action_validate()

    def _refresh_automated(self, period, quarter):
        targets = {key: by_quarter[quarter]
                   for key, by_quarter in AUTO_TARGETS.items()}
        if quarter == self.live:
            targets.update(LIVE_AUTO_TARGETS)
        for key, target in targets.items():
            measurement = period.measurement_ids.filtered(
                lambda m, k=key: m.kpi_id == self.kpis[k])
            if not measurement:
                continue
            measurement.target_value = target
            measurement._refresh_automated()

    def _write_reviews(self):
        """Write minutes into the review each closed quarter opened."""
        Review = self.env['bsc.review']
        closed = self.closed_quarters
        for quarter in closed:
            review = Review.search([('period_id', '=', self.periods[quarter].id)], limit=1)
            if not review:
                continue
            if quarter == closed[0]:
                values = {
                    'findings': "<p>A good quarter on the numbers. Delivery time missed "
                                "its target by a day, which nobody treated as material "
                                "at the time.</p>",
                    'decisions': "<p>No change to the strategy. Watch delivery time "
                                 "next quarter - if it moves again we act on it rather "
                                 "than explaining it.</p>",
                }
            elif quarter == closed[-1]:
                values = {
                    'findings': "<p>The chain the strategy map predicted is now visible "
                                "in the data: delivery slipped, rework rose, accounts "
                                "churned citing delivery, and revenue missed.</p>",
                    'decisions': "<p>Fund the delivery process redesign immediately "
                                 "and start the corrective hiring initiative. Revenue "
                                 "targets are unchanged - the problem is not in the "
                                 "financial perspective and cannot be fixed there.</p>",
                    'strategy_adjustment': "No objective changed. The link from "
                                           "delivery to retention is now the one the "
                                           "strategy leans on hardest.",
                }
            else:
                values = {
                    'findings': "<p>Delivery time slipped again and churn rose with "
                                "it.</p>",
                    'decisions': "<p>Approve the delivery process redesign.</p>",
                }
            values['participant_ids'] = [(6, 0, [self.user.id])]
            review.write(values)
            review.action_done()
            if quarter == closed[-1] and len(closed) > 1:
                self._make_corrective(review)

        redesign = self.initiatives['redesign']
        try:
            redesign.action_create_project()
        except Exception as error:  # noqa: BLE001 - the demo must still install
            _logger.info("BSC demo: skipped project creation (%s)", error)

    def _make_corrective(self, review):
        corrective = self.env['bsc.initiative'].create({
            'name': "Backfill two senior delivery engineers",
            'scorecard_id': self.scorecard.id,
            'review_id': review.id,
            'objective_ids': [(6, 0, [self.objectives['delivery'].id,
                                      self.objectives['capability'].id])],
            'owner_id': self.user.id,
            'priority': '3',
            'date_start': date(self.year, 7, 1),
            'date_end': date(self.year, 10, 31),
            'budget_planned': 45000,
            'budget_actual': 12000,
            'progress': 30,
            'expected_impact': "Two senior hires, restoring delivery capacity to the "
                               "level of the first quarter.",
        })
        corrective.stage_id = self.env.ref('bsc_strategy.initiative_stage_approved')
        corrective.stage_id = self.env.ref('bsc_strategy.initiative_stage_in_progress')
        self.initiatives['backfill'] = corrective
