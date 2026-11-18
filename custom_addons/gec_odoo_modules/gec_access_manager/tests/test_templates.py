# The ready-made profiles: the app-agnostic recipes, plus a test recipe for the
# parts that must be skipped and reported.
from odoo.tests import Form, TransactionCase, new_test_user, tagged

from odoo.addons.gec_access_manager.models.gec_access_templates import TEMPLATES, TEMPLATES_BY_KEY


@tagged('post_install', '-at_install')
class TestTemplates(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_access_template_user', groups='base.group_user')
        cls.discuss = cls.env.ref('mail.menu_root_discuss')

    def _create(self, key, **values):
        form = Form(self.env['gec.access.template.wizard'])
        form.template_key = key
        for name, value in values.items():
            setattr(form, name, value)
        action = form.save().action_create()
        return self.env['gec.access.profile'].browse(action['res_id'])

    def _add_recipe(self, recipe):
        TEMPLATES.append(recipe)
        TEMPLATES_BY_KEY[recipe['key']] = recipe
        self.addCleanup(TEMPLATES.remove, recipe)
        self.addCleanup(TEMPLATES_BY_KEY.pop, recipe['key'])

    def test_only_the_templates_of_installed_apps_are_offered(self):
        installed = self.env['ir.module.module']._installed()
        offered = {key for key, _label in self.env['gec.access.template.wizard']._selection_templates()}
        self.assertTrue({'auditor', 'app_user', 'app_readonly'} <= offered)
        for template in TEMPLATES:
            expected = all(module in installed for module in template['requires'])
            self.assertEqual(template['key'] in offered, expected, template['key'])

    def test_auditor(self):
        profile = self._create('auditor', user_ids=self.user)
        self.assertEqual(profile.name, 'Auditor')
        self.assertTrue(profile.global_readonly and profile.block_export and profile.block_import)
        self.assertIn('Created from the template Auditor', profile.note)
        Partner = self.env['res.partner'].with_user(self.user).browse()
        self.assertTrue(Partner.has_access('read'))
        self.assertFalse(Partner.has_access('write'))

    def test_accountant_on_enterprise_accounting(self):
        if not self.env.ref('accountant.menu_accounting', raise_if_not_found=False):
            self.skipTest("accountant is not installed")
        accountant = new_test_user(
            self.env, 'gec_access_accountant_user', groups='base.group_user,account.group_account_manager')
        profile = self._create('accountant', user_ids=accountant)
        configuration = self.env.ref('account.menu_finance_configuration')
        self.assertIn(configuration, profile.hidden_menu_ids)

        def can(model_name, operation):
            return self.env[model_name].with_user(accountant).browse().has_access(operation)

        for model_name in ('account.account', 'account.tax', 'account.journal'):
            with self.subTest(model=model_name):
                self.assertEqual((can(model_name, 'read'), can(model_name, 'write')), (True, False))
        self.assertFalse(profile.model_ids.filtered(lambda row: row.model_id.model == 'account.move'))
        self.assertTrue(can('account.move', 'create'))
        for model_name in ('account.online.link', 'account.online.account'):
            if model_name in self.env:
                with self.subTest(model=model_name):
                    self.assertTrue(can(model_name, 'write'))
                    # no row of its own: a row would hide the profile's menu rules from the model
                    self.assertFalse(profile.model_ids.filtered(lambda row: row.model_id.model == model_name))

    def test_app_user_on_enterprise_accounting_keeps_bank_sync(self):
        accounting = self.env.ref('accountant.menu_accounting', raise_if_not_found=False)
        if not accounting or 'account.online.link' not in self.env:
            self.skipTest("accountant or online bank sync is not installed")
        accountant = new_test_user(
            self.env, 'gec_access_app_user_accountant', groups='base.group_user,account.group_account_manager')
        profile = self._create('app_user', app_id=accounting, user_ids=accountant)

        def can(model_name, operation):
            return self.env[model_name].with_user(accountant).browse().has_access(operation)

        self.assertFalse(can('account.tax', 'write'))
        for model_name in ('account.online.link', 'account.online.account'):
            with self.subTest(model=model_name):
                self.assertTrue(can(model_name, 'write'))
                self.assertFalse(profile.model_ids.filtered(lambda row: row.model_id.model == model_name))

    def test_a_template_for_any_app(self):
        profile = self._create('app_readonly', app_id=self.discuss, user_ids=self.user)
        self.assertEqual(profile.name, 'Discuss: App Read Only')
        Channel = self.env['discuss.channel'].with_user(self.user).browse()
        self.assertTrue(Channel.has_access('read'))
        self.assertFalse(Channel.has_access('write'))

    def test_missing_parts_are_skipped_and_reported(self):
        self._add_recipe({
            'key': 'gec_test_recipe',
            'name': 'Test Recipe',
            'description': 'A recipe of the tests.',
            'requires': [],
            'apps': [
                {'app': 'mail.menu_root_discuss', 'level': 'none'},
                {'app': 'gec_not_installed.menu_root', 'level': 'user', 'optional': True},
            ],
            'hide_menus': ['base.menu_administration', 'gec_not_installed.menu_other'],
            'fields': [('res.partner', 'email', 'hide'), ('res.partner', 'gec_no_such_field', 'hide'),
                       ('gec.no.such.model', 'name', 'hide')],
            'switches': {'block_export': True},
        })
        profile = self._create('gec_test_recipe')
        self.assertTrue(profile.block_export)
        self.assertEqual(profile.hidden_menu_ids, self.discuss | self.env.ref('base.menu_administration'))
        self.assertEqual(profile.field_ids.field_id.name, 'email')
        self.assertIn('gec_not_installed is not installed', profile.note)
        self.assertIn('gec_no_such_field', profile.note)
        # what is not installed at all is no news: the model of an absent app
        self.assertNotIn('gec.no.such.model', profile.note)
        self.assertNotIn('menu_other', profile.note)

    def test_the_profile_stays_an_ordinary_one(self):
        profile = self._create('app_user', app_id=self.discuss)
        profile.model_ids.unlink()
        profile.hidden_menu_ids = False
        self.assertFalse(profile.model_ids or profile.hidden_menu_ids)
