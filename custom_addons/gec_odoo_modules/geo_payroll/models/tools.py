from odoo.exceptions import LockError, UserError


def gec_lock_for_update(records, allow_referencing=False):
    """lock_for_update() raises LockError at once; allow_referencing=True lets records pointing here still be saved."""
    try:
        records.lock_for_update(allow_referencing=allow_referencing)
    except LockError:
        raise UserError(records.env._("Another user is working on these payroll records right now. Try again in a moment.")) from None
