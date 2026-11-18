import { registry } from "@web/core/registry";
import { session } from "@web/session";

/** Body classes hide search and form switches (read by search_parts.scss); the server refuses the writes too. */
registry.category("services").add("gec_access_body_classes", {
    start() {
        const classes = session.gec_access_classes || [];
        if (classes.length) {
            document.body.classList.add(...classes);
        }
    },
});
