from . import controllers
from . import models
from . import wizard


def uninstall_hook(env):
    """Demo departments, groups and articles live outside our tables: remove them too."""
    env["business.process"]._demo_remove()
