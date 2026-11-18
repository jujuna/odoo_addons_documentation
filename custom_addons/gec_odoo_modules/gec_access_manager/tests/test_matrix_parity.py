# A profile record filter must behave exactly like the same filter as a global core ir.access row, for every domain
# shape and every operation. Each case compares the outcomes of one user under the profile with the outcomes of the
# same user under the core row, over a fixed set of records.
from contextlib import closing
from datetime import date, timedelta

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import SQL, mute_logger

OPERATIONS = ('read', 'write', 'create', 'unlink')
CORE_OPERATION = {'all': 'crud', 'read': 'r', 'write': 'u', 'create': 'c', 'unlink': 'd'}
CONFIGS = ('all', 'read', 'write', 'create', 'unlink')
HEAVY_MODELS = ('res.partner', 'res.partner.category')
PROFILE_FIELD = {'all': 'domain', 'read': 'domain_read', 'write': 'domain_write', 'create': 'domain_create',
                 'unlink': 'domain_unlink'}


def shapes_of(spec):
    """ The domain shapes of a model as (label, domain text, create values matching, create values not matching). """
    user = spec['user']
    char, char_match, char_other = spec['char']
    shapes = [
        ('eq', f"[('{char}', '=', '{char_match}')]", {char: char_match}, {char: char_other}),
        ('neg', f"['!', ('{char}', '=', '{char_match}')]", {char: char_other}, {char: char_match}),
        ('false', f"[('{char}', '=', False)]", {char: False}, {char: char_other}),
        ('maybe_false', f"[('{char}', '=?', False)]", {char: char_other}, {char: char_match}),
        ('maybe_value', f"[('{char}', '=?', '{char_match}')]", {char: char_match}, {char: char_other}),
        ('nothing', "[('id', '=', 0)]", {}, {}),
        ('everything', "[]", {}, {}),
        ('date', "[('create_date', '>=', 'today')]", {}, {}),
    ]
    if spec.get('sel'):
        name, values, match, other = spec['sel']
        shapes.append(('in_selection', f"[('{name}', 'in', {values!r})]", {name: match}, {name: other}))
        shapes.append(('or', f"['|', ('{char}', '=', '{char_match}'), ('{name}', 'in', {values!r})]",
                       {char: char_match}, {char: char_other, name: other}))
    else:
        shapes.append(('or', f"['|', ('{char}', '=', '{char_match}'), ('{char}', '=', '{char_other}')]",
                       {char: char_other}, {char: 'MX nomatch'}))
    if spec.get('m2o'):
        name, value = spec['m2o']
        shapes.append(('many2one', f"[('{name}', '=', {value})]", {name: value}, {}))
    if spec.get('user_field'):
        name, writable = spec['user_field']
        shapes.append(('user_id', f"[('{name}', '=', user.id)]", {name: user.id} if writable else {},
                       {name: spec['other_user'].id} if writable else {}))
    if spec.get('partner_field'):
        name = spec['partner_field']
        shapes.append(('user_partner', f"[('{name}', '=', user.partner_id.id)]", {name: user.partner_id.id}, {}))
    if spec.get('company'):
        name, other_company = spec['company']
        shapes.append(('company_ids', f"[('{name}', 'in', company_ids)]", {}, {name: other_company}))
        shapes.append(('company_or_false', f"['|', ('{name}', '=', False), ('{name}', 'in', company_ids)]",
                       {name: False}, {name: other_company}))
    if spec.get('child'):
        name, value = spec['child']
        shapes.append(('child_of', f"[('{name}', 'child_of', {value})]", {name: value}, {}))
    if spec.get('any'):
        domain, match, other = spec['any']
        shapes.append(('any', domain, match, other))
    return shapes


