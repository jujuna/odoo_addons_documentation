from odoo import _, api, models
from odoo.exceptions import UserError

# Lifts the field guard; a Python object cannot arrive over RPC or in an import.
GEC_BANK_WRITE_TOKEN = object()


class GecBankGuardMixin(models.AbstractModel):
    """Guards the fields only bank flows write: transfer state, bank ids, approval.
    ``readonly=True`` only guides the web client; this stops a form, import or RPC call from forging them."""

    _name = 'gec.bank.guard.mixin'
    _description = 'Bank Transfer Field Guard'
    _inherit = ['gec.bank.sendable']

    def _gec_bank_protected_fields(self):
        """The fields this guard refuses to write directly. Each bank adds its own."""
        return set()

    def _gec_bank_check_protected(self, field_names):
        """Refuse a direct write of a protected field unless the bank flow holds the token."""
        if self.env.context.get('gec_bank_write_token') is GEC_BANK_WRITE_TOKEN:
            return
        protected = self._gec_bank_protected_fields() & set(field_names)
        if protected:
            raise UserError(_(
                "These fields are set by the bank integration and cannot be changed directly: %s",
                ', '.join(sorted(self._fields[name]._description_string(self.env)
                                 for name in protected))))

    def _gec_bank_internal_write(self, vals):
        """Write protected fields from a bank flow; the token covers this write only, never the web client."""
        return self.with_context(gec_bank_write_token=GEC_BANK_WRITE_TOKEN).write(vals)

    @api.model
    def default_get(self, fields):
        """A context key or a saved default (ir.default) never presets what only the bank flow writes; the field's own default stays."""
        defaults = super().default_get(fields)
        for name in self._gec_bank_protected_fields() & defaults.keys():
            if default := self._fields[name].default:
                defaults[name] = default(self.browse())
            else:
                del defaults[name]
        return defaults

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._gec_bank_check_protected(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._gec_bank_check_protected(vals)
        return super().write(vals)
