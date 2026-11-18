import { patch } from "@web/core/utils/patch";
import { ReferenceField } from "@web/views/fields/reference/reference_field";

// Play Audio wrappers are internal to their nodes. Filter them from every
// Reference picker targeting Menus, including existing views using the default
// widget, without requiring an update of those stored views (e.g. Group).
// TODO avoid patch in master
patch(ReferenceField.prototype, {
    get m2oProps() {
        const props = super.m2oProps;
        if (props.relation !== "voip.ivr") {
            return props;
        }
        return {
            ...props,
            domain: () => [...props.domain(), ["is_audio_message", "=", false]],
        };
    },
});
