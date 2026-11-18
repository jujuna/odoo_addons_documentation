def post_init_hook(env):
    env['gec.declaration.card']._gec_place_menus()


def uninstall_hook(env):
    """Put the declaration menus back in Accounting before this module's menus are deleted: a menu cannot be
    deleted while it has children."""
    env['gec.declaration.card']._gec_place_menus(restore=True)
