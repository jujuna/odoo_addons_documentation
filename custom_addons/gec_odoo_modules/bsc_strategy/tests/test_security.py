# -*- coding: utf-8 -*-
"""Who may do what - the rules beyond the access-rights table (bsc_security.py)."""
from datetime import date, datetime, timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)

        def user(login, group):
            return Users.create({'name': login, 'login': login,
                                 'group_ids': [(6, 0, [cls.env.ref(group).id])]})
        cls.contrib = user('sec_contrib', 'bsc_strategy.group_bsc_contributor')
        cls.other = user('sec_other', 'bsc_strategy.group_bsc_contributor')
        cls.manager = user('sec_manager', 'bsc_strategy.group_bsc_manager')
        year = date.today().year
        cls.card = cls.env['bsc.scorecard'].create({
            'name': 'Sec', 'date_from': date(year, 1, 1), 'date_to': date(year, 12, 31),
            'frequency': 'quarterly', 'responsible_id': cls.manager.id})
        cls.objective = cls.env['bsc.objective'].create({
            'name': 'O', 'scorecard_id': cls.card.id, 'owner_id': cls.contrib.id,
            'perspective_id': cls.env.ref('bsc_strategy.perspective_financial').id})
        cls.kpi = cls.env['bsc.kpi'].create({
            'name': 'K', 'objective_id': cls.objective.id, 'owner_id': cls.contrib.id,
            'default_target': 100})
        cls.kpi_other = cls.env['bsc.kpi'].create({
            'name': 'K2', 'objective_id': cls.objective.id, 'owner_id': cls.other.id,
            'default_target': 100})
        cls.card.action_activate()
        cls.first = cls.card.period_ids.sorted('date_from')[0]
        cls.first.measurement_ids.write({'actual_value': 100})
        cls.first.action_close()
        current = cls.card.current_period_id
        cls.row = current.measurement_ids.filtered(lambda m: m.kpi_id == cls.kpi)
        cls.row_other = current.measurement_ids.filtered(lambda m: m.kpi_id == cls.kpi_other)
        cls.closed_row = cls.first.measurement_ids.filtered(lambda m: m.kpi_id == cls.kpi)

    def _stage(self, state):
        return self.env['bsc.initiative.stage'].search([('state', '=', state)], limit=1)

    def test_contributor_reports_but_does_not_judge(self):
        row = self.row.with_user(self.contrib)
        row.write({'actual_value': 100})
        row.action_submit()
        with self.assertRaises(AccessError):
            row.write({'target_value': 1})
        with self.assertRaises(AccessError):
            row.action_validate()
        with self.assertRaises(AccessError):
            row.write({'state': 'validated'})
        with self.assertRaises(AccessError):
            self.row_other.with_user(self.contrib).write({'actual_value': 1})
        self.row.with_user(self.manager).action_validate()
        with self.assertRaises(AccessError):
            row.write({'actual_value': 50, 'comment': 'changed after sign-off'})

    def test_context_keys_are_not_trusted(self):
        with self.assertRaises(UserError):
            self.closed_row.with_user(self.manager).with_context(
                bsc_bypass_period_lock=True).write({'actual_value': 5, 'comment': 'c'})
        with self.assertRaises(AccessError):
            self.row.with_user(self.contrib).with_context(bsc_automated_write=True).write(
                {'actual_value': 1, 'is_automated': True, 'auto_state': 'ok'})

    def test_only_an_administrator_reopens_a_period(self):
        with self.assertRaises(UserError):
            self.first.with_user(self.manager).action_reopen()
        with self.assertRaises(AccessError):
            self.first.with_user(self.manager).write({'state': 'open'})
        self.first.with_user(self.env.ref('base.user_admin')).action_reopen()
        self.assertEqual(self.first.state, 'open')

    def test_contributor_proposes_manager_approves(self):
        initiative = self.env['bsc.initiative'].with_user(self.contrib).create({
            'name': 'Mine', 'scorecard_id': self.card.id, 'budget_planned': 10,
            'objective_ids': [(6, 0, self.objective.ids)]})
        with self.assertRaises(AccessError):
            initiative.write({'stage_id': self._stage('approved').id})
        with self.assertRaises(AccessError):
            initiative.write({'approved_by_id': self.manager.id})
        with self.assertRaises(AccessError):
            self.env['bsc.initiative'].with_user(self.contrib).create({
                'name': 'Pre-approved', 'scorecard_id': self.card.id,
                'stage_id': self._stage('approved').id,
                'objective_ids': [(6, 0, self.objective.ids)]})
        initiative.with_user(self.manager).write({'stage_id': self._stage('approved').id})
        self.assertEqual(initiative.approved_by_id, self.manager)
        with self.assertRaises(AccessError):
            initiative.with_user(self.contrib).write({'budget_planned': 1000})
        initiative.with_user(self.contrib).write({'progress': 30})

    def test_demo_flag_cannot_be_set_by_hand(self):
        with self.assertRaises(AccessError):
            self.card.with_user(self.manager).write({'is_demo': True})

    def test_filter_cannot_reach_hidden_records(self):
        self.env['res.users.apikeys'].with_user(self.other)._generate(
            None, 'key', datetime.now() + timedelta(days=5))
        source = self.env['bsc.kpi.source'].create({
            'name': 'Keys', 'model_id': self.env['ir.model']._get('res.users.apikeys').id,
            'date_field_id': self.env['ir.model.fields']._get('res.users.apikeys', 'create_date').id})
        kpi = self.kpi.with_user(self.manager)
        kpi.write({'data_source': 'odoo', 'source_id': source.id})
        with self.assertRaises(AccessError):
            kpi.write({'source_extra_domain': "[('name', '!=', False)]"})

    def test_contributor_can_comment(self):
        self.card.with_user(self.contrib).message_post(body='A question')
