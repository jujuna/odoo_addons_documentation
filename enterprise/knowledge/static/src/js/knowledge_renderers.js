import { providePlugins, useEffect, useListener, usePlugin } from "@odoo/owl";
import { FormRenderer } from "@web/views/form/form_renderer";
import { KnowledgeArticleBodyPlugin } from "./knowledge_article_body_plugin";

export class KnowledgeArticleFormRenderer extends FormRenderer {

    //--------------------------------------------------------------------------
    // Component
    //--------------------------------------------------------------------------
    setup() {
        providePlugins([KnowledgeArticleBodyPlugin]);
        super.setup();
        const bodyPlugin = usePlugin(KnowledgeArticleBodyPlugin);
        useEffect(() => {
            const isTopEmbeddedView = bodyPlugin.isTopEmbeddedView();
            this.rootRef()
                ?.querySelector(".o_knowledge_body")
                ?.classList.toggle("o_knowledge_body_top_embedded_view", isTopEmbeddedView);
        });
        useListener(document, "click", event => {
            if (event.target.classList.contains("o_nocontent_create_btn")) {
                this.env.createArticle("private");
            }
        });
    }
}