@tagged('post_install', '-at_install', 'gec_matrix')
class TestMatrixParity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref('base.user_admin')
        cls.company_b = cls.env['res.company'].create({'name': 'MX Parity Company B'})
        cls.full_group = cls.env['res.groups'].create({'name': 'MX Parity Full Access'})
        cls.specs, cls.spec_errors = {}, {}
        for model_name, builder in (
            ('res.partner', cls._spec_partner), ('res.partner.category', cls._spec_category),
            ('sale.order', cls._spec_sale), ('account.move', cls._spec_move), ('stock.picking', cls._spec_picking),
            ('hr.employee', cls._spec_employee), ('product.template', cls._spec_product),
        ):
            if model_name not in cls.env:
                continue
            try:
                with cls.env.cr.savepoint():
                    cls.specs[model_name] = builder.__func__(cls)
            except Exception as error:  # noqa: BLE001
                cls.spec_errors[model_name] = error
        for model_name in cls.specs:
            cls.env['ir.access'].create({
                'name': 'MX parity full access', 'model_id': cls.env['ir.model']._get(model_name).id,
                'group_id': cls.full_group.id, 'operation': 'crud', 'domain': '[]',
            })

    # fixtures

    @classmethod
    def _user(cls, name, groups):
        user = new_test_user(cls.env, login=f'mx_parity_{name}', groups=f'base.group_user,{groups}',
                             password=f'mx-parity-{name}')
        user.group_ids = [Command.link(cls.full_group.id)]
        return user

    @classmethod
    def _age(cls, records, days):
        cls.env.cr.execute(SQL(
            "UPDATE %s SET create_date = now() - %s * interval '1 day' WHERE id IN %s",
            SQL.identifier(records._table), days, tuple(records.ids)))
        records.invalidate_recordset(['create_date'])

    @classmethod
    def _spec_partner(cls):
        user = cls._user('partner', 'base.group_partner_manager')
        Partner = cls.env['res.partner']
        cats = cls.env['res.partner.category'].create([{'name': f'MX Parity Cat {i}'} for i in range(3)])
        main, other = cls.env.company, cls.company_b
        rows = [
            ('A', 'Paris', True, [0], None, main, 'contact', None),
            ('A', 'Rome', False, [0, 1], 0, main, 'invoice', None),
            ('B', 'Paris', False, [1], 0, main, 'delivery', user),
            ('B', False, False, [], 1, False, 'contact', cls.admin),
            ('C', 'Oslo', True, [], None, main, 'contact', None),
            ('C', 'Oslo', False, [2], 4, main, 'other', user),
            (False, 'Rome', False, [2], None, False, 'contact', None),
            ('D', False, True, [0, 1, 2], None, other, 'invoice', None),
            ('D', 'Paris', False, [], 7, other, 'contact', cls.admin),
            ('A', 'Oslo', False, [], 'own', main, 'contact', user),
            ('B', 'Rome', False, [1], 'own', False, 'delivery', None),
            (False, False, False, [], None, main, 'contact', None),
            ('E', 'Paris', True, [0], None, False, 'invoice', user),
            ('E', 'Rome', False, [], 12, main, 'delivery', None),
            ('F', 'Oslo', False, [2], 3, main, 'contact', cls.admin),
        ]
        made = Partner.browse()
        for index, (ref, city, is_company, category, parent, company, kind, owner) in enumerate(rows):
            parent_record = user.partner_id if parent == 'own' else made[parent] if parent is not None else Partner
            made |= Partner.create({
                'name': f'MX Parity Partner {index}', 'ref': ref, 'city': city, 'is_company': is_company,
                'category_id': [Command.set([cats[i].id for i in category])], 'parent_id': parent_record.id,
                'company_id': company.id if company else False, 'type': kind, 'user_id': owner.id if owner else False,
            })
        cls._age(made[:6], 10)
        return {
            'model': 'res.partner', 'user': user, 'other_user': cls.admin, 'ids': made.ids, 'group': 'city',
            'read': 'name', 'write': {'function': 'MX changed'}, 'create': {'name': 'MX new partner'},
            'char': ('ref', 'A', 'Z'), 'sel': ('type', ['invoice', 'delivery'], 'invoice', 'contact'),
            'm2o': ('country_id', cls.env.ref('base.be').id), 'user_field': ('user_id', True),
            'partner_field': 'parent_id', 'company': ('company_id', other.id), 'child': ('parent_id', made[0].id),
            'any': ("[('child_ids', 'any', [('ref', '=', 'A')])]",
                    {'child_ids': [Command.create({'name': 'MX kid', 'ref': 'A'})]}, {}),
        }

    @classmethod
    def _spec_category(cls):
        user = cls._user('category', 'base.group_partner_manager')
        Category = cls.env['res.partner.category']
        rows = [('MX Parity A', None, 1), ('MX Parity A', 0, 2), ('MX Parity B', 0, 1), ('MX Parity B', 1, 3),
                ('MX Parity C', None, 2), ('MX Parity C', 4, 1), ('MX Parity D', None, 3), ('MX Parity D', 6, 1),
                ('MX Parity E', 6, 2), ('MX Parity A', None, 1), ('MX Parity F', 9, 1), ('MX Parity F', 10, 2),
                ('MX Parity G', None, 3), ('MX Parity G', 12, 1), ('MX Parity H', None, 2)]
        made = Category.browse()
        for name, parent, color in rows:
            made |= Category.create({'name': name, 'color': color,
                                     'parent_id': made[parent].id if parent is not None else False})
        cls._age(made[:6], 10)
        return {
            'model': 'res.partner.category', 'user': user, 'other_user': cls.admin, 'ids': made.ids, 'group': 'color',
            'read': 'name', 'write': {'color': 9}, 'create': {'name': 'MX new category'},
            'char': ('name', 'MX Parity A', 'MX Parity Z'), 'sel': ('color', [1, 2], 1, 3),
            'user_field': ('create_uid', False), 'child': ('parent_id', made[0].id),
            'any': ("[('child_ids', 'any', [('color', '=', 1)])]",
                    {'child_ids': [Command.create({'name': 'MX kid', 'color': 1})]}, {}),
        }

    @classmethod
    def _spec_sale(cls):
        user = cls._user('sale', 'sales_team.group_sale_salesman_all_leads')
        Order = cls.env['sale.order']
        partners = cls.env['res.partner'].create([{'name': f'MX Parity Customer {i}'} for i in range(3)])
        owners = (user, cls.admin, cls.env['res.users'])
        states = ('draft', 'draft', 'sent', 'sale', 'cancel')
        made = Order.browse()
        for index in range(15):
            partner = user.partner_id if index % 5 == 4 else partners[index % 3]
            order = Order.create({
                'partner_id': partner.id, 'client_order_ref': ('A', 'B', 'C')[index % 3],
                'user_id': owners[index % 3].id,
            })
            order.state = states[index % 5]
            made |= order
        cls._age(made[:6], 10)
        return {
            'model': 'sale.order', 'user': user, 'other_user': cls.admin, 'ids': made.ids, 'group': 'state',
            'read': 'name', 'write': {'note': '<p>MX changed</p>'}, 'create': {'partner_id': partners[0].id},
            'char': ('client_order_ref', 'A', 'Z'), 'sel': ('state', ['draft', 'sent'], 'sent', 'cancel'),
            'm2o': ('partner_id', partners[1].id), 'user_field': ('user_id', True), 'partner_field': 'partner_id',
            'company': ('company_id', cls.company_b.id),
            'any': (f"[('partner_id', 'any', [('id', '=', {partners[2].id})])]", {'partner_id': partners[2].id},
                    {'partner_id': partners[0].id}),
        }

    @classmethod
    def _spec_move(cls):
        user = cls._user('move', 'account.group_account_invoice')
        Move = cls.env['account.move']
        journal = cls.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', cls.env.company.id)], limit=1)
        partners = cls.env['res.partner'].create([{'name': f'MX Parity Payer {i}'} for i in range(2)])
        owners = (user, cls.admin, cls.env['res.users'])
        made = Move.browse()
        for index in range(15):
            move = Move.create({
                'move_type': 'entry', 'journal_id': journal.id, 'ref': ('A', 'B', 'C')[index % 3],
                'invoice_user_id': owners[index % 3].id,
                'partner_id': user.partner_id.id if index % 5 == 4 else partners[index % 2].id,
                'date': date.today() - timedelta(days=index - 5),
            })
            if index % 4 == 3:
                move.button_cancel()
            made |= move
        cls._age(made[:6], 10)
        return {
            'model': 'account.move', 'user': user, 'other_user': cls.admin, 'ids': made.ids, 'group': 'state',
            'read': 'name', 'write': {'narration': '<p>MX changed</p>'},
            'create': {'move_type': 'entry', 'journal_id': journal.id},
            'char': ('ref', 'A', 'Z'), 'sel': ('state', ['draft', 'posted'], 'draft', 'cancel'),
            'm2o': ('partner_id', partners[1].id), 'user_field': ('invoice_user_id', True),
            'partner_field': 'partner_id', 'company': ('company_id', cls.company_b.id),
            'any': (f"[('partner_id', 'any', [('id', '=', {partners[0].id})])]", {'partner_id': partners[0].id},
                    {'partner_id': partners[1].id}),
        }

    @classmethod
    def _spec_picking(cls):
        user = cls._user('picking', 'stock.group_stock_user')
        Picking = cls.env['stock.picking']
        picking_type = cls.env['stock.picking.type'].search(
            [('code', '=', 'incoming'), ('company_id', '=', cls.env.company.id)], limit=1)
        partners = cls.env['res.partner'].create([{'name': f'MX Parity Carrier {i}'} for i in range(2)])
        owners = (user, cls.admin, cls.env['res.users'])
        made = Picking.browse()
        for index in range(15):
            picking = Picking.create({
                'picking_type_id': picking_type.id, 'origin': ('A', 'B', 'C')[index % 3],
                'priority': str(index % 2), 'user_id': owners[index % 3].id,
                'partner_id': user.partner_id.id if index % 5 == 4 else partners[index % 2].id,
            })
            if index % 4 == 3:
                picking.action_cancel()
            made |= picking
        cls._age(made[:6], 10)
        return {
            'model': 'stock.picking', 'user': user, 'other_user': cls.admin, 'ids': made.ids, 'group': 'priority',
            'read': 'name', 'write': {'note': '<p>MX changed</p>'}, 'create': {'picking_type_id': picking_type.id},
            'char': ('origin', 'A', 'Z'), 'sel': ('priority', ['1'], '1', '0'),
            'm2o': ('partner_id', partners[1].id), 'user_field': ('user_id', True), 'partner_field': 'partner_id',
            'company': ('company_id', cls.company_b.id),
            'any': (f"[('partner_id', 'any', [('id', '=', {partners[0].id})])]", {'partner_id': partners[0].id},
                    {'partner_id': partners[1].id}),
        }

    @classmethod
    def _spec_employee(cls):
        user = cls._user('employee', 'hr.group_hr_user')
        Employee = cls.env['hr.employee']
        tag = cls.env['hr.employee.category'].create({'name': 'MX Parity Tag'})
        made = Employee.browse()
        for index in range(15):
            parent = made[0] if index in (1, 2) else made[1] if index == 3 else Employee
            made |= Employee.create({
                'name': ('MX Parity A', 'MX Parity B', 'MX Parity C')[index % 3], 'parent_id': parent.id,
                'category_ids': [Command.set(tag.ids if index % 4 == 0 else [])],
                'marital': 'married' if index % 2 else 'single', 'birthday': date(1990, 1, 1) + timedelta(days=index),
            })
        cls._age(made[:6], 10)
        return {
            'model': 'hr.employee', 'public_read': True, 'user': user, 'other_user': cls.admin, 'ids': made.ids, 'group': 'marital',
            'read': 'name', 'write': {'work_email': 'mx.changed@example.com'}, 'create': {'name': 'MX new employee'},
            'char': ('name', 'MX Parity A', 'MX Parity Z'), 'sel': ('marital', ['married'], 'married', 'single'),
            'user_field': ('user_id', False), 'company': ('company_id', cls.company_b.id),
            'child': ('parent_id', made[0].id),
            'any': ("[('category_ids', 'any', [('name', '=', 'MX Parity Tag')])]",
                    {'category_ids': [Command.set(tag.ids)]}, {}),
        }

    @classmethod
    def _spec_product(cls):
        user = cls._user('product', 'product.group_product_manager')
        Product = cls.env['product.template']
        category = cls.env['product.category'].create({'name': 'MX Parity Category'})
        child_category = cls.env['product.category'].create({'name': 'MX Parity Child', 'parent_id': category.id})
        types = ('consu', 'service', 'consu')
        made = Product.browse()
        for index in range(15):
            made |= Product.create({
                'name': f'MX Parity Product {index}', 'default_code': ('A', 'B', 'C')[index % 3],
                'type': types[index % 3], 'categ_id': (category, child_category)[index % 2].id,
                'company_id': cls.company_b.id if index % 5 == 4 else cls.env.company.id if index % 5 else False,
            })
        cls._age(made[:6], 10)
        return {
            'model': 'product.template', 'user': user, 'other_user': cls.admin, 'ids': made.ids, 'group': 'type',
            'read': 'name', 'write': {'description_sale': 'MX changed'},
            'create': {'name': 'MX new product', 'type': 'consu'},
            'char': ('default_code', 'A', 'Z'), 'sel': ('type', ['service'], 'service', 'consu'),
            'm2o': ('categ_id', category.id), 'user_field': ('create_uid', False),
            'company': ('company_id', cls.company_b.id), 'child': ('categ_id', category.id),
            'any': ("[('product_variant_ids', 'any', [('default_code', '=', 'A')])]",
                    {'default_code': 'A'}, {'default_code': 'Z'}),
        }

    # outcomes

    def _spec(self, model_name):
        if model_name in self.spec_errors:
            raise self.spec_errors[model_name]
        if model_name not in self.specs:
            self.skipTest(f"{model_name} is not installed")
        return self.specs[model_name]

    def _attempt(self, action):
        try:
            with closing(self.env.cr.savepoint()):
                action()
        except AccessError:
            return 'AccessError'
        except Exception as error:  # noqa: BLE001
            return type(error).__name__
        return 'ok'

    def _value(self, action):
        try:
            return action()
        except AccessError:
            return 'AccessError'

    def _outcomes(self, spec, match=None, other=None):
        """ What the user of ``spec`` gets from the fixture records, by every entry point. """
        self.env.invalidate_all()
        self.env.transaction.invalidate_access_cache()
        Model = self.env[spec['model']].with_user(spec['user'])
        ids = spec['ids']
        domain = [('id', 'in', ids)]
        records = Model.browse(ids)
        out = {
            'search': self._value(lambda: Model.search(domain, order='id').ids),
            'count': self._value(lambda: Model.search_count(domain)),
            'group': self._value(lambda: sorted(
                (str(group[spec['group']]), group['__count'])
                for group in Model.formatted_read_group(domain, [spec['group']], ['__count']))),
            'name_search': self._value(lambda: sorted(found[0] for found in Model.name_search('MX', domain, limit=100))),
        }
        for operation in OPERATIONS:
            out[f'model_{operation}'] = Model.browse().has_access(operation)
        for operation in ('read', 'write', 'unlink'):
            out[f'filtered_{operation}'] = records._filtered_access(operation).ids
            out[f'has_{operation}'] = [Model.browse(id_).has_access(operation) for id_ in ids]
        out['read_each'] = [self._attempt(lambda: Model.browse(id_).read([spec['read']])) for id_ in ids]
        out['write_each'] = [self._attempt(lambda: Model.browse(id_).write(spec['write'])) for id_ in ids]
        out['unlink_each'] = [self._attempt(lambda: Model.browse(id_).unlink()) for id_ in ids[::3]]
        out['create_match'] = self._attempt(lambda: Model.create({**spec['create'], **(match or {})}))
        out['create_other'] = self._attempt(lambda: Model.create({**spec['create'], **(other or {})}))
        return out

    def _profile(self, spec, config, text, **values):
        model_id = self.env['ir.model']._get(spec['model']).id
        return self.env['gec.access.profile'].create({
            'name': 'MX parity profile', 'user_ids': [Command.set(spec['user'].ids)],
            'model_ids': [Command.create({'model_id': model_id, PROFILE_FIELD[config]: text, **values})],
        })

    def _core_row(self, spec, config, text):
        return self.env['ir.access'].create({
            'name': 'MX parity core row', 'model_id': self.env['ir.model']._get(spec['model']).id,
            'group_id': False, 'operation': CORE_OPERATION[config], 'domain': text,
        })

    def _differences(self, left, right):
        return {key: (left[key], right[key]) for key in left if left[key] != right[key]}

    def _check_parity(self, spec, label, text, match, other, config):
        profile = self._profile(spec, config, text)
        profile_outcomes = self._outcomes(spec, match, other)
        profile.unlink()
        row = self._core_row(spec, config, text)
        core_outcomes = self._outcomes(spec, match, other)
        row.unlink()
        self.assertFalse(
            self._differences(profile_outcomes, core_outcomes),
            f"{spec['model']} shape {label!r} config {config!r} domain {text}: profile and core row differ "
            "as {key: (profile, core)}")

    def _parity_of(self, model_name):
        spec = self._spec(model_name)
        for index, (label, text, match, other) in enumerate(shapes_of(spec)):
            configs = ('all', OPERATIONS[index % 4]) if model_name in HEAVY_MODELS else (CONFIGS[index % 5],)
            for config in configs:
                with self.subTest(model=model_name, shape=label, config=config):
                    self._check_parity(spec, label, text, match, other, config)

    @mute_logger('odoo.sql_db')
    def test_parity_partner(self):
        self._parity_of('res.partner')

    @mute_logger('odoo.sql_db')
    def test_parity_partner_every_operation(self):
        spec = self._spec('res.partner')
        for label, text, match, other in shapes_of(spec):
            if label not in ('eq', 'or', 'child_of', 'any', 'neg'):
                continue
            for config in OPERATIONS:
                with self.subTest(model='res.partner', shape=label, config=config):
                    self._check_parity(spec, label, text, match, other, config)

    @mute_logger('odoo.sql_db')
    def test_parity_partner_category(self):
        self._parity_of('res.partner.category')

    @mute_logger('odoo.sql_db')
    def test_parity_sale_order(self):
        self._parity_of('sale.order')

    @mute_logger('odoo.sql_db')
    def test_parity_account_move(self):
        self._parity_of('account.move')

    @mute_logger('odoo.sql_db')
    def test_parity_stock_picking(self):
        self._parity_of('stock.picking')

    @mute_logger('odoo.sql_db')
    def test_parity_hr_employee(self):
        self._parity_of('hr.employee')

    @mute_logger('odoo.sql_db')
    def test_parity_product_template(self):
        self._parity_of('product.template')

    # the safeguards around the parity

    def _each_spec(self):
        if not self.specs:
            self.skipTest("no model of the matrix is installed")
        for model_name, spec in self.specs.items():
            yield model_name, spec
        for model_name, error in self.spec_errors.items():
            with self.subTest(model=model_name):
                raise error

    def _shape(self, spec, label):
        return next(shape for shape in shapes_of(spec) if shape[0] == label)

    @mute_logger('odoo.sql_db')
    def test_sanity_phases_differ_and_caches_follow(self):
        """ A filter restricts, leaving the profile gives everything back, and the core row restricts the same. """
        spec = self._spec('res.partner')
        _label, text, match, other = self._shape(spec, 'eq')
        open_outcomes = self._outcomes(spec, match, other)
        profile = self._profile(spec, 'all', text)
        restricted = self._outcomes(spec, match, other)
        profile.unlink()
        self.assertEqual(self._outcomes(spec, match, other), open_outcomes)
        row = self._core_row(spec, 'all', text)
        core = self._outcomes(spec, match, other)
        row.unlink()
        self.assertEqual(self._outcomes(spec, match, other), open_outcomes)
        self.assertEqual(restricted, core)
        self.assertNotEqual(restricted['search'], open_outcomes['search'])
        self.assertTrue(restricted['search'], "some fixture partners carry ref A")
        readable = [id_ in open_outcomes['search'] for id_ in spec['ids']]
        self.assertTrue(all(readable[:6]) and not all(readable), "company B partners stay out of reach of the user")
        self.assertEqual(
            [outcome == 'ok' for outcome in open_outcomes['write_each']], readable,
            "the baseline write attempts succeed on every record the user reaches")
        self.assertEqual(open_outcomes['create_match'], 'ok')
        self.assertEqual(open_outcomes['create_other'], 'ok')
        self.assertIn('AccessError', restricted['write_each'])

    @mute_logger('odoo.sql_db')
    def test_archived_profile_gives_the_baseline(self):
        spec = self._spec('res.partner')
        _label, text, match, other = self._shape(spec, 'eq')
        baseline = self._outcomes(spec, match, other)
        profile = self._profile(spec, 'all', text)
        self.assertNotEqual(self._outcomes(spec, match, other)['search'], baseline['search'])
        profile.active = False
        self.assertEqual(self._outcomes(spec, match, other), baseline)

    @mute_logger('odoo.sql_db')
    def test_never_wider_than_core(self):
        """ A line with every right and no filter, or the filter [], changes nothing. """
        for model_name, spec in self._each_spec():
            with self.subTest(model=model_name):
                baseline = self._outcomes(spec)
                for text in (None, '[]'):
                    profile = self._profile(spec, 'all', text)
                    outcomes = self._outcomes(spec)
                    profile.unlink()
                    self.assertFalse(self._differences(baseline, outcomes), f"{model_name} with filter {text!r}")

    @mute_logger('odoo.sql_db')
    def test_profile_cannot_undo_a_core_restriction(self):
        for model_name, spec in self._each_spec():
            _label, text, match, other = self._shape(spec, 'eq')
            with self.subTest(model=model_name):
                row = self._core_row(spec, 'all', text)
                core = self._outcomes(spec, match, other)
                profile = self._profile(spec, 'all', '[]')
                with_profile = self._outcomes(spec, match, other)
                profile.unlink()
                row.unlink()
                self.assertFalse(self._differences(core, with_profile), model_name)

    @mute_logger('odoo.sql_db')
    def test_core_restriction_and_profile_filter_combine_as_and(self):
        for model_name, spec in self._each_spec():
            _label, first, match, other = self._shape(spec, 'eq')
            second = self._shape(spec, 'or')[1]
            with self.subTest(model=model_name):
                first_row = self._core_row(spec, 'all', first)
                profile = self._profile(spec, 'all', second)
                with_profile = self._outcomes(spec, match, other)
                profile.unlink()
                second_row = self._core_row(spec, 'all', second)
                core = self._outcomes(spec, match, other)
                (first_row | second_row).unlink()
                self.assertFalse(self._differences(with_profile, core), model_name)

    @mute_logger('odoo.sql_db')
    def test_a_refused_right_is_no_access_at_all(self):
        for model_name, spec in self._each_spec():
            Model = self.env[model_name].with_user(spec['user'])
            baseline = self._outcomes(spec)
            for operation in OPERATIONS:
                with self.subTest(model=model_name, operation=operation):
                    profile = self._profile(spec, 'all', None, **{f'perm_{operation}': False})
                    outcomes = self._outcomes(spec)
                    with self.assertRaises(AccessError):
                        Model.browse().check_access(operation)
                    profile.unlink()
                    self.assertFalse(outcomes[f'model_{operation}'])
                    if operation == 'read':
                        if not spec.get('public_read'):
                            self.assertEqual(outcomes['search'], 'AccessError')
                            self.assertEqual(outcomes['count'], 'AccessError')
                            self.assertEqual(set(outcomes['read_each']), {'AccessError'})
                        self.assertFalse(any(outcomes['has_read']))
                    elif operation == 'create':
                        self.assertEqual((outcomes['create_match'], outcomes['create_other']),
                                         ('AccessError', 'AccessError'))
                    else:
                        self.assertEqual(outcomes[f'filtered_{operation}'], [])
                        self.assertEqual(set(outcomes[f'{operation}_each']), {'AccessError'})
                        self.assertFalse(any(outcomes[f'has_{operation}']))
                        self.assertEqual(outcomes['search'], baseline['search'], "the other rights are untouched")

    # the documented exceptions and refusals

    def test_a_user_always_reads_their_own_partner(self):
        """ The profile filter is OR-ed with the user's own contact for reading only (base_model.py). """
        spec = self._spec('res.partner')
        user = spec['user']
        Partner = self.env['res.partner'].with_user(user)
        self._profile(spec, 'all', "[('id', '=', 0)]")
        own = Partner.browse(user.partner_id.id)
        self.assertEqual(Partner.search([('id', '=', own.id)]), own)
        self.assertTrue(own.read(['name']))
        self.assertTrue(own.has_access('read'))
        self.assertFalse(own.has_access('write'), "only reading is spared")
        with self.assertRaises(AccessError):
            own.write({'function': 'MX self edit'})
        self.assertFalse(Partner.search([('id', 'in', spec['ids'])]), "no other contact stays readable")
        self.assertTrue(self.env['res.users'].with_user(user).browse(user.id).read(['name']), "their own user too")

    def test_the_core_row_has_no_own_partner_exception(self):
        """ The exception belongs to profiles: the same filter as a core row hides the user's own contact. """
        spec = self._spec('res.partner')
        user = spec['user']
        self._core_row(spec, 'all', "[('id', '=', 0)]")
        own = self.env['res.partner'].with_user(user).browse(user.partner_id.id)
        self.assertFalse(own.has_access('read'))

    def test_a_filter_with_a_call_is_refused_where_a_core_row_takes_it(self):
        """ time.strftime works in a core row; a profile filter is never run as Python, so it is refused. """
        spec = self._spec('res.partner')
        text = "[('create_date', '>=', time.strftime('%Y-%m-%d'))]"
        self._core_row(spec, 'all', text)
        with self.assertRaises(ValidationError):
            self._profile(spec, 'all', text)
