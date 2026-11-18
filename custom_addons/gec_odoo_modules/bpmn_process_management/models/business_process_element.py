# Part of bpmn_process_management. License LGPL-3.
from odoo import api, fields, models

ELEMENT_GROUPS = {
    "event": {"startEvent", "endEvent", "intermediateThrowEvent", "intermediateCatchEvent",
              "boundaryEvent"},
    "gateway": {"exclusiveGateway", "inclusiveGateway", "parallelGateway", "complexGateway",
                "eventBasedGateway"},
    "subprocess": {"subProcess", "transaction", "adHocSubProcess", "callActivity"},
    "lane": {"lane"},
    "pool": {"participant"},
    "data": {"dataObjectReference", "dataStoreReference"},
}


class BusinessProcessElement(models.Model):
    """Searchable index of diagram elements, rebuilt from the BPMN XML on every save (the XML stays the source)."""
    _name = "business.process.element"
    _description = "Business Process Element"
    _order = "process_id, element_group, name, id"

    process_id = fields.Many2one("business.process", required=True, ondelete="cascade",
                                 index=True)
    process_state = fields.Selection(related="process_id.state", store=True)
    company_id = fields.Many2one(related="process_id.company_id", store=True)
    element_id = fields.Char("BPMN ID", required=True)
    element_type = fields.Char("BPMN Type", required=True)
    element_group = fields.Selection([
        ("task", "Task"),
        ("event", "Event"),
        ("gateway", "Gateway"),
        ("subprocess", "Sub-process"),
        ("lane", "Lane"),
        ("pool", "Pool"),
        ("data", "Data"),
    ], compute="_compute_element_group", store=True, string="Element")
    name = fields.Char()
    lane_name = fields.Char("Lane")
    pool_name = fields.Char("Pool")
    documentation = fields.Text()
    link_count = fields.Integer("Links")
    responsible_model = fields.Char("Responsible Model")
    responsible_res_id = fields.Many2oneReference("Responsible Record",
                                                  model_field="responsible_model")
    responsible_name = fields.Char("Responsible")
    responsible_inherited = fields.Boolean(help="Responsibility comes from the lane.")
    review_status = fields.Selection([("none", "OK"), ("pending", "To Review")],
                                     default="none", required=True, index=True)
    review_reason = fields.Selection([
        ("responsible_missing", "Assign a department / role"),
        ("responsible_auto", "Confirm the automatic match"),
        ("type_guessed", "Check the element type"),
        ("link_broken", "Fix the broken link"),
        ("imported", "Check after import"),
    ], string="What to do")
    review_note = fields.Char("Note")

    @api.depends("element_type")
    def _compute_element_group(self):
        for rec in self:
            group = "task"
            for key, types in ELEMENT_GROUPS.items():
                if rec.element_type in types:
                    group = key
                    break
            rec.element_group = group

    @api.depends("name", "element_type")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name or rec.element_id

    def action_open_process(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "business.process",
            "res_id": self.process_id.id,
            "views": [[False, "form"]],
            "target": "current",
            "context": {"bpmn_focus_element": self.element_id},
        }
