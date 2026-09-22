import { Component, t, useProps } from "@odoo/owl";
import { getScriptTitle } from "../utils";

export class AiGeneratedScriptsPanel extends Component {
    static template = "ai_website.AiGeneratedScriptsPanel";

    props = useProps({
        scripts: t.array(),
    });

    get shared() {
        return this.env.editor.shared;
    }

    getScriptTitle = getScriptTitle;

    stopScript(scriptEl) {
        this.shared.aiScript.stopScript(scriptEl);
    }

    runScript(scriptEl) {
        this.shared.aiScript.runScript(scriptEl);
    }

    removeScript(scriptEl) {
        this.shared.aiScript.removeScript(scriptEl);
    }
}
