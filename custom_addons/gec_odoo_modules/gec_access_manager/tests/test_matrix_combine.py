# Random combinations of 1-3 profiles on one user, against a plain Python oracle of the documented rules: every
# override profile must allow and filter, the additive profiles that allow an operation widen each other, and the
# result never goes beyond what Odoo gives the user without any profile.
import ast
import os
import random

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

OPERATIONS = ('read', 'write', 'create', 'unlink')
POOL = (
    "[]",
    "[('id', '=', 0)]",
    "[('ref', '=', 'A')]",
    "[('city', '=', 'Paris')]",
    "[('is_company', '=', True)]",
    "[('parent_id', '!=', False)]",
    "[('ref', 'in', ['A', 'B'])]",
    "['|', ('city', '=', 'Rome'), ('ref', '=', 'C')]",
    "['!', ('city', '=', 'Oslo')]",
    "[('category_id', '!=', False)]",
)


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixCombine(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        cls.company_b = cls.env['res.company'].create({'name': 'MX Combine Company B'})
        cats = cls.env['res.partner.category'].create([{'name': f'MX Combine Cat {i}'} for i in range(3)])
        made = Partner.browse()
        for index in range(24):
            made |= Partner.create({
                'name': f'MX Combine Partner {index}',
                'ref': (False, 'A', 'B', 'C')[index % 4],
                'city': ('Paris', 'Rome', 'Oslo', False)[(index // 2 + index) % 4],
                'is_company': index % 3 == 0,
                'category_id': [Command.set(cats[index % 3].ids)] if index % 5 else [],
                'parent_id': made[index - 12].id if index >= 12 and index % 2 else False,
                'company_id': cls.company_b.id if index in (5, 17) else False,
            })
        cls.ids = made.ids
        full_group = cls.env['res.groups'].create({'name': 'MX Combine Full Access'})
        cls.env['ir.access'].create({
            'name': 'MX combine full access', 'model_id': cls.env['ir.model']._get('res.partner').id,
            'group_id': full_group.id, 'operation': 'crud', 'domain': '[]',
        })
        cls.user = new_test_user(cls.env, login='mx_combine_user', groups='base.group_user,base.group_partner_manager',
                                 password='mx-combine-user')
        cls.user.group_ids = [Command.link(full_group.id)]
        cls.partner_model = cls.env['ir.model']._get('res.partner')
        cls.pool = {text: cls._fixture_matches(text) for text in POOL}
        cls.baseline = {operation: cls._baseline(operation) for operation in ('read', 'write', 'unlink')}

    @classmethod
    def _fixture_matches(cls, text):
        return set(cls.env['res.partner'].search([('id', 'in', cls.ids)] + ast.literal_eval(text)).ids)

    @classmethod
    def _baseline(cls, operation):
        return set(cls.env['res.partner'].browse(cls.ids).with_user(cls.user)._filtered_access(operation).ids)

    # the oracle

    def _line(self, rng):
        """ A random model line as (values for the line, its terms by operation as sets of fixture ids). """
        values = {'model_id': self.partner_model.id}
        for operation in OPERATIONS:
            values[f'perm_{operation}'] = rng.random() < 0.75
        if rng.random() < 0.6:
            values['domain'] = rng.choice(POOL)
        for operation in OPERATIONS:
            if rng.random() < 0.3:
                values[f'domain_{operation}'] = rng.choice(POOL)
        return values

    def _profile_view(self, values):
        """ What the oracle needs of one profile: whether it allows an operation, and the ids it leaves. """
        line = values.get('line')
        everything = set(self.ids)

        def allows(operation):
            if values['global_readonly'] and operation != 'read':
                return False
            return True if line is None else line[f'perm_{operation}']

        def left(operation):
            if line is None:
                return everything
            result = everything
            for key in ('domain', f'domain_{operation}'):
                if line.get(key):
                    result = result & self.pool[line[key]]
            return result

        return allows, left

    def _expected(self, profiles):
        """ {operation: set of fixture ids, or None when the operation is refused outright}. """
        views = [(profile['strictness'], *self._profile_view(profile)) for profile in profiles]
        expected = {}
        for operation in OPERATIONS:
            override = [(allows, left) for strictness, allows, left in views if strictness == 'override']
            additive = [(allows, left) for strictness, allows, left in views if strictness == 'additive']
            if not all(allows(operation) for allows, _left in override):
                expected[operation] = None
                continue
            allowing = [left for allows, left in additive if allows(operation)]
            if additive and not allowing:
                expected[operation] = None
                continue
            result = set(self.ids)
            for _allows, left in override:
                result &= left(operation)
            if additive:
                union = set()
                for left in allowing:
                    union |= left(operation)
                result &= union
            expected[operation] = result
        return expected

    # the actual outcomes

    def _actual(self):
        self.env.invalidate_all()
        self.env.transaction.invalidate_access_cache()
        Partner = self.env['res.partner'].with_user(self.user)
        records = Partner.browse(self.ids)
        actual = {}
        for operation in OPERATIONS:
            if not Partner.browse().has_access(operation):
                with self.assertRaises(AccessError):
                    Partner.browse().check_access(operation)
                actual[operation] = None
            elif operation == 'create':
                actual[operation] = set(self.ids)
            elif operation == 'read':
                actual[operation] = set(Partner.search([('id', 'in', self.ids)]).ids)
            else:
                actual[operation] = set(records._filtered_access(operation).ids)
        return actual

    def _expected_for_user(self, expected):
        """ The oracle's sets under what Odoo gives the user: the baseline caps each operation. """
        result = {}
        for operation, ids in expected.items():
            if ids is None:
                result[operation] = None
            elif operation == 'create':
                result[operation] = set(self.ids)
            else:
                result[operation] = ids & self.baseline[operation]
        return result

    def _assign(self, profiles):
        self.env['gec.access.profile'].search([('name', '=like', 'MX combine %')]).unlink()
        for index, profile in enumerate(profiles):
            values = {
                'name': f'MX combine {index}', 'strictness': profile['strictness'],
                'global_readonly': profile['global_readonly'], 'user_ids': [Command.set(self.user.ids)],
            }
            if profile.get('line') is not None:
                values['model_ids'] = [Command.create(profile['line'])]
            self.env['gec.access.profile'].create(values)

    def _random_profiles(self, rng):
        profiles = []
        for _index in range(rng.randint(1, 3)):
            profiles.append({
                'strictness': rng.choice(('additive', 'override')),
                'global_readonly': rng.random() < 0.1,
                'line': self._line(rng) if rng.random() < 0.7 else None,
            })
        return profiles

    def _check(self, profiles, message):
        self._assign(profiles)
        expected = self._expected_for_user(self._expected(profiles))
        actual = self._actual()
        self.assertEqual(actual, expected, message)
        for operation in ('read', 'write', 'unlink'):
            if actual[operation] is not None:
                self.assertLessEqual(actual[operation], self.baseline[operation], f"wider than core: {message}")

    def test_random_combinations(self):
        seed = int(os.environ.get('GEC_MATRIX_SEED', 20261026))
        cases = int(os.environ.get('GEC_MATRIX_CASES', 300))
        rng = random.Random(seed)
        shapes = set()
        for index in range(cases):
            profiles = self._random_profiles(rng)
            with self.subTest(seed=seed, case=index):
                self._check(profiles, f"seed {seed} case {index} profiles {profiles!r}")
            actual = self._actual()
            shapes.add('refused' if actual['write'] is None else 'none' if not actual['read'] else
                       'partial' if actual['read'] < self.baseline['read'] else 'full')
        if cases >= 100:
            self.assertEqual(shapes, {'refused', 'none', 'partial', 'full'}, "the cases cover every kind of outcome")

    # the edge rules, one by one

    def _profile(self, line=None, **values):
        profile = {'strictness': 'additive', 'global_readonly': False, 'line': None}
        rights = {f'perm_{operation}': True for operation in OPERATIONS}
        profile.update(values, line=None if line is None else {'model_id': self.partner_model.id, **rights, **line})
        return profile

    def _ids_of(self, text):
        return self.pool[text]

    def test_baseline_is_narrower_than_everything(self):
        for operation in ('read', 'write', 'unlink'):
            self.assertTrue(self.baseline[operation])
            self.assertLess(self.baseline[operation], set(self.ids), "the company B partners are out of reach")

    def test_additive_profile_without_a_line_lifts_the_restriction(self):
        profiles = [self._profile(line={'domain': "[('ref', '=', 'A')]"}), self._profile()]
        self._check(profiles, "an additive profile that says nothing about partners")
        self._assign(profiles)
        self.assertEqual(self._actual()['read'], self.baseline['read'])

    def test_additive_profile_that_refuses_does_not_widen_the_union(self):
        profiles = [self._profile(line={'perm_write': False}), self._profile(line={'domain': "[('ref', '=', 'A')]"})]
        self._check(profiles, "refusing profile beside a filtering one")
        self._assign(profiles)
        actual = self._actual()
        self.assertEqual(actual['write'], self._ids_of("[('ref', '=', 'A')]") & self.baseline['write'])
        self.assertEqual(actual['read'], self.baseline['read'], "the refusing profile still reads everything")

    def test_override_always_narrows(self):
        profiles = [self._profile(), self._profile(strictness='override', line={
            'domain': "[('ref', '=', 'A')]", 'perm_unlink': False})]
        self._check(profiles, "override beside an open additive profile")
        self._assign(profiles)
        actual = self._actual()
        self.assertEqual(actual['read'], self._ids_of("[('ref', '=', 'A')]") & self.baseline['read'])
        self.assertIsNone(actual['unlink'])

    def test_two_override_profiles_both_apply(self):
        profiles = [
            self._profile(strictness='override', line={'domain': "[('ref', 'in', ['A', 'B'])]"}),
            self._profile(strictness='override', line={'domain_read': "[('is_company', '=', True)]"}),
        ]
        self._check(profiles, "two override profiles")
        self._assign(profiles)
        expected = self._ids_of("[('ref', 'in', ['A', 'B'])]") & self._ids_of("[('is_company', '=', True)]")
        self.assertEqual(self._actual()['read'], expected & self.baseline['read'])

    def test_read_only_override_beats_an_open_additive_profile(self):
        profiles = [self._profile(), self._profile(strictness='override', global_readonly=True)]
        self._check(profiles, "global read only")
        self._assign(profiles)
        actual = self._actual()
        self.assertEqual(actual['read'], self.baseline['read'])
        self.assertEqual((actual['write'], actual['create'], actual['unlink']), (None, None, None))

    def test_archived_profile_is_ignored(self):
        self._assign([self._profile(line={'domain': "[('id', '=', 0)]"})])
        self.assertEqual(self._actual()['read'], set())
        self.env['gec.access.profile'].search([('name', '=like', 'MX combine %')]).active = False
        self.assertEqual(self._actual()['read'], self.baseline['read'])

    def test_profile_of_a_company_the_user_lacks_is_ignored(self):
        self._assign([self._profile(line={'domain': "[('id', '=', 0)]"})])
        profile = self.env['gec.access.profile'].search([('name', '=like', 'MX combine %')])
        profile.company_id = self.company_b
        self.assertNotIn(self.company_b, self.user.company_ids)
        self.assertEqual(self._actual()['read'], self.baseline['read'])
        profile.company_id = self.user.company_id
        self.assertEqual(self._actual()['read'], set())

    def test_settings_user_is_exempt_unless_the_profile_applies_to_admins(self):
        self._assign([self._profile(line={'domain': "[('id', '=', 0)]"})])
        profile = self.env['gec.access.profile'].search([('name', '=like', 'MX combine %')])
        self.user.group_ids = [Command.link(self.env.ref('base.group_system').id)]
        baseline = self._baseline('read')
        self.assertEqual(self._actual()['read'], baseline)
        profile.apply_to_admin = True
        self.assertEqual(self._actual()['read'], set())
