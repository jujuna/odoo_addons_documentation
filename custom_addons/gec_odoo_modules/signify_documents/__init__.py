from . import models


def _signify_documents_post_init(env):
    env['res.company'].with_context(active_test=False).search([])._signify_create_documents_folders()
