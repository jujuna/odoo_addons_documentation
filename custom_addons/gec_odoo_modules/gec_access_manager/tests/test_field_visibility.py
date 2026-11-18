from itertools import product

from lxml import etree

from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval

from .test_round2_fixes import client_call


@tagged('post_install', '-at_install')
class TestFieldVisibility(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(cls.env, 'gec_field_visibility', groups='base.group_user,base.group_partner_manager')
        cls.Profile = cls.env['gec.access.profile']

    def _profile(self, field='email', model='res.partner', mode='hide', condition=False, strictness='override'):
        return self.Profile.create({
            'name': 'Field visibility', 'strictness': strictness, 'user_ids': [Command.set(self.user.ids)],
            'field_ids': [Command.create({
                'model_id': self.env['ir.model']._get(model).id,
                'field_id': self.env['ir.model.fields']._get(model, field).id,
                'mode': mode, 'condition': condition,
            })],
        })

    def _rewrite(self, xml, model='res.partner'):
        tree = etree.fromstring(xml)
        profile = self.Profile.with_user(self.user)
        self.added = profile._apply_view_rules(profile._current_rules(), tree, model, tree.tag)
        return tree

    def test_explicit_labels_before_and_after_duplicate_fields(self):
        self._profile()
        tree = self._rewrite('''<form><group>
            <label for="email" invisible="not active"/><field name="email" nolabel="1"/>
            <field name="email" nolabel="1"/><label for="email" invisible="active"/>
            <field name="phone"/><label for="phone"/>
        </group></form>''')
        self.assertEqual([node.get('invisible') for node in tree.xpath('//label[@for="email"]')], ['1', '1'])
        self.assertEqual([node.get('invisible') for node in tree.xpath('//field[@name="email"]')], ['1', '1'])
        self.assertIsNone(tree.xpath('//label[@for="phone"]')[0].get('invisible'))
        self.assertEqual(len(tree.xpath('//field[@name="email"]')), 2)

    def test_explicit_field_ids_select_their_own_labels(self):
        self._profile()
        tree = self._rewrite('''<form><group>
            <label for="first"/><field name="email" id="first"/>
            <field name="email" id="second"/><label for="second"/>
            <field name="phone" id="email"/><label for="email"/>
        </group></form>''')
        self.assertEqual([node.get('invisible') for node in tree.xpath('//label')], ['1', '1', None])

    def test_non_hidden_modes_leave_labels_and_wrappers_alone(self):
        for mode in ('keep', 'readonly', 'required'):
            with self.subTest(mode=mode):
                profile = self._profile(mode=mode)
                tree = self._rewrite('''<form><group>
                    <div class="o_td_label"><label for="email" invisible="not active"/></div>
                    <div class="o_row"><field name="email"/></div>
                </group></form>''')
                self.assertEqual(tree.find('.//label').get('invisible'), 'not active')
                self.assertTrue(all(node.get('invisible') is None for node in tree.iter('div')))
                profile.unlink()

    def test_unmatched_label_is_not_inferred_from_rules_without_a_target(self):
        self._profile()
        tree = self._rewrite('<form><label for="missing"/><field name="email" id="email_widget"/></form>')
        self.assertIsNone(tree.find('label').get('invisible'))

    def test_label_after_an_id_field_can_use_the_field_name(self):
        self._profile()
        tree = self._rewrite('<form><field name="email" id="email_input"/><label for="email"/></form>')
        self.assertEqual(tree.find('label').get('invisible'), '1')

    def test_same_model_subview_id_collision_does_not_hide_another_field_label(self):
        self._profile()
        tree = self._rewrite('''<form><label for="contact"/><field name="email" id="contact"/>
            <field name="child_ids"><form><label for="contact"/><field name="phone" id="contact"/></form></field>
        </form>''')
        self.assertEqual(tree.find('label').get('invisible'), '1')
        self.assertIsNone(tree.find('.//field/form/label').get('invisible'))

    def test_nested_comodel_rules_do_not_change_parent_labels(self):
        self._profile('name', model='res.partner.category')
        tree = self._rewrite('''<form><label for="name"/><field name="name"/>
            <field name="category_id"><form><label for="name"/><field name="name"/></form></field>
        </form>''')
        self.assertIsNone(tree.find('label').get('invisible'))
        self.assertEqual(tree.find('.//field/form/label').get('invisible'), '1')

    def test_sibling_subviews_keep_label_targets_separate(self):
        self._profile()
        tree = self._rewrite('''<form>
            <field name="child_ids"><form><label for="same"/><field name="email" id="same"/></form></field>
            <field name="child_ids"><form><label for="same"/><field name="phone" id="same"/></form></field>
        </form>''')
        self.assertEqual([node.get('invisible') for node in tree.iter('label')], ['1', None])

    def test_conditional_labels_preserve_native_conditions_and_load_dependencies(self):
        self._profile(condition="ref == 'hide'")
        tree = self._rewrite('''<form><label for="email" invisible="not active"/>
            <field name="email" invisible="phone == 'private'"/><field name="active"/><field name="phone"/>
        </form>''')
        expression = tree.find('label').get('invisible')
        for active, ref in product((False, True), ('hide', 'show')):
            with self.subTest(active=active, ref=ref):
                self.assertEqual(bool(safe_eval(expression, {'active': active, 'ref': ref})),
                                 not active or ref == 'hide')
        self.assertNotIn('phone', expression)
        self.assertEqual(len(tree.xpath('./field[@name="ref"]')), 1)
        self.assertEqual(self.added, {'res.partner': {'ref'}})

    def test_duplicate_occurrences_do_not_repeat_the_profile_condition(self):
        self._profile(condition="ref == 'hide'")
        tree = self._rewrite('''<form><label for="email"/>
            <field name="email" invisible="active"/><field name="email" invisible="not active"/>
        </form>''')
        expression = tree.find('label').get('invisible')
        self.assertEqual(expression.count("ref == 'hide'"), 1)
        self.assertFalse(safe_eval(expression, {'ref': 'show'}))
        self.assertTrue(safe_eval(expression, {'ref': 'hide'}))

    def test_additive_and_override_conditions_match_field_and_label(self):
        self._profile(condition="ref == 'hide'", strictness='additive')
        self._profile(condition='not active', strictness='additive')
        self._profile(condition='color == 3')
        tree = self._rewrite('<form><label for="email"/><field name="email"/></form>')
        field_expression = tree.find('field').get('invisible')
        label_expression = tree.find('label').get('invisible')
        for ref, active, color in product(('hide', 'show'), (False, True), (0, 3)):
            values = {'ref': ref, 'active': active, 'color': color}
            with self.subTest(**values):
                expected = (ref == 'hide' and not active) or color == 3
                self.assertEqual(bool(safe_eval(field_expression, values)), expected)
                self.assertEqual(bool(safe_eval(label_expression, values)), expected)

    def test_permissive_additive_profile_restores_both_field_and_label(self):
        self._profile(strictness='additive')
        self.Profile.create({'name': 'Permissive', 'user_ids': [Command.set(self.user.ids)]})
        tree = self._rewrite('<form><label for="email"/><field name="email"/></form>')
        self.assertIsNone(tree.find('field').get('invisible'))
        self.assertIsNone(tree.find('label').get('invisible'))

    def test_dedicated_label_and_value_wrappers_disappear(self):
        self._profile()
        for classes in ('o_td_label', 'o_wrap_label extra'):
            with self.subTest(classes=classes):
                tree = self._rewrite(f'''<form><group>
                    <div class="{classes}"><label for="email"/></div>
                    <div class="o_row align-items-center"><field name="email"/></div>
                </group></form>''')
                self.assertEqual([node.get('invisible') for node in tree.iter('div')], ['1', '1'])
                self.assertIsNone(tree.find('group').get('invisible'))

    def test_conditional_wrapper_requires_all_fields_hidden(self):
        self._profile(condition="ref == 'hide'")
        self._profile('phone', condition='color == 3')
        tree = self._rewrite('''<form>
            <div class="o_td_label" invisible="not active"><label for="email"/><label for="phone"/></div>
            <div class="o_row" invisible="not active"><field name="email"/><field name="phone"/></div>
        </form>''')
        for ref, color, active in product(('hide', 'show'), (0, 3), (False, True)):
            values = {'ref': ref, 'color': color, 'active': active}
            with self.subTest(**values):
                expected = not active or (ref == 'hide' and color == 3)
                for node in tree.iter('div'):
                    self.assertEqual(bool(safe_eval(node.get('invisible'), values)), expected)

    def test_shared_labels_and_value_rows_keep_unrestricted_content(self):
        self._profile()
        tree = self._rewrite('''<form>
            <div class="o_td_label"><label for="email"/><label for="phone"/></div>
            <div class="o_row"><field name="email"/><field name="phone" widget="badge"/></div>
        </form>''')
        self.assertEqual(tree.find('.//label').get('invisible'), '1')
        self.assertIsNone(tree.xpath('//label[@for="phone"]')[0].get('invisible'))
        self.assertTrue(all(node.get('invisible') is None for node in tree.iter('div')))
        self.assertIsNone(tree.xpath('//field[@name="phone"]')[0].get('invisible'))

    def test_text_buttons_widgets_and_other_children_prevent_wrapper_hiding(self):
        self._profile()
        contents = (
            'Text<field name="email"/>', '<field name="email"/> days',
            '<field name="email"/><span>or</span>', '<field name="email"/><button name="action_archive"/>',
            '<field name="email"/><widget name="web_ribbon"/>',
        )
        for content in contents:
            with self.subTest(content=content):
                tree = self._rewrite(f'<form><div class="o_row">{content}</div></form>')
                self.assertIsNone(tree.find('div').get('invisible'))
                self.assertEqual(tree.find('.//field').get('invisible'), '1')
        tree = self._rewrite('''<form><div class="o_td_label"><label for="email"/><span>Help</span></div>
            <field name="email"/></form>''')
        self.assertIsNone(tree.find('div').get('invisible'))

    def test_arbitrary_and_template_wrappers_are_not_collapsed(self):
        self._profile()
        for attributes in ('class="custom"', 'class="o_row" t-out="extra_content"'):
            with self.subTest(attributes=attributes):
                tree = self._rewrite(f'<form><div {attributes}><field name="email"/></div></form>')
                self.assertIsNone(tree.find('div').get('invisible'))

    def test_normal_columns_and_search_fields_keep_existing_behavior(self):
        self._profile()
        tree = self._rewrite('<list><field name="email" sum="Total" required="1"/><field name="phone"/></list>')
        hidden = tree.find('field')
        self.assertEqual(hidden.get('column_invisible'), '1')
        self.assertEqual(hidden.get('readonly'), '1')
        self.assertNotIn('sum', hidden.attrib)
        self.assertNotIn('required', hidden.attrib)
        self.assertIsNone(tree.xpath('./field[@name="phone"]')[0].get('column_invisible'))
        search = self._rewrite('<search><field name="email"/><field name="phone"/></search>')
        self.assertEqual([node.get('name') for node in search.iter('field')], ['phone'])

    def test_stacked_column_hides_child_and_optional_entry_without_hiding_sibling(self):
        self._profile()
        tree = self._rewrite('''<list><column name="contact" column_invisible="parent.active">
            <field name="email" optional="show"/><field name="phone" optional="hide"/>
        </column></list>''')
        hidden, visible = tree.findall('.//field')
        self.assertEqual((hidden.get('invisible'), hidden.get('column_invisible')), ('1', '1'))
        self.assertIsNone(hidden.get('optional'))
        self.assertEqual(visible.get('optional'), 'hide')
        self.assertIsNone(visible.get('invisible'))
        self.assertEqual(tree.find('column').get('column_invisible'), 'parent.active')

    def test_all_hidden_stacked_children_hide_the_header(self):
        self._profile()
        self._profile('phone')
        tree = self._rewrite('''<list><column name="contact" column_invisible="parent.active">
            <field name="email" optional="show"/><field name="phone" optional="hide"/>
        </column></list>''')
        self.assertEqual(tree.find('column').get('column_invisible'), '1')
        self.assertTrue(all(node.get('invisible') == '1' for node in tree.iter('field')))
        self.assertTrue(all(node.get('optional') is None for node in tree.iter('field')))

    def test_conditional_stacked_child_keeps_header_and_optional_toggle(self):
        self._profile(condition="ref == 'hide'")
        tree = self._rewrite('<list><column><field name="email" optional="show"/></column></list>')
        column, field = tree.find('column'), tree.find('column/field')
        self.assertIsNone(column.get('column_invisible'))
        self.assertIsNone(field.get('column_invisible'))
        self.assertEqual(field.get('optional'), 'show')
        self.assertTrue(safe_eval(field.get('invisible'), {'ref': 'hide'}))
        self.assertFalse(safe_eval(field.get('invisible'), {'ref': 'show'}))

    def test_groupby_fields_follow_the_comodel(self):
        self._profile('name', model='res.country')
        tree = self._rewrite('''<list><field name="name"/>
            <groupby name="country_id"><field name="name"/></groupby>
        </list>''')
        self.assertIsNone(tree.find('field').get('column_invisible'))
        self.assertEqual(tree.find('groupby/field').get('invisible'), '1')
        self.assertIsNone(tree.find('groupby/field').get('column_invisible'))

    def test_groupby_condition_dependencies_stay_in_comodel_scope(self):
        self._profile('name', model='res.country', condition="code == 'BE'")
        tree = self._rewrite('''<list><field name="name"/><groupby name="country_id"><field name="name"/></groupby>
            <groupby name="parent_id"><field name="name"/></groupby>
        </list>''')
        self.assertFalse(tree.xpath('./field[@name="code"]'))
        self.assertFalse(tree.xpath('./groupby[@name="parent_id"]/field[@name="code"]'))
        self.assertEqual(len(tree.xpath('./groupby[@name="country_id"]/field[@name="code"]')), 1)
        self.assertEqual(self.added, {'res.country': {'code'}})
        field = tree.xpath('./groupby[@name="country_id"]/field[@name="name"]')[0]
        self.assertTrue(safe_eval(field.get('invisible'), {'code': 'BE'}))
        self.assertFalse(safe_eval(field.get('invisible'), {'code': 'FR'}))

    def test_nested_condition_dependencies_are_loaded_in_each_subview(self):
        self._profile(condition="ref == 'hide'")
        tree = self._rewrite('''<form><label for="email"/><field name="email"/>
            <field name="child_ids"><form><label for="email"/><field name="email"/></form></field>
        </form>''')
        self.assertEqual(len(tree.xpath('./field[@name="ref"]')), 1)
        self.assertEqual(len(tree.xpath('./field/form/field[@name="ref"]')), 1)
        self.assertEqual([node.get('invisible') for node in tree.iter('label')], ["ref == 'hide'"] * 2)

    def test_setting_tiles_and_card_static_labels_are_not_inferred(self):
        self._profile()
        tree = self._rewrite('''<form><setting string="Contact" help="Shared help">
            <field name="email"/></setting></form>''')
        self.assertIsNone(tree.find('setting').get('invisible'))
        self.assertEqual(tree.find('setting').get('string'), 'Contact')
        card = self._rewrite('''<kanban><card><div><span>Email</span><field name="email"/></div></card></kanban>''')
        self.assertEqual(card.find('.//field').get('invisible'), '1')
        self.assertIsNone(card.find('.//span').get('invisible'))
        self.assertIsNone(card.find('.//div').get('invisible'))

    def test_get_view_is_user_specific_and_preserves_the_core_cached_arch(self):
        self._profile()
        view = self.env['ir.ui.view'].create({
            'name': 'gec.visibility.form', 'model': 'res.partner', 'type': 'form',
            'arch': '<form><group><label for="email"/><field name="email" nolabel="1"/></group></form>',
        })
        partners = self.env['res.partner']
        before = partners.get_view(view.id, 'form')['arch']
        result = partners.with_user(self.user).get_view(view.id, 'form')
        tree = etree.fromstring(result['arch'])
        self.assertEqual(tree.find('.//label').get('invisible'), '1')
        self.assertEqual(tree.find('.//field').get('invisible'), '1')
        self.assertEqual(partners.get_view(view.id, 'form')['arch'], before)
        self.assertIsNone(etree.fromstring(before).find('.//label').get('invisible'))

    def test_conditional_hidden_values_are_still_blanked_in_client_batch_reads(self):
        self._profile(condition="ref == 'hide'")
        partners = self.env['res.partner'].create([
            {'name': 'Hidden email', 'ref': 'hide', 'email': 'secret@example.com'},
            {'name': 'Visible email', 'ref': 'show', 'email': 'visible@example.com'},
        ])
        with client_call('res.partner', 'read'):
            rows = partners.with_user(self.user).read(['email', 'ref'])
        self.assertEqual([row['email'] for row in rows], [False, 'visible@example.com'])
        tree = self._rewrite('<form><label for="email"/><field name="email"/></form>')
        expression = tree.find('label').get('invisible')
        self.assertEqual([bool(safe_eval(expression, {'ref': row['ref']})) for row in rows], [True, False])
        self.assertEqual(partners[0].email, 'secret@example.com')
