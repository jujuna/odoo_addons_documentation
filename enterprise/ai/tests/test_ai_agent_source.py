# Part of Odoo. See LICENSE file for full copyright and licensing details.
from unittest.mock import patch

from odoo.tools import mute_logger

from odoo.addons.ai.tests.common import TestAICommon


class TestAIAgentSource(TestAICommon):
    def test_unlink_source_should_unlinks_attachment(self):
        """Tests that unlinking a source unlinks its linked attachment."""

        attachment_id = self.test_source.attachment_id

        self.test_source.unlink()
        self.assertFalse(attachment_id.exists(), "Attachment should be deleted with its source.")

    def test_ai_web_page_source_unlink_if_single_source(self):
        """Tests that unlinking a source unlinks its linked web page
        if it's the only source referencing that web page."""

        web_page = self.env["ai.web.page"].create({
                "url": "http://example.com",
                "content": "<p>Some content</p>",
        })

        source_a = self.env["ai.agent.source"].create({
            "name": "Some web source",
            "agent_id": self.agent.id,
            "type": "url",
            "web_page_id": web_page.id,
            "status": "indexed",
        })

        source_b = self.env["ai.agent.source"].create({
            "name": "Some web source",
            "agent_id": self.agent.id,
            "type": "url",
            "web_page_id": web_page.id,
            "status": "indexed",
        })

        source_a.unlink()
        self.assertTrue(web_page.exists(), "Web page should not be deleted if still referenced by a source.")
        source_b.unlink()
        self.assertFalse(web_page.exists(), "Web page should be deleted if not linked to any source.")

    @mute_logger("odoo.addons.ai.models.ai_embedding_mixin")
    def test_reindexing_skipped_source_indexes_it(self):
        """Tests that re-indexing a skipped source after changing its content updates it to indexed."""
        test_attachment = self.env["ir.attachment"].create(
            {
                "name": "test_doc.txt",
                "raw": b"",
            },
        )
        skipped_source = self.env["ai.agent.source"].create(
            {
                "agent_id": self.agent.id,
                "attachment_id": test_attachment.id,
            },
        )

        self.assertFalse(test_attachment.embedding_ids)
        self.assertEqual("skipped", skipped_source.status, "Source with too short content should be skipped.")

        with (
            self.registry_test_mode(),
            self.mock_embedding_request(),
            patch("odoo.addons.ai.models.ai_embedding.AIEmbedding._get_default_embedding_model", return_value="default_embedding_model"),
        ):
            test_attachment.raw = b"Actual document content."
            skipped_source._reindex_sources()
            self.env.ref('ai.ir_cron_generate_embedding').method_direct_trigger()

        self.assertTrue(bool(test_attachment.embedding_ids.embedding_vector))
        self.assertEqual("indexed", skipped_source.status, "Source with actual content should be indexed.")
