from . import controllers
from . import models
from . import wizard

from odoo.addons.pos_platform_order import setup_provider, reset_platform_provider

from .const import PROVIDER_CODE


def post_init_hook(env):
    setup_provider(env, PROVIDER_CODE)


def uninstall_hook(env):
    reset_platform_provider(env, PROVIDER_CODE)
