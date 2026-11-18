from odoo import Command
from odoo.tests.common import TransactionCase


class GecMarginCommon(TransactionCase):
    """A two-plan cost model small enough to check by hand, built from analytic lines rather than posted invoices."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Plan = cls.env['account.analytic.plan']
        Account = cls.env['account.analytic.account']

        cls.source_plan = Plan.create({'name': 'T Direction'})
        cls.target_plan = Plan.create({'name': 'T Business Line'})
        cls.source_col = cls.source_plan._column_name()
        cls.target_col = cls.target_plan._column_name()

        cls.service_plan = Plan.create({'name': 'T Services'})
        cls.service_col = cls.service_plan._column_name()
        cls.it = Account.create({'name': 'T IT', 'plan_id': cls.service_plan.id})

        cls.dir_a = Account.create({'name': 'T DIR-A', 'plan_id': cls.source_plan.id})
        cls.bl_a = Account.create({'name': 'T BL-A', 'plan_id': cls.target_plan.id})
        cls.bl_b = Account.create({'name': 'T BL-B', 'plan_id': cls.target_plan.id})

        cls.overhead = cls.env['gec.margin.component'].create({
            'name': 'T Overhead', 'code': 't_overhead',
            'nature': 'cost', 'allocatable': True,
        })
        cls.direct = cls.env['gec.margin.component'].create({
            'name': 'T Direct', 'code': 't_direct',
            'nature': 'cost', 'allocatable': False,
        })
        cls.gl_pool = cls.env['account.account'].create({
            'name': 'T Cloud', 'code': 'TST900', 'account_type': 'expense',
            'company_ids': [Command.set(cls.company.ids)],
            'gec_margin_component_id': cls.overhead.id,
        })

        # Park existing rules: a run with no rules means "every active rule",
        # which the double-allocation guard would refuse.
        cls.preexisting_rules = cls.env['gec.allocation.rule'].search([])

        cls.date = '2026-06-15'
        cls.date_from = '2026-06-01'
        cls.date_to = '2026-06-30'

    @classmethod
    def _line(cls, amount=0.0, quantity=0.0, source=None, target=None, gl=None,
              service=None, name='T'):
        vals = {
            'name': name,
            'date': cls.date,
            'amount': amount,
            'unit_amount': quantity,
            'company_id': cls.company.id,
        }
        if service:
            vals[cls.service_col] = service.id
        if source:
            vals[cls.source_col] = source.id
        if target:
            vals[cls.target_col] = target.id
        if gl:
            vals['general_account_id'] = gl.id
        return cls.env['account.analytic.line'].create(vals)

    @classmethod
    def _pool(cls, amount=-40000.0):
        """The shared cost, sitting on the source plan and nowhere else."""
        return cls._line(amount=amount, quantity=1.0, source=cls.dir_a,
                         gl=cls.gl_pool, name='T pool')

    @classmethod
    def _drivers(cls, a=70.0, b=30.0):
        """Timesheet-like lines: hours against a target account, no GL account."""
        return (cls._line(quantity=a, target=cls.bl_a, name='T hours A')
                | cls._line(quantity=b, target=cls.bl_b, name='T hours B'))

    @classmethod
    def _activity(cls, **overrides):
        vals = {
            'name': 'T Development',
            'company_id': cls.company.id,
            'driver_label': 'hour',
            'source_model_id': cls.env['ir.model']._get_id('account.analytic.line'),
            'source_date_field': 'date',
            'source_analytic_path': cls.target_col,
            'source_domain': "[('general_account_id', '=', False)]",
            'measure': 'field',
            'measure_field': 'unit_amount',
            'rate_mode': 'actual',
        }
        vals.update(overrides)
        return cls.env['gec.activity'].create(vals)

    @classmethod
    def _rule(cls, activity=None, **overrides):
        vals = {
            'name': 'T rule',
            'company_id': cls.company.id,
            'source_plan_id': cls.source_plan.id,
            'source_account_ids': [Command.set(cls.dir_a.ids)],
            'source_gl_account_ids': [Command.set(cls.gl_pool.ids)],
            'target_plan_id': cls.target_plan.id,
        }
        if activity:
            vals.update({'driver': 'activity', 'activity_id': activity.id,
                         'share_mode': 'declared', 'resource_share': 100.0})
        vals.update(overrides)
        return cls.env['gec.allocation.rule'].create(vals)

    @classmethod
    def _run(cls, rules=None):
        """A run pinned to the rules this test created."""
        if rules is None:
            rules = cls.env['gec.allocation.rule'].search([]) - cls.preexisting_rules
        return cls.env['gec.allocation.run'].create({
            'name': 'T run',
            'date_from': cls.date_from,
            'date_to': cls.date_to,
            'company_id': cls.company.id,
            'rule_ids': [Command.set(rules.ids)],
        })
