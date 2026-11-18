from datetime import date

from freezegun import freeze_time

from odoo.tests import common, tagged
from odoo.tests.common import new_test_user


@tagged("voip", "post_install", "-at_install")
class TestVoipHrRecruitmentMailActivity(common.TransactionCase):
    # 23:30 UTC is already the next day in Brussels: "today" must be evaluated
    # in the user's timezone, not in UTC.
    @freeze_time("2026-11-10 23:30:00")
    def test_voip_hr_recruitment_fetch_applicant_related_call_activities(self):
        """
        Tests that "call activities" associated with an hr.applicant record are
        fetched correctly, and only if the user has the appropriate access
        rights.
        """
        today_in_brussels = date(2026, 11, 11)
        interviewer = new_test_user(
            self.env,
            "interviewer",
            groups="base.group_user,hr_recruitment.group_hr_recruitment_interviewer",
            name="Interviewer",
            tz="Europe/Brussels",
        )
        not_an_interviewer = new_test_user(self.env, "not_an_interviewer", tz="Europe/Brussels")
        applicant_partner = self.env["res.partner"].create({"name": "Applicant's partner", "phone": "070-1740605"})
        applicant = self.env["hr.applicant"].create(
            {
                "partner_name": "Applicant",
                "partner_id": applicant_partner.id,
                "interviewer_ids": interviewer.ids,
            }
        )
        applicant.activity_schedule(
            "mail.mail_activity_data_call", date_deadline=today_in_brussels, user_id=not_an_interviewer.id
        )
        activity = applicant.activity_schedule(
            "mail.mail_activity_data_call", date_deadline=today_in_brussels, user_id=interviewer.id
        )

        activities_of_interviewer = (
            self.env["mail.activity"]
            .with_user(interviewer)
            .get_today_call_activities()
            ._build_result()
        )
        activities_of_not_an_interviewer = (
            self.env["mail.activity"].with_user(not_an_interviewer).get_today_call_activities()._build_result()
        )

        self.assertEqual(activities_of_not_an_interviewer, {})
        self.assertEqual(len(activities_of_interviewer["mail.activity"]), 1)
        activity_data = activities_of_interviewer["mail.activity"][0]
        self.assertEqual(activity_data["id"], activity.id)
        self.assertEqual(activity_data["res_model"], "hr.applicant")
