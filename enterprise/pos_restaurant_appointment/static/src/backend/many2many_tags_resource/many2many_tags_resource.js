import { registry } from "@web/core/registry";
import {
    Many2ManyTagsField,
    many2ManyTagsField,
} from "@web/views/fields/many2many_tags/many2many_tags_field";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { deserializeDateTime, serializeDateTime } from "@web/core/l10n/dates";

export class FieldMany2ManyTagsResourceMany2XAutocomplete extends Many2XAutocomplete {
    static template = "pos_restaurant_appointment.FieldMany2ManyTagsResourceMany2XAutocomplete";
    static components = {
        ...Many2XAutocomplete.components,
    };

    getUsage(record) {
        if (!record.is_used?.event_id) {
            return false;
        }
        const { event_start, event_stop, capacity } = record.is_used;
        return {
            start: deserializeDateTime(event_start).toFormat("HH:mm"),
            stop: deserializeDateTime(event_stop).toFormat("HH:mm"),
            capacity,
        };
    }
}

export class FieldMany2ManyTagsResource extends Many2ManyTagsField {
    static template = "pos_restaurant_appointment.FieldMany2ManyTagsResource";
    static components = {
        ...Many2ManyTagsField.components,
        Many2XAutocomplete: FieldMany2ManyTagsResourceMany2XAutocomplete,
    };

    get context() {
        const context = this.props.context || {};
        const { start, stop } = this.props.record.data;
        context["start_date"] = start ? serializeDateTime(start) : null;
        context["stop_date"] = stop ? serializeDateTime(stop) : null;
        return context;
    }

    get specification() {
        return {
            is_used: {},
        };
    }
}

export const fieldMany2ManyTagsResource = {
    ...many2ManyTagsField,
    component: FieldMany2ManyTagsResource,
};

registry.category("fields").add("many2many_tags_resource", fieldMany2ManyTagsResource);
