from odoo import models, fields


class ProjectTags(models.Model):
    _inherit = 'project.tags'

    # Rework is work done twice; tagging the task counts its hours without a tick on every timesheet.
    gec_rework = fields.Boolean(
        string='Counts as Rework',
        help="Hours on tasks carrying this tag count as rework on the ABC "
             "dashboard (benchmark: below 5–10% of delivery hours).",
    )
