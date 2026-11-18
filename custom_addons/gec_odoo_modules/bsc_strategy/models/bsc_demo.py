# -*- coding: utf-8 -*-
"""One-click demo data (a worked year) and its removal.
All records are reachable from ``is_demo`` scorecards (and perspectives it created); removal never touches real ones.
Texts: Georgian or English, by user language."""
from datetime import date

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

# The scenario. Every text is (english, georgian).
SCORECARD_NAME = ("Demo: Company Strategy %s", "დემო: კომპანიის სტრატეგია %s")
VISION = (
    "To be the most reliable distributor in the region, the one customers "
    "recommend first.",
    "ვიყოთ რეგიონის ყველაზე საიმედო დისტრიბუტორი - ის, ვისაც მომხმარებლები "
    "პირველს ურჩევენ.",
)
MISSION = (
    "We deliver the right goods on time, every time, through skilled people and "
    "simple digital processes.",
    "სწორ საქონელს ყოველთვის დროულად ვაწვდით - კვალიფიციური გუნდითა და მარტივი "
    "ციფრული პროცესებით.",
)

PERSPECTIVES = {
    # code: (xmlid, english, georgian, sequence)
    'learning': ('perspective_learning', "Learning and Growth", "სწავლა და განვითარება", 10),
    'process': ('perspective_process', "Internal Processes", "შიდა პროცესები", 20),
    'customer': ('perspective_customer', "Customer", "მომხმარებელი", 30),
    'financial': ('perspective_financial', "Financial", "ფინანსური", 40),
}

OBJECTIVES = [
    # code, perspective, (en, ka), mode, weight, (description en, ka)
    ('F1', 'financial', ("Grow revenue", "შემოსავლების ზრდა"), 'kpi', 60,
     ("Sell more to existing customers and win new ones in two new regions.",
      "არსებულ მომხმარებლებზე მეტი გაყიდვა და ორ ახალ რეგიონში ახალი მომხმარებლების მოზიდვა.")),
    ('F2', 'financial', ("Improve profitability", "მომგებიანობის გაუმჯობესება"), 'kpi', 40,
     ("Keep discounts under control and lower the cost of every delivery.",
      "ფასდაკლებების კონტროლი და თითოეული მიწოდების ხარჯის შემცირება.")),
    ('C1', 'customer', ("Raise customer satisfaction", "მომხმარებელთა კმაყოფილების ამაღლება"), 'kpi', 50,
     ("Customers get what they ordered, on time, and would recommend us.",
      "მომხმარებელი შეკვეთილს დროულად იღებს და სხვებსაც გვირჩევს.")),
    ('C2', 'customer', ("Retain key customers", "ძირითადი მომხმარებლების შენარჩუნება"), 'kpi', 50,
     ("The top 50 customers stay with us and buy more every year.",
      "50 უმსხვილესი მომხმარებელი ჩვენთან რჩება და ყოველწლიურად მეტს ყიდულობს.")),
    ('P1', 'process', ("Speed up order fulfilment", "შეკვეთების შესრულების დაჩქარება"), 'kpi', 60,
     ("From order to delivery in three days or less.",
      "შეკვეთიდან მიწოდებამდე - სამი დღე ან ნაკლები.")),
    ('P2', 'process', ("Improve service quality", "მომსახურების ხარისხის გაუმჯობესება"), 'kpi', 40,
     ("Fewer wrong, damaged or late deliveries.",
      "ნაკლები არასწორი, დაზიანებული ან დაგვიანებული მიწოდება.")),
    ('L1', 'learning', ("Develop employee skills", "თანამშრომელთა უნარების განვითარება"), 'kpi', 60,
     ("Every employee gets regular, practical training for their job.",
      "ყველა თანამშრომელი რეგულარულად გადის საკუთარ საქმესთან დაკავშირებულ პრაქტიკულ სწავლებას.")),
    ('L2', 'learning', ("Digitalise core processes", "ძირითადი პროცესების ციფრიზაცია"), 'qualitative', 40,
     ("Orders, stock and deliveries are tracked in one system, without paper.",
      "შეკვეთები, მარაგი და მიწოდება ერთ სისტემაში აღირიცხება, ქაღალდის გარეშე.")),
]

