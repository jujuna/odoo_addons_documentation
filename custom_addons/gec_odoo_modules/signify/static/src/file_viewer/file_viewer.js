import { onWillStart } from "@odoo/owl";
import { FileViewer } from "@web/core/file_viewer/file_viewer";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

patch(FileViewer.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");

        onWillStart(async () => {
            this.isSignifyUser = await user.hasGroup("signify.group_signify_user");
        });
    },

    /** A getter, so that moving to another file in the viewer shows or hides the button. */
    get canSendWithSignify() {
        const { isPdf, thread } = this.state.file;
        return Boolean(this.isSignifyUser && isPdf && thread && thread.model !== "signify.document");
    },

    async onClickSendWithSignify() {
        const action = await this.orm.call("signify.document", "action_new_from_attachment", [
            this.state.file.id,
        ]);
        this.close();
        await this.action.doAction(action);
    },
});
