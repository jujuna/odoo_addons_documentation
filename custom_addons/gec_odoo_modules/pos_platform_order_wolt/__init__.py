from . import controllers
from . import models

from odoo.addons.pos_platform_order import reset_platform_provider, setup_provider


def post_init_hook(env):
    setup_provider(env, 'wolt')


def uninstall_hook(env):
    reset_platform_provider(env, 'wolt')
