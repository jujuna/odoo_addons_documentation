from odoo import models, fields, api, _
from .rs_waybill import WAYBILL_STATUS
from .rs_waybill_soap_service import TBILISI_TZ, UTC_TZ
from datetime import timedelta, datetime
import base64
import html
import re
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)


# Used when the company has no valid color set (Settings > Companies; the brand kit writes them on Apply).
DEFAULT_HEADER_COLOR = '#0b2545'
DEFAULT_ACCENT_COLOR = '#ffd166'
DARK_TEXT = '#0f172a'
HEX_COLOR = re.compile(r'^#(?:[0-9a-fA-F]{3}){1,2}$')


def _luminance(color):
    """ WCAG relative luminance of a #rgb / #rrggbb color. """
    value = color.lstrip('#')
    if len(value) == 3:
        value = ''.join(ch * 2 for ch in value)
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class RsWaybill(models.Model):
    _inherit = 'rs.waybill'

    @api.model
    def _rs_mail_brand(self, company):
        """ Email colors and logo of the company. Text on the header is white or dark, whichever reads better;
            an accent that does not stand out on the header falls back to that text color. """
        def color(value, default):
            return value if value and HEX_COLOR.match(value) else default

        header = color(company.primary_color, DEFAULT_HEADER_COLOR)
        light = _contrast(header, '#ffffff') >= _contrast(header, DARK_TEXT)
        text = '#ffffff' if light else DARK_TEXT
        accent = color(company.email_secondary_color, DEFAULT_ACCENT_COLOR)
        if _contrast(accent, header) < 3:
            accent = text
        return {
            'header': header,
            'text': text,
            'text_soft': 'rgba(255,255,255,0.65)' if light else 'rgba(15,23,42,0.65)',
            'chip_bg': 'rgba(255,255,255,0.08)' if light else 'rgba(15,23,42,0.06)',
            'chip_border': 'rgba(255,255,255,0.18)' if light else 'rgba(15,23,42,0.15)',
            'accent': accent,
            # Absolute URL: email clients have no host to resolve a relative one against.
            'logo_url': '%s/logo.png?company=%s' % (company.get_base_url(), company.id) if company.logo else '',
            'company': company.name or '',
        }

    @api.model
    def _rs_mail_top_bar(self, brand, ref=''):
        """ White bar with the company logo (or name): any logo reads on white, not every one on the header color. """
        if brand['logo_url']:
            logo = Markup('<img src="%s" alt="%s" height="40" style="height:40px;max-width:200px;'
                          'border:0;display:block;"/>') % (brand['logo_url'], brand['company'])
        else:
            logo = Markup('<span style="font-size:17px;font-weight:700;color:#0f172a;">%s</span>') % brand['company']
        return Markup(
            '<tr><td style="padding:20px 40px;background:#ffffff;border-bottom:1px solid #e2e8f0;">'
            '<table width="100%%" cellpadding="0" cellspacing="0" border="0"><tr>'
            '<td valign="middle">%s</td>'
            '<td align="right" valign="middle" style="font-size:11px;color:#94a3b8;font-family:monospace;">%s</td>'
            '</tr></table></td></tr>') % (logo, ref)

    @api.model
    def _rs_mail_frame(self, company, title, content):
        """ The digest emails in the same frame as a waybill email: logo bar, colored title, content. """
        brand = self._rs_mail_brand(company)
        return Markup(
            '<div style="background:#f4f5f7;padding:32px 0;font-family:Helvetica,Arial,sans-serif;">'
            '<table width="620" align="center" cellpadding="0" cellspacing="0" border="0" '
            'style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 4px 12px rgba(15,23,42,0.08);">'
            '%(top)s'
            '<tr><td style="background:%(header)s;padding:24px 40px;color:%(text)s;font-size:20px;font-weight:700;">'
            '%(title)s</td></tr>'
            '<tr><td style="padding:24px 40px 32px;font-size:14px;color:#0f172a;">%(content)s</td></tr>'
            '<tr><td style="padding:16px 40px;background:#f8fafc;border-top:1px solid #e2e8f0;'
            'font-size:11px;color:#94a3b8;">%(company)s</td></tr>'
            '</table></div>') % {
                'top': self._rs_mail_top_bar(brand), 'header': brand['header'], 'text': brand['text'],
                'title': title, 'content': content, 'company': brand['company']}

    def _get_waybill_email_body(self, recipient_direction=None, action=None):
        self.ensure_one()
        brand = self._rs_mail_brand(self.company_id or self.env.company)

        direction = recipient_direction or self.waybill_direction

        if action:
            status_label = action
            status_label_ge = {
                'Confirmed': 'დადასტურებული',
                'Rejected': 'უარყოფილი',
                'Refused': 'უარყოფილი',
                'New': 'ახალი',
                'Sent to Transporter': 'გადამზიდთან გადაგზავნილი',
                'Transport Activated': 'გადაზიდვა გააქტიურდა',
                'Transport Completed': 'გადაზიდვა დასრულდა',
                'Edited': 'რედაქტირებული',
            }.get(action, action)
        else:
            status_label = dict(WAYBILL_STATUS).get(self.waybill_status, 'Unknown')
            status_labels_ge = {
                '0': 'შენახული',
                '1': 'აქტიური',
                '2': 'დასრულებული',
                '8': 'ტრანსპორტიორთან გაგზავნილი',
                '-1': 'წაშლილი',
                '-2': 'გაუქმებული',
            }
            status_label_ge = status_labels_ge.get(self.waybill_status, '')

        direction_label = dict([
            ('seller', 'Seller'),
            ('buyer', 'Buyer'),
            ('transporter', 'Transporter'),
        ]).get(direction, '')
        direction_label_ge = dict([
            ('seller', 'გამყიდველი'),
            ('buyer', 'მყიდველი'),
            ('transporter', 'გადამზიდავი'),
        ]).get(direction, '')

        step_map = {'0': 0, '1': 1, '8': 2, '2': 3, '-1': -1, '-2': -1}
        current_step = step_map.get(self.waybill_status, 0)
        steps = [
            ('Saved', 'შენახული'),
            ('Active', 'აქტიური'),
            ('In Transit', 'გზაში'),
            ('Completed', 'დასრულებული'),
        ]

        step_cells = ''
        for idx, (en, ge) in enumerate(steps):
            done = current_step >= 0 and idx <= current_step
            bg = brand['header'] if done else '#ffffff'
            border = brand['header'] if done else '#cbd5e1'
            circle_color = brand['text'] if done else '#94a3b8'
            text_color = '#0f172a' if done else '#94a3b8'
            sub_color = '#475569' if done else '#cbd5e1'
            mark = '&#10003;' if done else str(idx + 1)
            step_cells += (
                              '<td align="center" valign="top" width="25%%" style="padding:0 4px;">'
                              '<div style="width:26px;height:22px;line-height:22px;'
                              'border-radius:13px;background:%s;border:2px solid %s;color:%s;'
                              'font-size:12px;font-weight:700;text-align:center;margin:0 auto;'
                              'padding:0;">%s</div>'
                              '<div style="margin-top:10px;font-size:11px;font-weight:700;'
                              'color:%s;letter-spacing:0.3px;">%s</div>'
                              '<div style="font-size:10px;color:%s;margin-top:2px;">%s</div>'
                              '</td>'
                          ) % (bg, border, circle_color, mark, text_color, en, sub_color, ge)

        # Stored UTC; the email shows Georgian time, as RS.GE does.
        activation_str = (self.activation_date.replace(tzinfo=UTC_TZ).astimezone(TBILISI_TZ)
                          .strftime('%Y-%m-%d %H:%M:%S') if self.activation_date else '')
        if ' ' in activation_str:
            activation_date_part, activation_time_part = activation_str.split(' ', 1)
        else:
            activation_date_part, activation_time_part = activation_str, ''

        waybill_no = self.rs_waybill_number or self.rs_internal_id or ''

        return """
    <div style="background:#f4f5f7;padding:32px 0;font-family:Helvetica,Arial,sans-serif;">
      <table width="620" align="center" cellpadding="0" cellspacing="0" border="0"
             style="background:#ffffff;border-radius:14px;overflow:hidden;
                    box-shadow:0 4px 12px rgba(15,23,42,0.08);">

        %(top_bar)s

        <!-- HERO (company color) -->
        <tr><td style="background:%(header)s;padding:32px 40px 40px;color:%(text)s;">
          <div style="font-size:11px;color:%(accent)s;letter-spacing:2px;
                      text-transform:uppercase;font-weight:700;">
            Status Update · სტატუსის განახლება
          </div>
          <div style="font-size:30px;font-weight:700;line-height:1.15;margin-top:10px;
                      color:%(text)s;">
            Your waybill is <span style="color:%(accent)s;">%(status)s.</span>
          </div>
          <div style="font-size:16px;color:%(text_soft)s;margin-top:8px;">
            ზედნადები %(status_ge)s.
          </div>

          <div style="margin-top:28px;display:inline-block;padding:10px 16px;
                      background:%(chip_bg)s;
                      border:1px solid %(chip_border)s;border-radius:999px;">
            <span style="font-size:11px;color:%(text_soft)s;
                          text-transform:uppercase;letter-spacing:1px;font-weight:600;">
              Number
            </span>
            <span style="margin:0 10px;color:%(text_soft)s;">|</span>
            <span style="font-size:14px;font-weight:600;font-family:monospace;
                          color:%(text)s;letter-spacing:0.5px;">%(number)s</span>
          </div>
        </td></tr>

        <!-- LIFECYCLE -->
        <tr><td style="padding:32px 40px 16px;border-bottom:1px solid #f1f5f9;">
          <div style="font-size:10px;color:#94a3b8;text-transform:uppercase;
                      letter-spacing:1.5px;font-weight:700;margin-bottom:20px;">
            Lifecycle · ცხოვრების ციკლი
          </div>
          <table width="100%%" cellpadding="0" cellspacing="0" border="0">
            <tr>%(steps)s</tr>
          </table>
        </td></tr>

        <!-- META: Direction + Activation -->
        <tr><td style="padding:32px 40px 0;">
          <table width="100%%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td width="50%%" valign="top" style="padding-right:12px;">
                <div style="font-size:10px;color:#94a3b8;text-transform:uppercase;
                            letter-spacing:1px;font-weight:700;">Direction · მიმართულება</div>
                <div style="font-size:15px;font-weight:600;color:#0f172a;margin-top:6px;">%(direction)s</div>
                <div style="font-size:12px;color:#64748b;margin-top:1px;">%(direction_ge)s</div>
              </td>
              <td width="50%%" valign="top" style="padding-left:12px;">
                <div style="font-size:10px;color:#94a3b8;text-transform:uppercase;
                            letter-spacing:1px;font-weight:700;">Activation · გააქტიურება</div>
                <div style="font-size:15px;font-weight:600;color:#0f172a;margin-top:6px;
                            font-family:monospace;">%(activation_date)s</div>
                <div style="font-size:12px;color:#64748b;margin-top:1px;
                            font-family:monospace;">%(activation_time)s</div>
              </td>
            </tr>
          </table>

          <div style="height:1px;background:#f1f5f9;margin:28px 0;"></div>

          <!-- Seller -->
          <div style="font-size:10px;color:#94a3b8;text-transform:uppercase;
                      letter-spacing:1px;font-weight:700;">Seller · გამყიდველი</div>
          <div style="font-size:15px;font-weight:600;color:#0f172a;margin-top:6px;
                      line-height:1.4;">%(seller)s</div>

          <div style="height:20px;"></div>

          <!-- Buyer -->
          <div style="font-size:10px;color:#94a3b8;text-transform:uppercase;
                      letter-spacing:1px;font-weight:700;">Buyer · მყიდველი</div>
          <div style="font-size:15px;font-weight:600;color:#0f172a;margin-top:6px;
                      line-height:1.4;">%(buyer)s</div>

          <div style="height:1px;background:#f1f5f9;margin:28px 0 0;"></div>
        </td></tr>

        <!-- FOOTER -->
        <tr><td style="padding:24px 40px 32px;background:#f8fafc;
                       border-top:1px solid #e2e8f0;">
          <table width="100%%" cellpadding="0" cellspacing="0" border="0"><tr>
            <td style="font-size:11px;color:#94a3b8;line-height:1.6;">
              %(company)s · Waybill Center<br/>
              Automated notification — do not reply
            </td>
            <td align="right" style="font-size:11px;color:#94a3b8;
                                     font-family:monospace;">REF: %(number)s</td>
          </tr></table>
        </td></tr>

      </table>
    </div>
        """ % {
            'top_bar': self._rs_mail_top_bar(brand, ref=str(waybill_no)),
            'header': brand['header'],
            'text': brand['text'],
            'text_soft': brand['text_soft'],
            'chip_bg': brand['chip_bg'],
            'chip_border': brand['chip_border'],
            'accent': brand['accent'],
            'status': html.escape(status_label),
            'status_ge': html.escape(status_label_ge),
            'number': html.escape(str(waybill_no)),
            'steps': step_cells,
            'direction': direction_label,
            'direction_ge': direction_label_ge,
            'activation_date': html.escape(activation_date_part),
            'activation_time': html.escape(activation_time_part),
            'seller': html.escape(self.seller_name or ''),
            'buyer': html.escape(self.buyer_name or ''),
            'company': html.escape(brand['company']),
        }


    def _send_notification_email(self, action=None):
        self.ensure_one()
        digest = self.env.context.get('rs_notify_digest')
        if digest is not None:
            # Sync run: note on the waybill only; the run ends with one summary per user and one email per customer.
            self.message_post(body=Markup(self._get_waybill_email_body(action=action)),
                              subject=self._rs_notification_subject(action),
                              subtype_xmlid='mail.mt_note')
            digest.append((self.id, action))
            return
        if action:
            subject = _('Waybill %s - %s') % (
                self.rs_waybill_number or self.rs_internal_id, action)
        else:
            subject = _('Waybill %s - %s') % (
                self.rs_waybill_number or self.rs_internal_id,
                dict(WAYBILL_STATUS).get(self.waybill_status, ''))

        if self.waybill_direction == 'seller' and self.buyer_contact_email and self.buyer_contact_email.email:
            body = self._get_waybill_email_body(recipient_direction='buyer', action=action)
            mail = self.env['mail.mail'].sudo().create({
                'subject': subject,
                'email_to': self.buyer_contact_email.email,
                'body_html': body,
                'auto_delete': True,
            })
            # Send now, not via the mail queue: a stopped queue cron would silently drop this transactional notice.
            # raise_exception=False so a bad address never breaks the lifecycle action.
            mail.send(raise_exception=False)

        users = self._get_notification_users()
        partners = users.partner_id.filtered('email')
        if partners:
            body = self._get_waybill_email_body(action=action)
            self.message_post(
                # Built from escaped values: mark it HTML or the chatter shows its source.
                body=Markup(body),
                subject=subject,
                partner_ids=partners.ids,
                subtype_xmlid='mail.mt_comment',
            )


    def _rs_notification_subject(self, action=None):
        return _('Waybill %s - %s') % (self.rs_waybill_number or self.rs_internal_id,
                                       action or dict(WAYBILL_STATUS).get(self.waybill_status, ''))


    @api.model
    def _rs_send_notification_digest(self, entries):
        """ End of a sync run: each company's notification users get one email listing every changed
            waybill; each customer (buyer contact email) gets one listing their own waybills by number
            (customers cannot open our Odoo). """
        waybills = self.browse(dict.fromkeys(wid for wid, _action in entries)).exists()
        actions = {wid: action for wid, action in entries}
        if not waybills:
            return

        def status(waybill):
            return actions.get(waybill.id) or dict(WAYBILL_STATUS).get(waybill.waybill_status, '')

        def number(waybill):
            return waybill.rs_waybill_number or str(waybill.rs_internal_id or '')

        for company in waybills.company_id | (self.env['res.company'] if all(waybills.mapped('company_id'))
                                              else self.env.company):
            mine = waybills.filtered(lambda w: (w.company_id or self.env.company) == company)
            partners = company.sudo().rs_notification_user_ids.partner_id.filtered('email')
            if not mine or not partners:
                continue
            # Full URL: a relative link has no host to open from inside an email client.
            rows = Markup('').join(
                Markup('<tr><td><a href="%s/odoo/rs.waybill/%s">%s</a></td><td>%s</td><td>%s</td></tr>')
                % (w.get_base_url(), w.id, number(w), w.buyer_name or w.seller_name or '', status(w)) for w in mine)
            body = Markup(_('<p>%(count)s waybills came in or changed on RS.GE:</p>'
                            '<table border="1" cellpadding="4" style="border-collapse:collapse">'
                            '<tr><th>Waybill</th><th>Partner</th><th>Status</th></tr>%(rows)s</table>')
                          ) % {'count': len(mine), 'rows': rows}
            body = self._rs_mail_frame(company, _('RS.GE: %s waybills changed') % len(mine), body)
            self.env['mail.mail'].sudo().create({
                'subject': _('RS.GE: %s waybills changed') % len(mine),
                'body_html': body,
                'recipient_ids': [(6, 0, partners.ids)],
                'auto_delete': True,
            }).send(raise_exception=False)

        by_customer = {}
        for waybill in waybills.filtered(lambda w: w.waybill_direction == 'seller'
                                         and w.buyer_contact_email.email):
            by_customer.setdefault(waybill.buyer_contact_email.email, []).append(waybill)
        for email, theirs in by_customer.items():
            rows = Markup('').join(Markup('<tr><td>%s</td><td>%s</td></tr>') % (number(w), status(w))
                                   for w in theirs)
            body = Markup(_('<p>Your waybills from %(company)s were updated on RS.GE:</p>'
                            '<table border="1" cellpadding="4" style="border-collapse:collapse">'
                            '<tr><th>Waybill</th><th>Status</th></tr>%(rows)s</table>')
                          ) % {'company': theirs[0].company_id.name or self.env.company.name, 'rows': rows}
            body = self._rs_mail_frame(theirs[0].company_id or self.env.company,
                                       _('Waybills updated: %s') % ', '.join(number(w) for w in theirs), body)
            self.env['mail.mail'].sudo().create({
                'subject': _('Waybills updated: %s') % ', '.join(number(w) for w in theirs),
                'email_to': email,
                'body_html': body,
                'auto_delete': True,
            }).send(raise_exception=False)
