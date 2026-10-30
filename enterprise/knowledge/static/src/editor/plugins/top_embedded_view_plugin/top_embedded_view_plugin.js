import { Plugin } from "@html_editor/plugin";

const PLACEHOLDER_SELECTOR = "[data-selection-placeholder]";
const EMBEDDED_VIEW_SELECTOR = "[data-embedded='view']";

/**
 * Notifies, through `config.onTopEmbeddedViewChange`, whether the content
 * starts with an embedded view (the selection placeholder set apart).
 */
export class KnowledgeTopEmbeddedViewPlugin extends Plugin {
    static id = "knowledgeTopEmbeddedView";
    /** @type {import("plugins").EditorResources} */
    resources = {
        /** Processors */
        normalize_processors: this.updateTopEmbeddedView.bind(this),
    };

    isTopEmbeddedView = false;

    destroy() {
        super.destroy();
        this.setTopEmbeddedView(false);
    }

    updateTopEmbeddedView() {
        let first = this.editable.firstElementChild;
        if (first?.matches(PLACEHOLDER_SELECTOR)) {
            first = first.nextElementSibling;
        }
        this.setTopEmbeddedView(Boolean(first?.matches(EMBEDDED_VIEW_SELECTOR)));
    }

    /**
     * @param {boolean} isTopEmbeddedView
     */
    setTopEmbeddedView(isTopEmbeddedView) {
        if (isTopEmbeddedView !== this.isTopEmbeddedView) {
            this.isTopEmbeddedView = isTopEmbeddedView;
            this.config.onTopEmbeddedViewChange?.(isTopEmbeddedView);
        }
    }
}
