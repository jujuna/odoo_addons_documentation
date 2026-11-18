import json
import logging
import threading
import xml.etree.ElementTree as ET
import requests as http_requests
from datetime import date, datetime
from lxml import etree
from zoneinfo import ZoneInfo
from odoo import models, _
from odoo.exceptions import UserError


TBILISI_TZ = ZoneInfo('Asia/Tbilisi')
UTC_TZ = ZoneInfo('UTC')


_logger = logging.getLogger(__name__)


WSDL_URL = "https://services.rs.ge/WayBillService/WayBillService.asmx?WSDL"

# Per-call SOAP timeout: a hung request must not lock an Odoo worker.
SOAP_TIMEOUT = 30
# One zeep Client + HistoryPlugin per thread: a history slot shared between threads mixes up overlapping replies.
_RS_CLIENT_LOCAL = threading.local()


class RsWaybillSoapService(models.AbstractModel):
    _name = 'rs.waybill.soap.service'
    _description = 'Revenue Service Waybill Soap Service'


    def _get_credentials(self):
        getter = getattr(self.env.user, '_get_rs_credentials', None)
        if not callable(getter):
            raise UserError(_("The RS Base Methods module is not installed, so rs.ge logins cannot be read."
                              " Ask your administrator to install it from Apps."))
        creds = getter()
        return creds['su'], creds['sp']


    def _rs_company_un_id(self, waybill):
        """ RS.GE taxpayer id of the waybill's company, stored per company by Test RS Credentials for the user's login.
            Named as seller in the XML, so a waybill is filed for its company even via a representative login. """
        company = waybill.company_id or self.env.company
        user = self.env.user.with_company(company)
        un_id = int(getattr(user, 'rs_un_id', 0) or 0)
        if not un_id:
            raise UserError(_("The RS.GE taxpayer id of %s is not stored yet. Switch to that "
                              "company, open your User Preferences and click 'Test RS Credentials'.", company.display_name))
        return str(un_id)


    def _get_client(self):
        """ Returns a cached zeep Client (WSDL parsed once per thread), reusing its HTTP session and the
            HistoryPlugin that _call_datatable reads raw responses from. """
        cached = getattr(_RS_CLIENT_LOCAL, 'cached', None)
        if cached is None:
            try:
                from zeep import Client
                from zeep.plugins import HistoryPlugin
                from zeep.transports import Transport
            except ImportError:
                raise UserError(_("The Python package 'zeep' is required for RS.GE. "
                                  "Ask the system administrator to install it: pip install zeep"))
            session = http_requests.Session()
            transport = Transport(session=session, timeout=SOAP_TIMEOUT, operation_timeout=SOAP_TIMEOUT,)
            history = HistoryPlugin()
            client = Client(WSDL_URL, transport=transport, plugins=[history])
            cached = (client, history)
            _RS_CLIENT_LOCAL.cached = cached
        client, history = cached
        su, sp = self._get_credentials()
        return client, su, sp, history


    def _check_rs_result(self, method_name, result):
        """ Interpret RS.GE integer result codes: 1 is success, anything else raises with RS.GE's own text for the code
            (get_error_codes), the code and the action in plain words. -100 / -101 keep their Odoo hint. """
        code = int(result) if result is not None else -1
        if code == 1:
            return code
        if code == -100:
            raise UserError(_("RS.GE rejected credentials. Open your User Preferences and "
                              "verify the RS Username and RS Password."))
        if code == -101:
            raise UserError(_("RS.GE: this waybill belongs to another taxpayer and cannot "
              "be modified from this account."))
        action = self._rs_action_label(method_name)
        rs_text = self._rs_error_codes().get(code)
        if rs_text:
            raise UserError(_("RS.GE did not accept %(action)s: %(text)s (code %(code)s).")
                            % {'action': action, 'text': rs_text, 'code': code})
        if code == -1:
            raise UserError(_("RS.GE did not accept %s (code -1, RS.GE gives no reason). Check "
                              "the waybill's data and state, then try again.") % action)
        raise UserError(_("RS.GE did not accept %(action)s (code %(code)s).")
                        % {'action': action, 'code': code})


    def _rs_action_label(self, method_name):
        """ The button the user pressed, for a SOAP method name in a message. """
        return {
            'save_waybill': _("Save"),
            'send_waybill': _("Activate"),
            'send_waybil_vd': _("Activate"),
            'close_waybill': _("Complete"),
            'close_waybill_vd': _("Complete"),
            'close_waybill_transporter': _("Complete"),
            'delete_waybill': _("Delete"),
            'refuse_waybill': _("Cancel"),
            'ref_waybill_vd': _("Cancel"),
            'confirm_waybill': _("Received"),
            'reject_waybill': _("Reject"),
            'send_waybill_transporter': _("Send to Transporter"),
            'save_car_numbers': _("Send car number to RS.GE"),
        }.get(method_name, method_name)


    def _rs_error_codes(self):
        """ {code: text} from RS.GE's own list (get_error_codes), kept for a day in a system parameter.
            Empty when RS.GE cannot be reached: the message then shows the code alone. """
        key = 'rs_waybill.error_codes'
        params = self.env['ir.config_parameter'].sudo()
        try:
            stored = json.loads(params.get_str(key, '') or '{}')
        except ValueError:
            stored = {}
        today = date.today().isoformat()
        if stored.get('date') != today:
            fresh = self._fetch_error_codes()
            if fresh:
                stored = {'date': today, 'codes': {str(k): v for k, v in fresh.items()}}
                # Own cursor: the refusal being reported rolls the current one back.
                with self.env.registry.cursor() as cr:
                    self.env(cr=cr)['ir.config_parameter'].sudo().set_str(key, json.dumps(stored))
        return {int(k): v for k, v in (stored.get('codes') or {}).items()}


    def _fetch_error_codes(self):
        try:
            client, su, sp, history = self._get_client()
            try:
                client.service.get_error_codes(su=su, sp=sp)
            except Exception as e:
                # Expected: zeep cannot read RS.GE's table reply; the raw XML is in history.
                _logger.debug("get_error_codes typed call failed (reading raw): %s", e)
            return self._parse_error_codes(history.last_received['envelope'])
        except Exception as e:
            _logger.warning("RS.GE error code list unavailable: %s", e)
            return {}


    def _parse_error_codes(self, envelope):
        """ {code: text} from a get_error_codes reply. Read by shape, not by tag names
            (not documented): each row's first whole-number field is the code, its first
            other non-empty field the text. """
        root = ET.fromstring(envelope.encode()) if isinstance(envelope, str) \
            else self._envelope_to_root(envelope)
        codes = {}
        for row in root.iter():
            fields = [child for child in row if not len(child)]
            if len(fields) < 2 or len(fields) != len(row):
                continue
            code = text = None
            for field in fields:
                value = (field.text or '').strip()
                if code is None and value.lstrip('-').isdigit():
                    code = int(value)
                elif value and not value.lstrip('-').isdigit() and text is None:
                    text = value
            if code is not None and text:
                codes[code] = text
        return codes


    def rs_login_ok(self):
        """ True / False whether RS.GE accepts the current user's RS Username and
            Password (chek_service_user), None when RS.GE cannot be reached. """
        try:
            client, su, sp, _history = self._get_client()
            result = client.service.chek_service_user(su=su, sp=sp)
        except UserError:
            return False
        except Exception as e:
            _logger.warning("RS.GE login check failed: %s", e)
            return None
        ok = result.get('chek_service_userResult') if isinstance(result, dict) else \
            getattr(result, 'chek_service_userResult', result)
        return bool(ok)


    def _check_rs_action_result(self, method_name, result):
        """ Judge an RS.GE action reply by sign, not == 1 (send_waybill returns the waybill number, confirm True).
            Negative, 0, False or nothing raises via _check_rs_result; anything else is success, returned unchanged. """
        if result is True:
            return result
        text = str(result).strip() if result is not None else ''
        if not text or text.lower() in ('false', 'null', 'none'):
            raise UserError(_("RS.GE did not accept %s: it returned no result. Nothing was "
                              "changed in Odoo. Click Update on the waybill to see its state on "
                              "RS.GE, then try again.") % self._rs_action_label(method_name))
        try:
            code = int(text)
        except ValueError:
            return result
        if code <= 0:
            self._check_rs_result(method_name, code if code else -1)
        return result


    @staticmethod
    def rs_local_to_utc(value):
        """ RS datetime string (Georgian local, UTC+4, no DST) -> UTC string for an Odoo Datetime (ingest only).
            Unparsable: returns the cleaned local string, so the sync row survives. """
        if not value:
            return None
        v = value.replace('T', ' ').strip()
        if '.' in v:
            v = v.split('.', 1)[0]
        try:
            naive = datetime.strptime(v, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return v
        return naive.replace(tzinfo=TBILISI_TZ).astimezone(UTC_TZ).strftime('%Y-%m-%d %H:%M:%S')


    def _check_rs_id(self, method_name, value):
        """ New-record-id replies (save_waybill_tamplate): a positive int is the id; <= 0 is an error
            code decoded like _check_rs_result. Returns the int id; otherwise raises UserError. """
        try:
            rs_id = int(value)
        except (TypeError, ValueError):
            _logger.error("RS.GE %s returned an unreadable id: %r", method_name, value)
            raise UserError(_("RS.GE returned an unexpected response for %s.") % method_name)
        if rs_id > 0:
            return rs_id
        # <= 0 is an error code: decode it for a real message.
        return self._check_rs_result(method_name, rs_id)


    def _envelope_to_root(self, envelope):
        """ Convert SOAP envelope to ElementTree(python XML tree) root for parsing"""
        raw_xml = etree.tostring(envelope).decode()
        return ET.fromstring(raw_xml)


    def _parse_datatable(self, envelope, row_tag='Table'):
        """ Parse RS.GE datatable response into list of dicts """
        root = self._envelope_to_root(envelope)
        rows = root.findall(f'.//{row_tag}')
        return [{field.tag: field.text for field in row} for row in rows]


    def _call_datatable(self, client, history, su, sp, method_name, params=None, row_tag='Table'):
        """ Zeep cannot parse RS.GE DataTable replies: the expected parse error is swallowed, raw XML read from
            HistoryPlugin; real failures (network, transport, SOAP fault) re-raise. """
        if params is None:
            params = {'su': su, 'sp': sp}
        try:
            from zeep.exceptions import Fault, TransportError
        except ImportError:
            Fault = TransportError = type('_NoSuch', (Exception,), {})
        # HistoryPlugin's buffer can be empty on the first call: guard .last_received (IndexError).
        try:
            prev_received = history.last_received
        except IndexError:
            prev_received = None
        try:
            getattr(client.service, method_name)(**params)
        except TransportError as e:
            _logger.error("RS.GE transport error in %s: %s", method_name, e)
            raise UserError(_("RS.GE service unreachable: %s") % e)
        except Fault as e:
            _logger.error("RS.GE SOAP fault in %s: %s", method_name, e)
            raise UserError(_("RS.GE rejected the request: %s") % e)
        except Exception as e:
            # Expected: zeep cannot deserialize DataTable replies; the response is read from the history buffer below.
            # Logged at debug so a genuine bug does not vanish.
            _logger.debug("%s: typed call raised (expected for DataTable replies), "
                          "reading the raw envelope instead: %s", method_name, e)
        try:
            current_received = history.last_received
        except IndexError:
            current_received = None
        if current_received is None or current_received is prev_received:
            raise UserError(_("RS.GE returned no response for %s. "
                              "Check network and credentials. ") % method_name)
        raw = etree.tostring(current_received['envelope'], pretty_print=True).decode()
        _logger.debug("RAW RESPONSE for %s: %s", method_name, raw)
        return self._parse_datatable(current_received['envelope'], row_tag)


    def _build_waybill_xml(self, waybill, client,
                           su, sp, removed_good_ids=None):
        """ Builds the full waybill XML with the goods list. removed_good_ids: RS good IDs deleted in an edit,
            appended as GOODS with STATUS=-1 so RS removes them (omitting them is not enough). """
        seller_un_id = self._rs_company_un_id(waybill)
        root = etree.Element('WAYBILL')

        fields_map = {
            'ID': str(waybill.rs_internal_id or '0'),
            # Sub: distribution (Odoo type 4) -> RS TYPE 6 (SUBWB) with a buyer; internal transport (type 1) -> TYPE 1,
            # the only type where RS waives the buyer (TYPE 6 without buyer -> -1004). Non-subs send their own type.
            'TYPE': (('1' if waybill.waybill_type == '1' else '6')
                     if waybill.parent_waybill_id else waybill.waybill_type),
            'BUYER_TIN': waybill.buyer_tin or '',
            'CHEK_BUYER_TIN': '1' if not waybill.citizen else '0',
            'BUYER_NAME': waybill.buyer_name or '',
            'START_ADDRESS': waybill.start_address or '',
            'END_ADDRESS': '' if waybill.waybill_type == '3' else (waybill.end_address or ''),
            'TRANSPORTER_TIN': waybill.transporter_tin or '',
            'DRIVER_TIN': waybill.driver_tin or '',
            'CHEK_DRIVER_TIN': '1' if not waybill.driver_is_foreigner else '0',
            'DRIVER_NAME': waybill.driver_name or '',
            'TRANSPORT_COAST': str(waybill.transport_cost or 0),
            'RECEPTION_INFO': waybill.reception_info or '',
            'RECEIVER_INFO': waybill.receiver_info or '',
            # delivery_date: stored UTC, RS expects Georgian local; sending it stops a live-edit save wiping it on RS.
            'DELIVERY_DATE': (waybill.delivery_date.replace(tzinfo=UTC_TZ)
                              .astimezone(TBILISI_TZ).strftime('%Y-%m-%dT%H:%M:%S')
                              if waybill.delivery_date else ''),
            'STATUS': str(waybill.waybill_status or '0'),
            'SELER_UN_ID': seller_un_id,
            'PAR_ID': str(waybill.parent_waybill_id.rs_internal_id) if waybill.parent_waybill_id.rs_internal_id else '',
            'FULL_AMOUNT': str(waybill.full_amount or 0),
            'CAR_NUMBER': waybill.car_number or '',
            'WAYBILL_NUMBER': waybill.rs_waybill_number or '',
            'S_USER_ID': '',
            # transport_start_date is stored UTC; RS expects Georgian local time. Subs inherit begin from the parent
            # (PAR_ID) and are saved with an empty BEGIN_DATE even though the sub holds its own transport_start_date.
            'BEGIN_DATE': ('' if waybill.parent_waybill_id else
                           (waybill.transport_start_date.replace(tzinfo=UTC_TZ)
                            .astimezone(TBILISI_TZ).strftime('%Y-%m-%dT%H:%M:%S')
                            if waybill.transport_start_date else '')),
            'TRAN_COST_PAYER': waybill.transport_cost_payer or '1',
            # Internal-transport sub has no transport of its own: empty TRANS_ID so RS does not demand a driver (-1012).
            'TRANS_ID': '' if (waybill.parent_waybill_id and waybill.waybill_type == '1')
                        else (waybill.transport_type or '1'),
            'TRANS_TXT': waybill.other_transport or '',
            'COMMENT': waybill.comment or '',
            'CATEGORY': waybill.category or '0',
            'IS_MED': waybill.is_medicine or '0',
        }

        for tag, value in fields_map.items():
            el = etree.SubElement(root, tag)
            el.text = str(value or '')

        goods_list = etree.SubElement(root, 'GOODS_LIST')
        for line in waybill.line_ids:
            goods = etree.SubElement(goods_list, 'GOODS')
            unit_id, unit_txt = line._rs_send_unit()
            line_map = {
                'ID': str(line.rs_good_id or 0),
                'W_NAME': line.name or '',
                'UNIT_ID': unit_id,
                'UNIT_TXT': unit_txt,
                'QUANTITY': str(line.quantity),
                'PRICE': str(line.unit_price),
                'STATUS': '1',
                'AMOUNT': str(line.amount),
                'BAR_CODE': line.bar_code or '',
                'A_ID': str(line.product_id.product_tmpl_id.rs_excise_id.rs_id or 0),
                'VAT_TYPE': line.vat_type or '0',
            }

            for tag, value in line_map.items():
                el = etree.SubElement(goods, tag)
                el.text = str(value or '')

        # Tombstones for lines removed in an edit: the good's ID with STATUS=-1, else RS keeps it.
        for good_id in (removed_good_ids or []):
            if not good_id or str(good_id).strip() in ('', '0'):
                continue
            goods = etree.SubElement(goods_list, 'GOODS')
            tomb_map = {
                'ID': str(good_id),
                'STATUS': '-1',
                'QUANTITY': '0',
                'PRICE': '0',
                'AMOUNT': '0',
                'A_ID': '0',
            }
            for tag, value in tomb_map.items():
                el = etree.SubElement(goods, tag)
                el.text = str(value)

        return root


    def save_waybill(self, waybill, removed_good_ids=None):
        """ Creates or Updates waybill. removed_good_ids: RS good IDs to tombstone
            (STATUS=-1) for lines deleted during an edit. """
        client, su, sp, history = self._get_client()
        waybill_xml = self._build_waybill_xml(waybill, client, su, sp, removed_good_ids=removed_good_ids)
        _logger.debug("SENDING XML: %s", etree.tostring(waybill_xml, encoding='unicode'))
        try:
            result = client.service.save_waybill(su=su, sp=sp, waybill=waybill_xml)
            _logger.debug("RS.GE save_waybill result: %s", etree.tostring(result,encoding='unicode'))
            # A response with no STATUS is not a success (taking it as status 0 would store an empty RS id).
            status = result.find('STATUS')
            if status is None or status.text is None:
                _logger.error("RS.GE save_waybill: response carries no STATUS element: %s",
                              etree.tostring(result, encoding='unicode'))
                raise UserError(_("RS.GE returned an unexpected response for save_waybill "
                                  "(no STATUS element). The waybill was NOT saved."))
            status_code = int(status.text)
            # save_waybill answers 0 for success, unlike the actions (1): only a negative code is decoded and raised.
            if status_code < 0:
                self._check_rs_result('save_waybill', status_code)
            
            goods_response = []
            for g in result.findall('.//GOODS'):
                goods_response.append({
                    'id': g.findtext('ID') or '0',
                    'name': g.findtext('W_NAME') or '',
                    'bar_code': g.findtext('BAR_CODE') or '',
                    'error': g.findtext('ERROR') or '0',
                })

            return {
                'status': status_code,
                'id': result.findtext('ID', ''),
                'waybill_number': result.findtext('WAYBILL_NUMBER', ''),
                'goods': goods_response,
            }
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE save_waybill failed: %s", e)
            raise UserError(_("Failed to save waybill on RS.GE: %s") % e)


    def send_waybill(self, waybill_id):
        """ Activates/Sents waybill on RS.GE """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.send_waybill(su=su, sp=sp, waybill_id=int(waybill_id))
            _logger.info("RS.GE send_waybill result: %s", result)
            return self._check_rs_action_result('send_waybill', result)
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE send_waybill failed: %s", e)
            raise UserError(_("Failed to activate waybill: %s") % e)


    def close_waybill(self, waybill_id):
        """ Marks a waybill as Delivered on RS.GE """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.close_waybill(su=su, sp=sp, waybill_id=int(waybill_id))
            _logger.info("RS.GE close_waybill result: %s", result)
            return self._check_rs_result('close_waybill', result)
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE close_waybill failed: %s", e)
            raise UserError(_("Failed to close waybill on RS.GE: %s") % e)


    def delete_waybill(self, waybill_id):
        """ Deletes a draft waybill on RS.GE """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.del_waybill(su=su, sp=sp, waybill_id=int(waybill_id))
            _logger.info("RS.GE delete_waybill result: %s", result)
            return self._check_rs_result('delete_waybill', result)
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE delete_waybill failed: %s", e)
            raise UserError(_("Failed to delete waybill on RS.GE: %s") % e)


    def refuse_waybill(self, waybill_id):
        """ Seller refuses/cancels an active waybill on RS.GE """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.ref_waybill(su=su, sp=sp, waybill_id=int(waybill_id))
            _logger.info("RS.GE refuse_waybill result: %s", result)
            return self._check_rs_result('refuse_waybill', result)
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE refuse_waybill failed: %s", e)
            raise UserError(_("Failed to refuse waybill on RS.GE: %s") % e)


    def ref_waybill_vd(self, waybill_id, comment=''):
        """ Cancel a distribution (VD) waybill on RS.GE — the VD variant of
        ref_waybill. The non-VD ref_waybill returns -3 for a distribution; RS
        cascades this cancel to the distribution's sub-waybills. """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.ref_waybill_vd(su=su, sp=sp, waybill_id=int(waybill_id),
                                                   comment=comment or '')
            _logger.info("RS.GE ref_waybill_vd result: %s", result)
            return self._check_rs_result('ref_waybill_vd', result)
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE ref_waybill_vd failed: %s", e)
            raise UserError(_("Failed to cancel distribution waybill on RS.GE: %s") % e)


    def confirm_waybill(self, waybill_id):
        """ Buyer confirms/accepts received waybill """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.confirm_waybill(su=su, sp=sp, waybill_id=int(waybill_id))
            _logger.info("RS.GE confirm_waybill result: %s", result)
            return self._check_rs_action_result('confirm_waybill', result)
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE confirm_waybill failed: %s", e)
            raise UserError(_("Failed to confirm waybill on RS.GE: %s") % e)


    def reject_waybill(self, waybill_id):
        """ Buyer rejects the waybill on RS.GE """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.reject_waybill(su=su, sp=sp, waybill_id=int(waybill_id))
            _logger.info("RS.GE reject_waybill result: %s", result)
            return self._check_rs_action_result('reject_waybill', result)
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE reject_waybill failed: %s", e)
            raise UserError(_("Failed to reject waybill on RS.GE: %s") % e)


    def send_waybil_vd(self, waybill_id, begin_date):
        """Activate a distribution (VD) waybill with a transport start date.
        Used for distribution sub-waybills."""
        client, su, sp, history = self._get_client()
        # begin_date is stored UTC; RS expects Georgian local wall-clock.
        if begin_date and hasattr(begin_date, 'astimezone'):
            begin_date = begin_date.replace(tzinfo=UTC_TZ).astimezone(TBILISI_TZ).replace(tzinfo=None)
        try:
            result = client.service.send_waybil_vd(
                su=su, sp=sp,
                begin_date=begin_date,
                waybill_id=int(waybill_id),
            )
            _logger.info("RS.GE send_waybil_vd result: %s", result)
            return self._check_rs_action_result('send_waybil_vd', result)
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE send_waybil_vd failed: %s", e)
            raise UserError(_("Failed to activate sub-waybill on RS.GE: %s") % e)


    def close_waybill_vd(self, waybill_id, delivery_date, check=True):
        """Close with a delivery date: RS wants Georgian local, stored UTC looks 4h early (RS answers -1).
        check=False returns the raw RS code instead of raising on a negative one; transport failures still raise."""
        client, su, sp, history = self._get_client()
        if delivery_date and hasattr(delivery_date, 'astimezone'):
            delivery_date = delivery_date.replace(tzinfo=UTC_TZ).astimezone(TBILISI_TZ).replace(tzinfo=None)
        try:
            result = client.service.close_waybill_vd(
                su=su, sp=sp,
                delivery_date=delivery_date,
                waybill_id=int(waybill_id),
            )
            _logger.info("RS.GE close_waybill_vd result: %s", result)
            if not check:
                return int(result) if result is not None else -1
            return self._check_rs_result('close_waybill_vd', result)
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE close_waybill_vd failed: %s", e)
            raise UserError(_("Failed to close waybill with date: %s") % e)


    def get_waybills_v1(self, buyer_tin='', last_update_start=None, last_update_end=None):
        """ Gets Seller/Buyer modified within the given time range(max 3 days) """
        client, su, sp, history = self._get_client()
        params = {
            'su': su,
            'sp': sp,
            'buyer_tin': buyer_tin,
            'last_update_date_s': last_update_start,
            'last_update_date_e': last_update_end,
        }
        return self._call_datatable(client, history, su, sp, 'get_waybills_v1', params, row_tag='WAYBILL')


    def get_waybills(self, start_date, end_date, buyer_tin='', statuses=''):
        """ The outgoing waybills created between start_date and end_date. """
        client, su, sp, history = self._get_client()
        params = {
            'su': su,
            'sp': sp,
            'itypes': '',
            'buyer_tin': buyer_tin,
            'statuses': statuses,
            'car_number': '',
            # Creation date only: RS applies all date filters, so a waybill delivered/closed outside the window is lost.
            'begin_date_s': None,
            'begin_date_e': None,
            'create_date_s': start_date,
            'create_date_e': end_date,
            'driver_tin': '',
            'delivery_date_s': None,
            'delivery_date_e': None,
            'full_amount': -1,
            'waybill_number': '',
            'close_date_s': None,
            'close_date_e': None,
            's_user_ids': '',
            'comment': '',
        }
        return self._call_datatable(client, history, su, sp, 'get_waybills',
                                    params=params, row_tag='WAYBILL')


    def get_buyer_waybills(self, start_date, end_date, seller_tin='', statuses=''):
        """ The incoming waybills created between start_date and end_date. """
        client, su, sp, history = self._get_client()
        params = {
            'su': su,
            'sp': sp,
            'itypes': '',
            'seller_tin': seller_tin,
            'statuses': statuses,
            'car_number': '',
            # Creation date only: RS applies all date filters, so a waybill delivered/closed outside the window is lost.
            'begin_date_s': None,
            'begin_date_e': None,
            'create_date_s': start_date,
            'create_date_e': end_date,
            'driver_tin': '',
            'delivery_date_s': None,
            'delivery_date_e': None,
            'full_amount': -1,
            'waybill_number': '',
            'close_date_s': None,
            'close_date_e': None,
            's_user_ids': '',
            'comment': '',
        }
        return self._call_datatable(client, history, su, sp, 'get_buyer_waybills', params=params, row_tag='WAYBILL')


    def get_transporter_waybills(self):
        """ Gets all the waybills where this company is the transporter """
        client, su, sp, history = self._get_client()
        params = {'su': su, 'sp': sp}
        return self._call_datatable(client, history, su, sp, 'get_transporter_waybills', params=params, row_tag='WAYBILL')


    def get_full_waybill(self, waybill_id):
        """ Gets a single waybill with full details(header + goods) """
        client, su, sp, history = self._get_client()
        params = {'su': su, 'sp': sp, 'waybill_id': int(waybill_id)}
        error = None
        try:
            client.service.get_waybill(**params)
        except Exception as e:
            # Expected: zeep cannot deserialize the DataTable reply; the raw XML is read from the history buffer below.
            error = e
            _logger.debug("get_waybill typed call failed for %s (reading raw): %s", waybill_id, e)
        try:
            envelope = history.last_received['envelope']
        except (IndexError, TypeError, KeyError):
            # Cold history buffer or a request that never reached RS: .last_received raises IndexError.
            _logger.warning("No RS response available for waybill %s: %s", waybill_id, error)
            return None, []
        return self._rs_waybill_from_envelope(envelope, waybill_id)


    def get_adjusted_waybills(self, waybill_id):
        """ Returns the list of historical adjustment snapshots for a waybill """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.get_adjusted_waybills(su=su, sp=sp, waybill_id=int(waybill_id))
        except Exception as e:
            _logger.warning("get_adjusted_waybills failed for %s: %s", waybill_id, e)
            return []
        adjustments = []
        for adjustment in result.findall('.//ADJUSTED_WAYBILL'):
            date_str = adjustment.findtext('DT') or ''
            if 'T' in date_str:
                date_str = date_str.replace('T', ' ')
            if '.' in date_str:
                date_str = date_str.split('.', 1)[0]
            adjustments.append({'archival_id': int(adjustment.findtext('ID') or 0),
                                'date': date_str,
                                'user_name': adjustment.findtext('USER_NAME') or ''})
        return adjustments


    def get_adjusted_waybill(self, archival_id):
        """ Returns full data of a specific historical snapshot
            archival_id is the ID from get_adjusted_waybills (the old version's archived id). """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.get_adjusted_waybill(su=su, sp=sp, id=int(archival_id))
        except Exception as e:
            _logger.warning("get_adjusted_waybill failed for %s: %s", archival_id, e)
            return None, []
        try:
            envelope = history.last_received['envelope']
        except (IndexError, TypeError, KeyError):
            return None, []
        header = self._parse_datatable(envelope, row_tag='WAYBILL')
        header = header[0] if header else None
        goods = self._parse_datatable(envelope, row_tag='GOODS')
        return header, goods


    def get_full_waybill_with_client(self, client, su, sp, history, waybill_id):
        """Same as get_full_waybill but reuses an existing client."""
        params = {'su': su, 'sp': sp, 'waybill_id': int(waybill_id)}
        error = None
        try:
            client.service.get_waybill(**params)
        except Exception as e:
            # Expected too (DataTable reply): only worth logging if no reply came back.
            error = e
        try:
            envelope = history.last_received['envelope']
        except (IndexError, TypeError, KeyError):
            _logger.warning("No RS response available for waybill %s: %s", waybill_id, error)
            return None, []
        return self._rs_waybill_from_envelope(envelope, waybill_id)


    def _rs_waybill_from_envelope(self, envelope, waybill_id):
        """ (header, goods) of waybill `waybill_id` from a raw get_waybill reply, or (None, []) when the reply is
            about another waybill (never write its data onto this one); the caller treats it like no reply. """
        header = self._parse_datatable(envelope, row_tag='WAYBILL')
        header = header[0] if header else None
        if not header:
            # RS answers a refusal as <RESULT><STATUS>-100</STATUS>...: say which, else it looks like no data.
            status = self._envelope_to_root(envelope).findtext('.//STATUS')
            _logger.warning("RS returned no data for waybill %s (STATUS %s%s)", waybill_id, status,
                            ': wrong RS Username / Password' if status == '-100' else '')
            return None, []
        if str(header.get('ID') or '').strip() not in ('', str(int(waybill_id))):
            _logger.error("RS reply for waybill %s carries waybill %s: reply ignored.",
                          waybill_id, header.get('ID'))
            return None, []
        goods = self._parse_datatable(envelope, row_tag='GOODS')
        return header, goods


    def get_transporter_info(self, tin):
        """ looks up a company name by TIN """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.get_name_from_tin(su=su, sp=sp, tin=tin)
            return '' if result in (None, 'null') else result.strip()
        except Exception as e:
            _logger.error("RS.GE transporter_info failed: %s", e)
            return ''


    def save_transporter_waybill(self, waybill_id, car_number, driver_tin,driver_name='',trans_id=1,
                                 trans_txt='',chek_driver_tin=1, reception_info='', receiver_info=''):
        """ Transporter fills in their car/driver details on a waybill """

        client, su, sp, history = self._get_client()
        try:
            result = client.service.save_waybill_transporter(su=su, sp=sp, waybill_id=int(waybill_id), car_number=car_number,
                                                         driver_tin=driver_tin, driver_name=driver_name, trans_id=trans_id, trans_txt=trans_txt,
                                                         chek_driver_tin=chek_driver_tin, reception_info=reception_info,receiver_info=receiver_info)
            _logger.debug("RS.GE save_waybill_transporter result: %s", result)
            # RS.GE answers an int: a refusal is a code <= 0, never a silent success.
            return self._check_rs_action_result('save_waybill_transporter', result)
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE save_waybill_transporter failed: %s", e)
            raise UserError(_("Failed to save transporter data: %s") % e)


    def send_transporter_waybill(self, waybill_id, begin_date):
        """ Transporter activates the transport leg """
        client, su, sp, history = self._get_client()
        # begin_date is stored UTC; RS expects Georgian local wall-clock (as in send_waybil_vd), else it reads 4h early.
        if begin_date and hasattr(begin_date, 'astimezone'):
            begin_date = begin_date.replace(tzinfo=UTC_TZ).astimezone(TBILISI_TZ).replace(tzinfo=None)
        try:
            result = client.service.send_waybill_transporter(su=su, sp=sp, waybill_id=int(waybill_id), begin_date=begin_date)
            _logger.debug("RS.GE send_waybill_transporter result: %s", result)
            status_code = getattr(result, 'send_waybill_transporterResult', None)
            waybill_number = getattr(result, 'waybill_number', None)
            if status_code is None and waybill_number is None:
                # Not RS.GE's documented answer (a code + the waybill number): it is not
                # taken as a waybill number, and the waybill is not marked active.
                _logger.warning("RS.GE send_waybill_transporter: unexpected answer %r", result)
                raise UserError(_("RS.GE gave an unexpected answer to Send to Transporter, so "
                                  "the waybill was not marked active. Click Update to see its "
                                  "state on RS.GE, then try again."))
            self._check_rs_result('send_waybill_transporter', status_code)
            return waybill_number or ''
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE send_waybill_transporter failed: %s", e)
            raise UserError(_("Failed to activate transporter waybill: %s") % e)


    def close_transporter_waybill(self, waybill_id, delivery_date, reception_info='', receiver_info=''):
        """ Transporter marks delivery complete """
        client, su, sp, history = self._get_client()
        # delivery_date is stored UTC; RS validates delivery > start in Georgian local: UTC looks 4h early -> -1.
        if delivery_date and hasattr(delivery_date, 'astimezone'):
            delivery_date = delivery_date.replace(tzinfo=UTC_TZ).astimezone(TBILISI_TZ).replace(tzinfo=None)
        try:
            result = client.service.close_waybill_transporter(su=su, sp=sp, waybill_id=int(waybill_id),delivery_date=delivery_date,
                                                  reception_info=reception_info,receiver_info=receiver_info)
            _logger.debug("RS.GE close_waybill_transporter result: %s", result)
            return self._check_rs_result('close_waybill_transporter', result)
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE close_waybill_transporter failed: %s", e)
            raise UserError(_("Failed to close transporter waybill: %s") % e)


    def save_waybill_template(self, waybill, v_name):
        """ Saves waybill as template for several usage. Returns the RS template id
            (positive int) — a negative reply is an error code, not an id. """
        client, su, sp, history = self._get_client()
        if hasattr(waybill, '_name'):
            waybill_dict = self._build_waybill_xml(waybill, client=client, su=su, sp=sp)
        else:
            waybill_dict = waybill
        params = {'su': su, 'sp': sp, 'waybill': waybill_dict, 'v_name': v_name}
        response = client.service.save_waybill_tamplate(**params)
        return self._check_rs_id('save_waybill_template', response)


    def get_waybill_template(self, template_id):
        """ Gets single waybill as template for several usage """
        client, su, sp, _history = self._get_client()
        params = {'su': su, 'sp': sp, 'id': int(template_id)}
        response = client.service.get_waybill_tamplate(**params)
        try:
            return response.waybill_tamplate._value_1
        except AttributeError:
            return None


    def get_waybill_templates(self):
        """ Gets all waybill as template for several usage """
        client, su, sp, history = self._get_client()
        params = {'su': su, 'sp': sp}
        return self._call_datatable(client, history, su, sp,'get_waybill_tamplates',params=params, row_tag='WAYBILL_TAMPLATE',)


    def delete_waybill_template(self, template_id):
        """ Delete waybill template """
        client, su, sp, history = self._get_client()
        params = {'su': su, 'sp': sp, 'id': int(template_id)}
        response = client.service.delete_waybill_tamplate(**params)
        return response


    def save_car_number(self, car_number):
        """ Adds a car plate to the RS.GE account's car list """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.save_car_numbers(su=su, sp=sp, car_number=car_number)
            _logger.info("RS.GE save_car_numbers(%s) result: %s", car_number, result)
            return result
        except Exception as e:
            _logger.error("RS.GE save_car_numbers failed: %s", e)
            raise UserError(_("Failed to save car number to RS.GE: %s") % e)


    def get_car_numbers(self):
        """ Returns a list of registered car plate numbers for rs account """
        client, su, sp, history = self._get_client()
        try:
            client.service.get_car_numbers(su=su, sp=sp)
        except Exception as e:
            _logger.debug("get_car_numbers typed call failed (reading raw): %s", e)
        try:
            envelope = history.last_received['envelope']
        except (IndexError, TypeError, KeyError):
            _logger.warning("No RS response available for get_car_numbers")
            return []
        root = self._envelope_to_root(envelope)
        return [el.text for el in root.findall('.//CAR_NUMBER') if el.text]


    def get_bar_codes(self, bar_code=''):
        """ Gets registered products barcodes from RS.GE """
        client, su, sp, history = self._get_client()
        params = {'su': su, 'sp': sp, 'bar_code': bar_code}
        return self._call_datatable(client, history, su, sp, 'get_bar_codes',
                                    params=params, row_tag='BAR_CODE')


    def get_akciz_codes(self, s_text=''):
        """ Gets the excise (akciz) code catalog from RS.GE. Read-only: RS.GE has no save method for these codes. """
        client, su, sp, history = self._get_client()
        params = {'su': su, 'sp': sp, 's_text': s_text}
        return self._call_datatable(client, history, su, sp, 'get_akciz_codes',
                                    params=params, row_tag='AKCIZ_CODE')


    def save_bar_code(self, bar_code, goods_name, unit_id=0, unit_txt='', a_id=0):
        """ Registers product bar code on RS.GE"""
        client, su, sp, history = self._get_client()
        try:
            result = client.service.save_bar_code(su=su, sp=sp, bar_code=bar_code or '',
                                                  goods_name=goods_name or '',
                                                  unit_id=int(unit_id or 0),
                                                  unit_txt=unit_txt or '',
                                                  a_id=int(a_id or 0),)
            _logger.info("RS.GE save_bar_code result: %s (barcode=%s)", result, bar_code)
            result = int(result) if result is not None else -1
            if result == -100:
                raise UserError(_("RS.GE: invalid service user or password."))
            if result != 1:
                raise UserError(_("RS.GE save_bar_code failed (code %s) for barcode %s") % (result, bar_code))
            verification = self.get_bar_codes(bar_code=bar_code)
            if not any(r.get('CODE') == bar_code for r in verification):
                raise UserError(_("RS.GE accepted the request but did not register barcode '%s'."
                                  "It is likely already registered by another company. "
                                  "Use a unique barcode (e.g. prefix with a company code).") % bar_code)
            _logger.info("RS.GE save_bar_code persisted: barcode=%s", bar_code)
            return result
        except UserError:
            raise
        except Exception as e:
            _logger.error("RS.GE save_bar_code failed: %s", e)
            raise UserError(_("Failed to save barcode on RS.GE: %s") % e)


    def get_waybill_units(self):
        client, su, sp, history = self._get_client()
        return self._call_datatable(client, history, su, sp, 'get_waybill_units', row_tag='WAYBILL_UNIT')


    def get_print_pdf(self, waybill_id):
        """ Prints PDF for given waybill_id """
        client, su, sp, history = self._get_client()
        try:
            result = client.service.get_print_pdf(su=su, sp=sp, waybill_id=int(waybill_id))
            _logger.info("RS.GE print_pdf returned data length: %s", len(str(result)) if result else 0)
            return result
        except Exception as e:
            _logger.error("RS.GE print_pdf failed: %s", e)
            raise UserError(_("Failed to get PDF: %s") % e)
