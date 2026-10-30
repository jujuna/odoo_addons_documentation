from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from odoo.addons.appointment.controllers.calendar_view import AppointmentCalendarView


class AppointmentHrRecruitmentCalendarView(AppointmentCalendarView):

    @classmethod
    def _get_calendar_slot_editor_info(cls, appointment_type, applicant_code=None, **kwargs):
        slot_editor_info = super()._get_calendar_slot_editor_info(appointment_type, applicant_code=applicant_code, **kwargs)
        if applicant_code:
            invite_url = urlsplit(slot_editor_info['invite_url'])
            invite_url_qs = parse_qs(invite_url.query)
            invite_url_qs['applicant_code'] = applicant_code
            # Force the domain of the website linked to the job
            applicant_sudo = appointment_type.env['hr.applicant'].sudo().search([
                ('interview_invite_code', '=', applicant_code)
            ], limit=1)
            if applicant_sudo and applicant_sudo.job_id:
                base_url = urlsplit(applicant_sudo.job_id.get_base_url())
                invite_url = invite_url._replace(
                    scheme=base_url.scheme,
                    netloc=base_url.netloc,
                )
            slot_editor_info['invite_url'] = urlunsplit(invite_url._replace(query=urlencode(invite_url_qs)))
        return slot_editor_info
