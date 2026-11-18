from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain

from .conditions import ConditionError, condition_domain
from .value_filters import check_read_fields


class GecAccessConditionMixin(models.AbstractModel):
    _name = 'gec.access.condition.mixin'
    _description = 'Condition of an Access Rule'

    condition = fields.Char(
        string='Only When',
        help="Leave empty to use the rule on every record. Otherwise it is used only on records that match this "
             "condition. Write it like an Odoo view condition: state == 'sale', amount_total > 1000, state in ['draft',"
             " 'sent'] and not is_company.")

    @api.constrains('condition', 'model_id')
    def _check_condition(self):
        """ Refuse an invalid condition or one reading a field its editor cannot read: it is judged as superuser. """
        reader = None if self.env['gec.access.profile']._gec_editor_is_trusted() else self.env(su=False)
        for line in self:
            if not (line.condition or '').strip() or not line.model_id.model:
                continue
            if line.model_id.model not in self.env:
                continue
            try:
                domain = condition_domain(line.condition, self.env[line.model_id.model], self.env.uid)
                if reader is not None:
                    check_read_fields(reader[line.model_id.model], Domain(domain))
            except (ConditionError, AccessError) as error:
                raise ValidationError(_("%(rule)s: %(error)s", rule=line.display_name,
                                        error=self.env._(error.args[0]))) from error
