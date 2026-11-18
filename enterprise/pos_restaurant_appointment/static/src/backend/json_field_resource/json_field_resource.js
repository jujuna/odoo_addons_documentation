import { registry } from "@web/core/registry";
import { JsonField, jsonField } from "@web/views/fields/json/json_field";
import { deserializeDateTime } from "@web/core/l10n/dates";

export class JsonFieldResource extends JsonField {
    static template = "pos_restauramt_appointment.JsonFieldResource";

    get usage() {
        const value = this.props.record.data[this.props.name];
        if (!value?.event_id) {
            return false;
        }
        return {
            start: deserializeDateTime(value.event_start).toFormat("HH:mm"),
            stop: deserializeDateTime(value.event_stop).toFormat("HH:mm"),
            capacity: value.capacity,
        };
    }
}

export const jsonFieldResource = {
    ...jsonField,
    component: JsonFieldResource,
    listViewWidth: 125,
};

registry.category("fields").add("json_field_resource", jsonFieldResource);
