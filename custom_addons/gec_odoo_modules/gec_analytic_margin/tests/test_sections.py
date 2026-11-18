from odoo import Command
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPlanScopedSections(TransactionCase):
    """A reading must account for amounts it cannot attribute.
    By Products keeps only rows on the product plan,
    so an amount with no product would drop and the reading fall short of the company total."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Plan = cls.env['account.analytic.plan']
        Account = cls.env['account.analytic.account']

        cls.project_plan, _others = Plan._get_all_plans()
        # One reading, one plan — release whatever holds it in this database.
        Plan.search([('gec_section_key', '=', 'product')]).gec_section_key = False
        cls.prod_plan = Plan.create({'name': 'S Product',
                                     'gec_section_key': 'product'})
        cls.cc_plan = Plan.create({'name': 'S Cost Center'})
        Plan.search([])._sync_all_plan_column()
        cls.env.transaction.will_change_registry()
        cls.PCOL = cls.prod_plan._column_name()
        cls.CCOL = cls.cc_plan._column_name()

        cls.product = Account.create({'name': 'S PROD-A', 'plan_id': cls.prod_plan.id})
        cls.centre = Account.create({'name': 'S CC-ADMIN', 'plan_id': cls.cc_plan.id})

        Component = cls.env['gec.margin.component']
        cls.gl_revenue = cls._gl('S Revenue', 'SEC400', 'income', 'revenue')
        cls.gl_overhead = cls._gl('S Office', 'SEC900', 'expense', 'overhead')

        cls._line('S sale', 100000.0, {cls.PCOL: cls.product.id}, cls.gl_revenue)
        cls._line('S office', -30000.0, {cls.CCOL: cls.centre.id}, cls.gl_overhead)

        cls.report = cls.env.ref(
            'gec_analytic_margin.gec_margin_statement_report'
        )

    @classmethod
    def _gl(cls, name, code, account_type, component_code):
        component = cls.env['gec.margin.component'].search(
            [('code', '=', component_code)], limit=1)
        return cls.env['account.account'].create({
            'name': name, 'code': code, 'account_type': account_type,
            'company_ids': [Command.set(cls.company.ids)],
            'gec_margin_component_id': component.id})

    @classmethod
    def _line(cls, name, amount, tags, general):
        vals = {'name': name, 'date': '2026-06-15', 'amount': amount,
                'company_id': cls.company.id, 'general_account_id': general.id}
        vals.update(tags)
        return cls.env['account.analytic.line'].create(vals)

    def _sections(self, section_by):
        options = self.report.get_options({
            'selected_variant_id': self.report.id,
            'sections_source_id': self.report.id,
            'gec_section_by': section_by,
            'date': {'date_from': '2026-06-01', 'date_to': '2026-06-30',
                     'mode': 'range', 'filter': 'custom'},
        })
        lines = self.report._get_lines(options)
        return {line.name: line for line in lines if line.level == 0}

    @staticmethod
    def _value(line, label='actual'):
        for column in line.columns:
            if column.expression_label == label:
                return column.no_format
        return None

    def test_by_products_accounts_for_what_it_cannot_attribute(self):
        """Measured as a movement, not as an absolute: the remainder depends on what else the database holds."""
        sections = self._sections('product')
        self.assertIn('S PROD-A', sections)
        self.assertAlmostEqual(self._value(sections['S PROD-A']), 100000.0, places=2)
        self.assertIn(
            'No Product', sections,
            "the product reading dropped every amount with no product and said "
            "nothing about it",
        )
        before = self._value(sections['No Product'])

        self._line('S more office', -5000.0, {self.CCOL: self.centre.id},
                   self.gl_overhead)
        after = self._value(self._sections('product')['No Product'])
        self.assertAlmostEqual(
            after - before, -5000.0, places=2,
            msg="cost with no product did not reach the remainder",
        )

    def test_the_product_reading_reconciles_to_the_company(self):
        """The property that makes the remainder worth having."""
        sections = self._sections('product')
        total = sum(self._value(line) or 0.0 for line in sections.values())
        company = self.env['account.analytic.line']._read_group(
            [('date', '>=', '2026-06-01'), ('date', '<=', '2026-06-30'),
             ('company_id', '=', self.company.id)],
            [], ['amount:sum'],
        )[0][0]
        self.assertAlmostEqual(total, company, places=2)

    def test_the_remainder_does_not_pretend_to_be_openable(self):
        """There is nothing under it — by definition it is not on this plan."""
        sections = self._sections('product')
        self.assertFalse(sections['No Product'].unfoldable)
        self.assertFalse(sections['No Product'].expand_function)

    def test_by_projects_still_groups_its_own_remainder_under_a_real_fold(self):
        """A project is a field on every row, so that reading has no hole and keeps its openable No Project line."""
        sections = self._sections('project')
        missing = sections.get('No Project')
        self.assertTrue(missing, "the project reading lost its remainder line")
        self.assertTrue(missing.unfoldable)
