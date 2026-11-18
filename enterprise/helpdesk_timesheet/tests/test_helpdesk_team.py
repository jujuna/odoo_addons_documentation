# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('-at_install', 'post_install')
class TestHelpdeskTeamGroups(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.feature_group = cls.env.ref('helpdesk_timesheet.group_use_helpdesk_timesheet')
        cls.helpdesk_user_group = cls.env.ref('helpdesk.group_helpdesk_user')
        cls.user_groups = (
            cls.helpdesk_user_group
            + cls.env.ref('hr_timesheet.group_hr_timesheet_user')
        )
        cls.enabled_team, cls.disabled_team = cls.env['helpdesk.team'].create([
            {'name': 'Timesheet team', 'use_helpdesk_timesheet': True},
            {'name': 'No timesheets', 'use_helpdesk_timesheet': False},
        ])
        cls.feature_user = new_test_user(cls.env, login='helpdesk_feature_user', groups='base.group_user')

    def test_enable_timesheet_group(self):
        """Restore a missing group link even when the caller already has timesheet access."""
        self.user_groups.write({'implied_ids': [Command.link(self.feature_group.id)]})
        self.helpdesk_user_group.write({'implied_ids': [Command.unlink(self.feature_group.id)]})
        self.feature_group.write({'user_ids': [Command.link(self.feature_user.id)]})

        self.enabled_team.with_user(self.feature_user).sudo()._check_timesheet_group()

        for group in self.user_groups:
            self.assertIn(self.feature_group, group.implied_ids)

    def test_enable_timesheet_group_with_indirect_link(self):
        """Restore the direct implication even when an indirect path already exists."""
        intermediate_group = self.env['res.groups'].create({
            'name': 'Shared timesheet group',
            'implied_ids': [Command.link(self.feature_group.id)],
        })
        self.user_groups.write({'implied_ids': [Command.link(self.feature_group.id)]})
        self.helpdesk_user_group.write({'implied_ids': [
            Command.unlink(self.feature_group.id),
            Command.link(intermediate_group.id),
        ]})

        self.enabled_team._check_timesheet_group()

        for group in self.user_groups:
            self.assertIn(self.feature_group, group.implied_ids)
        self.assertIn(intermediate_group, self.helpdesk_user_group.implied_ids)
        self.assertIn(self.feature_group, intermediate_group.implied_ids)

    def test_disable_timesheet_group(self):
        """Remove group links and all memberships when no team uses timesheets."""
        self.env['helpdesk.team'].search([('use_helpdesk_timesheet', '=', True)]).write({
            'use_helpdesk_timesheet': False,
        })
        self.user_groups.write({'implied_ids': [Command.link(self.feature_group.id)]})
        self.feature_group.write({'user_ids': [Command.link(self.feature_user.id)]})
        self.assertIn(self.feature_user, self.feature_group.user_ids)

        self.disabled_team._check_timesheet_group()

        for group in self.user_groups:
            self.assertNotIn(self.feature_group, group.implied_ids)
        self.assertFalse(self.feature_group.user_ids)

    def test_disable_timesheet_group_preserves_indirect_links(self):
        """Disabling timesheets must not change an intermediate group's implications."""
        self.env['helpdesk.team'].search([('use_helpdesk_timesheet', '=', True)]).write({
            'use_helpdesk_timesheet': False,
        })
        intermediate_group = self.env['res.groups'].create({
            'name': 'Shared timesheet group',
            'implied_ids': [Command.link(self.feature_group.id)],
        })
        self.user_groups.write({'implied_ids': [Command.link(self.feature_group.id)]})
        self.helpdesk_user_group.write({'implied_ids': [Command.link(intermediate_group.id)]})

        self.disabled_team._check_timesheet_group()

        for group in self.user_groups:
            self.assertNotIn(self.feature_group, group.implied_ids)
        self.assertIn(intermediate_group, self.helpdesk_user_group.implied_ids)
        self.assertIn(self.feature_group, intermediate_group.implied_ids)

    def test_disabled_team_preserves_timesheet_group_for_other_teams(self):
        """Keep timesheet access while another team still uses timesheets."""
        self.user_groups.write({'implied_ids': [Command.link(self.feature_group.id)]})
        self.feature_group.write({'user_ids': [Command.link(self.feature_user.id)]})
        self.assertIn(self.feature_user, self.feature_group.user_ids)

        self.disabled_team._check_timesheet_group()

        for group in self.user_groups:
            self.assertIn(self.feature_group, group.implied_ids)
        self.assertIn(self.feature_user, self.feature_group.user_ids)
