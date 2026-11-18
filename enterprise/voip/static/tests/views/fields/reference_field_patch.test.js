import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, queryAllTexts, test } from "@odoo/hoot";
import { waitFor } from "@odoo/hoot-dom";
import { contains, defineModels, fields, models, mountView } from "@web/../tests/web_test_helpers";

import "@voip/views/fields/extension_destination_field";
import "@voip/views/fields/pbx_forward_destination_field";
import "@voip/views/fields/reference_field_patch";

const destinations = [
    ["voip.ivr", "Menu"],
    ["voip.queue", "Queue"],
];

class Route extends models.Model {
    _name = "voip.test.route";

    destination_kind = fields.Selection({ selection: destinations });
    destination_ref = fields.Reference({ selection: destinations });

    _records = [
        { id: 1, destination_kind: "voip.ivr", destination_ref: "voip.ivr,2" },
        { id: 2, destination_kind: "voip.queue", destination_ref: "voip.queue,1" },
    ];
}

class VoipIvr extends models.Model {
    _name = "voip.ivr";

    name = fields.Char();
    is_audio_message = fields.Boolean();

    _records = [
        { id: 1, name: "Play Audio", is_audio_message: true },
        { id: 2, name: "Menu" },
        { id: 3, name: "Excluded menu" },
    ];
}

class VoipQueue extends models.Model {
    _name = "voip.queue";

    name = fields.Char();

    _records = [
        { id: 1, name: "First queue" },
        { id: 2, name: "Second queue" },
        { id: 3, name: "Excluded queue" },
    ];
}

defineMailModels();
defineModels([Route, VoipIvr, VoipQueue]);

async function getProposedDestinations(arch, resId) {
    await mountView({ type: "form", resModel: "voip.test.route", resId, arch });
    await contains("[name=destination_ref] .o-autocomplete--input").click();
    await waitFor(".o-autocomplete--dropdown-item");
    return queryAllTexts(".o-autocomplete--dropdown-item:not(.o_m2o_dropdown_option)");
}

// The patch is on the base ReferenceField: it must still apply through the
// voip widgets extending it, which add their own logic around m2oProps.
for (const widget of [
    "reference",
    "voip_extension_destination",
    "voip_pbx_forward_destination_ref",
]) {
    const arch = /* xml */ `
        <form>
            <field name="destination_kind" invisible="1"/>
            <field name="destination_ref" widget="${widget}"
                options="{'kind_field': 'destination_kind', 'no_create': True}"
                domain="[('id', '!=', 3)]"/>
        </form>`;

    test.tags("desktop");
    test(`${widget}: Menu destinations hide 'Play Audio' Menus and keep the view's domain`, async () => {
        expect(await getProposedDestinations(arch, 1)).toEqual(["Menu"]);
    });

    test.tags("desktop");
    test(`${widget}: other destination models are not filtered`, async () => {
        expect(await getProposedDestinations(arch, 2)).toEqual(["First queue", "Second queue"]);
    });
}
