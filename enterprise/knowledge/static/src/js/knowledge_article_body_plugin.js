import { Plugin, signal } from "@odoo/owl";

/**
 * State shared between the article form and its editor.
 */
export class KnowledgeArticleBodyPlugin extends Plugin {
    /** Whether the article starts with an embedded view. */
    isTopEmbeddedView = signal(false);
}
