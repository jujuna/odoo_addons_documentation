from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


class GecMarginDashboardDelivery(models.AbstractModel):
    """Projects & Cash: delivery dates, receivables, cash and forecast quality, which margin cannot answer.

    Company-wide, as receivables and cash do not belong to an analytic plan."""
    _inherit = 'gec.margin.dashboard'

    COMPLETION_ROWS = 10
    CASH_WEEKS = 13
    ACCURACY_MONTHS = 6
    # A bank movement whose other side is one of these is financing or investing, not operations.
    NON_OPERATING = ('equity', 'equity_unaffected', 'liability_non_current', 'asset_fixed', 'asset_non_current')
    OPEN_STATES = ('draft', 'canceled', 'rejected')

    @api.model
    def get_dashboard_data(self, date_from, date_to, plan_id=False):
        data = super().get_dashboard_data(date_from, date_to, plan_id)
        self = self._gec_reporting_env()
        date_from = fields.Date.to_date(date_from)
        date_to = fields.Date.to_date(date_to)
        data['delivery'] = self._gec_delivery(date_from, date_to)
        data['cash'] = self._gec_cash(date_from, date_to)
        return data

    def _gec_customer_projects(self):
        projects = self.env['project.project'].search([
            ('account_id', '!=', False), ('is_template', '=', False),
            ('company_id', 'in', [False, *self.env.companies.ids]),
        ])
        # Internal projects have no customer: an R&D function, or the company's own internal project.
        internal = self.env.companies.mapped('internal_project_id')
        return projects.filtered(lambda p: not p.gec_function_component_id and p not in internal)

    def _gec_delivery(self, date_from, date_to):
        today = fields.Date.context_today(self)
        end = min(date_to, today)
        projects = self._gec_customer_projects()
        result = {}

        milestones = self.env['project.milestone'].search([
            ('project_id', 'in', projects.ids), ('deadline', '>=', date_from), ('deadline', '<=', end),
        ]) if end >= date_from else self.env['project.milestone']
        if milestones:
            on_time = milestones.filtered(lambda m: m.is_reached and m.reached_date and m.reached_date <= m.deadline)
            result['milestones'] = {
                'due': len(milestones), 'on_time': len(on_time),
                'late': len(milestones) - len(on_time),
                'open_overdue': len(milestones.filtered(lambda m: not m.is_reached and m.deadline < today)),
                'rate': len(on_time) / len(milestones),
            }

        golive = projects.filtered(lambda p: p.gec_golive_planned and date_from <= p.gec_golive_planned <= end)
        if golive:
            slipped = golive.filtered(lambda p: p.gec_golive_actual > p.gec_golive_planned if p.gec_golive_actual
                                      else p.gec_golive_planned < today)
            delays = [((p.gec_golive_actual or today) - p.gec_golive_planned).days for p in slipped]
            result['golive'] = {
                'due': len(golive), 'slipped': len(slipped), 'rate': len(slipped) / len(golive),
                'avg_days': sum(delays) / len(delays) if delays else 0.0,
                'live': len(golive.filtered('gec_golive_actual')),
            }

        dated = projects.filtered(lambda p: p.gec_end_forecast and p.date)
        if dated:
            late = dated.filtered(lambda p: p.gec_end_delay_days > 0)
            rows = dated.sorted(lambda p: -p.gec_end_delay_days)[:self.COMPLETION_ROWS]
            result['completion'] = {
                'projects': len(dated), 'late': len(late), 'rate': len(late) / len(dated),
                'rows': [{
                    'id': p.id, 'name': p.display_name,
                    'planned_end': fields.Date.to_string(p.date),
                    'forecast_end': fields.Date.to_string(p.gec_end_forecast),
                    'delay': p.gec_end_delay_days, 'burn': p.gec_burn_rate,
                    'hours_to_go': max((p.allocated_hours or 0.0) - (p.effective_hours or 0.0), 0.0),
                } for p in rows],
            }

        templated = projects.filtered('gec_template_id')
        if projects and (templated or self.env['project.project'].search_count([('is_template', '=', True)], limit=1)):
            result['templates'] = {
                'projects': len(projects), 'from_template': len(templated),
                'rate': len(templated) / len(projects),
            }
        return result

    def _gec_cash(self, date_from, date_to):
        today = fields.Date.context_today(self)
        end = min(date_to, today)
        if end < date_from:
            return {}
        result = {}
        dso = self._gec_dso(date_from, end)
        if dso:
            result['dso'] = dso
        conversion = self._gec_cash_conversion(date_from, end)
        if conversion:
            result['conversion'] = conversion
        forecast = self._gec_cash_forecast(today)
        if forecast:
            result['forecast'] = forecast
        accuracy = self._gec_forecast_accuracy(date_to)
        if accuracy:
            result['accuracy'] = accuracy
        return result

    def _gec_paid_by(self, move, end):
        """Amount of an invoice or bill settled by ``end``.
        A payment with no journal entry (no outstanding account) counts from its own date;
        capped at the total so a bank match is not counted twice."""
        total = abs(move.amount_total_signed)
        terms = move.line_ids.filtered(lambda l: l.account_type in ('asset_receivable', 'liability_payable'))
        reconciled = sum(p.amount for p in (terms.matched_debit_ids | terms.matched_credit_ids)
                         if p.max_date and p.max_date <= end)
        registered = sum(abs(p.amount_company_currency_signed) for p in move.matched_payment_ids
                         if not p.move_id and p.state not in self.OPEN_STATES and p.date and p.date <= end)
        return min(reconciled + registered, total)

    def _gec_open_documents(self, kinds, end):
        """Invoices (or bills) dated by ``end`` that were not fully settled by then."""
        return self.env['account.move'].search([
            ('move_type', 'in', kinds), ('state', '=', 'posted'),
            ('invoice_date', '<=', end), ('company_id', 'in', self.env.companies.ids),
            '|', '|', ('payment_state', 'not in', ('paid', 'reversed')),
            ('line_ids.matched_credit_ids.max_date', '>', end),
            ('line_ids.matched_debit_ids.max_date', '>', end),
        ])

    def _gec_open_amount(self, move, end):
        sign = -1 if move.move_type in ('out_refund', 'in_refund') else 1
        amount = sign * (abs(move.amount_total_signed) - self._gec_paid_by(move, end))
        return self._gec_convert(amount, move.company_currency_id, end)

    def _gec_dso(self, date_from, end):
        """Days sales outstanding: receivables ÷ what was invoiced × days."""
        invoices = self.env['account.move'].search([
            ('move_type', 'in', ('out_invoice', 'out_refund')), ('state', '=', 'posted'),
            ('invoice_date', '>=', date_from), ('invoice_date', '<=', end),
            ('company_id', 'in', self.env.companies.ids),
        ])
        invoiced = sum(self._gec_convert(m.amount_total_signed, m.company_currency_id, m.invoice_date)
                       for m in invoices)
        if invoiced <= 0:
            return {}
        open_moves = self._gec_open_documents(('out_invoice', 'out_refund'), end)
        receivables = sum(self._gec_open_amount(m, end) for m in open_moves)
        days = (end - date_from).days + 1
        return {
            'days': receivables / invoiced * days, 'receivables': receivables, 'invoiced': invoiced,
            'period_days': days, 'through': fields.Date.to_string(end),
            'open_ids': [m.id for m in open_moves if self._gec_open_amount(m, end)],
            'invoice_ids': invoices.ids,
        }

    def _gec_registered_payments(self, date_from, end):
        """Payments registered without a journal entry and not yet on a bank statement."""
        domain = [('move_id', '=', False), ('state', 'not in', self.OPEN_STATES),
                  ('date', '<=', end), ('company_id', 'in', self.env.companies.ids)]
        if date_from:
            domain.append(('date', '>=', date_from))
        payments = self.env['account.payment'].search(domain)
        # Matched with the bank, the invoice leaves "In Payment" and the cash is already in the bank lines.
        return payments.filtered(lambda p: not p.invoice_ids or 'in_payment' in p.invoice_ids.mapped('payment_state'))

    def _gec_operating_bank(self, date_from, end):
        """Bank movements in the period from operations: (amount, line domain)."""
        domain = [('account_id.account_type', '=', 'asset_cash'), ('parent_state', '=', 'posted'),
                  ('date', '>=', date_from), ('date', '<=', end),
                  ('company_id', 'in', self.env.companies.ids)]
        Line = self.env['account.move.line']
        moves = dict(Line._read_group(domain, ['move_id'], ['balance:sum']))
        if not moves:
            return 0.0, domain
        ids = [m.id for m in moves]
        non_cash = {m.id for (m,) in Line._read_group(
            [('move_id', 'in', ids), ('account_id.account_type', '!=', 'asset_cash')], ['move_id'])}
        excluded = {m.id for (m,) in Line._read_group(
            [('move_id', 'in', ids), ('account_id.account_type', 'in', self.NON_OPERATING)], ['move_id'])}
        keep = [i for i in ids if i in non_cash and i not in excluded]
        amount = sum(self._gec_convert(balance or 0.0, move.company_currency_id, move.date)
                     for move, balance in moves.items() if move.id in keep)
        return amount, domain + [('move_id', 'in', keep)]

    def _gec_company_ebitda(self, date_from, end):
        level = self.env['gec.margin.level'].search([('code', '=', 'ebitda')], limit=1)
        column = level._column_name() if level else False
        if not column or column not in self.env['gec.margin.report']._fields:
            return False
        [(ebitda,)] = self.env['gec.margin.report']._read_group([
            ('line_type', '=', 'actual'), ('is_primary_plan', '=', True),
            ('date', '>=', date_from), ('date', '<=', end),
            ('company_id', 'in', self.env.companies.ids),
        ], [], [f'{column}:sum'])
        return ebitda or 0.0

    def _gec_cash_conversion(self, date_from, end):
        """Operating cash ÷ EBITDA: does the profit arrive as money?"""
        bank, bank_domain = self._gec_operating_bank(date_from, end)
        payments = self._gec_registered_payments(date_from, end)
        registered = sum(self._gec_convert(p.amount_company_currency_signed, p.company_currency_id, p.date)
                         for p in payments)
        ebitda = self._gec_company_ebitda(date_from, end)
        if ebitda is False or (not bank and not registered):
            return {}
        cash = bank + registered
        return {
            'ratio': cash / ebitda if ebitda > 0 else False,
            'operating_cash': cash, 'bank': bank, 'registered': registered, 'ebitda': ebitda,
            'bank_domain': bank_domain, 'payment_ids': payments.ids,
        }

    def _gec_cash_forecast(self, today):
        """Thirteen weeks: cash now plus what customers owe minus what is owed.
        Invoices and bills fall on their due date (overdue: week one);
        non-bill costs (payroll, accruals) go out at the last thirteen weeks' average."""
        start = today - timedelta(days=today.weekday())
        weeks = [{'start': start + timedelta(weeks=i), 'inflow': 0.0, 'outflow': 0.0}
                 for i in range(self.CASH_WEEKS)]
        Line = self.env['account.move.line']
        company = [('company_id', 'in', self.env.companies.ids)]
        bank = sum(self._gec_convert(balance or 0.0, currency, today) for currency, balance in Line._read_group(
            [('account_id.account_type', '=', 'asset_cash'), ('parent_state', '=', 'posted'),
             ('date', '<=', today), *company], ['company_currency_id'], ['balance:sum']))
        registered = sum(self._gec_convert(p.amount_company_currency_signed, p.company_currency_id, p.date)
                         for p in self._gec_registered_payments(False, today))

        def place(moves, key):
            for move in moves:
                amount = self._gec_open_amount(move, today)
                if not amount:
                    continue
                due = move.invoice_date_due or move.invoice_date
                index = max(0, (due - start).days // 7)
                if index < self.CASH_WEEKS:
                    weeks[index][key] += amount

        receivable = self._gec_open_documents(('out_invoice', 'out_refund'), today)
        payable = self._gec_open_documents(('in_invoice', 'in_refund'), today)
        place(receivable, 'inflow')
        place(payable, 'outflow')

        since = today - timedelta(weeks=self.CASH_WEEKS)
        other_domain = [('parent_state', '=', 'posted'), ('move_id.move_type', '=', 'entry'),
                        ('account_id.account_type', 'in', ('expense', 'expense_other', 'expense_direct_cost')),
                        ('date', '>', since), ('date', '<=', today), *company]
        other = sum(self._gec_convert(balance or 0.0, currency, today) for currency, balance in Line._read_group(
            other_domain, ['company_currency_id'], ['balance:sum'])) / self.CASH_WEEKS
        opening = bank + registered
        if not (opening or receivable or payable or other):
            return {}
        balance, low, low_week = opening, opening, None
        rows = []
        for week in weeks:
            balance += week['inflow'] - week['outflow'] - other
            iso = week['start'].isocalendar()
            label = f"W{iso[1]:02d}"
            rows.append({'label': label, 'start': fields.Date.to_string(week['start']),
                         'inflow': week['inflow'], 'outflow': week['outflow'], 'other': other,
                         'closing': balance})
            if low_week is None or balance < low:
                low, low_week = balance, label
        return {
            'opening': opening, 'bank': bank, 'registered': registered, 'other_weekly': other,
            'weeks': rows, 'low': low, 'low_week': low_week, 'closing': balance,
            'inflow': sum(w['inflow'] for w in rows), 'outflow': sum(w['outflow'] for w in rows),
            'receivable_ids': receivable.ids, 'payable_ids': payable.ids, 'other_domain': other_domain,
        }

    def _gec_forecast_accuracy(self, date_to):
        """The last closed months' forecast against what happened."""
        today = fields.Date.context_today(self)
        last = min(date_to, today).replace(day=1)
        snapshots = self.env['gec.forecast.snapshot'].search([
            ('company_id', 'in', self.env.companies.ids), ('month', '<=', last),
        ])
        months = {}
        for snapshot in snapshots:
            month_end = snapshot.month + relativedelta(months=1) - timedelta(days=1)
            if month_end >= today:
                continue
            row = months.setdefault(snapshot.month, {'forecast': 0.0, 'actual': 0.0, 'basis': set(),
                                                     'reconstructed': False, 'ids': []})
            row['forecast'] += self._gec_convert(snapshot.forecast_revenue, snapshot.currency_id, month_end)
            row['actual'] += self._gec_convert(snapshot.actual_revenue, snapshot.currency_id, month_end)
            row['basis'].add(snapshot.basis)
            row['reconstructed'] |= snapshot.reconstructed
            row['ids'].append(snapshot.id)
        rows = []
        for month in sorted(months, reverse=True)[:self.ACCURACY_MONTHS]:
            row = months[month]
            if row['actual'] <= 0:
                continue
            rows.append({
                'month': fields.Date.to_string(month), 'forecast': row['forecast'], 'actual': row['actual'],
                'error': (row['actual'] - row['forecast']) / row['actual'],
                'basis': ', '.join(sorted(row['basis'])), 'reconstructed': row['reconstructed'],
                'ids': row['ids'],
            })
        if not rows:
            return {}
        return {
            'error': sum(abs(r['error']) for r in rows) / len(rows),
            'within': len([r for r in rows if abs(r['error']) <= 0.15]),
            'months': rows,
            'reconstructed': any(r['reconstructed'] for r in rows),
        }

    def _gec_project_parts(self, ctx, projects, value):
        return [{'label': p.display_name, 'value': value(p),
                 'action': self._rows(p.display_name, [('id', '=', p.id)], model='project.project', views=('form',))}
                for p in projects]

    def _gec_proof_milestones(self, ctx):
        m = ctx['data']['delivery']['milestones']
        projects = self._gec_customer_projects()
        due = [('project_id', 'in', projects.ids), ('deadline', '>=', ctx['date_from']), ('deadline', '<=', ctx['end'])]
        Milestone = 'project.milestone'
        parts = [
            {'label': _("Due in the period"), 'value': str(m['due']), 'count': m['due'],
             'action': self._rows(_("Milestones due"), due, model=Milestone, views=('list', 'form'))},
            {'label': _("Reached on or before the deadline"), 'value': str(m['on_time'])},
            {'label': _("Reached late or not reached"), 'value': str(m['late'])},
            {'label': _("Still open past the deadline"), 'value': str(m['open_overdue']),
             'action': self._rows(_("Overdue milestones"),
                                  due + [('is_reached', '=', False), ('deadline', '<', fields.Date.context_today(self))],
                                  model=Milestone, views=('list', 'form'))},
        ]
        return self._proof(
            _("Milestones on time"), self._pct(m['rate']),
            _("On time = milestones reached on or before their deadline ÷ milestones whose deadline falls in the period."),
            f"{m['on_time']} ÷ {m['due']} = {self._pct(m['rate'])}", parts,
            _("Benchmark: base 60–80%, strong 85–95%."),
            [_("Customer projects only; milestones are Odoo's own (Project ▸ a project ▸ Milestones)."),
             _("A milestone counts when it is marked reached; the date it was reached is what is compared.")],
        )

    def _gec_proof_golive(self, ctx):
        g = ctx['data']['delivery']['golive']
        today = fields.Date.context_today(self)
        projects = self._gec_customer_projects().filtered(
            lambda p: p.gec_golive_planned and ctx['date_from'] <= p.gec_golive_planned <= ctx['end'])
        parts = self._gec_project_parts(ctx, projects, lambda p: _(
            "planned %(planned)s · %(actual)s", planned=p.gec_golive_planned,
            actual=p.gec_golive_actual or _("not live yet")))
        return self._proof(
            _("Go-live slippage"), self._pct(g['rate']),
            _("Slippage = projects that went live after the planned date, or are still not live past it ÷ projects "
              "planned to go live in the period."),
            _("%(s)s ÷ %(d)s = %(r)s; on average %(days).0f days late.", s=g['slipped'], d=g['due'],
              r=self._pct(g['rate']), days=g['avg_days']), parts,
            _("Benchmark: strong below 10–15% of projects."),
            [_("Planned and actual go-live are set on the project's Margin Forecast tab."),
             _("A project not live yet counts as late from the day after its planned date (today is %s).", today)],
        )

    def _gec_proof_completion(self, ctx):
        c = ctx['data']['delivery']['completion']
        projects = self.env['project.project'].browse([r['id'] for r in c['rows']])
        parts = self._gec_project_parts(ctx, projects, lambda p: _(
            "%(h).0f h to go at %(b).1f h/week → %(end)s (planned %(planned)s, %(d)+d days)",
            h=max((p.allocated_hours or 0.0) - (p.effective_hours or 0.0), 0.0), b=p.gec_burn_rate,
            end=p.gec_end_forecast, planned=p.date, d=p.gec_end_delay_days))
        return self._proof(
            _("Projects finishing late"), f"{c['late']} / {c['projects']}",
            _("Forecast end = today + hours to go ÷ hours logged per week over the last 8 weeks. "
              "Late = forecast end after the project's planned end date."),
            _("%(l)s of %(n)s projects forecast to finish after their planned end.", l=c['late'], n=c['projects']),
            parts, None,
            [_("Hours to go = allocated time − hours logged. A project with no hours logged lately has no forecast."),
             _("The planned end date is the project's own End Date.")],
        )

    def _gec_proof_templates(self, ctx):
        t = ctx['data']['delivery']['templates']
        projects = self._gec_customer_projects()
        parts = [
            {'label': _("Built from a template"), 'value': str(t['from_template']), 'count': t['from_template'],
             'action': self._rows(_("From a template"), [('id', 'in', projects.filtered('gec_template_id').ids)],
                                  model='project.project', views=('list', 'form'))},
            {'label': _("All customer projects"), 'value': str(t['projects']), 'count': t['projects'],
             'action': self._rows(_("Customer projects"), [('id', 'in', projects.ids)],
                                  model='project.project', views=('list', 'form'))},
        ]
        return self._proof(
            _("Projects from a template"), self._pct(t['rate']),
            _("Template use = customer projects created from a project template ÷ all customer projects."),
            f"{t['from_template']} ÷ {t['projects']} = {self._pct(t['rate'])}", parts,
            _("Benchmark: increasing — standard templates are a main route from the base to the strong tier."),
            [_("Set automatically when a project is created from a template; set Built From Template by hand on older "
               "projects.")],
        )

    def _gec_proof_dso(self, ctx):
        d = ctx['data']['cash']['dso']
        parts = [
            {'label': _("Receivables open at %s", d['through']), 'value': self._money(ctx, d['receivables']),
             'count': len(d['open_ids']),
             'action': self._rows(_("Open customer invoices"), [('id', 'in', d['open_ids'])],
                                  model='account.move', views=('list', 'form'))},
            {'label': _("Invoiced in the period (taxes included)"), 'value': self._money(ctx, d['invoiced']),
             'count': len(d['invoice_ids']),
             'action': self._rows(_("Customer invoices"), [('id', 'in', d['invoice_ids'])],
                                  model='account.move', views=('list', 'form'))},
        ]
        return self._proof(
            _("Days sales outstanding"), _("%s days", round(d['days'])),
            _("DSO = receivables open at the end of the period ÷ invoiced in the period × days in the period."),
            f"{self._money(ctx, d['receivables'])} ÷ {self._money(ctx, d['invoiced'])} × {d['period_days']} "
            f"= {d['days']:.0f}", parts,
            _("Benchmark: below 60–75 days, depending on the banks' procurement cycles."),
            [_("A payment registered but not yet matched with the bank already counts as paid."),
             _("Company-wide; both sides include taxes, so they compare like with like.")],
        )

    def _gec_proof_conversion(self, ctx):
        c = ctx['data']['cash']['conversion']
        parts = [
            {'label': _("Bank movements from operations"), 'value': self._money(ctx, c['bank']),
             'action': self._rows(_("Operating bank lines"), c['bank_domain'], model='account.move.line',
                                  views=('list',))},
            {'label': _("Registered payments not yet on a bank statement"), 'value': self._money(ctx, c['registered']),
             'count': len(c['payment_ids']),
             'action': self._rows(_("Registered payments"), [('id', 'in', c['payment_ids'])],
                                  model='account.payment', views=('list', 'form'))},
            {'label': _("EBITDA, company-wide"), 'value': self._money(ctx, c['ebitda'])},
        ]
        return self._proof(
            _("Cash conversion"), self._pct(c['ratio']),
            _("Cash conversion = operating cash ÷ EBITDA. Operating cash = bank movements whose other side is not "
              "a loan, capital or fixed asset, plus payments registered and not yet on a bank statement."),
            f"{self._money(ctx, c['operating_cash'])} ÷ {self._money(ctx, c['ebitda'])} = {self._pct(c['ratio'])}",
            parts, _("Benchmark: 80–100% of EBITDA."),
            [_("Transfers between bank accounts are left out."),
             _("Below zero EBITDA the ratio has no meaning and is not shown.") if c['ratio'] is False else None],
        )

    def _gec_proof_cash_forecast(self, ctx):
        f = ctx['data']['cash']['forecast']
        parts = [
            {'label': _("Cash today (bank + payments not yet on a statement)"), 'value': self._money(ctx, f['opening'])},
            {'label': _("Customer invoices due within 13 weeks"), 'value': self._money(ctx, f['inflow']),
             'count': len(f['receivable_ids']),
             'action': self._rows(_("Open customer invoices"), [('id', 'in', f['receivable_ids'])],
                                  model='account.move', views=('list', 'form'))},
            {'label': _("Vendor bills due within 13 weeks"), 'value': self._money(ctx, f['outflow']),
             'count': len(f['payable_ids']),
             'action': self._rows(_("Open vendor bills"), [('id', 'in', f['payable_ids'])],
                                  model='account.move', views=('list', 'form'))},
            {'label': _("Other costs per week (payroll, accruals; last 13 weeks' average)"),
             'value': self._money(ctx, f['other_weekly']),
             'action': self._rows(_("Costs outside vendor bills"), f['other_domain'], model='account.move.line',
                                  views=('list',))},
        ]
        return self._proof(
            _("13-week cash forecast"), self._money(ctx, f['low']),
            _("Each week: cash + customer invoices due − vendor bills due − other costs at their weekly average. "
              "Overdue items fall in the first week."),
            _("%(open)s + %(in)s − %(out)s − 13 × %(other)s = %(close)s at the end; lowest %(low)s in %(week)s.",
              open=self._money(ctx, f['opening']), **{'in': self._money(ctx, f['inflow'])},
              out=self._money(ctx, f['outflow']), other=self._money(ctx, f['other_weekly']),
              close=self._money(ctx, f['closing']), low=self._money(ctx, f['low']), week=f['low_week']),
            parts, None,
            [_("Customers who pay late make this optimistic: it assumes every invoice is paid on its due date."),
             _("Company-wide, looking forward from this week, whatever period is selected.")],
        )

    def _gec_proof_accuracy(self, ctx):
        a = ctx['data']['cash']['accuracy']
        parts = [
            {'label': r['month'][:7] + (" *" if r['reconstructed'] else ""),
             'value': _("forecast %(f)s · actual %(a)s · %(e)s", f=self._money(ctx, r['forecast']),
                        a=self._money(ctx, r['actual']), e=f"{r['error'] * 100:+.1f}%"),
             'action': self._rows(_("Forecast %s", r['month'][:7]), [('id', 'in', r['ids'])],
                                  model='gec.forecast.snapshot', views=('list', 'form'))}
            for r in a['months']
        ]
        return self._proof(
            _("Forecast accuracy"), f"±{a['error'] * 100:.1f}%",
            _("Error per month = (actual − forecast) ÷ actual; the card shows the average size of the error over the "
              "last closed months. The forecast is frozen on the first of each month: the month's budget, or the "
              "run rate of the three months before."),
            _("%(n)s of %(m)s months within ±15%%.", n=a['within'], m=len(a['months'])), parts,
            _("Benchmark: within ±10–15%."),
            [_("* Reconstructed: a month before forecasts were recorded, rebuilt from the data dated before it.")
             if a['reconstructed'] else None],
        )
