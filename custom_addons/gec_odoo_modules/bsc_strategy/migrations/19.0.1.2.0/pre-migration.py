# -*- coding: utf-8 -*-
"""Hand the ``bsc_project`` bridge's ir_model_data rows over to ``bsc_strategy``.
Uninstalling the bridge would drop its columns on ``bsc_initiative`` and project links; only the prefix changes."""
import logging

_logger = logging.getLogger(__name__)

OLD_MODULE = 'bsc_project'
NEW_MODULE = 'bsc_strategy'


def migrate(cr, version):
    if not version:
        return

    cr.execute("SELECT id, state FROM ir_module_module WHERE name = %s", (OLD_MODULE,))
    row = cr.fetchone()
    if not row:
        return
    module_id, state = row
    if state not in ('installed', 'to upgrade', 'to install'):
        return

    # On a duplicate name the bridge's row carries the live record id; drop this side's.
    cr.execute("""
        DELETE FROM ir_model_data new
         WHERE new.module = %s
           AND EXISTS (SELECT 1 FROM ir_model_data old
                        WHERE old.module = %s
                          AND old.name = new.name
                          AND old.model = new.model)
    """, (NEW_MODULE, OLD_MODULE))

    cr.execute("UPDATE ir_model_data SET module = %s WHERE module = %s",
               (NEW_MODULE, OLD_MODULE))
    moved = cr.rowcount

    # Owning nothing, the bridge can be retired; its dependency rows go too.
    cr.execute("DELETE FROM ir_module_module_dependency WHERE module_id = %s",
               (module_id,))
    cr.execute("""
        UPDATE ir_module_module
           SET state = 'uninstalled', latest_version = NULL
         WHERE id = %s
    """, (module_id,))

    _logger.info("bsc_strategy: absorbed %s (%s records re-owned)", OLD_MODULE, moved)
