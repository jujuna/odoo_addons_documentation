import { patch } from "@web/core/utils/patch";
import { MailComposerFormRenderer } from "@mail/chatter/web/mail_composer_form";

patch(MailComposerFormRenderer.prototype, {
    setup() {
        super.setup();
        if (this.props.record.resModel === "equity.mail.compose.message") {
            this.env.dialogData.dismiss = undefined;
        }
    },
});
