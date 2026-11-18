# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from . import models
from . import report


def _uninstall_hook(env):
    # the Overview menu of hr_holidays is routed to this module's server action:
    # give it back its original action, else the menu disappears
    menu = env.ref('hr_holidays.menu_hr_holidays_dashboard', raise_if_not_found=False)
    dashboard_action = env.ref('hr_holidays.action_hr_holidays_dashboard', raise_if_not_found=False)
    if menu and dashboard_action:
        menu.action = dashboard_action
