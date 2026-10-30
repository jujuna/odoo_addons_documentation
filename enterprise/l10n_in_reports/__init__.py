from . import models
from . import wizard


def _post_init_hook(env):
    if indian_companies := env['res.company'].search([('chart_template', 'like', 'in%')]):
        indian_companies._l10n_in_toggle_regular_and_composition_returns()
        indian_companies._l10n_in_toggle_iff_return()
