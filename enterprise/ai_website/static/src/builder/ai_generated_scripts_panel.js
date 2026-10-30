import { Component, t, useProps } from "@odoo/owl";
import { useOperation } from "@html_builder/core/operation_plugin";
import { _t } from "@web/core/l10n/translation";
import { getScriptTitle } from "../utils";

export class AiGeneratedScriptsPanel extends Component {
    static template = "ai_website.AiGeneratedScriptsPanel";

    props = useProps({
        scripts: t.array(),
    });

    setup() {
        this.callOperation = useOperation();
    }

    get shared() {
        return this.env.editor.shared;
    }

    getScriptTitle = getScriptTitle;
    notRemovableTooltip = _t("Removing a script requires 'Editor and Designer' access");

    stopScript(scriptEl) {
        this.shared.aiScript.stopScript(scriptEl);
    }

    runScript(scriptEl) {
        this.shared.aiScript.runScript(scriptEl);
    }

    removeScript(scriptEl) {
        this.callOperation(() => this.shared.aiScript.removeScript(scriptEl));
    }
}
