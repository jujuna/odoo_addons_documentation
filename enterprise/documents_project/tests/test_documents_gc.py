from odoo.tests import tagged

from odoo.addons.documents.tests.test_documents_common import TransactionCaseDocuments


@tagged('post_install', '-at_install')
class TestDocumentsProjectGcClearBin(TransactionCaseDocuments):
    """Folders linked to a project must survive the documents trash
    autovacuum. Removing one would null `project.documents_folder_id`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_int(
            'documents.deletion_delay', 0,
        )
        cls.Document = cls.env['documents.document']
        cls.Project = cls.env['project.project']

    def _make_project_with_folder(self, project_name):
        folder = self.Document.create({
            'type': 'folder',
            'name': f'folder for {project_name}',
            'owner_id': self.doc_user.id,
        })
        project = self.Project.create({
            'name': project_name,
            'documents_folder_id': folder.id,
        })
        return project, folder

    def test_gc_keeps_folder_of_active_project_when_folder_archived(self):
        project, folder = self._make_project_with_folder('active project')
        folder.action_archive()
        self.assertFalse(folder.active)
        self.assertTrue(project.active)

        self.Document._gc_clear_bin()

        self.assertTrue(
            folder.exists(),
            "A folder linked to an active project must survive the GC bin.",
        )
        self.assertEqual(
            project.documents_folder_id, folder,
            "The project documents_folder_id link must remain intact.",
        )

    def test_gc_keeps_folder_when_project_also_archived(self):
        project, folder = self._make_project_with_folder('archived project')
        project.action_archive()
        folder.action_archive()
        self.assertFalse(project.active)
        self.assertFalse(folder.active)

        self.Document._gc_clear_bin()

        self.assertTrue(folder.exists())
        self.assertEqual(project.documents_folder_id, folder)

    def test_gc_keeps_archived_folder_when_last_child_collected(self):
        # Collecting the last trashed document of an archived project folder
        # makes documents.unlink() try to remove that now-empty folder. It must
        # survive: unlinking it would null project.documents_folder_id.
        project, folder = self._make_project_with_folder('project with trash')
        document = self.Document.create({
            'name': 'trashed child',
            'folder_id': folder.id,
            'owner_id': self.doc_user.id,
            'active': False,
            'type': 'binary',
            'raw': b'test',
        })
        folder.action_archive()
        self.assertFalse(folder.active)
        self.assertFalse(document.active)

        self.Document._gc_clear_bin()

        self.assertFalse(document.exists(), "The trashed child document should be collected.")
        self.assertTrue(folder.exists(), "Its archived project folder must survive the GC.")
        self.assertEqual(project.documents_folder_id, folder)

    def test_unlink_keeps_archived_folder_of_unreadable_project(self):
        # A user without access to the project must not be able to remove its
        # folder as the parent cleanup of a deleted document.
        project, folder = self._make_project_with_folder('private project')
        project.privacy_visibility = 'followers'
        document = self.Document.create({
            'name': 'trashed child',
            'folder_id': folder.id,
            'owner_id': self.doc_user.id,
            'active': False,
            'type': 'binary',
            'raw': b'test',
        })
        folder.action_archive()
        self.assertFalse(self.env['project.project'].with_user(self.doc_user).search([('id', '=', project.id)]))

        document.with_user(self.doc_user).unlink()

        self.assertTrue(folder.exists(), "The project folder must survive the parent cleanup.")
        self.assertEqual(project.documents_folder_id, folder)
