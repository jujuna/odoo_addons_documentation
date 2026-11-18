from odoo import models, fields, _
from odoo.tools.translate import LazyTranslate

from odoo.addons.account_reports.utils.report_data_objects import AccountReportLineData

_lt = LazyTranslate(__name__)


class GecMarginStatementReportHandler(models.AbstractModel):
    """Margin ladder as a P&L by analytic plan, five levels folded by default.
    Cost object first (plan > project > rung > GL account > document); Ladder First swaps the first two.
    No grand total: plans and subtotal rungs count the same money again."""
    _name = 'gec.margin.statement.report.handler'
    _inherit = ['account.report.custom.handler']
    _description = 'Analytic Margin Statement Custom Handler'

    def _custom_options_initializer(self, report, options, previous_options):
        super()._custom_options_initializer(report, options, previous_options=previous_options)
        # Shows as a tick in the Options dropdown: declare the key here and extend filterExtraOptionsData in JS.
        options['gec_before_allocation'] = previous_options.get('gec_before_allocation', False)
        options['gec_ladder_first'] = previous_options.get('gec_ladder_first', False)
        sections = self._gec_sections()
        section = previous_options.get('gec_section_by')
        options['gec_section_by'] = section if section in sections else 'plans'
        options['gec_section_choices'] = [
            {'id': key, 'name': data['label']} for key, data in sections.items()
        ]
        self._gec_init_section_filter(report, options, previous_options)
        display = options.setdefault('custom_display_config', {})
        display.setdefault('components', {})['AccountReportFilters'] = 'GecMarginStatementFilters'

    # Sections: analytic plans by default; the others are dimensions every amount already carries
    # (a customer across projects, a project whatever plans it is on).
    FIXED_SECTIONS = {
        'plans': ('plan_id', 'account.analytic.plan', _lt("By Analytic Plans"), _lt("No Analytic Plan")),
        'project': ('project_id', 'project.project', _lt("By Projects"), _lt("No Project")),
        # Partner, not Customer: the field holds the customer on an invoice, the vendor on a bill; most cost has none.
        'partner': ('partner_id', 'res.partner', _lt("By Partner"), _lt("No Partner")),
        'activity': ('activity_id', 'gec.activity', _lt("By Activity"), _lt("No Activity")),
    }
    # Offered only when a plan says it holds them (account.analytic.plan.gec_section_key).
    PLAN_SECTIONS = {
        'product': (_lt("By Products"), _lt("No Product")),
        'department': (_lt("By Department"), _lt("No Department")),
    }

    def _gec_sections(self):
        """Every reading the report can offer, in dropdown order."""
        sections = {
            key: {'field': field, 'model': model, 'label': str(label), 'missing': str(missing)}
            for key, (field, model, label, missing) in self.FIXED_SECTIONS.items()
        }
        plans = self.env['account.analytic.plan'].search(
            [('gec_section_key', '!=', False)],
        )
        for key, (label, missing) in self.PLAN_SECTIONS.items():
            plan = plans.filtered(lambda p, k=key: p.gec_section_key == k)[:1]
            if plan:
                sections[key] = {
                    'field': 'analytic_account_id',
                    'model': 'account.analytic.account',
                    'label': str(label),
                    'missing': str(missing),
                    'plan': plan.id,
                }
        return sections

    def _gec_section(self, options):
        sections = self._gec_sections()
        return sections.get(options.get('gec_section_by')) or sections['plans']

    def _gec_init_section_filter(self, report, options, previous_options):
        """Offer only the sections this period has, and forget the choice when the reading changes
        (a stale project id would hide everything)."""
        options['gec_section_records'] = self._gec_available_sections(options)
        kept = (
            previous_options.get('gec_section_filter') or []
            if previous_options.get('gec_section_filter_for') == options['gec_section_by']
            else []
        )
        available = {record['id'] for record in options['gec_section_records']}
        options['gec_section_filter'] = [id_ for id_ in kept if id_ in available]
        options['gec_section_filter_for'] = options['gec_section_by']

    def _gec_available_sections(self, options):
        """What the report is about to render, as {id, name} — nothing more."""
        date = options.get('date') or {}
        if not date.get('date_from'):
            return []
        section = self._gec_section(options)
        # The same scope the body reads (companies, allocation toggle), or the picker offers sections never shown.
        domain = (
            self._gec_domain(options)
            + self._gec_allocation_domain(options)
            + [('is_component_row', '=', True)]
            + self._gec_section_domain(options)
        )
        groups = self.env['gec.margin.statement.report']._read_group(
            domain, groupby=[section['field']],
        )
        records = self.env[section['model']].browse(
            [group[0].id for group in groups if group[0]]
        )
        return [
            {'id': record.id, 'name': record.display_name}
            for record in records.sorted('display_name')
        ]

    def _gec_section_domain(self, options):
        """Count each amount once unless the sections are the plans.
        The model holds one row per (amount, plan, ladder rung): only a plan section wants that;
        otherwise a project on three plans reports triple revenue."""
        section = self._gec_section(options)
        if section.get('plan'):
            return [('plan_id', '=', section['plan'])]
        if section['field'] == 'plan_id':
            return []
        return [('is_primary_plan', '=', True)]

    @staticmethod
    def _gec_allocation_domain(options):
        """Cost as booked, before any run moved it: what the cost centre actually spent."""
        return [('is_allocation', '=', False)] if options.get('gec_before_allocation') else []

    def _gec_domain(self, column_options):
        """The slice of the statement model one column shows;
        built by hand as ``_get_options_domain`` speaks account.move.line."""
        date = column_options['date']
        domain = [
            ('date', '>=', date['date_from']),
            ('date', '<=', date['date_to']),
        ]
        companies = [company['id'] for company in column_options.get('companies') or []]
        if companies:
            domain.append(('company_id', 'in', companies))
        return domain

    def _gec_read(self, report, options, groupby, extra_domain=None):
        """Aggregate the statement model once per column group, returning ``{(key, ...): {column_group_key: {...}}}``.
        Split by ``line_type`` in the query: revenue/expense columns are actuals only;
        a plain sum would add budget rows to actual."""
        statement = self.env['gec.margin.statement.report']
        results = {}
        for group_key, column_options in report._split_options_per_column_group(options).items():
            domain = (
                self._gec_domain(column_options)
                + self._gec_allocation_domain(options)
                + (extra_domain or [])
            )
            for group in statement._read_group(
                domain,
                groupby=[*groupby, 'line_type'],
                aggregates=['actual_amount:sum', 'budget_amount:sum',
                            'revenue_amount:sum', 'expense_amount:sum'],
            ):
                *keys, line_type, actual, budget, revenue, expense = group
                key = tuple(
                    value.id if hasattr(value, 'id') else value for value in keys
                )
                values = results.setdefault(key, {}).setdefault(group_key, {
                    'actual': 0.0, 'budget': 0.0, 'revenue': 0.0, 'expense': 0.0,
                })
                values['actual'] += actual
                values['budget'] += budget
                if line_type == 'actual':
                    values['revenue'] += revenue
                    values['expense'] += expense

        for by_group in results.values():
            for values in by_group.values():
                # Signed throughout (revenue positive, cost negative): a positive variance is always better than budget.
                values['variance'] = values['actual'] - values['budget']
        return results

    def _gec_columns(self, report, options, values):
        return [
            report._build_column_data(
                (values.get(column['column_group_index']) or {}).get(column['expression_label']),
                column,
                options=options,
            )
            for column in options['columns']
        ]

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        # Component lines only: a plan's figure is its Net; subtotal rungs repeat amounts the component rungs carry.
        section = self._gec_section(options)
        field, model = section['field'], section['model']
        values = self._gec_read(
            report, options, [field],
            [('is_component_row', '=', True)] + self._gec_section_domain(options),
        )
        remainder = self._gec_plan_section_remainder(report, options)
        if remainder:
            values[(False,)] = remainder
        self._gec_add_margin_pct(values)
        if warnings is not None:
            self._gec_add_warnings(report, options, warnings)

        chosen = options.get('gec_section_filter') or []
        records = self._gec_section_records(options, values)
        if chosen:
            records = [record for record in records if record.id in chosen]

        lines = [
            (0, self._gec_section_line(report, options, model, record, values[(record.id,)]))
            for record in records
        ]
        # Amounts that answer this question with nothing (no project, no customer): left out,
        # the report would disagree with the books. Hidden once a pick is made.
        if values.get((False,)) and not chosen:
            lines.append((0, self._gec_section_line(
                report, options, model, None, values[(False,)],
                # A plan-scoped remainder only reconciles to the company; its amounts are not on this plan,
                # so there is nothing to open (By Analytic Plans has the detail).
                unfoldable=not self._gec_section(options).get('plan'),
            )))
        return lines

    def _gec_plan_section_remainder(self, report, options):
        """What a plan-scoped reading leaves out, as one reconciling row.
        By Products keeps only rows exploded onto the product plan, so an amount with no product would drop;
        the leftover is counted once, company-wide."""
        section = self._gec_section(options)
        if not section.get('plan'):
            return None
        column = self.env['account.analytic.plan'].browse(
            section['plan'],
        )._column_name()
        if column not in self.env['gec.margin.statement.report']._fields:
            return None
        values = self._gec_read(report, options, [], [
            ('is_component_row', '=', True),
            ('is_primary_plan', '=', True),
            (column, '=', False),
        ])
        return values.get(())

    def _gec_section_records(self, options, values):
        """The records that head the sections, in the order they should read."""
        section = self._gec_section(options)
        field, model = section['field'], section['model']
        ids = [key[0] for key in values if key[0]]
        if field == 'plan_id':
            project_plan, other_plans = self.env['account.analytic.plan']._get_all_plans()
            return [plan for plan in project_plan | other_plans if plan.id in ids]
        return self.env[model].browse(ids).sorted('display_name')

    def _gec_section_line(self, report, options, model, record, values,
                          unfoldable=True):
        # Its own translatable label: cutting "By " off a translated string only works in English.
        missing = self._gec_section(options)['missing']
        line_id = report._get_generic_line_id(
            model if record else None, record.id if record else None,
            markup=None if record else 'no_section',
        )
        return AccountReportLineData(
            id=line_id,
            name=record.display_name if record else missing,
            level=0,
            css_class='fw-bold',
            columns=self._gec_columns(report, options, values),
            unfoldable=unfoldable,
            unfolded=unfoldable and (
                line_id in options['unfolded_lines'] or options['unfold_all']
            ),
            expand_function=(
                '_report_expand_unfoldable_line_gec_margin_node' if unfoldable
                else None
            ),
        )

    def _gec_add_warnings(self, report, options, warnings):
        """Three findings that show nowhere in the body: money on no margin line, money no cost object was charged,
        and money a cost centre holds that no rule will move."""
        statement = self.env['gec.margin.statement.report']
        column_options = next(
            iter(report._split_options_per_column_group(options).values()), options,
        )
        base = self._gec_domain(column_options)

        [(unclassified,)] = statement._read_group(
            base + [('margin_row_id', '=', False),
                    ('is_primary_plan', '=', True),
                    ('is_component_row', '=', True)],
            [], ['amount:sum'],
        )
        unclassified = unclassified or 0.0
        if not self.env.company.currency_id.is_zero(unclassified):
            warnings['gec_analytic_margin.warning_unclassified'] = {
                'alert_type': 'warning',
                'amount': report._format_value(options, abs(unclassified), 'monetary'),
            }

        date = column_options['date']
        rates = self.env['gec.activity.rate'].search([
            ('date_from', '<=', date['date_to']),
            ('date_to', '>=', date['date_from']),
        ])
        left_behind = sum(rates.mapped('variance_amount'))
        if not self.env.company.currency_id.is_zero(left_behind):
            warnings['gec_analytic_margin.warning_unused_capacity'] = {
                'alert_type': 'info',
                'amount': report._format_value(options, abs(left_behind), 'monetary'),
            }

        self._gec_add_unallocated_warning(report, options, column_options, warnings)

    def _gec_add_unallocated_warning(self, report, options, column_options, warnings):
        """Cost centres holding allocatable cost that no rule reaches;
        the arithmetic lives on gec.allocation.rule, shared with the setup health check."""
        date = column_options['date']
        total, by_account = self.env['gec.allocation.rule']._uncovered_pool(
            date['date_from'], date['date_to'], self.env.companies,
        )
        if not total:
            return

        names = sorted(account.display_name for account in by_account)
        if len(names) > 4:
            listed = ", ".join(names[:4]) + _(" and %s more", len(names) - 4)
        else:
            listed = ", ".join(names)

        warnings['gec_analytic_margin.warning_unallocated_pool'] = {
            'alert_type': 'warning',
            'amount': report._format_value(options, abs(total), 'monetary'),
            'accounts': listed,
        }

    def _custom_unfold_all_batch_data_generator(self, report, options, lines_to_expand_by_function):
        section = self._gec_section(options)
        axis = self._gec_axis(options)
        fields = [section['field'], *axis]
        # The same restriction every expansion applies, or a non-plan reading counts each amount once per plan.
        base = self._gec_section_domain(options)
        return {
            'fields': fields,
            'all': self._gec_read(report, options, fields, base),
            'component': self._gec_read(
                report, options, fields, base + [('is_component_row', '=', True)],
            ),
            'sources': self._gec_source_batch(report, options, fields, base),
        }

    def _gec_batch_for(self, batch, options):
        """The batch, but only if it was built for this arrangement."""
        if not batch:
            return None
        section = self._gec_section(options)
        return batch if batch.get('fields') == [section['field'], *self._gec_axis(options)] else None

    def _gec_chain_key(self, chain, options, axis):
        """The ids already chosen, in the order the batch is keyed by."""
        section = self._gec_section(options)
        key = [chain.get(section['model'], False)]
        for field in axis:
            model = self._AXIS_MODEL[field]
            if model in chain:
                key.append(chain[model])
            elif f'no_{field}' in chain:
                key.append(False)
            else:
                break
        return tuple(key)

    @staticmethod
    def _gec_fold(source, prefix, index):
        """Everything under one line, regrouped by the next dimension down."""
        folded = {}
        for key, by_group in source.items():
            if key[:len(prefix)] != prefix or len(key) <= index:
                continue
            target = folded.setdefault((key[index],), {})
            for group_key, values in by_group.items():
                into = target.setdefault(group_key, {
                    'actual': 0.0, 'budget': 0.0, 'revenue': 0.0, 'expense': 0.0,
                })
                for name in ('actual', 'budget', 'revenue', 'expense'):
                    into[name] += values.get(name) or 0.0
        for by_group in folded.values():
            for values in by_group.values():
                values['variance'] = values['actual'] - values['budget']
        return folded

    def _gec_axis(self, options):
        """The order the report drills in: cost object first by default (a project's P&L is one block),
        or ladder first (the plan's P&L with projects inside each line)."""
        if self._gec_section(options)['field'] != 'plan_id':
            # The section already is the cost object; analytic accounts under a project would restate it.
            return ('margin_row_id', 'general_account_id')
        if options.get('gec_ladder_first'):
            return ('margin_row_id', 'analytic_account_id', 'general_account_id')
        return ('analytic_account_id', 'margin_row_id', 'general_account_id')

    _AXIS_MODEL = {
        'analytic_account_id': 'account.analytic.account',
        'margin_row_id': 'gec.margin.row',
        'general_account_id': 'account.account',
    }

    @staticmethod
    def _gec_line_chain(report, line_dict_id):
        """What has already been picked on the way down: keyed by model for a record,
        by markup for buckets with no record (Unclassified, No GL Account)."""
        chain = {}
        for markup, model, value in report._parse_line_id(line_dict_id):
            if model:
                chain[model] = value
            elif isinstance(markup, str) and markup:
                chain[markup] = True
        return chain

    def _gec_chain_domain(self, chain, axis, options, exclude=()):
        """The filters already chosen on the way down; ``exclude`` drops one,
        so the margin percentage can read the cost object's revenue without the ladder line."""
        section = self._gec_section(options)
        section_field, section_model = section['field'], section['model']
        domain = self._gec_section_domain(options)
        if section_model in chain:
            domain.append((section_field, '=', chain[section_model]))
        elif 'no_section' in chain:
            domain.append((section_field, '=', False))

        by_model = {self._AXIS_MODEL[field]: field for field in axis}
        for model, field in by_model.items():
            if field in exclude:
                continue
            if model in chain:
                domain.append((field, '=', chain[model]))
            elif f'no_{field}' in chain:
                domain.append((field, '=', False))
        return domain

    def _gec_object_revenue(self, report, options, chain, axis, batch=None):
        """Revenue of the cost object this expansion sits inside, the denominator of every percentage below it;
        read without the ladder line and GL account."""
        if batch:
            # Match on the section and the cost object only, wherever they sit in the axis; a prefix
            # would keep the rung too under Ladder First and measure a cost rung against its own zero revenue.
            prefix = self._gec_chain_key(chain, options, axis)
            keep = [
                index for index, field in enumerate(('section', *axis))
                if field in ('section', 'analytic_account_id') and index < len(prefix)
            ]
            totals = {}
            for key, by_group in batch['component'].items():
                if any(key[index] != prefix[index] for index in keep):
                    continue
                for group_key, group_values in by_group.items():
                    totals[group_key] = totals.get(group_key, 0.0) + (group_values.get('revenue') or 0.0)
            return totals
        domain = self._gec_chain_domain(
            chain, axis, options, exclude=('margin_row_id', 'general_account_id'),
        ) + [('is_component_row', '=', True)]
        values = self._gec_read(report, options, [], domain)
        return {
            group_key: group_values.get('revenue') or 0.0
            for group_key, group_values in (values.get(()) or {}).items()
        }

    @staticmethod
    def _gec_add_margin_pct(values, denominators=None):
        """Net as a share of revenue, its own where it has one; a cost rung against the cost object's revenue."""
        for by_group in values.values():
            for group_key, group_values in by_group.items():
                base = group_values.get('revenue') or (denominators or {}).get(group_key)
                group_values['margin_pct'] = (
                    group_values['actual'] / base * 100.0 if base else None
                )

    def _report_expand_unfoldable_line_gec_margin_node(
        self, line_dict_id, groupby, options, unfold_all_batch_data=None, limit_to_load=None,
    ):
        report = self.env['account.report'].browse(options['report_id'])
        chain = self._gec_line_chain(report, line_dict_id)
        axis = self._gec_axis(options)
        depth = sum(
            1 for field in axis
            if self._AXIS_MODEL[field] in chain or f'no_{field}' in chain
        )
        if depth >= len(axis):
            return self._gec_expand_to_sources(
                report, options, line_dict_id, chain, axis, limit_to_load,
                unfold_all_batch_data,
            )

        field = axis[depth]
        batch = self._gec_batch_for(unfold_all_batch_data, options)
        base_domain = self._gec_chain_domain(chain, axis, options)
        # Above the ladder a figure is a Net, so subtotal rungs are kept out, else amounts count again in each subtotal.
        # Exception: the ladder itself, whose rows need the subtotals (Gross Margin, EBITDA).
        component_only = 'gec.margin.row' not in chain and field != 'margin_row_id'
        if component_only:
            base_domain = base_domain + [('is_component_row', '=', True)]

        if batch:
            prefix = self._gec_chain_key(chain, options, axis)
            values = self._gec_fold(
                batch['component' if component_only else 'all'], prefix, len(prefix),
            )
        else:
            values = self._gec_read(report, options, [field], base_domain)
        self._gec_add_margin_pct(
            values, self._gec_object_revenue(report, options, chain, axis, batch),
        )

        builder = getattr(self, f'_gec_{field}_lines')
        lines = builder(report, options, values, line_dict_id, level=2 + depth)
        return lines

    def _gec_node_line(self, report, options, name, model, res_id, values,
                       parent_line_id, level, markup=None, unfoldable=True,
                       caret=None, css_class=''):
        line_id = report._get_generic_line_id(
            model, res_id, markup=markup, parent_line_id=parent_line_id,
        )
        return AccountReportLineData(
            id=line_id,
            name=name,
            parent_id=parent_line_id,
            level=level,
            css_class=css_class,
            columns=self._gec_columns(report, options, values),
            unfoldable=unfoldable,
            unfolded=line_id in options['unfolded_lines'] or options['unfold_all'],
            expand_function=(
                '_report_expand_unfoldable_line_gec_margin_node' if unfoldable else None
            ),
            caret_options=caret,
        )

    def _gec_analytic_account_id_lines(self, report, options, values, parent_line_id, level):
        accounts = self.env['account.analytic.account'].browse(
            [key[0] for key in values if key[0]]
        ).sorted('display_name')
        return [
            self._gec_node_line(
                report, options, account.display_name,
                'account.analytic.account', account.id, values[(account.id,)],
                parent_line_id, level, caret='account.analytic.account',
            )
            for account in accounts
        ]

    def _gec_margin_row_id_lines(self, report, options, values, parent_line_id, level):
        rows = self.env['gec.margin.row'].browse(
            [key[0] for key in values if key[0]]
        ).sorted(lambda row: (row.sequence, row.id))
        lines = [
            self._gec_node_line(
                report, options, row.name, 'gec.margin.row', row.id,
                values[(row.id,)], parent_line_id, level,
                # A subtotal repeats amounts already printed above it, so it is not unfoldable.
                unfoldable=row.row_type != 'level',
                css_class='fw-bold' if row.row_type == 'level' else '',
            )
            for row in rows
        ]
        # Amounts on an account no component claims are part of Net; hiding them would make the header disagree.
        if values.get((False,)):
            lines.append(self._gec_node_line(
                report, options, _("Unclassified"), None, None,
                values[(False,)], parent_line_id, level,
                markup='no_margin_row_id',
            ))
        return lines

    def _gec_general_account_id_lines(self, report, options, values, parent_line_id, level):
        accounts = self.env['account.account'].browse(
            [key[0] for key in values if key[0]]
        ).sorted(lambda account: account.code or '')
        lines = [
            self._gec_node_line(
                report, options, account.display_name,
                'account.account', account.id, values[(account.id,)],
                parent_line_id, level, caret='account.account',
            )
            for account in accounts
        ]
        if values.get((False,)):
            lines.append(self._gec_node_line(
                report, options, _("No GL Account"), None, None,
                values[(False,)], parent_line_id, level,
                markup='no_general_account_id',
            ))
        return lines

    def _gec_expand_to_sources(self, report, options, line_dict_id, chain, axis, limit_to_load,
                               unfold_all_batch_data=None):
        batch = self._gec_batch_for(unfold_all_batch_data, options)
        sources = self._gec_sources(
            report, options, self._gec_chain_domain(chain, axis, options),
            batch=batch['sources'] if batch else None,
            prefix=self._gec_chain_key(chain, options, axis) if batch else None,
        )
        # Paged in Python: the domain is already one cell, so one aggregate beats re-querying per page.
        # Odoo 20 returns ``limit_to_load`` lines plus one "N more" line; clicking it calls again with no limit.
        window = sources[:limit_to_load] if limit_to_load else sources
        lines = [
            self._gec_source_line(report, options, source, line_dict_id)
            for source in window
        ]
        rest = sources[len(window):]
        if rest:
            totals = {}
            for source in rest:
                for group_key, group_values in source['values'].items():
                    bucket = totals.setdefault(group_key, {})
                    for label, value in group_values.items():
                        # A share of revenue does not add up across documents.
                        if label != 'margin_pct' and isinstance(value, (int, float)):
                            bucket[label] = bucket.get(label, 0.0) + value
            lines.append(AccountReportLineData(
                id=report._get_generic_line_id(
                    None, None, parent_line_id=line_dict_id, markup='load_more',
                ),
                name=_("%s more", len(rest)),
                level=5,
                parent_id=line_dict_id,
                expand_function='_report_expand_unfoldable_line_gec_margin_node',
                columns=self._gec_columns(report, options, totals),
                unfoldable=False,
                unfolded=False,
            ))
        return lines

    def _gec_source_batch(self, report, options, fields, base_domain=()):
        """Every document in the report keyed by its cell: the same three passes as one cell,
        grouped by the whole chain, so unfold-all costs three queries."""
        batch = {}
        for prefix, key, source in self._gec_iter_sources(
            report, options, list(base_domain), fields,
        ):
            batch.setdefault(prefix, {})[key] = source
        return batch

    def _gec_sources(self, report, options, base_domain, batch=None, prefix=None):
        """What caused one cell, newest first."""
        if batch is not None:
            return self._gec_sort_sources(batch.get(prefix, {}).values())
        sources = {}
        for _prefix, key, source in self._gec_iter_sources(report, options, base_domain, []):
            sources[key] = source
        return self._gec_sort_sources(sources.values())

    @staticmethod
    def _gec_sort_sources(sources):
        # An allocation writes a charge on the target and a credit on the source, both with the activity;
        # on the source plan they cancel and would print an empty row.
        return sorted(
            (
                source for source in sources
                if any(
                    values.get('actual') or values.get('budget')
                    for values in source['values'].values()
                )
            ),
            key=lambda source: (source['date'] or fields.Date.today(), source['name']),
            reverse=True,
        )

    def _gec_iter_sources(self, report, options, base_domain, prefix_fields):
        """What caused one cell, newest first, in three passes.
        Items of one invoice collapse onto the move; an activity is one cause of all its ABC charges;
        anything else is its own cause."""
        statement = self.env['gec.margin.statement.report']
        sources = {}
        rate_cache = {}

        def collect(prefix, key, name, model, res_id, date, group_key, actual, budget):
            source = sources.setdefault((prefix, key), {
                'name': name, 'model': model, 'res_id': res_id,
                'date': date, 'values': {},
            })
            if date and (not source['date'] or date > source['date']):
                source['date'] = date
            source['values'][group_key] = {
                # Blanks, not zeros: a budget has no actual and an invoice no budget, and 0.00 reads as a figure.
                'actual': actual or None,
                'budget': budget or None,
                # Blank on purpose: a budget is not attached to the invoice that spent against it,
                # so a variance only means something from the analytic account up.
                'variance': None,
            }

        def unpack(group, tail):
            values = list(group)
            head = values[:len(prefix_fields)]
            return (
                tuple(v.id if hasattr(v, 'id') else v for v in head),
                *values[len(prefix_fields):],
            )

        for group_key, column_options in report._split_options_per_column_group(options).items():
            domain = (
                self._gec_domain(column_options)
                + self._gec_allocation_domain(options)
                + base_domain
            )

            for group in statement._read_group(
                domain + [('move_id', '!=', False)],
                groupby=[*prefix_fields, 'move_id'],
                aggregates=['actual_amount:sum', 'budget_amount:sum', 'date:max'],
            ):
                prefix, move, actual, budget, date = unpack(group, 4)
                collect(prefix, ('account.move', move.id), move.display_name,
                        'account.move', move.id, date, group_key, actual, budget)

            for group in statement._read_group(
                domain + [('move_id', '=', False), ('activity_id', '!=', False)],
                groupby=[*prefix_fields, 'activity_id'],
                aggregates=['actual_amount:sum', 'budget_amount:sum', 'date:max'],
            ):
                prefix, activity, actual, budget, date = unpack(group, 4)
                # Driver units derived as charge / rate: the activity measures hours per analytic account,
                # but this line is one GL account's slice, so the account's total would not match the money beside it.
                driver = self._gec_charged_quantity(activity, column_options, actual, rate_cache)
                collect(prefix, ('gec.activity', activity.id),
                        self._gec_activity_name(activity, column_options, driver, rate_cache),
                        'gec.activity', activity.id, date, group_key, actual, budget)

            for group in statement._read_group(
                domain + [('move_id', '=', False), ('activity_id', '=', False)],
                groupby=[*prefix_fields, 'analytic_line_id', 'budget_analytic_id'],
                aggregates=['actual_amount:sum', 'budget_amount:sum', 'date:max'],
            ):
                prefix, analytic_line, budget, actual, budget_amount, date = unpack(group, 5)
                if analytic_line:
                    collect(prefix, ('account.analytic.line', analytic_line.id),
                            analytic_line.name or analytic_line.display_name,
                            'account.analytic.line', analytic_line.id,
                            date, group_key, actual, budget_amount)
                elif budget:
                    collect(prefix, ('budget.analytic', budget.id), budget.display_name,
                            'budget.analytic', budget.id,
                            date, group_key, actual, budget_amount)

        for (prefix, key), source in sources.items():
            yield prefix, key, source

    def _gec_activity_rate(self, activity, column_options, cache=None):
        """The rate this period was charged at, if there is only one;
        a period spanning two runs has two rates, so none is printed and the Activity Rates caret shows both."""
        date = column_options['date']
        key = (activity.id, date['date_from'], date['date_to'])
        if cache is not None and key in cache:
            return cache[key]
        rates = self.env['gec.activity.rate'].search([
            ('activity_id', '=', activity.id),
            ('date_from', '<=', date['date_to']),
            ('date_to', '>=', date['date_from']),
        ])
        rate = rates if len(rates) == 1 else self.env['gec.activity.rate']
        if cache is not None:
            cache[key] = rate
        return rate

    def _gec_activity_name(self, activity, column_options, quantity=None, cache=None):
        """Name the cause and print its arithmetic (driver units x rate per unit),
        so an allocated figure can be checked where it lands."""
        rate = self._gec_activity_rate(activity, column_options, cache)
        if not rate or not rate.rate:
            return activity.name
        unit = rate.driver_label or activity.driver_label
        if not quantity:
            return _(
                "%(activity)s — %(rate)s per %(unit)s",
                activity=activity.name, rate=f"{rate.rate:,.2f}", unit=unit,
            )
        return _(
            "%(activity)s — %(quantity)s × %(rate)s per %(unit)s",
            activity=activity.name,
            quantity=f"{quantity:,.1f}",
            rate=f"{rate.rate:,.2f}",
            unit=unit,
        )

    def _gec_charged_quantity(self, activity, column_options, charged, cache=None):
        """Driver units behind one charge: the money divided by the rate."""
        rate = self._gec_activity_rate(activity, column_options, cache)
        if not rate or not rate.rate or not charged:
            return None
        return abs(charged) / rate.rate

    def _gec_source_line(self, report, options, source, parent_line_id):
        return AccountReportLineData(
            id=report._get_generic_line_id(
                source['model'], source['res_id'], parent_line_id=parent_line_id,
            ),
            name=source['name'],
            parent_id=parent_line_id,
            level=5,
            columns=self._gec_columns(report, options, source['values']),
            unfoldable=False,
            caret_options=source['model'],
            custom={'date': source['date']},
        )

    def _caret_options_initializer(self):
        # account.move is already in the defaults; the rest are the models the report can bottom out on.
        return {
            **self.env['account.report']._caret_options_initializer_default(),
            'account.analytic.account': [
                {'name': _("Analytic Account"), 'action': 'caret_option_open_record_form'},
            ],
            'account.analytic.line': [
                {'name': _("View Analytic Item"), 'action': 'caret_option_open_record_form'},
            ],
            'budget.analytic': [
                {'name': _("View Budget"), 'action': 'caret_option_open_record_form'},
            ],
            'gec.activity': [
                {'name': _("View Activity"), 'action': 'caret_option_open_record_form'},
                {'name': _("Activity Rates"), 'action': 'caret_option_open_gec_activity_rates'},
            ],
        }

    def caret_option_open_gec_activity_rates(self, options, params):
        report = self.env['account.report'].browse(options['report_id'])
        _model, activity_id = report._get_model_info_from_id(params['line_id'])
        return {
            'type': 'ir.actions.act_window',
            'name': _("Activity Rates"),
            'res_model': 'gec.activity.rate',
            'view_mode': 'list,form',
            'domain': [('activity_id', '=', activity_id)],
            'context': self.env.context,
        }