QUALITATIVE = {
    'L2': ('amber', (
        "The ERP rollout is on schedule, but warehouse barcode scanning is a quarter late.",
        "ERP-ის დანერგვა გეგმის მიხედვით მიდის, თუმცა საწყობში შტრიხკოდით სკანირება "
        "ერთი კვარტლით იგვიანებს.")),
}

KPIS = [
    # objective, (en, ka), (unit en, ka), direction, target, baseline, range,
    # four quarterly actuals (None = not reported), comments by quarter index
    ('F1', ("Revenue", "შემოსავალი"), ("thousand GEL", "ათასი ლარი"), 'higher_better',
     500.0, 450.0, None, [480.0, 520.0, 455.0, None],
     {2: ("The summer campaign moved sales into the fourth quarter.",
          "ზაფხულის კამპანიამ გაყიდვების ნაწილი მეოთხე კვარტალში გადაიტანა.")}),
    ('F2', ("Net profit margin", "წმინდა მოგების მარჟა"), ("%", "%"), 'higher_better',
     12.0, 10.0, None, [11.6, 12.4, 9.0, None],
     {2: ("Deep discounts during the summer campaign and higher fuel prices.",
          "ზაფხულის კამპანიის დიდი ფასდაკლებები და საწვავის გაძვირება.")}),
    ('C1', ("Net Promoter Score (NPS)", "რეკომენდაციის ინდექსი (NPS)"), ("points", "ქულა"),
     'higher_better', 40.0, 32.0, None, [35.0, 41.0, 44.0, 45.0],
     {0: ("Late deliveries in January pulled the score down.",
          "იანვრის დაგვიანებულმა მიწოდებებმა ქულა შეამცირა.")}),
    ('C2', ("Customer churn", "მომხმარებელთა გადინება"), ("%", "%"), 'lower_better',
     5.0, 7.0, None, [6.0, 5.2, 4.1, None], {}),
    ('P1', ("Average delivery time", "მიწოდების საშუალო დრო"), ("days", "დღე"), 'lower_better',
     3.0, 4.5, None, [4.2, 3.4, 2.9, 3.1],
     {0: ("The new warehouse layout was not ready; picking was still done by hand.",
          "საწყობის ახალი განლაგება ჯერ მზად არ იყო; შეკვეთებს ისევ ხელით აგროვებდნენ.")}),
    ('P2', ("Complaints per 100 orders", "საჩივრები 100 შეკვეთაზე"), ("complaints", "საჩივარი"),
     'lower_better', 2.0, 3.0, None, [2.5, 2.1, 1.8, None], {}),
    ('L1', ("Training hours per employee", "სწავლების საათები ერთ თანამშრომელზე"),
     ("hours", "საათი"), 'higher_better', 10.0, 4.0, None, [6.0, 9.0, 11.0, None],
     {0: ("The training programme only started in March.",
          "სასწავლო პროგრამა მხოლოდ მარტში დაიწყო.")}),
    ('L1', ("Employee engagement", "თანამშრომელთა ჩართულობა"), ("%", "%"), 'target_range',
     0.0, 64.0, (70.0, 85.0), [66.0, 72.0, 78.0, None], {}),
]

