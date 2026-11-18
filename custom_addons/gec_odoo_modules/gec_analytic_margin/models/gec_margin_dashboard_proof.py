from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.tools.misc import format_amount


class GecMarginDashboardProof(models.AbstractModel):
    """The proof behind a dashboard figure: formula, numbers, their rows and the benchmark that set the colour.

    Built from the same payload the dashboard drew, so the two cannot disagree."""
    _inherit = 'gec.margin.dashboard'

    @api.model
    def get_proof(self, key, date_from, date_to, plan_id=False):
        builder = getattr(self, f'_gec_proof_{key}', None)
        if not builder:
            return {}
        self = self._gec_reporting_env()
        data = self.get_dashboard_data(date_from, date_to, plan_id)
        ctx = self._gec_proof_context(data, date_from, date_to, plan_id)
        try:
            return builder(ctx)
        except (KeyError, TypeError, ZeroDivisionError, StopIteration):
            return self._proof(_("No figure for this period"), "—",
                               _("There is not enough data in the selected period to calculate this figure."), "—")

    def _gec_proof_context(self, data, date_from, date_to, plan_id):
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        plan = self._gec_plan(self._gec_plans(), plan_id)
        end = min(date_to, fields.Date.context_today(self))
        company = [('company_id', 'in', self.env.companies.ids)]
        return {
            'data': data,
            'p': data['profitability'],
            'plan': plan,
            'date_from': date_from,
            'date_to': date_to,
            'end': end,
            'scoped': self._gec_base_domain(plan, date_from, date_to),
            'company': [('line_type', '=', 'actual'), ('is_primary_plan', '=', True),
                        ('date', '>=', date_from), ('date', '<=', end), *company],
            'currency': self.env['res.currency'].browse(data['currency_id']),
            'scope_note': _("Company-wide: every amount once, whichever plan it is on.") if not plan
            else _("Amounts tagged on the analytic plan %s.", plan.name),
        }

    def _money(self, ctx, amount):
        return format_amount(self.env, amount or 0.0, ctx['currency'])

    @staticmethod
    def _pct(value):
        # `is`, not `in`: 0.0 == False, and a real 0% must print as 0.0%.
        return "—" if value is False or value is None else f"{value * 100:.1f}%"

    def _rows(self, name, domain, model='gec.margin.report', groupby=None, measures=None, views=None):
        """An action opening exactly the rows a number was summed from."""
        context = {k: v for k, v in self.env.context.items()
                   if k in ('gec_reporting_currency_id', 'gec_reporting_company_id')}
        if model == 'gec.margin.report':
            context.update({'pivot_measures': measures or ['revenue_amount', 'expense_amount', 'amount'],
                            'pivot_row_groupby': groupby or ['component_id']})
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'views': [(False, v) for v in (views or (('pivot', 'list') if model == 'gec.margin.report' else ('list', 'form')))],
            'domain': domain,
            'context': context,
        }

    def _expr(self, ctx, amounts):
        """A sum as it is read aloud: 1,284,066 − 337,022 − 427,773."""
        terms = []
        for i, amount in enumerate(amounts):
            money = self._money(ctx, abs(amount))
            terms.append(money if i == 0 and amount >= 0 else
                         (f"− {money}" if amount < 0 else f"+ {money}"))
        return " ".join(terms) or "0"

    def _part(self, ctx, label, amount, domain=None, model='gec.margin.report', count=True, money=True, **rows):
        part = {'label': label, 'value': self._money(ctx, amount) if money else amount, 'raw': amount}
        if domain is not None:
            part['action'] = self._rows(label, domain, model=model, **rows)
            if count:
                part['count'] = self.env[model].search_count(domain)
        return part

    def _proof(self, title, value, formula, computation, parts=(), benchmark=None, notes=()):
        return {
            'title': title, 'value': value, 'formula': formula, 'computation': computation,
            'parts': list(parts), 'benchmark': benchmark, 'notes': [n for n in notes if n],
        }

    def _kpi(self, ctx, key):
        return next((k for k in ctx['p']['kpis'] if k['key'] == key), None)

    def _ladder(self, ctx, code):
        return next((r for r in ctx['p']['ladder'] if r.get('code') == code), None)

    def _components(self, ctx, components):
        """Each component's amount in the selected scope, with its rows."""
        amounts = dict(self.env['gec.margin.report']._read_group(
            ctx['scoped'] + [('component_id', 'in', components.ids)], ['component_id'], ['amount:sum']))
        return [
            self._part(ctx, c.name, amounts.get(c, 0.0),
                       ctx['scoped'] + [('component_id', '=', c.id)], groupby=['general_account_id'])
            for c in components.sorted('sequence') if amounts.get(c)
        ]

    def _gec_proof_revenue(self, ctx):
        kpi = self._kpi(ctx, 'revenue')
        revenue_components = self.env['gec.margin.component'].search([('nature', '=', 'revenue')])
        parts = self._components(ctx, revenue_components)
        computation = self._expr(ctx, [p['raw'] for p in parts]) + f" = {self._money(ctx, kpi['value'])}"
        budget = ctx['p'].get('budget') or {}
        if budget.get('revenue_budget'):
            parts.append(self._part(ctx, _("Budget to date (prorated by day)"), budget['revenue_budget'],
                                    self._gec_proof_budget_domain(ctx), model='budget.line'))
        return self._proof(
            _("Revenue"), self._money(ctx, kpi['value']),
            _("Revenue = the sum of every revenue amount in the period."),
            computation,
            parts,
            _("Against budget: red below 90% of the budget to date, green at 100% or more."),
            [ctx['scope_note'],
             _("Previous period %(prev)s, a change of %(change)s.", prev=self._money(ctx, kpi['previous']),
               change=self._pct((kpi['value'] - kpi['previous']) / abs(kpi['previous'])) if kpi['previous'] else "—")],
        )

    def _gec_proof_level(self, ctx, code, title, benchmark):
        row = self._ladder(ctx, code)
        revenue = self._kpi(ctx, 'revenue')['value']
        level = self.env['gec.margin.level'].search([('code', '=', code)], limit=1)
        parts = self._components(ctx, level.component_ids)
        return self._proof(
            title, self._pct(row['pct']),
            _("%(level)s %% = %(level)s ÷ Revenue, where %(level)s = %(parts)s.",
              level=level.name, parts=" + ".join(level.component_ids.sorted('sequence').mapped('name'))),
            f"({self._expr(ctx, [p['raw'] for p in parts])}) ÷ {self._money(ctx, revenue)} = {self._pct(row['pct'])}",
            parts, benchmark,
            [ctx['scope_note'], _("Costs are negative, so each margin is a plain sum.")],
        )

    def _gec_proof_gross(self, ctx):
        return self._gec_proof_level(ctx, 'gross', _("Gross margin"),
                                     _("Benchmark: base 60–70%, strong 72–80%."))

    def _gec_proof_ebitda(self, ctx):
        return self._gec_proof_level(ctx, 'ebitda', _("EBITDA margin"),
                                     _("Benchmark: base 10–20%, strong 25–40%."))

    def _gec_proof_recurring(self, ctx):
        kpi = self._kpi(ctx, 'recurring')
        revenue = self._kpi(ctx, 'revenue')['value']
        streams = self.env['gec.revenue.stream'].search([('recurring', '=', True)])
        parts = [
            self._part(ctx, s['name'], s['amount'],
                       ctx['scoped'] + [('direction', '=', 'revenue'), ('revenue_stream_id', '=', s['id'])],
                       groupby=['partner_id'], measures=['revenue_amount'])
            for s in (ctx['p']['mix'] or {}).get('streams', []) if s['recurring']
        ]
        return self._proof(
            _("Recurring revenue"), self._pct(kpi['pct']),
            _("Recurring % = revenue on streams marked recurring ÷ all revenue."),
            f"{self._money(ctx, kpi['value'])} ÷ {self._money(ctx, revenue)} = {self._pct(kpi['pct'])}",
            parts, _("Benchmark: base 30–50%, strong 55–70%."),
            [ctx['scope_note'], _("Recurring streams: %s.", ", ".join(streams.mapped('name')) or "—")],
        )

    def _gec_proof_retention_parts(self, ctx, r):
        recurring = self.env['gec.revenue.stream'].search([('recurring', '=', True)])
        base = [('line_type', '=', 'actual'), ('direction', '=', 'revenue'), ('is_primary_plan', '=', True),
                ('company_id', 'in', self.env.companies.ids), ('partner_id', '!=', False)]
        if r['basis'] == 'recurring':
            base.append(('revenue_stream_id', 'in', recurring.ids))
        last = base + [('date', '>=', r['prev_from']), ('date', '<=', r['prev_to'])]
        this = base + [('date', '>=', ctx['date_from']), ('date', '<=', ctx['end'])]
        return [
            self._part(ctx, _("Last year, same customers"), r['start'], last, groupby=['partner_id'], measures=['revenue_amount']),
            self._part(ctx, _("+ Expansion"), r['expansion']),
            self._part(ctx, _("− Contraction"), -r['contraction']),
            self._part(ctx, _("− Churn (%s customers lost)", r['lost']), -r['churn']),
            self._part(ctx, _("= Retained this year"), r['retained'], this, groupby=['partner_id'], measures=['revenue_amount']),
            self._part(ctx, _("New customers (outside NRR, %s won)", r['won']), r['new']),
        ]

    def _gec_proof_nrr(self, ctx):
        r = ctx['p']['retention']
        return self._proof(
            _("Net revenue retention"), self._pct(r['nrr']),
            _("NRR = what last year's customers pay now ÷ what they paid a year earlier (same dates)."),
            f"{self._money(ctx, r['retained'])} ÷ {self._money(ctx, r['start'])} = {self._pct(r['nrr'])}",
            self._gec_proof_retention_parts(ctx, r),
            _("Benchmark: base 95–105%, strong 105–115% or more."),
            [_("Basis: %s, company-wide, invoiced revenue per customer company.",
               _("recurring streams") if r['basis'] == 'recurring' else _("all revenue")),
             _("Compared with %(a)s – %(b)s.", a=r['prev_from'], b=r['prev_to'])],
        )

    def _gec_proof_grr(self, ctx):
        r = ctx['p']['retention']
        kept = r['start'] - r['contraction'] - r['churn']
        return self._proof(
            _("Gross revenue retention"), self._pct(r['grr']),
            _("GRR = last year's revenue, less contraction and churn, ÷ last year's revenue. Growth is left out."),
            f"({self._money(ctx, r['start'])} − {self._money(ctx, r['contraction'])} − {self._money(ctx, r['churn'])}) "
            f"÷ {self._money(ctx, r['start'])} = {self._pct(kept / r['start'] if r['start'] else 0)}",
            self._gec_proof_retention_parts(ctx, r),
            _("Benchmark: base 85–95%, strong 95% or more."),
        )

    def _gec_proof_churn(self, ctx):
        r = ctx['p']['retention']
        return self._proof(
            _("Customers lost and won"), f"{r['lost']} / {r['won']}",
            _("Lost: paid last year, pay nothing now. Won: pay now, paid nothing last year."),
            _("%(lost)s lost of %(base)s customers; %(won)s new.", lost=r['lost'], base=r['customers'], won=r['won']),
            self._gec_proof_retention_parts(ctx, r),
        )

    def _gec_proof_revenue_fte(self, ctx):
        prod = ctx['p']['productivity']
        days = (ctx['end'] - ctx['date_from']).days + 1
        [(revenue,)] = self.env['gec.margin.report']._read_group(ctx['company'], [], ['revenue_amount:sum'])
        return self._proof(
            _("Revenue per FTE"), self._money(ctx, prod['revenue_per_fte']),
            _("Revenue per FTE = company revenue × (365 ÷ days in the period) ÷ average FTE."),
            f"{self._money(ctx, revenue)} × 365 ÷ {days} ÷ {prod['fte']:.2f} = {self._money(ctx, prod['revenue_per_fte'])}",
            [self._part(ctx, _("Company revenue"), revenue, ctx['company'] + [('direction', '=', 'revenue')],
                        groupby=['partner_id'], measures=['revenue_amount']),
             self._gec_proof_employees_part(ctx, prod)],
            _("Benchmark: base 225k, strong 400–500k per employee (USD)."),
            [_("Annualised, and the period stops at today, so a year to date is not divided by twelve months of staff.")],
        )

    def _gec_proof_employees_part(self, ctx, prod):
        return {
            'label': _("Average FTE (%s)", " · ".join(f"{t['label']} {t['fte']:.1f}" for t in prod['by_type'])),
            'value': f"{prod['fte']:.2f}",
            'action': self._rows(_("Employees"), [('company_id', 'in', self.env.companies.ids)], model='hr.employee',
                                 views=('list', 'form')) | {'context': {'active_test': False}},
        }

    def _gec_proof_backlog(self, ctx):
        fc = ctx['p']['forecast']
        projects = self.env['project.project'].browse([row['id'] for row in fc['projects']])
        parts = [
            self._part(ctx, f"{p.display_name}: {self._money(ctx, p.gec_contract_value_effective)} − "
                            f"{self._money(ctx, p.gec_actual_revenue)}", p.gec_backlog)
            | {'action': self._rows(p.display_name, [('id', '=', p.id)], model='project.project', views=('form',))}
            for p in projects if p.gec_backlog
        ]
        return self._proof(
            _("Backlog"), self._money(ctx, fc['backlog']),
            _("Backlog = for each project, contract value − revenue invoiced so far; summed."),
            self._expr(ctx, [p['raw'] for p in parts]) + f" = {self._money(ctx, fc['backlog'])}", parts,
            notes=[_("Contract value is the project's field, or its revenue budget when the field is empty."),
                   _("Project to date, not limited to the selected period.")],
        )

    def _gec_proof_projects(self, ctx):
        fc = ctx['p']['forecast']
        projects = self.env['project.project'].browse([row['id'] for row in fc['projects']])
        labels = dict(projects._fields['gec_forecast_status']._description_selection(self.env))
        parts = [
            {'label': f"{p.display_name} — {labels.get(p.gec_forecast_status)}",
             'value': f"{self._pct(p.gec_forecast_margin_pct)} (budget {self._pct(p.gec_budget_margin_pct)})",
             'action': self._rows(p.display_name, [('id', '=', p.id)], model='project.project', views=('form',))}
            for p in projects
        ]
        return self._proof(
            _("Projects at risk"), f"{fc['counts']['loss'] + fc['counts']['eroding']} / {sum(fc['counts'].values())}",
            _("Forecast margin = contract − cost to date − (remaining hours × hourly cost + remaining other cost)."),
            _("Loss: forecast margin below zero. Eroding: more than 5 points below the budgeted margin."),
            parts,
        )

    def _gec_proof_outlook(self, ctx):
        o = ctx['p']['outlook']
        parts = [
            {'label': q['label'], 'value': f"{_('budget')} {self._money(ctx, q['budget_revenue'])} · "
                                           f"{_('run rate')} {self._money(ctx, q['run_rate_revenue'])}"}
            for q in o['quarters']
        ]
        parts.append(self._part(ctx, _("Backlog (contracted, not invoiced)"), o['backlog']))
        return self._proof(
            _("Next four quarters"), self._money(ctx, o['plan_total']),
            _("Plan per quarter = its budget (lines prorated by day), or the run rate where no budget reaches it. "
              "Run rate = the average of the last three full months (%(a)s – %(b)s). Coverage = backlog ÷ plan.",
              a=o['run_rate_from'], b=o['run_rate_to']),
            _("Backlog %(backlog)s ÷ plan %(plan)s = %(cov)s covered; %(n)s of 4 quarters budgeted.",
              backlog=self._money(ctx, o['backlog']), plan=self._money(ctx, o['plan_total']),
              cov=self._pct(o['coverage']), n=o['budgeted_quarters']),
            parts, notes=[_("Company-wide, looking forward from today, whatever period is selected.")],
        )

    def _gec_proof_budget_domain(self, ctx):
        domain = [('date_from', '<=', ctx['end']), ('date_to', '>=', ctx['date_from']),
                  ('budget_analytic_id.state', '!=', 'canceled')]
        if ctx['plan']:
            domain.append((ctx['plan']._column_name(), '!=', False))
        return domain

    def _gec_proof_budget(self, ctx, which):
        b = ctx['p']['budget']
        actual, planned = b[which], b[f'{which}_budget']
        label = _("Revenue") if which == 'revenue' else _("Net")
        domain = ctx['scoped'] + ([('direction', '=', 'revenue')] if which == 'revenue' else [])
        return self._proof(
            _("%s vs budget", label), self._pct(actual / planned) if planned > 0 else self._money(ctx, actual - planned),
            _("Achievement = actual ÷ budget, the budget prorated by day to the same dates, through today."),
            f"{self._money(ctx, actual)} ÷ {self._money(ctx, planned)}"
            + (f" = {self._pct(actual / planned)}" if planned > 0 else ""),
            [self._part(ctx, _("Actual %s", label.lower()), actual, domain,
                        groupby=['analytic_account_id']),
             self._part(ctx, _("Budget lines overlapping the period"), planned, self._gec_proof_budget_domain(ctx),
                        model='budget.line')],
            notes=[_("A line dated for the whole year counts only for the days it shares with the period."),
                   _("Through %s.", b['through'])],
        )

    def _gec_proof_budget_revenue(self, ctx):
        return self._gec_proof_budget(ctx, 'revenue')

    def _gec_proof_budget_net(self, ctx):
        return self._gec_proof_budget(ctx, 'net')

    def _gec_proof_standard(self, ctx):
        mix = ctx['p']['mix']
        revenue = self._kpi(ctx, 'revenue')['value']
        parts = [
            self._part(ctx, s['name'], s['amount'],
                       ctx['scoped'] + [('direction', '=', 'revenue'), ('revenue_stream_id', '=', s['id'])],
                       groupby=['partner_id'], measures=['revenue_amount'])
            for s in mix['streams'] if s['standard']
        ]
        return self._proof(
            _("Product revenue"), self._pct(mix['standard_pct']),
            _("Product revenue % = revenue on streams marked Standard Product ÷ all revenue."),
            f"{self._money(ctx, mix['standard'])} ÷ {self._money(ctx, revenue)} = {self._pct(mix['standard_pct'])}",
            parts, _("Benchmark: base 50–70%, strong 75–90%."), [ctx['scope_note']],
        )

    def _gec_proof_concentration(self, ctx, top_n):
        conc = ctx['p']['concentration']
        customers = conc['customers'][:conc['top_n'] if top_n else 1]
        share = conc['top_n_pct'] if top_n else conc['top_pct']
        parts = [
            self._part(ctx, c['name'], c['amount'],
                       ctx['company'] + [('direction', '=', 'revenue'), ('partner_id', 'child_of', c['id'])],
                       groupby=['analytic_account_id'], measures=['revenue_amount'])
            for c in customers
        ]
        amount = sum(c['amount'] for c in customers)
        return self._proof(
            _("Top %s customers", conc['top_n']) if top_n else _("Largest customer"), self._pct(share),
            _("Share = their revenue ÷ company revenue. Contacts count as their company."),
            f"{self._money(ctx, amount)} ÷ {self._money(ctx, conc['total'])} = {self._pct(share)}", parts,
            _("Benchmark: top 10 below 40–50%.") if top_n else _("Benchmark: largest customer below 15–20%."),
            [_("Company-wide, whichever plan the revenue is on.")],
        )

    def _gec_proof_top(self, ctx):
        return self._gec_proof_concentration(ctx, False)

    def _gec_proof_top_n(self, ctx):
        return self._gec_proof_concentration(ctx, True)

    def _gec_proof_fte(self, ctx):
        prod = ctx['p']['productivity']
        return self._proof(
            _("Average FTE"), f"{prod['fte']:.2f}",
            _("FTE = for each employee, days employed in the period ÷ days in the period × their schedule's work rate; summed."),
            _("A half-time schedule counts 0.5; a starter on the 17th of a 31-day month counts 15/31."),
            [self._gec_proof_employees_part(ctx, prod)],
            notes=[_("Contractors count when recorded as employees; employees who left count for the time they were there.")],
        )

    def _gec_proof_growth(self, ctx):
        prod = ctx['p']['productivity']
        return self._proof(
            _("Revenue vs FTE growth"), self._pct(prod['revenue_growth']),
            _("Growth = this period ÷ the previous period − 1, both annualised; revenue and FTE side by side."),
            _("Revenue %(rev)s, FTE %(fte)s: %(verdict)s.", rev=self._pct(prod['revenue_growth']),
              fte=self._pct(prod['fte_growth']),
              verdict=_("revenue grows faster (leverage)") if prod['revenue_growth'] > prod['fte_growth']
              else _("headcount grows faster (dilution)")),
            [self._gec_proof_employees_part(ctx, prod)],
            _("Benchmark: revenue 20–30% a year, headcount 5–12%."),
        )

    def _gec_proof_hours_parts(self, ctx, hours):
        timesheets = [('project_id', '!=', False), ('employee_id', '!=', False), ('date', '>=', ctx['date_from']),
                      ('date', '<=', ctx['end']), ('company_id', 'in', self.env.companies.ids)]
        parts = [{'label': b['label'], 'value': f"{b['hours']:,.0f} h"} for b in hours['buckets']]
        parts.append({'label': _("Hours the working schedules offered"), 'value': f"{hours['available']:,.0f} h",
                      'action': self._rows(_("Employees"), [('company_id', 'in', self.env.companies.ids)],
                                           model='hr.employee', views=('list', 'form'))})
        parts.append({'label': _("All timesheets in the period"), 'value': f"{hours['logged']:,.0f} h",
                      'count': self.env['account.analytic.line'].search_count(timesheets),
                      'action': self._rows(_("Timesheets"), timesheets, model='account.analytic.line',
                                           views=('list', 'pivot'))})
        return parts

    def _gec_proof_hours(self, ctx, key, title, formula, computation, benchmark, note=None):
        hours = ctx['p']['productivity']['hours']
        return self._proof(title, self._pct(hours[key]), formula, computation,
                           self._gec_proof_hours_parts(ctx, hours), benchmark, [note])

    def _gec_proof_utilization(self, ctx):
        h = ctx['p']['productivity']['hours']
        customer = next((b['hours'] for b in h['buckets'] if b['label'] == _("Customer projects")), 0.0)
        return self._gec_proof_hours(
            ctx, 'utilization', _("Utilization"),
            _("Utilization = hours on customer projects ÷ hours the schedules offered (public holidays off)."),
            f"{customer:,.0f} h ÷ {h['available']:,.0f} h = {self._pct(h['utilization'])}",
            _("Benchmark: base 60–75%, strong 75–85%."),
            _("R&D and internal hours count as product or overhead work, not utilization."))

    def _gec_proof_coverage(self, ctx):
        h = ctx['p']['productivity']['hours']
        return self._gec_proof_hours(
            ctx, 'coverage', _("Timesheet coverage"), _("Coverage = hours logged ÷ hours the schedules offered."),
            f"{h['logged']:,.0f} h ÷ {h['available']:,.0f} h = {self._pct(h['coverage'])}",
            _("Below 90%, every hour-based figure undercounts."))

    def _gec_proof_product_share(self, ctx):
        h = ctx['p']['productivity']['hours']
        return self._gec_proof_hours(
            ctx, 'product_share', _("Product share of hours"),
            _("Product share = hours on R&D (function) projects ÷ hours on all projects."),
            _("See the split of hours below."), None,
            _("A project counts as product work when its P&L Function is R&D."))

    def _gec_proof_delivery(self, ctx):
        return self._gec_proof_hours(
            ctx, 'delivery_utilization', _("Delivery utilization"),
            _("Delivery utilization = customer-project hours of Cost of Sales staff ÷ the hours their schedules offered."),
            _("Staff are Cost of Sales when their department's P&L Function is Cost of Sales."),
            _("Benchmark: base 60–75%, strong 75–85%."))

    def _gec_proof_bespoke(self, ctx):
        h = ctx['p']['productivity']['hours']
        return self._gec_proof_hours(
            ctx, 'bespoke_share', _("Bespoke engineering"),
            _("Bespoke share = engineers' hours on customer projects ÷ engineers' hours on all projects."),
            _("Engineers are staff whose department's P&L Function is R&D; %s project hours counted.",
              f"{h['engineering_hours']:,.0f}"),
            _("Benchmark: strong below 20–25% of engineering effort."))

    def _gec_proof_rework(self, ctx):
        h = ctx['p']['productivity']['hours']
        customer = next((b['hours'] for b in h['buckets'] if b['label'] == _("Customer projects")), 0.0)
        rework = [('project_id', '!=', False), ('employee_id', '!=', False), ('date', '>=', ctx['date_from']),
                  ('date', '<=', ctx['end']), ('company_id', 'in', self.env.companies.ids),
                  ('task_id.tag_ids.gec_rework', '=', True)]
        return self._proof(
            _("Rework"), self._pct(h['rework_share']),
            _("Rework = hours on customer-project tasks tagged as rework ÷ all customer-project hours."),
            f"{h['rework_hours']:,.0f} h ÷ {customer:,.0f} h = {self._pct(h['rework_share'])}",
            [{'label': _("Rework timesheets"), 'value': f"{h['rework_hours']:,.0f} h",
              'count': self.env['account.analytic.line'].search_count(rework),
              'action': self._rows(_("Rework timesheets"), rework, model='account.analytic.line', views=('list', 'pivot'))},
             {'label': _("Tags counted as rework"),
              'value': ", ".join(self.env['project.tags'].search([('gec_rework', '=', True)]).mapped('name')),
              'action': self._rows(_("Task tags"), [('gec_rework', '=', True)], model='project.tags', views=('list',))}],
            _("Benchmark: strong below 5–10% of delivery hours."),
            [_("Mark a tag as Counts as Rework in Project ▸ Configuration ▸ Tags.")],
        )

    def _gec_proof_rnd_customer(self, ctx):
        prod = ctx['p']['productivity']
        rnd = self.env.ref('gec_analytic_margin.component_function_rnd')
        days = (ctx['end'] - ctx['date_from']).days + 1
        [(cost,)] = self.env['gec.margin.report']._read_group(
            ctx['company'] + [('component_id', '=', rnd.id)], [], ['amount:sum'])
        return self._proof(
            _("R&D per active customer"), self._money(ctx, prod['rnd_per_customer']),
            _("R&D per customer = R&D cost × (365 ÷ days) ÷ customers with revenue in the period."),
            f"{self._money(ctx, -(cost or 0))} × 365 ÷ {days} ÷ {prod['active_customers']} = "
            f"{self._money(ctx, prod['rnd_per_customer'])}",
            [self._part(ctx, _("R&D cost"), -(cost or 0.0), ctx['company'] + [('component_id', '=', rnd.id)],
                        groupby=['analytic_account_id'])],
            notes=[_("Company-wide, P&L by function.")],
        )

    def _gec_proof_per_fte(self, ctx, key, title, measure_note):
        prod = ctx['p']['productivity']
        value = prod[key]
        return self._proof(
            title, self._money(ctx, value),
            _("%s × (365 ÷ days in the period) ÷ average FTE.", measure_note),
            _("%(value)s per FTE, on %(fte)s FTE.", value=self._money(ctx, value), fte=f"{prod['fte']:.2f}"),
            [self._gec_proof_employees_part(ctx, prod)],
        )

    def _gec_proof_gross_fte(self, ctx):
        return self._gec_proof_per_fte(ctx, 'gross_per_fte', _("Gross profit per FTE"), _("Company gross margin"))

    def _gec_proof_recurring_fte(self, ctx):
        return self._gec_proof_per_fte(ctx, 'recurring_per_fte', _("Recurring revenue per FTE"),
                                       _("Company recurring revenue"))

    def _gec_proof_projects_sum(self, ctx, title, field, formula, keep=lambda v: v):
        fc = ctx['p']['forecast']
        projects = self.env['project.project'].browse([row['id'] for row in fc['projects']])
        parts = [
            self._part(ctx, p.display_name, keep(p[field]))
            | {'action': self._rows(p.display_name, [('id', '=', p.id)], model='project.project', views=('form',))}
            for p in projects if keep(p[field])
        ]
        total = sum(p['raw'] for p in parts)
        return self._proof(title, self._money(ctx, total), formula,
                           self._expr(ctx, [p['raw'] for p in parts]) + f" = {self._money(ctx, total)}" if parts else "—",
                           parts, notes=[_("Project to date.")])

    def _gec_proof_unbilled(self, ctx):
        return self._gec_proof_projects_sum(
            ctx, _("Unbilled work"), 'gec_unbilled',
            _("Unbilled = contract × percent complete − revenue invoiced; percent complete = cost to date ÷ forecast cost."),
            keep=lambda v: max(v, 0.0))

    def _gec_proof_ahead(self, ctx):
        return self._gec_proof_projects_sum(
            ctx, _("Billed ahead"), 'gec_unbilled',
            _("Billed ahead = revenue invoiced beyond the work done (the negative side of unbilled)."),
            keep=lambda v: -min(v, 0.0))

    def _gec_proof_cash(self, ctx):
        fc = ctx['p']['forecast']
        projects = self.env['project.project'].browse([row['id'] for row in fc['projects']])
        parts = [
            {'label': p.display_name,
             'value': f"{self._money(ctx, p.gec_collected)} − {self._money(ctx, p.gec_actual_cost)} = "
                      f"{self._money(ctx, p.gec_cash_margin)}",
             'action': self._rows(p.display_name, [('id', '=', p.id)], model='project.project', views=('form',))}
            for p in projects
        ]
        return self._proof(
            _("Cash-negative projects"), str(fc['cash_negative']),
            _("Cash margin = cash collected on the project's invoices − cost to date. Below zero, the company finances it."),
            _("%s projects below zero.", fc['cash_negative']), parts,
            notes=[_("Collected includes payments registered and not yet matched with the bank.")],
        )

    def _gec_proof_activity(self, ctx, key, title, formula):
        act = ctx['data']['activity']
        domain = self._gec_rate_domain(ctx['date_from'], ctx['date_to'])
        parts = [
            self._part(ctx, a['name'], a[key],
                       domain + [('activity_id', '=', a['id'])], model='gec.activity.rate', views=('list', 'pivot'))
            for a in act['activities']
        ]
        return self._proof(title, self._money(ctx, act['totals'][key]), formula,
                           self._expr(ctx, [p['raw'] for p in parts]) + f" = {self._money(ctx, act['totals'][key])}",
                           parts, notes=[_("From the activity rates the allocation runs wrote for the period, shown as positive cost.")])

    def _gec_proof_pool(self, ctx):
        return self._gec_proof_activity(ctx, 'pool', _("Activity cost pool"),
                                        _("Pool = the cost each allocation rule drew on, for its share of the cost centre."))

    def _gec_proof_charged(self, ctx):
        return self._gec_proof_activity(ctx, 'charged', _("Charged to cost objects"),
                                        _("Charged = units each cost object used × the rate per unit."))

    def _gec_proof_not_charged(self, ctx):
        return self._gec_proof_activity(ctx, 'not_charged', _("Not charged"),
                                        _("Not charged = pool − charged; it stays on the cost centre."))

    def _gec_proof_idle(self, ctx):
        return self._gec_proof_activity(ctx, 'idle', _("Idle capacity"),
                                        _("Idle capacity = (practical capacity − units used) × rate per unit."))

    def _gec_proof_rate_variance(self, ctx):
        return self._gec_proof_activity(ctx, 'rate_variance', _("Rate variance"),
                                        _("Rate variance = not charged − idle capacity: the pool differing from the standard rate."))

    def _gec_proof_capacity(self, ctx):
        act = ctx['data']['activity']
        domain = self._gec_rate_domain(ctx['date_from'], ctx['date_to'])
        parts = [
            {'label': a['name'], 'value': f"{self._pct(a['capacity_used'])} of capacity, {a['quantity']:,.0f} {a['unit']}",
             'action': self._rows(a['name'], domain + [('activity_id', '=', a['id'])], model='gec.activity.rate',
                                  views=('list', 'pivot'))}
            for a in act['activities']
        ]
        return self._proof(_("Capacity used"), self._pct(act['totals']['capacity_used']),
                           _("Capacity used = units measured ÷ practical capacity, over activities that have one."),
                           _("Weighted by capacity across activities."), parts)
