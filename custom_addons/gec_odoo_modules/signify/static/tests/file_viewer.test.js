import {
    click,
    contains,
    defineMailModels,
    openFormView,
    start,
    startServer,
} from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { defineModels, models, onRpc } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

class SignifyDocument extends models.ServerModel {
    _name = "signify.document";
    _inherit = ["mail.thread"];
}

defineMailModels();
defineModels([SignifyDocument]);

const SIGNIFY_GROUP = "signify.group_signify_user";
const BUTTON = ".o-FileViewer-headerButton[title='Send with Signify']";
const PDF = { mimetype: "application/pdf", name: "Contract.pdf" };
const IMAGE = { mimetype: "image/png", name: "Photo.png" };

function mockSignifyGroup(isMember) {
    onRpc("has_group", ({ args }) => (args[1] === SIGNIFY_GROUP ? isMember : true));
}

async function openChatter(attachments, model = "res.partner") {
    const pyEnv = await startServer();
    const recordId = pyEnv[model].create({});
    const attachmentIds = pyEnv["ir.attachment"].create(
        attachments.map((attachment) => ({
            ...attachment,
            res_id: recordId,
            res_model: model,
        }))
    );
    await start();
    await openFormView(model, recordId, {
        arch: `
            <form>
                <sheet></sheet>
                <chatter open_attachments="True"/>
            </form>`,
    });
    return attachmentIds;
}

async function openPdfViewer() {
    await click(`.o-mail-AttachmentContainer[aria-label="${PDF.name}"] .o-mail-AttachmentCard-image`);
    await contains(".o-FileViewer");
}

test("a Signify user sees the button on a PDF of the chatter", async () => {
    mockSignifyGroup(true);
    await openChatter([PDF]);
    await openPdfViewer();
    await contains(BUTTON);
});

test("a user without the Signify group does not see the button", async () => {
    mockSignifyGroup(false);
    await openChatter([PDF]);
    await openPdfViewer();
    await contains(".o-FileViewer-headerButton[title='Download']");
    await contains(BUTTON, { count: 0 });
});

test("a PDF of a Signify document has no button", async () => {
    mockSignifyGroup(true);
    await openChatter([PDF], "signify.document");
    await openPdfViewer();
    await contains(".o-FileViewer-headerButton[title='Download']");
    await contains(BUTTON, { count: 0 });
});

test("an image has no button", async () => {
    mockSignifyGroup(true);
    await openChatter([IMAGE]);
    await click(`.o-mail-AttachmentContainer[aria-label="${IMAGE.name}"] .o-mail-AttachmentImage`);
    await contains(".o-FileViewer");
    await contains(BUTTON, { count: 0 });
});

test("the button follows the file shown in the viewer", async () => {
    mockSignifyGroup(true);
    await openChatter([PDF, IMAGE]);
    await openPdfViewer();
    await contains(BUTTON);
    await click(".o-FileViewer-navigation[aria-label='Next']");
    await contains(".o-FileViewer-header:has(:text('Photo.png'))");
    await contains(BUTTON, { count: 0 });
    await click(".o-FileViewer-navigation[aria-label='Previous']");
    await contains(".o-FileViewer-header:has(:text('Contract.pdf'))");
    await contains(BUTTON);
});

test("clicking the button creates the draft from the file, closes the viewer and opens the document", async () => {
    class SignifyDocumentAction extends Component {
        static template = xml`<div class="o-signify-test-document">Signify document</div>`;
    }
    registry.category("actions").add("signify_test_document", SignifyDocumentAction);
    mockSignifyGroup(true);
    onRpc("signify.document", "action_new_from_attachment", ({ args }) => {
        expect.step(`action_new_from_attachment ${JSON.stringify(args)}`);
        return { type: "ir.actions.client", tag: "signify_test_document" };
    });
    const [attachmentId] = await openChatter([PDF]);
    await openPdfViewer();
    await click(BUTTON);
    await contains(".o-signify-test-document");
    await contains(".o-FileViewer", { count: 0 });
    await expect.waitForSteps([`action_new_from_attachment [${attachmentId}]`]);
});
