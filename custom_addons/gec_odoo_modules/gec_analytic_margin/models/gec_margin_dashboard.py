from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


class GecMarginDashboard(models.AbstractModel):
    """Every figure the ABC dashboard shows, in one call; the page only draws.

    Profitability reads ``gec.margin.report`` scoped to one analytic plan, so an amount on three plans counts once."""
    _name = 'gec.margin.dashboard'
    _description = 'Activity-Based Costing Dashboard'

    CHART_OBJECTS = 10
    TABLE_OBJECTS = 5

    @api.model
    def get_dashboard_data(self, date_from, date_to, plan_id=False):
        self = self._gec_reporting_env()
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        plans = self._gec_plans()
        plan = self._gec_plan(plans, plan_id)
        prev_from, prev_to = self._gec_previous_period(date_from, date_to)
        currency = self.env.company.currency_id
        return {
            'plans': [{'id': p.id, 'name': p.display_name} for p in plans],
            'plan_id': plan.id if plan else self.COMPANY_WIDE,
            'companies': self.env.companies.mapped('display_name'),
            'currency_id': currency.id,
            'currency_name': currency.name,
            'mixed_currency': len(self.env.companies.currency_id) > 1,
            'period': {
                'date_from': fields.Date.to_string(date_from),
                'date_to': fields.Date.to_string(date_to),
                'prev_from': fields.Date.to_string(prev_from),
                'prev_to': fields.Date.to_string(prev_to),
            },
            'profitability': self._gec_profitability(plan, date_from, date_to, prev_from, prev_to),
            'activity': self._gec_activity(date_from, date_to),
        }

    def _gec_reporting_env(self):
        """Convert to the current company's currency when companies differ."""
        if len(self.env.companies.currency_id) > 1:
            return self.with_context(gec_reporting_currency_id=self.env.company.currency_id.id,
                                     gec_reporting_company_id=self.env.company.id)
        return self

    def _gec_convert(self, amount, currency, date):
        """An amount outside the report (rates, payments) in the reporting currency."""
        target = self.env.context.get('gec_reporting_currency_id')
        if not target or not currency or currency.id == target or not amount:
            return amount
        return currency._convert(amount, self.env['res.currency'].browse(target), self.env.company, date)

    def _gec_plans(self):
        return self.env['account.analytic.plan'].browse(
            [plan.id for plan in self.env['gec.margin.report']._get_report_plans()]
        )

    # plan_id -1 = the whole company: every amount once, whatever plan it is on.
    COMPANY_WIDE = -1

    @classmethod
    def _gec_plan(cls, plans, plan_id):
        if plan_id == cls.COMPANY_WIDE:
            return plans.browse()
        chosen = plans.filtered(lambda p: p.id == plan_id)
        return chosen or plans[:1]

    @staticmethod
    def _gec_previous_period(date_from, date_to):
        """The period just before this one: whole months compare to whole months,
        anything else to the same number of days before."""
        next_day = date_to + timedelta(days=1)
        if date_from.day == 1 and next_day.day == 1:
            months = relativedelta(next_day, date_from)
            span = relativedelta(months=months.months + 12 * months.years)
            return date_from - span, date_from - timedelta(days=1)
        prev_to = date_from - timedelta(days=1)
        return prev_to - (date_to - date_from), prev_to

    def _gec_base_domain(self, plan, date_from, date_to):
        """Actual amounts on one plan, for the companies in the switcher."""
        domain = [
            ('line_type', '=', 'actual'),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('company_id', 'in', self.env.companies.ids),
        ]
        if plan:
            domain.append(('plan_id', '=', plan.id))
        else:
            domain.append(('is_primary_plan', '=', True))
        return domain

    def _gec_levels(self):
        report = self.env['gec.margin.report']
        return [
            level for level in self.env['gec.margin.level'].search([])
            if level._column_name() in report._fields
        ]

    def _gec_profitability(self, plan, date_from, date_to, prev_from, prev_to):
        Report = self.env['gec.margin.report']
        levels = self._gec_levels()
        measures = ['revenue_amount', 'expense_amount', 'amount'] + [
            level._column_name() for level in levels
        ]
        aggregates = [f'{m}:sum' for m in measures]

        def totals(start, end):
            groups = Report._read_group(
                self._gec_base_domain(plan, start, end), [], aggregates,
            )
            row = groups[0] if groups else [0.0] * len(measures)
            return dict(zip(measures, (value or 0.0 for value in row)))

        current = totals(date_from, date_to)
        previous = totals(prev_from, prev_to)

        kpis = [self._gec_kpi('revenue', _("Revenue"), 'revenue_amount', current, previous)]
        mix = self._gec_revenue_mix(plan, date_from, date_to, prev_from, prev_to, current, previous)
        if mix:
            kpis.append(mix.pop('kpi'))
        kpis.append(dict(
            self._gec_kpi('expense', _("Expense"), 'expense_amount', current, previous),
            is_cost=True,
        ))
        kpis += self._gec_function_kpis(plan, date_from, date_to, prev_from, prev_to, current, previous)
        for level in levels:
            kpis.append(self._gec_kpi(
                f'level_{level.id}', level.name, level._column_name(), current, previous,
                margin=True,
            ))
        kpis.append(self._gec_kpi('net', _("Net"), 'amount', current, previous, margin=True))

        unclassified_groups = Report._read_group(
            self._gec_base_domain(plan, date_from, date_to) + [('component_id', '=', False)],
            [], ['amount:sum'],
        )
        unclassified = (unclassified_groups[0][0] if unclassified_groups else 0.0) or 0.0

        return {
            'kpis': kpis,
            'trend': self._gec_trend(plan, date_to),
            'objects': self._gec_cost_objects(plan, date_from, date_to),
            'mix': mix,
            'concentration': self._gec_concentration(date_from, date_to, prev_from, prev_to),
            'productivity': self._gec_productivity(date_from, date_to, prev_from, prev_to),
            'forecast': self._gec_project_forecast(),
            'budget': self._gec_budget(plan, date_from, date_to),
            'retention': self._gec_retention(date_from, date_to),
            'outlook': self._gec_outlook(),
            'unclassified': unclassified,
            'ladder': self._gec_ladder(plan, date_from, date_to, current),
        }

    def _gec_ladder(self, plan, date_from, date_to, current):
        """The P&L in the statement's own order (each line, then its subtotal), read from gec.margin.row."""
        Report = self.env['gec.margin.report']
        by_component = {
            component.id: amount or 0.0
            for component, amount in Report._read_group(
                self._gec_base_domain(plan, date_from, date_to),
                ['component_id'], ['amount:sum'],
            ) if component
        }
        revenue = current['revenue_amount']
        rows = []
        for row in self.env['gec.margin.row'].search([]):
            if row.row_type == 'component':
                amount = by_component.get(row.component_id.id)
                if not amount:
                    continue
                kind = 'revenue' if row.component_id.nature == 'revenue' else 'cost'
            else:
                fname = row.level_id._column_name()
                if fname not in current:
                    continue
                amount, kind = current[fname], 'level'
            rows.append({
                'key': f'{row.row_type}_{row.id}',
                'code': row.code,
                'label': row.name,
                'amount': amount,
                'kind': kind,
                'pct': amount / revenue if revenue else False,
            })
        rows.append({'key': 'net', 'code': 'net', 'label': _("Net"), 'amount': current['amount'],
                     'kind': 'level', 'pct': current['amount'] / revenue if revenue else False})
        return rows

    CONCENTRATION_TOP = 10
    FORECAST_ROWS = 10

    def _gec_budget(self, plan, date_from, date_to):
        """Revenue and Net against budget over the same days.
        The report dates a budget line on its first day, so each line is prorated
        by the days it shares with the window (ends today)."""
        end = min(date_to, fields.Date.context_today(self))
        if end < date_from:
            return {}
        Report = self.env['gec.margin.report']
        scope = [d for d in self._gec_base_domain(plan, date_from, end)
                 if d[0] not in ('line_type', 'date')]
        planned = {'revenue': 0.0, 'net': 0.0}
        for line, revenue, net in Report._read_group(
            scope + [
                ('line_type', '=', 'budget'),
                ('budget_line_id.date_from', '<=', end),
                ('budget_line_id.date_to', '>=', date_from),
            ],
            ['budget_line_id'], ['revenue_amount:sum', 'amount:sum'],
        ):
            span = (line.date_to - line.date_from).days + 1
            shared = (min(line.date_to, end) - max(line.date_from, date_from)).days + 1
            share = shared / span if span > 0 else 0.0
            planned['revenue'] += (revenue or 0.0) * share
            planned['net'] += (net or 0.0) * share
        if not planned['revenue'] and not planned['net']:
            return {}
        [(revenue, net)] = Report._read_group(
            self._gec_base_domain(plan, date_from, end), [], ['revenue_amount:sum', 'amount:sum'],
        )
        return {
            'through': fields.Date.to_string(end),
            'revenue': revenue or 0.0,
            'revenue_budget': planned['revenue'],
            'net': net or 0.0,
            'net_budget': planned['net'],
        }

    def _gec_project_forecast(self):
        """Projects by forecast margin at completion, worst first; project to date, as a forecast spans the project."""
        projects = self.env['project.project'].search([
            ('account_id', '!=', False),
            ('company_id', 'in', [False, *self.env.companies.ids]),
        ])
        # Internal projects (a function set, R&D say) have no contract to earn.
        projects = projects.filtered(lambda p: not p.gec_function_component_id)
        rows = [p for p in projects if p.gec_forecast_status != 'none']
        if not rows:
            return {}
        order = {'loss': 0, 'eroding': 1, 'on_track': 2}
        rows.sort(key=lambda p: (order[p.gec_forecast_status], p.gec_forecast_margin_pct))
        counts = {status: 0 for status in order}
        for project in rows:
            counts[project.gec_forecast_status] += 1
        return {
            'counts': counts,
            'projects': [
                {
                    'id': p.id,
                    'name': p.display_name,
                    'status': p.gec_forecast_status,
                    'contract': p.gec_contract_value_effective,
                    'cost_to_date': p.gec_actual_cost,
                    'to_complete': p.gec_estimate_to_complete,
                    'hours_to_go': p.gec_remaining_hours,
                    'margin': p.gec_forecast_margin,
                    'margin_pct': p.gec_forecast_margin_pct,
                    'budget_pct': p.gec_budget_margin_pct,
                    'backlog': p.gec_backlog,
                    'complete': p.gec_percent_complete,
                    'unbilled': p.gec_unbilled,
                    'collected': p.gec_collected,
                    'cash_margin': p.gec_cash_margin,
                }
                for p in rows[:self.FORECAST_ROWS]
            ],
            'backlog': sum(p.gec_backlog for p in rows),
            'unbilled': sum(max(p.gec_unbilled, 0.0) for p in rows),
            'billed_ahead': sum(-min(p.gec_unbilled, 0.0) for p in rows),
            'cash_negative': len([p for p in rows if p.gec_cash_margin < 0]),
        }

    def _gec_fte(self, date_from, date_to):
        return self._gec_fte_detail(date_from, date_to)['by_type']

    def _gec_fte_detail(self, date_from, date_to):
        """Average FTE over the period, by employee type.
        Each employee version counts for its days, weighted by working schedule; leavers for their time there.
        Read as superuser (contracts are HR-restricted); only the total is shown."""
        Version = self.env['hr.version'].sudo().with_context(active_test=False)
        versions = Version.search([
            ('active', '=', True),
            ('employee_id', '!=', False),
            ('company_id', 'in', self.env.companies.ids),
        ])
        days = (date_to - date_from).days + 1
        by_type, by_function = {}, {}
        for version in versions:
            start = max(version.date_start, date_from)
            ends = [date_to, version.date_end, version.departure_date]
            end = min(d for d in ends if d)
            if end < start:
                continue
            rate = version.resource_calendar_id.work_time_rate or 1.0
            fte = ((end - start).days + 1) / days * rate
            label = version.employee_type_id.name or _("Employee")
            by_type[label] = by_type.get(label, 0.0) + fte
            function = version.department_id.gec_function_component_id
            by_function[function] = by_function.get(function, 0.0) + fte
        return {'by_type': by_type, 'by_function': by_function}

    def _gec_available_hours(self, date_from, date_to):
        return sum(self._gec_available_hours_by_employee(date_from, date_to).values())

    def _gec_available_hours_by_employee(self, date_from, date_to):
        """Working hours the schedules offered, public holidays off, per employee version for the days it covers."""
        Version = self.env['hr.version'].sudo().with_context(active_test=False)
        versions = Version.search([
            ('active', '=', True), ('employee_id', '!=', False),
            ('company_id', 'in', self.env.companies.ids),
        ])
        by_employee = {}
        for version in versions:
            start = max(version.date_start, date_from)
            end = min(d for d in (date_to, version.date_end, version.departure_date) if d)
            if end < start:
                continue
            calendar = version.resource_calendar_id
            hours = 0.0
            if calendar and version.company_id.tz:
                hours = calendar.with_company(version.company_id).get_work_hours_count(start, end)
            elif calendar:
                # No timezone to place the working day in: the weekly figure.
                hours = calendar.hours_per_week / 7.0 * ((end - start).days + 1)
            employee = version.employee_id
            by_employee[employee] = by_employee.get(employee, 0.0) + hours
        return by_employee

    def _gec_hours(self, date_from, date_to):
        """Where the hours went: customer projects, product work, internal.
        Utilization is customer-project hours over offered hours;
        the product share is hours on internal product projects (a function such as R&D) over all project hours."""
        if date_to < date_from:
            return {}
        available_by_employee = self._gec_available_hours_by_employee(date_from, date_to)
        available = sum(available_by_employee.values())
        internal_projects = self.env.companies.mapped('internal_project_id')
        groups = self.env['account.analytic.line'].sudo()._read_group([
            ('project_id', '!=', False),
            ('employee_id', '!=', False),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('company_id', 'in', self.env.companies.ids),
        ], ['employee_id', 'project_id'], ['unit_amount:sum'])
        cogs = self.env.ref('gec_analytic_margin.component_function_cogs', raise_if_not_found=False)
        rnd = self.env.ref('gec_analytic_margin.component_function_rnd', raise_if_not_found=False)
        buckets = {}
        # Per function of the PERSON (their department), split by kind of project.
        by_person = {}
        for employee, project, hours in groups:
            function = project.account_id.gec_function_component_id
            if project in internal_projects:
                kind, key = 'internal', _("Internal time")
            elif function and function != cogs:
                kind, key = 'product', function.name
            else:
                kind, key = 'customer', _("Customer projects")
            buckets[key] = buckets.get(key, 0.0) + (hours or 0.0)
            person = employee.sudo().department_id.gec_function_component_id
            slot = by_person.setdefault(person, {'customer': 0.0, 'product': 0.0, 'internal': 0.0})
            slot[kind] += hours or 0.0
        logged = sum(buckets.values())
        if not available and not logged:
            return {}
        customer = buckets.get(_("Customer projects"), 0.0)
        product = sum(h for k, h in buckets.items() if k not in (_("Customer projects"), _("Internal time")))

        # Delivery staff alone: implementation-staff utilization, which the company-wide figure dilutes with engineers.
        delivery_available = sum(
            hours for employee, hours in available_by_employee.items()
            if cogs and employee.sudo().department_id.gec_function_component_id == cogs
        )
        delivery = by_person.get(cogs) if cogs else None
        # Engineering staff alone: share of project hours spent on one customer's project rather than the product.
        engineering = by_person.get(rnd) if rnd else None
        engineering_project = (engineering['customer'] + engineering['product']) if engineering else 0.0
        # Rework: customer-project hours on tasks tagged as rework.
        [(rework,)] = self.env['account.analytic.line'].sudo()._read_group([
            ('project_id', '!=', False), ('employee_id', '!=', False),
            ('date', '>=', date_from), ('date', '<=', date_to),
            ('company_id', 'in', self.env.companies.ids),
            ('task_id.tag_ids.gec_rework', '=', True),
            ('project_id', 'not in', internal_projects.ids),
        ], [], ['unit_amount:sum'])
        rework = rework or 0.0
        rework_in_use = bool(self.env['project.tags'].search_count([('gec_rework', '=', True)], limit=1))
        return {
            'rework_hours': rework,
            'rework_share': rework / customer if rework_in_use and customer else False,
            'delivery_utilization': delivery['customer'] / delivery_available
            if delivery and delivery_available else False,
            'bespoke_share': engineering['customer'] / engineering_project
            if engineering_project else False,
            'engineering_hours': engineering_project,
            'available': available,
            'logged': logged,
            'buckets': [{'label': k, 'hours': h} for k, h in sorted(buckets.items(), key=lambda i: -i[1])],
            'utilization': customer / available if available else False,
            'coverage': logged / available if available else False,
            'product_share': product / (customer + product) if customer + product else False,
        }

    # Staffing by the P&L's function lines: implementation and support together are Cost of Sales.
    HEADCOUNT_TARGETS = {
        'function_cogs': (0.23, 0.37),
        'function_rnd': (0.30, 0.40),
        'function_sm': (0.10, 0.15),
        'function_ga': (0.08, 0.12),
    }

    def _gec_headcount_mix(self, by_function, total):
        """FTE per function line, in P&L order, with the benchmark's range."""
        if not by_function or len(by_function) == 1 and not next(iter(by_function)):
            return []
        rows = sorted(
            by_function.items(),
            key=lambda item: (not item[0], item[0].sequence if item[0] else 0),
        )
        return [
            {
                'label': function.name if function else _("No function"),
                'fte': fte,
                'pct': fte / total if total else False,
                'target': self.HEADCOUNT_TARGETS.get(function.code) if function else None,
            }
            for function, fte in rows
        ]

    def _gec_company_totals(self, date_from, date_to):
        """Company-wide revenue, gross profit and recurring revenue, counted once."""
        Report = self.env['gec.margin.report']
        domain = [
            ('line_type', '=', 'actual'),
            ('is_primary_plan', '=', True),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('company_id', 'in', self.env.companies.ids),
        ]
        gross = self.env['gec.margin.level'].search([('code', '=', 'gross')], limit=1)
        gross_fname = gross._column_name() if gross and gross._column_name() in Report._fields else None
        aggregates = ['revenue_amount:sum'] + ([f'{gross_fname}:sum'] if gross_fname else [])
        [row] = Report._read_group(domain, [], aggregates)
        recurring = sum(
            amount or 0.0 for stream, amount in Report._read_group(
                domain + [('direction', '=', 'revenue'), ('revenue_stream_id.recurring', '=', True)],
                ['revenue_stream_id'], ['revenue_amount:sum'],
            )
        )
        by_stream = {
            stream: amount or 0.0 for stream, amount in Report._read_group(
                domain + [('direction', '=', 'revenue'), ('revenue_stream_id', '!=', False)],
                ['revenue_stream_id'], ['revenue_amount:sum'],
            )
        }
        rnd = self.env.ref('gec_analytic_margin.component_function_rnd', raise_if_not_found=False)
        [(rnd_cost,)] = Report._read_group(
            domain + [('component_id', '=', rnd.id if rnd else 0)], [], ['amount:sum'])
        customers = Report._read_group(
            domain + [('direction', '=', 'revenue'), ('partner_id', '!=', False)],
            ['partner_id'], [])
        return {
            'revenue': row[0] or 0.0,
            'gross': (row[1] or 0.0) if gross_fname else None,
            'recurring': recurring,
            'by_stream': by_stream,
            'rnd': -(rnd_cost or 0.0),
            'customers': len({partner.commercial_partner_id for (partner,) in customers}),
        }

    def _gec_productivity(self, date_from, date_to, prev_from, prev_to):
        """Revenue, gross profit and recurring revenue per FTE, annualised (the benchmark is annual);
        company-wide like the headcount."""
        # Never past today: counting staff to December but revenue to September would understate every figure.
        today = fields.Date.context_today(self)

        def measure(start, end):
            end = min(end, today)
            if end < start:
                return None
            detail = self._gec_fte_detail(start, end)
            by_type = detail['by_type']
            fte = sum(by_type.values())
            if not fte:
                return None
            totals = self._gec_company_totals(start, end)
            year = 365.0 / ((end - start).days + 1)
            per = {key: (totals[key] * year / fte if totals[key] is not None else None)
                   for key in ('revenue', 'gross', 'recurring')}
            return {'fte': fte, 'by_type': by_type, 'per_fte': per,
                    'by_function': detail['by_function'],
                    'annual_revenue': totals['revenue'] * year,
                    'stream_per_fte': [
                        {'id': stream.id, 'name': stream.name, 'per_fte': amount * year / fte}
                        for stream, amount in sorted(totals['by_stream'].items(), key=lambda i: i[0].sequence)
                    ],
                    'rnd_per_customer': totals['rnd'] * year / totals['customers']
                    if totals['rnd'] and totals['customers'] else False,
                    'customers': totals['customers']}

        now = measure(date_from, date_to)
        if not now:
            return {}
        before = measure(prev_from, prev_to) or {}
        return {
            'fte': now['fte'],
            'prev_fte': before.get('fte', False),
            'by_type': [{'label': label, 'fte': fte} for label, fte in sorted(now['by_type'].items())],
            'by_function': self._gec_headcount_mix(now['by_function'], now['fte']),
            'hours': self._gec_hours(date_from, min(date_to, today)),
            'revenue_per_fte': now['per_fte']['revenue'],
            'prev_revenue_per_fte': before.get('per_fte', {}).get('revenue', False),
            'gross_per_fte': now['per_fte']['gross'],
            # Both annualised, so a period cut at today still compares with a whole previous one;
            # revenue should grow faster than the workforce.
            'revenue_growth': (now['annual_revenue'] / before['annual_revenue'] - 1)
            if before.get('annual_revenue') else False,
            'fte_growth': (now['fte'] / before['fte'] - 1) if before.get('fte') else False,
            'recurring_per_fte': now['per_fte']['recurring'],
            'stream_per_fte': now['stream_per_fte'],
            'rnd_per_customer': now['rnd_per_customer'],
            'active_customers': now['customers'],
        }

    def _gec_revenue_by_customer(self, date_from, date_to):
        """Actual revenue per customer company, company-wide and not plan-scoped
        (concentration is a risk across plans); contacts fold into their company."""
        groups = self.env['gec.margin.report']._read_group([
            ('line_type', '=', 'actual'),
            ('direction', '=', 'revenue'),
            ('is_primary_plan', '=', True),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('company_id', 'in', self.env.companies.ids),
        ], ['partner_id'], ['revenue_amount:sum'])
        by_customer = {}
        for partner, amount in groups:
            customer = partner.commercial_partner_id
            by_customer[customer] = by_customer.get(customer, 0.0) + (amount or 0.0)
        return by_customer

    def _gec_retention(self, date_from, date_to):
        """Net and gross revenue retention, year on year, company-wide, on invoiced revenue per customer company.
        Recurring streams only when any is in use, else all revenue.
        NRR/GRR cover last year's payers; new customers shown beside."""
        end = min(date_to, fields.Date.context_today(self))
        if end < date_from:
            return {}
        prev_from, prev_to = date_from - relativedelta(years=1), end - relativedelta(years=1)
        recurring = self.env['gec.revenue.stream'].search([('recurring', '=', True)])
        Report = self.env['gec.margin.report']

        def by_customer(start, stop, streams):
            domain = [
                ('line_type', '=', 'actual'), ('direction', '=', 'revenue'),
                ('is_primary_plan', '=', True), ('date', '>=', start), ('date', '<=', stop),
                ('company_id', 'in', self.env.companies.ids), ('partner_id', '!=', False),
            ]
            if streams:
                domain.append(('revenue_stream_id', 'in', streams.ids))
            amounts = {}
            for partner, amount in Report._read_group(domain, ['partner_id'], ['revenue_amount:sum']):
                customer = partner.commercial_partner_id
                amounts[customer] = amounts.get(customer, 0.0) + (amount or 0.0)
            return amounts

        streams = recurring
        now, before = by_customer(date_from, end, streams), by_customer(prev_from, prev_to, streams)
        if streams and not (any(now.values()) or any(before.values())):
            streams = recurring.browse()
            now, before = by_customer(date_from, end, streams), by_customer(prev_from, prev_to, streams)
        base = sum(amount for amount in before.values() if amount > 0)
        if not base:
            return {}
        expansion = contraction = churn = retained = kept = 0.0
        lost = 0
        for customer, was in before.items():
            if was <= 0:
                continue
            is_ = max(now.get(customer, 0.0), 0.0)
            retained += is_
            kept += min(is_, was)
            if not is_:
                churn += was
                lost += 1
            elif is_ >= was:
                expansion += is_ - was
            else:
                contraction += was - is_
        new = sum(amount for customer, amount in now.items()
                  if amount > 0 and before.get(customer, 0.0) <= 0)
        return {
            'basis': 'recurring' if streams else 'all',
            'prev_from': fields.Date.to_string(prev_from),
            'prev_to': fields.Date.to_string(prev_to),
            'start': base,
            'expansion': expansion,
            'contraction': contraction,
            'churn': churn,
            'retained': retained,
            'new': new,
            'nrr': retained / base,
            'grr': kept / base,
            'customers': len([v for v in before.values() if v > 0]),
            'lost': lost,
            'won': len([c for c, v in now.items() if v > 0 and before.get(c, 0.0) <= 0]),
        }

    def _gec_outlook(self):
        """Next four quarters: budget, run rate and contracted backlog, company-wide, whatever the selected period.
        Run rate is the last three full months' average carried forward;
        backlog coverage is the signed share of the year's budget."""
        today = fields.Date.context_today(self)
        first = (today.replace(day=1) + relativedelta(months=3 - (today.month - 1) % 3)).replace(day=1)
        quarters = []
        for i in range(4):
            start = first + relativedelta(months=3 * i)
            end = start + relativedelta(months=3) - timedelta(days=1)
            quarters.append((start, end))
        Report = self.env['gec.margin.report']
        company = [('company_id', 'in', self.env.companies.ids), ('is_primary_plan', '=', True)]
        lines = Report._read_group(
            company + [('line_type', '=', 'budget'),
                       ('budget_line_id.date_from', '<=', quarters[-1][1]),
                       ('budget_line_id.date_to', '>=', quarters[0][0])],
            ['budget_line_id'], ['revenue_amount:sum', 'amount:sum'])
        month_end = today.replace(day=1) - timedelta(days=1)
        rate_from = (month_end.replace(day=1) - relativedelta(months=2))
        [(rate_revenue, rate_net)] = Report._read_group(
            company + [('line_type', '=', 'actual'), ('date', '>=', rate_from), ('date', '<=', month_end)],
            [], ['revenue_amount:sum', 'amount:sum'])
        rows = []
        for start, end in quarters:
            revenue = net = 0.0
            for line, line_revenue, line_net in lines:
                span = (line.date_to - line.date_from).days + 1
                shared = (min(line.date_to, end) - max(line.date_from, start)).days + 1
                if shared > 0 and span > 0:
                    revenue += (line_revenue or 0.0) * shared / span
                    net += (line_net or 0.0) * shared / span
            quarter = (start.month - 1) // 3 + 1
            rows.append({
                'label': f"Q{quarter} {start.year}",
                'start': fields.Date.to_string(start), 'end': fields.Date.to_string(end),
                'budget_revenue': revenue, 'budget_net': net,
                'run_rate_revenue': (rate_revenue or 0.0), 'run_rate_net': (rate_net or 0.0),
                # The quarter's budget, or the run rate where none reaches it;
                # a one-quarter budget must not stand in for a year.
                'plan_revenue': revenue or (rate_revenue or 0.0),
                'budgeted': bool(revenue),
            })
        projects = self.env['project.project'].search([
            ('account_id', '!=', False), ('company_id', 'in', [False, *self.env.companies.ids])])
        backlog = sum(p.gec_backlog for p in projects if not p.gec_function_component_id)
        budget_total = sum(r['budget_revenue'] for r in rows)
        run_rate_total = sum(r['run_rate_revenue'] for r in rows)
        plan_total = sum(r['plan_revenue'] for r in rows)
        if not plan_total:
            return {}
        return {
            'quarters': rows,
            'budget_total': budget_total,
            'run_rate_total': run_rate_total,
            'plan_total': plan_total,
            'budgeted_quarters': len([r for r in rows if r['budgeted']]),
            'backlog': backlog,
            'coverage': backlog / plan_total,
            'coverage_budget': backlog / budget_total if budget_total else False,
            'coverage_run_rate': backlog / run_rate_total if run_rate_total else False,
            'run_rate_from': fields.Date.to_string(rate_from),
            'run_rate_to': fields.Date.to_string(month_end),
        }

    def _gec_concentration_shares(self, by_customer):
        total = sum(by_customer.values())
        ranked = sorted(
            ((customer, amount) for customer, amount in by_customer.items() if customer),
            key=lambda item: -item[1],
        )
        if not total or not ranked:
            return total, ranked, False, False
        top = ranked[0][1] / total
        top_n = sum(amount for _c, amount in ranked[:self.CONCENTRATION_TOP]) / total
        return total, ranked, top, top_n

    def _gec_concentration(self, date_from, date_to, prev_from, prev_to):
        """How much of the revenue a few customers carry;
        revenue with no partner counts in the total but belongs to no customer."""
        by_customer = self._gec_revenue_by_customer(date_from, date_to)
        total, ranked, top, top_n = self._gec_concentration_shares(by_customer)
        if not ranked:
            return {}
        _p_total, _p_ranked, prev_top, prev_top_n = self._gec_concentration_shares(
            self._gec_revenue_by_customer(prev_from, prev_to))
        cumulative = 0.0
        customers = []
        for customer, amount in ranked[:self.CONCENTRATION_TOP]:
            cumulative += amount
            customers.append({
                'id': customer.id,
                'name': customer.display_name,
                'amount': amount,
                'pct': amount / total,
                'cumulative_pct': cumulative / total,
            })
        return {
            'total': total,
            'customer_count': len(ranked),
            'top_pct': top,
            'prev_top_pct': prev_top,
            'top_n': min(self.CONCENTRATION_TOP, len(ranked)),
            'top_n_pct': top_n,
            'prev_top_n_pct': prev_top_n,
            'customers': customers,
            'no_customer': by_customer.get(self.env['res.partner'], 0.0),
        }

    def _gec_revenue_mix(self, plan, date_from, date_to, prev_from, prev_to, current, previous):
        """Revenue by stream and the share that renews; empty until a stream is in use, so no misleading 0% card."""
        Report = self.env['gec.margin.report']

        def by_stream(start, end):
            return {
                stream: amount or 0.0
                for stream, amount in Report._read_group(
                    self._gec_base_domain(plan, start, end) + [('direction', '=', 'revenue')],
                    ['revenue_stream_id'], ['revenue_amount:sum'],
                )
            }

        now, before = by_stream(date_from, date_to), by_stream(prev_from, prev_to)
        if not any(stream for stream in (*now, *before)):
            return {}

        # Gross margin per stream, cost included; only as complete as the streams set on projects and product lines.
        gross = self.env['gec.margin.level'].search([('code', '=', 'gross')], limit=1)
        gross_fname = gross._column_name() if gross and gross._column_name() in Report._fields else None
        margins = {
            stream: amount or 0.0
            for stream, amount in Report._read_group(
                self._gec_base_domain(plan, date_from, date_to),
                ['revenue_stream_id'], [f'{gross_fname}:sum'],
            )
        } if gross_fname else {}

        def recurring(amounts):
            return sum(amount for stream, amount in amounts.items() if stream.recurring)

        revenue, prev_revenue = current['revenue_amount'], previous['revenue_amount']
        streams = sorted((stream for stream in now if stream), key=lambda s: (s.sequence, s.id))
        return {
            'kpi': {
                'key': 'recurring',
                'label': _("Recurring revenue"),
                'value': recurring(now),
                'previous': recurring(before),
                'pct': recurring(now) / revenue if revenue else False,
                'prev_pct': recurring(before) / prev_revenue if prev_revenue else False,
            },
            'streams': [
                {
                    'id': stream.id,
                    'name': stream.name,
                    'recurring': stream.recurring,
                    'amount': now[stream],
                    'pct': now[stream] / revenue if revenue else False,
                    'standard': stream.standard_product,
                    'gross': margins.get(stream) if gross_fname else None,
                    'gross_pct': margins.get(stream, 0.0) / now[stream]
                    if gross_fname and now[stream] else False,
                }
                for stream in streams
            ],
            # The benchmark's scalability signal: product revenue, not bespoke work.
            'standard': sum(now[s] for s in streams if s.standard_product),
            'standard_pct': sum(now[s] for s in streams if s.standard_product) / revenue
            if revenue else False,
            # Revenue no stream claims is shown, so the mix visibly adds up to the Revenue card.
            'unassigned': now.get(self.env['gec.revenue.stream'], 0.0),
        }

    def _gec_function_kpis(self, plan, date_from, date_to, prev_from, prev_to, current, previous):
        """One card per function line, as a share of revenue, for a company reporting by function."""
        if self.env.company.gec_pl_mode != 'function':
            return []
        functions = self.env['gec.margin.component'].search([('is_function', '=', True)])
        if not functions:
            return []
        Report = self.env['gec.margin.report']

        def by_function(start, end):
            return {
                component.id: amount or 0.0
                for component, amount in Report._read_group(
                    self._gec_base_domain(plan, start, end) + [('component_id', 'in', functions.ids)],
                    ['component_id'], ['amount:sum'],
                )
            }

        now, before = by_function(date_from, date_to), by_function(prev_from, prev_to)
        revenue, prev_revenue = current['revenue_amount'], previous['revenue_amount']
        return [
            {
                'key': f'function_{function.id}',
                'label': function.name,
                'value': now.get(function.id, 0.0),
                'previous': before.get(function.id, 0.0),
                'pct': abs(now.get(function.id, 0.0)) / revenue if revenue else False,
                'prev_pct': abs(before.get(function.id, 0.0)) / prev_revenue if prev_revenue else False,
                'is_cost': True,
            }
            for function in functions
        ]

    @staticmethod
    def _gec_kpi(key, label, fname, current, previous, margin=False):
        revenue = current['revenue_amount']
        prev_revenue = previous['revenue_amount']
        value = current[fname]
        return {
            'key': key,
            'label': label,
            'value': value,
            'previous': previous[fname],
            'pct': (value / revenue) if margin and revenue else False,
            'prev_pct': (previous[fname] / prev_revenue) if margin and prev_revenue else False,
        }

    def _gec_trend(self, plan, date_to):
        """Twelve months ending with the selected period's last month, but not past the current month."""
        date_to = min(date_to, fields.Date.context_today(self))
        end = date_to.replace(day=1) + relativedelta(months=1) - timedelta(days=1)
        start = end.replace(day=1) - relativedelta(months=11)
        Report = self.env['gec.margin.report']
        domain = self._gec_base_domain(plan, start, end)
        levels = {
            level.code: level._column_name()
            for level in self.env['gec.margin.level'].search([('code', 'in', ('gross', 'ebitda'))])
            if level._column_name() in Report._fields
        }
        aggregates = ['revenue_amount:sum', 'expense_amount:sum', 'amount:sum'] + [
            f'{fname}:sum' for fname in levels.values()
        ]
        by_month = {}
        for month, rev, exp, net, *subtotals in Report._read_group(domain, ['date:month'], aggregates):
            by_month[month] = (rev or 0.0, exp or 0.0, net or 0.0,
                               dict(zip(levels, (v or 0.0 for v in subtotals))))
        recurring = {
            month: amount or 0.0 for month, amount in Report._read_group(
                domain + [('direction', '=', 'revenue'), ('revenue_stream_id.recurring', '=', True)],
                ['date:month'], ['revenue_amount:sum'],
            )
        }
        months = []
        cursor = start
        while cursor <= end:
            rev, exp, net, subtotals = by_month.get(cursor, (0.0, 0.0, 0.0, {}))
            months.append({
                'month': fields.Date.to_string(cursor),
                'revenue': rev,
                'expense': -exp or 0.0,
                'net': net,
                'gross_pct': subtotals.get('gross', 0.0) / rev if rev and 'gross' in levels else False,
                'ebitda_pct': subtotals.get('ebitda', 0.0) / rev if rev and 'ebitda' in levels else False,
                'recurring_pct': recurring.get(cursor, 0.0) / rev if rev else False,
            })
            cursor += relativedelta(months=1)
        return months

    def _gec_cost_objects(self, plan, date_from, date_to):
        groups = self.env['gec.margin.report']._read_group(
            self._gec_base_domain(plan, date_from, date_to),
            ['analytic_account_id'],
            ['revenue_amount:sum', 'expense_amount:sum', 'amount:sum'],
        )
        objects = [
            {
                'id': account.id,
                # The account's own name: its display name repeats the partner (the project name on a project account).
                'name': f"[{account.code}] {account.name}" if account.code else account.name,
                'function': account.gec_function_component_id.name or False,
                'revenue': revenue or 0.0,
                'expense': -(expense or 0.0) or 0.0,
                'net': net or 0.0,
                'pct': (net / revenue) if revenue else False,
            }
            for account, revenue, expense, net in groups
            if account
        ]
        # An internal project (a function set, e.g. R&D) earns nothing by design: on the project plan it is
        # shown as spend, not ranked as a loss-maker; other plans keep everything.
        project_plan, _others = self.env['account.analytic.plan']._get_all_plans()
        internal = []
        if plan == project_plan:
            internal = [o for o in objects if o['function']]
            objects = [o for o in objects if not o['function']]
        internal.sort(key=lambda o: o['net'])
        objects.sort(key=lambda o: o['net'], reverse=True)
        # Cut after the full sort so the worst are the real worst; with few objects the two tables
        # split them in half, not repeating one.
        split = min(self.TABLE_OBJECTS, (len(objects) + 1) // 2)
        top = objects[:split]
        bottom = objects[split:][::-1][:self.TABLE_OBJECTS]
        return {
            'count': len(objects),
            'chart': objects[:self.CHART_OBJECTS],
            'top': top,
            'bottom': bottom,
            'internal': internal,
        }

    def _gec_rate_domain(self, date_from, date_to):
        # Every rate whose period touches the selection, as the unused-capacity warning reads them;
        # a quarterly run is counted whole, rates cannot be prorated.
        return [
            ('date_from', '<=', date_to),
            ('date_to', '>=', date_from),
            ('company_id', 'in', self.env.companies.ids),
        ]

    def _gec_activity(self, date_from, date_to):
        """Costs are negative in the rate history; shown here as positive cost."""
        rates = self.env['gec.activity.rate'].search(
            self._gec_rate_domain(date_from, date_to), order='date_from, id',
        )
        value_labels = dict(
            self.env['gec.activity']._fields['value_added']._description_selection(self.env)
        )

        by_activity = {}
        for rate in rates:
            entry = by_activity.setdefault(rate.activity_id.id, {
                'id': rate.activity_id.id,
                'name': rate.activity_id.display_name,
                'unit': rate.driver_label or rate.activity_id.driver_label or '',
                'value_added': rate.activity_id.value_added,
                'pool': 0.0, 'charged': 0.0, 'not_charged': 0.0,
                'idle': 0.0, 'rate_variance': 0.0,
                'quantity': 0.0, 'capacity': 0.0, 'capacity_quantity': 0.0,
                'rate': 0.0,
            })
            convert = lambda value, r=rate: self._gec_convert(value, r.currency_id, r.date_to)
            entry['pool'] -= convert(rate.pool_amount)
            entry['charged'] -= convert(rate.charged_amount)
            entry['not_charged'] -= convert(rate.variance_amount)
            entry['idle'] -= convert(rate.volume_variance)
            entry['rate_variance'] -= convert(rate.spending_variance)
            entry['quantity'] += rate.quantity
            if rate.practical_capacity:
                entry['capacity'] += rate.practical_capacity
                entry['capacity_quantity'] += rate.quantity
            # Ordered by date, so the last one written is the latest period's.
            entry['rate'] = self._gec_convert(rate.rate, rate.currency_id, rate.date_to)

        activities = sorted(by_activity.values(), key=lambda a: a['pool'], reverse=True)
        for entry in activities:
            entry['capacity_used'] = (
                entry['capacity_quantity'] / entry['capacity'] if entry['capacity'] else False
            )

        def total(key):
            return sum(entry[key] for entry in activities)

        capacity = total('capacity')
        by_value = {}
        for entry in activities:
            by_value[entry['value_added']] = by_value.get(entry['value_added'], 0.0) + entry['pool']

        uncovered, _by_account = self.env['gec.allocation.rule']._uncovered_pool(
            date_from, date_to, self.env.companies,
        )
        return {
            'totals': {
                'pool': total('pool'),
                'charged': total('charged'),
                'not_charged': total('not_charged'),
                'idle': total('idle'),
                'rate_variance': total('rate_variance'),
                'capacity_used': (total('capacity_quantity') / capacity) if capacity else False,
                'uncovered': abs(uncovered or 0.0),
            },
            'activities': activities,
            'value_split': [
                {'key': key, 'label': value_labels.get(key, key).split(' — ')[0], 'amount': amount}
                for key, amount in by_value.items()
            ],
        }

    @api.model
    def action_drilldown(self, kind, date_from, date_to, plan_id=False, res_id=False):
        """What a click on the dashboard opens — the rows behind the figure."""
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        plan = self._gec_plan(self._gec_plans(), plan_id)

        if kind == 'project':
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'project.project',
                'res_id': res_id,
                'views': [(False, 'form')],
            }

        if kind in ('activity', 'activities'):
            domain = self._gec_rate_domain(date_from, date_to)
            if kind == 'activity' and res_id:
                domain.append(('activity_id', '=', res_id))
            return {
                'type': 'ir.actions.act_window',
                'name': _("Activity Rates"),
                'res_model': 'gec.activity.rate',
                'views': [(False, 'list'), (False, 'pivot'), (False, 'graph'), (False, 'form')],
                'domain': domain,
                'context': {'search_default_group_activity': 1},
            }

        domain = self._gec_base_domain(plan, date_from, date_to)
        context = {'pivot_measures': ['revenue_amount', 'expense_amount', 'amount']}
        name = _("Margin Analysis")
        if kind == 'object' and res_id:
            domain.append(('analytic_account_id', '=', res_id))
            context['pivot_row_groupby'] = ['component_id']
            name = self.env['account.analytic.account'].browse(res_id).display_name
        elif kind == 'customer':
            # Company-wide, like the concentration it explains: the customer's
            # whole revenue, once, whichever plan it was tagged on.
            domain = [
                ('line_type', '=', 'actual'),
                ('direction', '=', 'revenue'),
                ('is_primary_plan', '=', True),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
                ('company_id', 'in', self.env.companies.ids),
                ('partner_id', 'child_of', res_id) if res_id else ('partner_id', '=', False),
            ]
            context['pivot_row_groupby'] = ['analytic_account_id']
            context['pivot_measures'] = ['revenue_amount']
            name = self.env['res.partner'].browse(res_id).display_name if res_id else _("Revenue Without a Customer")
        elif kind == 'stream':
            domain.append(('direction', '=', 'revenue'))
            domain.append(('revenue_stream_id', '=', res_id or False))
            context['pivot_row_groupby'] = ['analytic_account_id']
            context['pivot_measures'] = ['revenue_amount']
            name = (self.env['gec.revenue.stream'].browse(res_id).name if res_id
                    else _("Revenue Without a Stream"))
        elif kind == 'unclassified':
            domain.append(('component_id', '=', False))
            context['pivot_row_groupby'] = ['general_account_id']
            name = _("Unclassified Amounts")
        elif kind == 'month' and res_id:
            month = fields.Date.to_date(res_id)
            end = month + relativedelta(months=1) - timedelta(days=1)
            domain = self._gec_base_domain(plan, month, end)
            context['pivot_row_groupby'] = ['analytic_account_id']
        else:
            context['pivot_row_groupby'] = ['analytic_account_id']
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'gec.margin.report',
            'views': [(False, 'pivot'), (False, 'list'), (False, 'graph')],
            'domain': domain,
            'context': context,
        }
