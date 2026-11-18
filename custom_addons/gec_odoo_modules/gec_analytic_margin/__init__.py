from . import models
from . import reports
from . import wizard


def post_init_hook(env):
    """Create the report columns for existing plans and levels, then classify the chart."""
    env['account.analytic.plan'].search([])._sync_all_plan_column()
    env['gec.margin.level'].search([])._sync_all_level_columns()

    # Carry over the old Selection column: Odoo leaves it in place, so the tags are recoverable.
    env.cr.execute("""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'account_account' AND column_name = 'gec_margin_component'
    """)
    if env.cr.fetchone():
        env.cr.execute("""
            UPDATE account_account a
               SET gec_margin_component_id = c.id
              FROM gec_margin_component c
             WHERE c.code = a.gec_margin_component
               AND a.gec_margin_component IS NOT NULL
               AND a.gec_margin_component_id IS NULL
        """)

    env['gec.margin.classification.rule']._apply_all()

    env['gec.forecast.snapshot']._gec_backfill()