KPI_DEFINITIONS = [
    ("Invoiced revenue for the quarter, without VAT, from the accounting report.",
     "კვარტლის ინვოისებული შემოსავალი დღგ-ს გარეშე, საბუღალტრო ანგარიშგებიდან."),
    ("Net profit divided by revenue for the quarter, times 100.",
     "კვარტლის წმინდა მოგება გაყოფილი შემოსავალზე, გამრავლებული 100-ზე."),
    ("Quarterly survey: % promoters minus % detractors, at least 100 answers.",
     "კვარტალური გამოკითხვა: მხარდამჭერების % მინუს კრიტიკოსების %, მინიმუმ 100 პასუხი."),
    ("Share of the top 50 customers who placed no order this quarter.",
     "50 უმსხვილესი მომხმარებლიდან იმათი წილი, ვისაც ამ კვარტალში შეკვეთა არ გაუკეთებია."),
    ("Working days from order confirmation to delivery, average of all orders.",
     "სამუშაო დღეები შეკვეთის დადასტურებიდან მიწოდებამდე, ყველა შეკვეთის საშუალო."),
    ("Registered complaints divided by orders delivered, times 100.",
     "რეგისტრირებული საჩივრები გაყოფილი მიწოდებულ შეკვეთებზე, გამრავლებული 100-ზე."),
    ("Training hours recorded in HR for the quarter, divided by headcount.",
     "კვარტალში HR-ში აღრიცხული სწავლების საათები გაყოფილი თანამშრომელთა რაოდენობაზე."),
    ("Engagement survey score; healthy between 70 % and 85 %.",
     "ჩართულობის გამოკითხვის შედეგი; ჯანსაღი დონე 70 %-სა და 85 %-ს შორისაა."),
]

LINKS = [
    # cause, effect, (hypothesis en, ka), strength, validated
    ('L1', 'P1', ("Trained staff pick and dispatch orders faster.",
                  "მომზადებული თანამშრომლები შეკვეთებს უფრო სწრაფად აგროვებენ და აგზავნიან."),
     'medium', False),
    ('L1', 'P2', ("Better skills mean fewer mistakes and complaints.",
                  "უკეთესი უნარები ნაკლებ შეცდომასა და საჩივარს ნიშნავს."), 'strong', True),
    ('L2', 'P1', ("Digital order tracking removes manual hand-offs.",
                  "შეკვეთების ციფრული აღრიცხვა ხელით გადაცემის ეტაპებს აქრობს."), 'medium', False),
    ('P1', 'C1', ("Faster delivery makes customers happier.",
                  "უფრო სწრაფი მიწოდება მომხმარებელს უფრო კმაყოფილს ხდის."), 'strong', True),
    ('P2', 'C1', ("Fewer complaints raise satisfaction.",
                  "ნაკლები საჩივარი კმაყოფილებას ზრდის."), 'medium', False),
    ('P2', 'C2', ("Reliable service keeps key customers.",
                  "საიმედო მომსახურება ძირითად მომხმარებლებს ინარჩუნებს."), 'medium', False),
    ('C1', 'F1', ("Satisfied customers buy more and recommend us.",
                  "კმაყოფილი მომხმარებლები მეტს ყიდულობენ და სხვებსაც გვირჩევენ."), 'strong', True),
    ('C2', 'F1', ("Keeping a customer costs less than winning a new one.",
                  "მომხმარებლის შენარჩუნება ახლის მოზიდვაზე იაფი ჯდება."), 'medium', False),
    ('F1', 'F2', ("More revenue on the same fixed costs lifts the margin.",
                  "იმავე ფიქსირებულ ხარჯებზე მეტი შემოსავალი მარჟას ზრდის."), 'weak', False),
]

