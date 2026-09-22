import { useSubEnv } from "@web/owl2/utils";
import { _t } from "@web/core/l10n/translation";
import { AttendeeCalendarController } from "@calendar/views/attendee_calendar/attendee_calendar_controller";
import { patch } from "@web/core/utils/patch";
import { usePopover } from "@web/core/popover/popover_hook";
import { rpc } from "@web/core/network/rpc";
import { Tooltip } from "@web/core/tooltip/tooltip";
import { useService } from "@web/core/utils/hooks";
import { onWillStart, proxy, signal } from "@odoo/owl";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { user } from "@web/core/user";


patch(AttendeeCalendarController, {
    components: {
        ...AttendeeCalendarController.components,
        Dropdown,
        DropdownItem,
    },
});

patch(AttendeeCalendarController.prototype, {
    setup() {
        super.setup(...arguments);
        this.popover = usePopover(Tooltip, { position: "bottom" });
        this.copyLinkRef = signal.ref();
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.uiService = useService("ui");

        useSubEnv({
            calendarState: proxy({
                // default: regular calendar event edition, should behave mostly as if no patching had been done
                // slots-creation: enables editing slots of the "editing appointment" selected by a user
                // slots-deletion: enables deleting slots when they are clicked for the "editing appointment"
                mode: "default",
            }),
        });

        onWillStart(async () => {
            // if the appointment type being edited was set via context, enable slot creation mode
            if (
                this.model.slotsAppointmentData() ||
                this.props.context.calendar_editing_custom_appointment_id
            ) {
                this.env.calendarState.mode = "slots-creation";
            }
            [this.isAppointmentManager, this.isAppointmentUser] =
await Promise.all([
                user.hasGroup("appointment.group_appointment_manager"),
                user.hasGroup("appointment.group_appointment_user"),
            ]);
        });
    },

    get showAddClosingDayBtn() {
        return this.isAppointmentManager && this.className.includes('o_appointment_calendar_view');
    },
    _writeUrlToClipboard(url) {
        url ??= this.model.slotsAppointmentData()?.url;
        if (!url) {
            return;
        }
        setTimeout(async () => await navigator.clipboard.writeText(url));
        this.notification.add(_t("Link copied to clipboard!"), { type: "success" });
    },

    async onAddClosingDay() {
        const defaultAppointmentTypeId = this.props.context.default_appointment_type_id;
        const scheduleBasedOn = this.props.context.appointment_schedule_based_on;
        this.actionService.doAction({
            name: _t("New Closing Day"),
            type: "ir.actions.act_window",
            res_model: "appointment.leave",
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
            context: {
                ...(defaultAppointmentTypeId && { default_appointment_type_ids: [defaultAppointmentTypeId] }),
                ...(scheduleBasedOn && { appointment_schedule_based_on: scheduleBasedOn }),
            },
        });
    },

    onClickCustomLink() {
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: 'appointment.invite',
            name: _t('Share Link'),
            views: [[false, 'form']],
            target: 'new',
            context: {
                ...this.props.context,
                dialog_size: 'medium',
            },
        })
    },

    _getSelectAvailabilityNotificationMessage() {
        return _t("Pick your availabilities.");
    },

    async setEditingAppointmentId(appointmentTypeId) {
        // slot edition relies on drag interactions, it is desktop only
        if (this.uiService.isSmall && appointmentTypeId) {
            return;
        }
        await this.model.setEditingAppointmentId(appointmentTypeId);
        this.env.calendarState.mode = appointmentTypeId ? "slots-creation" : "default";
        if (appointmentTypeId) {
            this.notification.add(this._getSelectAvailabilityNotificationMessage(), {
                type: "info",
            });
        }
    },

    get sidePanelProps() {
        return {
            ...super.sidePanelProps,
            copyAppointmentURL: this.onClickGetAppointmentUrl.bind(this),
            openAppointmentForm: this.onClickOpenForm.bind(this),
            openAppointmentEditWizard: this.openAppointmentEditSlotsForm.bind(this),
            setEditingAppointmentId: this.setEditingAppointmentId.bind(this),
        };
    },

    async onClickOpenForm(appointmentId) {
        if (!appointmentId) {
            appointmentId = this.model.slotsAppointmentData()?.id;
        }
        this.openAppointmentEditSlotsForm(appointmentId);
    },

    async onClickSearchCreateAnytimeAppointment() {
        const anytimeAppointmentInfo = await rpc(
            "/appointment/appointment_type/search_create_anytime",
            this.model._getInviteParams()
        );
        this._writeUrlToClipboard(anytimeAppointmentInfo.invite_url);
    },

    async onClickGetAppointmentUrl(appointmentTypeId) {
        const appointmentInfo = await rpc(
            "/appointment/appointment_type/get_calendar_slot_editor_info",
            {
                appointment_type_id: appointmentTypeId,
                ...this.model._getInviteParams(),
            }
        );
        this._writeUrlToClipboard(appointmentInfo.invite_url);
    },

    async openAppointmentEditSlotsForm(appointmentTypeId, defaultName) {
        const action = await this.actionService.loadAction(
            "appointment.appointment_edit_slots_action"
        );
        const context = action.context;
        context.default_name =
            defaultName || _t("%(user_name)s - Free Time Slots", { user_name: user.name });
        context.default_slot_duration = this.model.getLocalStorageDuration(appointmentTypeId);
        this.displayDialog(FormViewDialog, {
            canExpand: false,
            context: context,
            size: "sm",
            title: action.name,
            viewId: action.view_id?.[0],
            resId: appointmentTypeId || false,
            resModel: action.res_model,
            onRecordSaved: async (record) => {
                const appointmentSlotDurationVals = {
                    appointmentDuration: record.data.slot_duration,
                };
                const savedAppointmentTypeId = record.resId;
                localStorage.setItem(
                    `appointment.slot.editor.data.${savedAppointmentTypeId}`,
                    JSON.stringify(appointmentSlotDurationVals)
                );
                const promises = [];
                // include new appointments in the sidebar
                if (!appointmentTypeId) {
                    promises.push(this.model.toggleAppointmentInList(savedAppointmentTypeId));
                }
                promises.push(this.setEditingAppointmentId(savedAppointmentTypeId));
                await Promise.all(promises);
                this._writeUrlToClipboard();
            },
        });
    },
});
