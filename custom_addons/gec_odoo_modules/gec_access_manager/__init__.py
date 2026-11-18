from . import models
from . import wizard
from . import controllers


def uninstall_hook(env):
    """ Delete every profile with its hidden group: the groups belong to no data
    file, so the uninstall would otherwise leave them behind. """
    env['gec.access.profile'].with_context(active_test=False).search([]).unlink()