INITIATIVES = [
    # key, (en, ka), objectives, stage xmlid, planned, actual, progress, priority, start, end (cycle months, 'overdue'),
    # (expected impact en, ka), (result en, ka) or None
    ('crm', ("Roll out a CRM for the sales team", "გაყიდვების გუნდისთვის CRM-ის დანერგვა"),
     ['F1', 'C2'], 'initiative_stage_in_progress', 40000.0, 26000.0, 60.0, '2', 1, 11,
     ("Every key customer has an owner and a visit plan; churn below 5 %.",
      "ყველა ძირითად მომხმარებელს ჰყავს პასუხისმგებელი და ვიზიტების გეგმა; გადინება 5 %-ზე ნაკლებია."),
     None),
    ('warehouse', ("Redesign the warehouse process", "საწყობის პროცესის გადაწყობა"),
     ['P1'], 'initiative_stage_in_progress', 35000.0, 37500.0, 70.0, '3', 0, 'overdue',
     ("Delivery time down to three days by the end of the second quarter.",
      "მიწოდების დრო მეორე კვარტლის ბოლოსთვის სამ დღემდე მცირდება."),
     None),
    ('academy', ("Staff training academy", "თანამშრომელთა სასწავლო აკადემია"),
     ['L1'], 'initiative_stage_done', 15000.0, 14200.0, 100.0, '1', 0, 6,
     ("Ten training hours per employee per quarter.",
      "კვარტალში ათი საათი სწავლება თითო თანამშრომელზე."),
     ("Academy launched in March; 46 employees completed the core course.",
      "აკადემია მარტში ამოქმედდა; ძირითადი კურსი 46-მა თანამშრომელმა გაიარა.")),
    ('quality', ("Quality control checklist", "ხარისხის კონტროლის ჩეკლისტი"),
     ['P2'], 'initiative_stage_proposed', 0.0, 0.0, 0.0, '1', 9, 12,
     ("Every order checked against a short list before dispatch.",
      "ყოველი შეკვეთა გაგზავნამდე მოკლე ჩეკლისტით მოწმდება."),
     None),
    ('barcode', ("Warehouse barcode scanning", "საწყობში შტრიხკოდით სკანირება"),
     ['L2', 'P1'], 'initiative_stage_approved', 20000.0, 5000.0, 20.0, '2', 6, 12,
     ("No paper picking lists; stock accurate in real time.",
      "ქაღალდის სიები აღარ არის; მარაგი რეალურ დროში ზუსტია."),
     None),
    ('pricing', ("Pricing and discount review", "ფასებისა და ფასდაკლებების გადახედვა"),
     ['F2'], 'initiative_stage_approved', 8000.0, 0.0, 10.0, '3', 9, 11,
     ("Margin back above 12 % without losing volume.",
      "მარჟა კვლავ 12 %-ს ზემოთ, გაყიდვების მოცულობის დაკარგვის გარეშე."),
     None),
]

REVIEWS = {
    # quarter index: (findings en, ka), (decisions en, ka), done
    0: (("Delivery time and training are off track; the warehouse layout is the bottleneck.",
         "მიწოდების დრო და სწავლება გეგმას ჩამორჩება; ვიწრო ადგილი საწყობის განლაგებაა."),
        ("Speed up the warehouse redesign; launch the training academy in March.",
         "დავაჩქაროთ საწყობის გადაწყობა; სასწავლო აკადემია მარტში ამოქმედდეს."), True),
    1: (("Most measures recovered. Delivery time is close to target.",
         "მაჩვენებლების უმეტესობა გამოსწორდა. მიწოდების დრო მიზნობრივს უახლოვდება."),
        ("Keep the course. Start planning barcode scanning for the second half.",
         "კურსი ვინარჩუნებთ. წლის მეორე ნახევრისთვის დავგეგმოთ შტრიხკოდით სკანირება."), True),
    2: (("Margin fell to 9 % after the summer discounts; revenue slightly behind.",
         "ზაფხულის ფასდაკლებების შემდეგ მარჟა 9 %-მდე დაეცა; შემოსავალი ოდნავ ჩამორჩება."),
        ("Review the discount policy before the next campaign.",
         "მომდევნო კამპანიამდე გადავხედოთ ფასდაკლებების პოლიტიკას."), False),
}


