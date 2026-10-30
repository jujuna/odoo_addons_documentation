# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date

from lxml import etree
from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import TestPayrollCommon


@tagged('post_install_l10n', 'post_install', '-at_install', 'payroll_281_mapping')
class TestL10nBe281Mapping(TestPayrollCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sheet = cls.env['l10n_be.281_45']
        cls.rule_ip = cls.env.ref('l10n_be_hr_payroll.cp200_employees_salary_ip')
        cls.rule_ip_ded = cls.env.ref('l10n_be_hr_payroll.cp200_employees_salary_ip_deduction')

        cls.employee_a.write({
            'niss': '03062411377',
            'job_title': 'Independent Consultant',
            'private_street': 'Rue du Paradis',
            'private_zip': '6870',
            'private_city': 'Eghezee',
            'l10n_be_legal_first_name': 'Employee',
            'l10n_be_legal_last_name': 'A',
        })

    def _get_mapping_vals(self, **kwargs):
        kwargs.setdefault('declaration_code', '281.45')
        kwargs.setdefault('evaluation_type', 'salary_rule')
        kwargs.setdefault('date_from', date(2026, 1, 1))
        kwargs.setdefault('tag', 'test_tag')
        if kwargs['evaluation_type'] == 'salary_rule' and 'salary_rule_ids' not in kwargs:
            kwargs['salary_rule_ids'] = [Command.set(self.rule_ip.ids)]
        return kwargs

    def _new_mapping(self, **kwargs):
        return self.env['l10n.be.281.mapping'].new(self._get_mapping_vals(**kwargs))

    def _create_mapping(self, **kwargs):
        return self.env['l10n.be.281.mapping'].create(self._get_mapping_vals(**kwargs))

    def _create_salary_rule(self, code, struct_ref='l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary', **kwargs):
        kwargs.setdefault('sequence', 2399)
        kwargs.setdefault('amount_fix', 0)
        return self.env['hr.salary.rule'].create({
            'name': f'Test Rule {code}',
            'code': code,
            'struct_ids': [(4, self.env.ref(struct_ref).id)],
            'country_id': self.env.ref('base.be').id,
            'condition_select': 'none',
            'amount_select': 'fix',
            **kwargs,
        })

    def _create_declaration(self, **kwargs):
        return self.env['l10n_be.281_xx'].with_company(self.belgian_company).create({
            'year': '2026',
            'company_id': self.belgian_company.id,
            **kwargs,
        })

    def _create_nested_control_rows(self):
        leaf_a = self._create_mapping(tag='leaf_a', evaluation_type='python', evaluation_value='result = 2')
        leaf_b = self._create_mapping(tag='leaf_b', evaluation_type='python', evaluation_value='result = 3')
        inner_control = self._create_mapping(
            tag='inner_control', evaluation_type='control',
            control_mapping_ids=[Command.set((leaf_a + leaf_b).ids)],
        )
        outer_control = self._create_mapping(
            tag='outer_control', evaluation_type='control',
            control_mapping_ids=[Command.set((leaf_a + leaf_b + inner_control).ids)],
        )
        return leaf_a + leaf_b + inner_control + outer_control

    def test_evaluate_salary_rule_multiple_codes_are_summed(self):
        row = self._new_mapping(
            tag='t', evaluation_type='salary_rule',
            salary_rule_ids=[Command.set((self.rule_ip + self.rule_ip_ded).ids)],
        )
        self.assertEqual(row._evaluate(self.sheet._get_localdict({'IP': 100, 'IP.DED': -20}), {}), 80)

    def test_evaluate_python_sets_result(self):
        row = self._new_mapping(
            tag='t', evaluation_type='python', evaluation_value="result = mapped_total['IP'] * 2",
        )
        self.assertEqual(row._evaluate(self.sheet._get_localdict({'IP': 10.0}), {}), 20.0)

    def test_evaluate_python_receives_all_codes(self):
        row = self._new_mapping(
            tag='t', evaluation_type='python', evaluation_value="result = sum(mapped_total.values())",
        )
        self.assertEqual(row._evaluate(self.sheet._get_localdict({'IP': 10.0, 'IP.DED': -2.0}), {}), 8.0)

    def test_evaluate_python_monetary_row_is_eurocent_converted(self):
        row = self._new_mapping(
            tag='t', evaluation_type='python', is_monetary=True,
            evaluation_value="result = mapped_total['IP'] / 2.0",
        ).with_context(round_281=True)
        self.assertEqual(
            row._evaluate(self.sheet.with_context(round_281=True)._get_localdict({'IP': 10.0}), {}), 500,
        )

    def test_eurocent_amounts_are_rounded(self):
        # 0.29 * 100 is 28.999..., it must not be truncated to 28
        self.assertEqual(self.env['l10n.be.281.mapping'].with_context(round_281=True)._to_eurocent(0.29), 29)
        self.assertEqual(self.env['l10n_be.274_xx']._to_eurocent(0.29), '29')
        row = self._new_mapping(
            tag='t', evaluation_type='salary_rule', salary_rule_ids=[Command.set(self.rule_ip.ids)],
        ).with_context(round_281=True)
        self.assertEqual(row._evaluate(self.sheet.with_context(round_281=True)._get_localdict({'IP': 1.15}), {}), 115)

    def test_evaluate_python_missing_result_raises_user_error(self):
        row = self._new_mapping(tag='t', evaluation_type='python', evaluation_value="x = 1")
        with self.assertRaises(UserError):
            row._evaluate(self.sheet._get_localdict({}), {})

    def test_evaluate_python_bad_expression_raises_user_error(self):
        row = self._new_mapping(tag='t', evaluation_type='python', evaluation_value="result = 1 / 0")
        with self.assertRaises(UserError):
            row._evaluate(self.sheet._get_localdict({}), {})

    def test_evaluate_control_sums_computed_tags(self):
        target_a = self._create_mapping(tag='control_target_a', evaluation_type='python', evaluation_value='result = 1')
        target_b = self._create_mapping(tag='control_target_b', evaluation_type='python', evaluation_value='result = 1')
        row = self._new_mapping(
            tag='total', evaluation_type='control',
            control_mapping_ids=[Command.set((target_a + target_b).ids)],
        )
        self.assertEqual(
            row._evaluate(self.sheet._get_localdict({}), {'control_target_a': 10, 'control_target_b': 5}), 15,
        )

    def test_evaluate_control_unknown_tag_raises_user_error(self):
        known_target = self._create_mapping(tag='known_control_target', evaluation_type='python', evaluation_value='result = 1')
        not_yet_computed_target = self._create_mapping(tag='not_yet_computed_target', evaluation_type='python', evaluation_value='result = 1')
        row = self._new_mapping(
            tag='total', evaluation_type='control',
            control_mapping_ids=[Command.set((known_target + not_yet_computed_target).ids)],
        )
        with self.assertRaises(UserError):
            row._evaluate(self.sheet._get_localdict({}), {'known_control_target': 10})

    def test_search_for_tag_raises_when_tag_missing(self):
        with self.assertRaises(UserError):
            self.env['l10n.be.281.mapping']._search_for_tag('281.45', 'nonexistent_tag', 2026)

    def test_get_codes_for_tag_returns_empty_list_when_tag_missing(self):
        codes = self.env['l10n.be.281.mapping']._get_codes_for_tag('281.45', 'nonexistent_tag', 2026)
        self.assertEqual(codes, [])

    def test_mapping_lookup_rejects_ambiguous_matches(self):
        self._create_mapping(tag='dup_tag')
        duplicate = self._create_mapping(tag='dup_tag_tmp')
        self.env.cr.execute("UPDATE l10n_be_281_mapping SET tag = %s WHERE id = %s", ('dup_tag', duplicate.id))
        duplicate.invalidate_recordset(['tag'])
        with self.assertRaises(UserError):
            self.env['l10n.be.281.mapping']._get_codes_for_tag('281.45', 'dup_tag', 2026)
        with self.assertRaises(UserError):
            self.env['l10n.be.281.mapping']._search_for_tag('281.45', 'dup_tag', 2026)

    def test_mapping_rejects_invalid_date_range(self):
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            self._create_mapping(date_from=date(2026, 1, 1), date_to=date(2025, 12, 31))

    def test_mapping_requires_complete_calendar_years(self):
        for values in (
            {'date_from': date(2026, 2, 1)},
            {'date_to': date(2026, 12, 30)},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                self._create_mapping(**values)

    def test_mapping_date_range_selection_and_open_end(self):
        Mapping = self.env['l10n.be.281.mapping']
        for declaration_code in ('281.45', '273S'):
            with self.subTest(declaration_code=declaration_code):
                previous = self._create_mapping(
                    tag='versioned_tag', declaration_code=declaration_code,
                    date_from=date(2020, 1, 1), date_to=date(2025, 12, 31),
                )
                current = self._create_mapping(
                    tag='versioned_tag', declaration_code=declaration_code,
                    date_to=date(2026, 12, 31), salary_rule_ids=[Command.set(self.rule_ip_ded.ids)],
                )
                self.assertFalse(Mapping._get_codes_for_tag(declaration_code, 'versioned_tag', 2019))
                self.assertEqual(Mapping._search_for_tag(declaration_code, 'versioned_tag', 2025), previous)
                self.assertEqual(Mapping._search_for_tag(declaration_code, 'versioned_tag', '2026'), current)
                self.assertFalse(Mapping._get_codes_for_tag(declaration_code, 'versioned_tag', 2027))
                current.date_to = False
                self.assertFalse(current.date_to)
                self.assertEqual(Mapping._get_codes_for_tag(declaration_code, 'versioned_tag', 2030), ['IP.DED'])
                if declaration_code == '281.45':
                    sheet = self.sheet.new()
                    for year, expected in ((2025, previous), (2026, current), (2030, current)):
                        self.assertEqual(
                            sheet._get_mapping_lines(year).filtered(lambda mapping: mapping.tag == 'versioned_tag'),
                            expected,
                        )

    def test_mapping_salary_rule_requires_salary_rule_ids(self):
        with self.assertRaises(ValidationError):
            self._create_mapping(salary_rule_ids=[Command.clear()])

    def test_mapping_salary_rule_rejects_control_or_python_fields(self):
        leaf_target = self._create_mapping(tag='leaf_target_a', evaluation_type='python', evaluation_value='result = 1')
        with self.assertRaises(ValidationError):
            self._create_mapping(control_mapping_ids=[Command.set(leaf_target.ids)])
        with self.assertRaises(ValidationError):
            self._create_mapping(evaluation_value='result = 1')

    def test_mapping_control_requires_control_mapping_ids(self):
        with self.assertRaises(ValidationError):
            self._create_mapping(evaluation_type='control')

    def test_mapping_control_rejects_salary_rule_or_python_fields(self):
        leaf_target = self._create_mapping(tag='leaf_target_b', evaluation_type='python', evaluation_value='result = 1')
        with self.assertRaises(ValidationError):
            self._create_mapping(
                evaluation_type='control', control_mapping_ids=[Command.set(leaf_target.ids)],
                salary_rule_ids=[Command.set(self.rule_ip.ids)],
            )
        with self.assertRaises(ValidationError):
            self._create_mapping(
                evaluation_type='control', control_mapping_ids=[Command.set(leaf_target.ids)],
                evaluation_value='result = 1',
            )

    def test_mapping_python_requires_evaluation_value(self):
        with self.assertRaises(ValidationError):
            self._create_mapping(evaluation_type='python', salary_rule_ids=[], evaluation_value=False)

    def test_mapping_python_rejects_control_mapping_ids(self):
        leaf_target = self._create_mapping(tag='leaf_target_c', evaluation_type='python', evaluation_value='result = 1')
        with self.assertRaises(ValidationError):
            self._create_mapping(
                evaluation_type='python', evaluation_value='result = 1',
                control_mapping_ids=[Command.set(leaf_target.ids)],
            )

    def test_mapping_salary_rule_rejects_non_belgian_rule(self):
        foreign_rule = self._create_salary_rule(
            'FOREIGN_CODE', struct_ref='l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary',
            country_id=self.env.ref('base.us').id,
        )
        mapping = self._new_mapping(salary_rule_ids=[Command.set(self.rule_ip.ids)])
        mapping.salary_rule_ids = foreign_rule
        with self.assertRaises(ValidationError):
            mapping._check_salary_rule_country()

    def test_mapping_python_unknown_code_is_checked_at_evaluation(self):
        row = self._create_mapping(
            evaluation_type='python', evaluation_value="result = mapped_total['UNKNOWN_CODE']",
        )
        with self.assertRaisesRegex(UserError, 'UNKNOWN_CODE'):
            row._evaluate(self.sheet._get_localdict({'IP': 10.0}), {})
        row.evaluation_value = "result = mapped_total.get('UNKNOWN_CODE', 0)"
        self.assertEqual(row._evaluate(self.sheet._get_localdict({'IP': 10.0}), {}), 0)

    def test_mapping_python_rejects_salary_rule_links(self):
        with self.assertRaises(ValidationError):
            self._create_mapping(
                evaluation_type='python', evaluation_value="result = mapped_total['IP']",
                salary_rule_ids=[Command.set(self.rule_ip.ids)],
            )

    def test_mapping_switch_to_python_clears_salary_rules(self):
        row = self._new_mapping()
        row.evaluation_type = 'python'
        row._onchange_evaluation_type()
        row.evaluation_value = "result = mapped_total['IP']"
        self.assertFalse(row.salary_rule_ids)
        row._check_evaluation_type_consistency()

    def test_mapping_row_changes_of_evaluation_type(self):
        # A row of the data may change of evaluation type when the module is updated
        row = self._create_mapping(tag='changing', evaluation_type='python', is_monetary=True, evaluation_value="result = mapped_total['IP']")
        row.write({'evaluation_type': 'salary_rule', 'salary_rule_ids': [Command.set(self.rule_ip.ids)]})
        self.assertFalse(row.evaluation_value)
        self.assertFalse(row.is_monetary)
        row.write({'evaluation_type': 'python', 'evaluation_value': 'result = 1'})
        self.assertFalse(row.salary_rule_ids)

    def test_mapping_rejects_overlapping_year_ranges(self):
        self._create_mapping(tag='dup_tag', date_from=date(2020, 1, 1), date_to=date(2026, 12, 31))
        with self.assertRaises(ValidationError):
            self._create_mapping(tag='dup_tag', date_from=date(2026, 1, 1))

    def test_evaluation_plan_gives_the_same_results(self):
        rows = self._create_mapping(tag='constant', evaluation_type='python', is_monetary=True, evaluation_value='result = 0')
        rows |= self._create_mapping(tag='empty', evaluation_type='python', evaluation_value="result = ''")
        rows |= self._create_mapping(tag='total', evaluation_type='python', is_monetary=True, evaluation_value="result = mapped_total['IP']")
        rows |= self._create_mapping(tag='python', evaluation_type='python', is_monetary=True, evaluation_value="result = mapped_total['IP'] / 3")
        rows |= self._create_mapping(tag='rule', salary_rule_ids=[Command.set((self.rule_ip + self.rule_ip_ded).ids)])
        plan = rows._get_evaluation_plan()
        self.assertEqual(
            {tag: kind for _line, tag, _is_monetary, kind, _data in plan},
            {'constant': 'constant', 'empty': 'constant', 'total': 'mapped_total', 'python': 'python', 'rule': 'salary_rule'},
        )
        for round_281 in (True, False):
            localdict = self.sheet.with_context(round_281=round_281)._get_localdict({'IP': 10.555, 'IP.DED': -2.0})
            computed = rows._evaluate_batch(localdict, plan)
            for row in rows:
                self.assertEqual(computed[row.tag], row._evaluate(localdict, {}), row.tag)

    def test_evaluation_plan_unknown_total_raises_user_error(self):
        row = self._new_mapping(tag='t', evaluation_type='python', evaluation_value="result = mapped_total['UNKNOWN']")
        self.assertEqual(row._get_python_shortcut(), ('mapped_total', 'UNKNOWN'))
        with self.assertRaises(UserError):
            row._evaluate_batch(self.sheet._get_localdict({'IP': 10.0}))

    def test_control_row_can_total_another_control_row(self):
        mapping_lines = self._create_nested_control_rows()
        computed = mapping_lines._evaluate_batch({})
        self.assertEqual(computed['inner_control'], 5)
        self.assertEqual(computed['outer_control'], 10)

    def test_nested_control_rows_are_resolved_whatever_their_order(self):
        mapping_lines = self._create_nested_control_rows()
        reversed_lines = self.env['l10n.be.281.mapping'].browse(list(reversed(mapping_lines.ids)))
        self.assertEqual(reversed_lines._evaluate_batch({})['outer_control'], 10)

    def test_control_rows_nest_deeper_than_two_levels(self):
        mapping = self.env['l10n.be.281.mapping']
        leaf = self._create_mapping(tag='deep_leaf', evaluation_type='python', evaluation_value='result = 1')
        controls = mapping
        innermost = leaf
        for level in range(4):
            innermost = self._create_mapping(
                tag=f'deep_control_{level}', evaluation_type='control',
                control_mapping_ids=[Command.set((innermost + leaf).ids)],
            )
            controls += innermost

        reversed_lines = mapping.browse(list(reversed((leaf + controls).ids)))
        computed = reversed_lines._evaluate_batch({})
        self.assertEqual([computed[control.tag] for control in controls], [1, 2, 3, 4])
        self.assertEqual(controls - controls.control_mapping_ids, controls[-1])

    def test_control_row_cannot_total_itself(self):
        mapping_lines = self._create_nested_control_rows()
        inner_control = mapping_lines.filtered(lambda line: line.tag == 'inner_control')
        outer_control = mapping_lines.filtered(lambda line: line.tag == 'outer_control')
        with self.assertRaises(ValidationError):
            inner_control.control_mapping_ids = [Command.link(outer_control.id)]

    def test_nested_control_row_is_not_counted_twice_in_the_envelope(self):
        mapping_lines = self._create_nested_control_rows()
        control_lines = mapping_lines.filtered(lambda line: line.evaluation_type == 'control')
        self.assertEqual(control_lines - control_lines.control_mapping_ids, mapping_lines[3])

    def test_control_row_cannot_reference_different_declaration_code(self):
        other_declaration_target = self._create_mapping(tag='other_declaration_target', declaration_code='273S')
        with self.assertRaises(ValidationError):
            self._create_mapping(
                tag='cross_declaration_control', evaluation_type='control',
                control_mapping_ids=[Command.set(other_declaration_target.ids)],
            )

    def test_deleting_linked_salary_rule_is_blocked(self):
        deletable_rule = self._create_salary_rule('DELETABLE', sequence=2322)
        self._create_mapping(tag='rule_deletion_guard', salary_rule_ids=[Command.set(deletable_rule.ids)])
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            deletable_rule.unlink()

    def test_deleting_linked_control_target_is_blocked(self):
        target = self._create_mapping(tag='target_deletion_guard', evaluation_type='python', evaluation_value='result = 1')
        self._create_mapping(
            tag='control_deletion_guard', evaluation_type='control',
            control_mapping_ids=[Command.set(target.ids)],
        )
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            target.unlink()

    def test_report_fetches_all_salary_rule_codes(self):
        extra_rule = self._create_salary_rule('UNMAPPED_CODE')
        self.rule_ip_ded.active = False
        codes = self._create_declaration().l10n_be_281_45_ids[:1]._get_line_codes()
        self.assertIn(extra_rule.code, codes)
        self.assertIn(self.rule_ip_ded.code, codes)

    def test_get_codes_salary_rule(self):
        row = self._new_mapping(
            tag='t', evaluation_type='salary_rule',
            salary_rule_ids=[Command.set((self.rule_ip + self.rule_ip_ded).ids)],
        )
        self.assertEqual(row._get_codes(), ['IP', 'IP.DED'])

    def test_get_codes_multiple_mappings(self):
        salary_mapping = self._new_mapping(
            tag='salary', evaluation_type='salary_rule',
            salary_rule_ids=[Command.set(self.rule_ip.ids)],
        )
        python_mapping = self._new_mapping(
            tag='python', evaluation_type='python',
            evaluation_value="result = mapped_total['IP'] + mapped_total['IP.DED']",
        )
        control_mapping = self._new_mapping(tag='control', evaluation_type='control')
        mapping_lines = salary_mapping + python_mapping + control_mapping
        self.rule_ip.active = False
        self.assertEqual(mapping_lines._get_codes(), ['IP'])
        self.assertEqual(self.env['l10n.be.281.mapping']._get_codes(), [])

    def test_mapping_python_supports_dynamic_lookups(self):
        for expression in (
            "code = 'IP'; result = mapped_total[code]",
            "result = mapped_total.get('I' + 'P', 0)",
            "totals = mapped_total; result = totals['IP']",
        ):
            with self.subTest(expression=expression):
                row = self._create_mapping(
                    tag=f'dynamic_{expression}', evaluation_type='python', evaluation_value=expression,
                )
                self.assertEqual(row._evaluate(self.sheet._get_localdict({'IP': 10.0}), {}), 10.0)

    def test_get_codes_dedups_shared_code_across_structures(self):
        rule_a = self._create_salary_rule(
            'IP.DUP', struct_ref='l10n_be_hr_payroll.hr_payroll_structure_cp200_employee_salary', sequence=2320,
        )
        rule_b = self._create_salary_rule(
            'IP.DUP', struct_ref='l10n_be_hr_payroll.hr_payroll_structure_cp200_profit_sharing_bonus', sequence=2321,
        )
        row = self._create_mapping(
            tag='dedup_tag', evaluation_type='salary_rule',
            salary_rule_ids=[Command.set((rule_a + rule_b).ids)],
        )
        self.assertEqual(len(row.salary_rule_ids), 2)
        self.assertEqual(row._get_codes(), ['IP.DUP'])
        self.assertEqual(row._evaluate(self.sheet._get_localdict({'IP.DUP': 15}), {}), 15)

    def test_salary_rule_fiscal_nature_exact_match(self):
        ip_tags = self.env['hr.salary.rule'].search(
            [('code', '=', 'IP'), ('country_id', '=', self.env.ref('base.be').id)], limit=1,
        ).l10n_be_fiscal_nature_ids.mapped('tag')
        self.assertIn('f45_2069_paidamount51', ip_tags)
        self.assertNotIn('f45_2063_roerendevoorheffing', ip_tags)
        self.assertNotIn('f45_2071_bookedamount5', ip_tags)

    def test_salary_rule_fiscal_nature_only_for_belgium(self):
        rule = self.env['hr.salary.rule'].new({'code': 'IP', 'country_id': self.env.ref('base.us').id})
        self.assertFalse(rule.l10n_be_fiscal_nature_ids)

    def test_281_45_eligibility_follows_income_box_mapping(self):
        self.employee_a.ip_wage_rate = 0
        extra_rule = self._create_salary_rule('IP.EXTRA_45', amount_fix=40.0, sequence=2310)
        mapping = self.env.ref('l10n_be_hr_payroll.l10n_be_281_mapping_281_45_2070')
        mapping.date_to = date(2025, 12, 31)
        self._create_mapping(tag=mapping.tag, salary_rule_ids=[Command.set(extra_rule.ids)])

        payslips = self.create_and_validate_payslips(employees=self.employee_a, year=2026, months=[1])
        extra_amount = sum(payslips.line_ids.filtered(lambda l: l.code == 'IP.EXTRA_45').mapped('total'))
        self.assertEqual(extra_amount, 40.0)

        sheet = self._create_declaration().l10n_be_281_45_ids[:1]
        sheet.action_generate_declarations()
        self.assertIn(self.employee_a, sheet.line_ids.employee_id)

        sheet_values = sheet.with_context(round_281=True)._get_rendering_data(self.employee_a)['employees_data'][0]
        self.assertEqual(sheet_values['f45_2070_paidamount52'], 4000)

    def test_281_45_python_income_uses_unmapped_archived_rule(self):
        self.employee_a.ip_wage_rate = 0
        extra_rule = self._create_salary_rule('PYTHON_INCOME', amount_fix=40.0, sequence=2310)
        mapping = self.env.ref('l10n_be_hr_payroll.l10n_be_281_mapping_281_45_2070')
        mapping.write({
            'evaluation_type': 'python',
            'salary_rule_ids': [Command.clear()],
            'is_monetary': True,
            'evaluation_value': "code = 'PYTHON_INCOME'; result = mapped_total[code]",
        })
        payslips = self.create_and_validate_payslips(employees=self.employee_a, year=2026, months=[1])
        self.assertEqual(sum(payslips.line_ids.filtered(lambda line: line.code == extra_rule.code).mapped('total')), 40.0)
        extra_rule.active = False
        sheet = self._create_declaration().l10n_be_281_45_ids[:1]
        sheet.action_generate_declarations()
        self.assertIn(self.employee_a, sheet.line_ids.employee_id)

        sheet_values = sheet.with_context(round_281=True)._get_rendering_data(self.employee_a)['employees_data'][0]
        self.assertEqual(sheet_values['f45_2070_paidamount52'], 4000)

    def test_281_45_eligibility_follows_new_monetary_tag_not_in_control_row(self):
        self.employee_a.ip_wage_rate = 0
        extra_rule = self._create_salary_rule('IP.NEWBOX', amount_fix=40.0, sequence=2311)
        self._create_mapping(tag='f45_9999_newbox', salary_rule_ids=[Command.set(extra_rule.ids)])

        payslips = self.create_and_validate_payslips(employees=self.employee_a, year=2026, months=[1])
        extra_amount = sum(payslips.line_ids.filtered(lambda l: l.code == 'IP.NEWBOX').mapped('total'))
        self.assertEqual(extra_amount, 40.0)

        sheet = self._create_declaration().l10n_be_281_45_ids[:1]
        sheet.action_generate_declarations()
        self.assertIn(self.employee_a, sheet.line_ids.employee_id)

    def test_281_45_xml_export_is_schema_valid(self):
        self.employee_a.ip_wage_rate = 0.25
        payslips = self.create_and_validate_payslips(employees=self.employee_a, year=2025, months=[1])
        income = sum(payslips.line_ids.filtered(lambda line: line.code == 'IP').mapped('total'))
        withholding = sum(payslips.line_ids.filtered(lambda line: line.code == 'IP.DED').mapped('total'))

        declaration = self._create_declaration(year='2025')
        declaration.action_generate_xml()

        self.assertEqual(declaration.state, 'ready', declaration.error_message)
        self.assertFalse(declaration.error_message)

        xml_root = etree.fromstring(bytes(declaration.xml_file))
        fiche = xml_root.find('.//Fiche28145')
        self.assertIsNotNone(fiche, "The 281.45 fiche must be present in the rendered XML")
        self.assertEqual(fiche.findtext('f2008_typefiche'), '28145')
        self.assertEqual(
            fiche.findtext('f45_2069_paidamount51'), str(int(round(income, 2) * 100)),
        )

        expected_order = [
            'f45_2030_aardpersoon', 'f45_2031_verantwoordingsstukken', 'f45_2059_totaalcontrole',
            'f45_2063_roerendevoorheffing', 'f45_2067_paidamount4', 'f45_2068_bookedamount4',
            'f45_2069_paidamount51', 'f45_2070_paidamount52', 'f45_2071_bookedamount5',
            'f45_2099_comment', 'f45_2109_fiscaalidentificat',
        ]
        f45_children = [child.tag for child in fiche if child.tag.startswith('f45_')]
        self.assertEqual(f45_children, expected_order)

        sheet = declaration.l10n_be_281_45_ids[:1]
        self.assertIn(self.employee_a, sheet.line_ids.employee_id)
        sheet_values = sheet.with_context(round_281=True)._get_rendering_data(self.employee_a)['employees_data'][0]
        self.assertEqual(sheet_values['f45_2069_paidamount51'], int(round(income, 2) * 100))
        self.assertEqual(sheet_values['f45_2063_roerendevoorheffing'], int(round(-withholding, 2) * 100))
        self.assertEqual(
            sheet_values['f45_2059_totaalcontrole'],
            sum(sheet_values[field] for field in (
                'f45_2063_roerendevoorheffing',
                'f45_2067_paidamount4',
                'f45_2068_bookedamount4',
                'f45_2069_paidamount51',
                'f45_2070_paidamount52',
                'f45_2071_bookedamount5',
            )),
        )
        for tag in expected_order:
            self.assertEqual(fiche.findtext(tag), str(sheet_values[tag]))

    def test_ip_mapping_covers_every_ip_code(self):
        """The IP declarations must map every salary rule paying intellectual property."""
        mapping = self.env['l10n.be.281.mapping']
        ip_codes = ['IP']
        year = date.today().year
        self.assertEqual(
            sorted(mapping._get_codes_for_tag('273S', '273s_gross_income', year)), ip_codes,
            "A salary rule paying IP is missing from the 273S gross income mapping",
        )
        self.assertEqual(
            sorted(mapping._get_codes_for_tag('281.45', 'f45_2069_paidamount51', year)), ip_codes,
            "A salary rule paying IP is missing from the 281.45 paid amount mapping",
        )
        self.assertEqual(
            sorted(mapping._get_codes_for_tag('273S', '273s_withholding_tax', year)), ['IP.DED'],
            "The 273S withholding tax mapping must stay on the IP deduction rule",
        )

    def test_adding_new_salary_rule_to_mapping_is_reflected_in_report(self):
        """
        Test that adding a new custom salary rule to a mapping is correctly reflected in the generated report.
        """
        old_payslip = self.create_and_validate_payslips(employees=self.employee_a, year=2026, months=[1])

        old_declaration_274_10 = self.env['l10n_be.274_xx'].create({
            'year': 2026,
            'month': '1',
        })
        old_withholding_amount_10 = old_declaration_274_10['pp_amount_10']
        old_declaration_281_10 = self._create_declaration()
        data_281 = old_declaration_281_10.l10n_be_281_10_ids.with_context(round_281=True)._get_rendering_data(self.employee_a)
        old_bonus_a = data_281['employees_data'][0]['f10_2115_bonus']

        old_payslip.action_payslip_cancel()
        old_payslip.unlink()

        new_rule = self._create_salary_rule('BRAND_NEW_RULE', amount_fix=250.0, sequence=2313)
        self.env.ref('l10n_be_hr_payroll.l10n_be_281_mapping_274_10_withholding').write({
            'salary_rule_ids': [Command.link(new_rule.id)],
        })
        self.env.ref('l10n_be_hr_payroll.l10n_be_281_mapping_281_10_2115').write({
            'salary_rule_ids': [Command.link(new_rule.id)],
        })
        self.create_and_validate_payslips(employees=self.employee_a, year=2026, months=[1])

        new_declaration_274_10 = self.env['l10n_be.274_xx'].create({
            'year': 2026,
            'month': '1',
        })
        new_withholding_amount_10 = new_declaration_274_10['pp_amount_10']
        new_declaration_281_10 = self._create_declaration()
        data_281 = new_declaration_281_10.l10n_be_281_10_ids.with_context(round_281=True)._get_rendering_data(self.employee_a)
        new_bonus_a = data_281['employees_data'][0]['f10_2115_bonus']

        self.assertEqual(new_withholding_amount_10, old_withholding_amount_10 + 250.0, "The new withholding amount should reflect the addition of the new salary rule")
        self.assertEqual(new_bonus_a, old_bonus_a + 25000, "The new bonus should reflect the addition of the new salary rule")  # 281.xx reports round to eurocent so 250.00 should be 25000
