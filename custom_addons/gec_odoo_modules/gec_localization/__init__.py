from . import models
from . import wizards


def post_init(env):
    """Correct l10n_ge's VAT taxes in companies whose chart was loaded before this module."""
    env['account.chart.template']._ge_fix_core_vat_taxes()
