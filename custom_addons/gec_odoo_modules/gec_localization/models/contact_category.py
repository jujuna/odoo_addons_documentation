from odoo import fields, models


class GecContactCategory(models.Model):
    _name = 'gec.contact.category'
    _description = 'Contact Category'
    _order = 'name, id'

    name = fields.Char(required=True, translate=True)
    color = fields.Integer()
    active = fields.Boolean(default=True)