class BscDemoData(models.TransientModel):
    _name = 'bsc.demo.data'
    _description = 'BSC Demo Data'

    demo_count = fields.Integer(compute='_compute_demo_count')

    def _compute_demo_count(self):
        count = self.env['bsc.scorecard'].sudo().with_context(active_test=False).search_count(
            [('is_demo', '=', True), ('company_id', '=', self.env.company.id)])
        for wizard in self:
            wizard.demo_count = count

    def _check_admin(self):
        # The loader runs as superuser, so the gate has to be explicit.
        if not (self.env.is_superuser() or self.env.user.has_group('bsc_strategy.group_bsc_admin')):
            raise AccessError(_("Only a Balanced Scorecard administrator can load or remove demo data."))

    def _is_georgian(self):
        return (self.env.context.get('lang') or self.env.user.lang or '').startswith('ka')

    def _t(self, pair):
        return pair[1] if self._is_georgian() else pair[0]

    @api.model
    def _cycle_dates(self):
        """A year ending with the current quarter: three closed quarters with reviews, one open."""
        today = fields.Date.context_today(self)
        quarter_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        start = quarter_start - relativedelta(months=9)
        end = start + relativedelta(years=1, days=-1)
        return start, end

    def _perspective(self, code, created):
        Perspective = self.env['bsc.perspective'].with_context(active_test=False)
        xmlid, english, georgian, sequence = PERSPECTIVES[code]
        perspective = self.env.ref('bsc_strategy.%s' % xmlid, raise_if_not_found=False)
        if not perspective or not perspective.active:
            perspective = Perspective.search([
                ('code', '=', code), ('active', '=', True),
                ('company_id', 'in', [False, self.env.company.id])], limit=1)
        if not perspective:
            perspective = Perspective.create({
                'name': georgian if self._is_georgian() else english,
                'code': 'demo_%s' % code,
                'sequence': sequence,
                'company_id': self.env.company.id,
                'is_demo': True,
            })
            created.append(perspective)
        return perspective

    def action_load(self):
        self.ensure_one()
        self._check_admin()
        if self.demo_count:
            raise UserError(_("The demo data is already loaded. Remove it first to load it again."))
        # Runs as system so a manager's rights never stop it halfway; the period lock is bypassed to fill history.
        env_user = self.env.user
        self = self.sudo().with_context(bsc_bypass_period_lock=True, tracking_disable=True,
                                        mail_notrack=True, mail_create_nolog=True)
        start, end = self._cycle_dates()
        created_perspectives = []
        perspectives = {code: self._perspective(code, created_perspectives) for code in PERSPECTIVES}

        card = self.env['bsc.scorecard'].create({
            'name': self._t(SCORECARD_NAME) % start.year if start.year == end.year
            else self._t(SCORECARD_NAME) % ('%s-%s' % (start.year, end.year)),
            'date_from': start,
            'date_to': end,
            'frequency': 'quarterly',
            'responsible_id': env_user.id,
            'vision': Markup('<p>%s</p>') % self._t(VISION),
            'mission': Markup('<p>%s</p>') % self._t(MISSION),
            'is_demo': True,
            'auto_create_review': True,
        })

        objectives = {}
        for code, persp, names, mode, weight, description in OBJECTIVES:
            values = {
                'scorecard_id': card.id,
                'code': code,
                'name': self._t(names),
                'perspective_id': perspectives[persp].id,
                'assessment_mode': mode,
                'weight': weight,
                'owner_id': env_user.id,
                'description': self._t(description),
            }
            if code in QUALITATIVE:
                status, note = QUALITATIVE[code]
                values.update({'qualitative_status': status, 'qualitative_note': self._t(note)})
            objectives[code] = self.env['bsc.objective'].create(values)

        kpis = []
        for index, (objective, names, unit, direction, target, baseline, rng, actuals,
                    comments) in enumerate(KPIS):
            values = {
                'objective_id': objectives[objective].id,
                'name': self._t(names),
                'uom_name': self._t(unit),
                'direction': direction,
                'default_target': target,
                'baseline_value': baseline,
                'owner_id': env_user.id,
                'description': self._t(KPI_DEFINITIONS[index]),
            }
            if rng:
                values.update({'target_min': rng[0], 'target_max': rng[1]})
            kpis.append((self.env['bsc.kpi'].create(values), actuals, comments))

        for cause, effect, hypothesis, strength, validated in LINKS:
            self.env['bsc.objective.link'].create({
                'source_id': objectives[cause].id,
                'target_id': objectives[effect].id,
                'hypothesis': self._t(hypothesis),
                'strength': strength,
                'validated': validated,
            })

        card.action_activate()
        periods = card.period_ids.sorted('date_from')

        for index, period in enumerate(periods[:4]):
            period.action_prepare_measurements()
            for kpi, actuals, comments in kpis:
                value = actuals[index] if index < len(actuals) else None
                if value is None:
                    continue
                row = period.measurement_ids.filtered(lambda m, k=kpi: m.kpi_id == k)
                if not row:
                    continue
                values = {'actual_value': value}
                if index in comments:
                    values['comment'] = self._t(comments[index])
                row.write(values)
                if index < 3:
                    row.write({'state': 'validated'})
                else:
                    row.write({'state': 'submitted'})
            if index < 3:
                period.action_close()
        card.activity_ids.unlink()

        initiatives = {}
        stage_proposed = self.env.ref('bsc_strategy.initiative_stage_proposed')
        for (key, names, objective_codes, stage, planned, actual, progress, priority,
             start_month, end_month, impact, result) in INITIATIVES:
            date_start = start + relativedelta(months=start_month)
            if end_month == 'overdue':
                date_end = fields.Date.context_today(self) - relativedelta(days=12)
            else:
                date_end = start + relativedelta(months=end_month, days=-1)
            initiative = self.env['bsc.initiative'].create({
                'scorecard_id': card.id,
                'name': self._t(names),
                'objective_ids': [(6, 0, [objectives[c].id for c in objective_codes])],
                'stage_id': stage_proposed.id,
                'owner_id': env_user.id,
                'priority': priority,
                'date_start': date_start,
                'date_end': date_end,
                'expected_impact': self._t(impact),
                'use_project_progress': False,
            })
            values = {'budget_planned': planned, 'budget_actual': actual,
                      'progress': progress}
            if result:
                values['result_summary'] = self._t(result)
            initiative.write(values)
            target_stage = self.env.ref('bsc_strategy.%s' % stage)
            if target_stage != stage_proposed:
                initiative.write({'stage_id': target_stage.id})
            initiatives[key] = initiative

        reviews = card.review_ids.sorted(lambda r: r.period_id.date_from)
        for index, review in enumerate(reviews):
            if index not in REVIEWS:
                continue
            findings, decisions, done = REVIEWS[index]
            review.write({
                'review_date': review.period_id.date_to + relativedelta(days=10),
                'participant_ids': [(6, 0, env_user.ids)],
                'findings': Markup('<p>%s</p>') % self._t(findings),
                'decisions': Markup('<p>%s</p>') % self._t(decisions),
            })
            if index == 2:
                initiatives['pricing'].review_id = review
            if done:
                review.action_done()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Demo data loaded"),
                'message': _("Open the scorecard \"%s\", the Dashboard or the Strategy Map "
                             "to explore it.", card.name),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_remove(self):
        self.ensure_one()
        self._check_admin()
        self = self.sudo().with_context(bsc_bypass_period_lock=True, active_test=False,
                                        tracking_disable=True)
        cards = self.env['bsc.scorecard'].search([
            ('is_demo', '=', True), ('company_id', '=', self.env.company.id)])
        if not cards:
            raise UserError(_("There is no demo data to remove."))
        count = len(cards)
        # Children first, through the ORM, so chatter, activities and followers go with them.
        cards.review_ids.unlink()
        initiatives = self.env['bsc.initiative'].search([('scorecard_id', 'in', cards.ids)])
        initiatives.unlink()
        self.env['bsc.measurement'].search([('scorecard_id', 'in', cards.ids)]).unlink()
        cards.period_ids.unlink()
        cards.link_ids.unlink()
        self.env['bsc.kpi'].search([('scorecard_id', 'in', cards.ids)]).unlink()
        self.env['bsc.objective'].search([('scorecard_id', 'in', cards.ids)]).unlink()
        cards.unlink()
        perspectives = self.env['bsc.perspective'].search([
            ('is_demo', '=', True), ('company_id', '=', self.env.company.id)])
        used = self.env['bsc.objective'].search_count([('perspective_id', 'in', perspectives.ids)])
        if perspectives and not used:
            perspectives.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Demo data removed"),
                'message': _("%s demo scorecard(s) and everything in them were deleted.", count),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }
