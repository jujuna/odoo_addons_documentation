import io
import re
from types import SimpleNamespace

from odoo.tests import tagged
from odoo.tools.pdf import DictionaryObject, PdfFileReader
from odoo.tools.pdf.signature import PdfSigner

from odoo.addons.id_ge_sign.tools import protocol
from odoo.addons.id_ge_sign.tools.cms import CmsVerificationError
from odoo.addons.id_ge_sign.tools.pdf_update import check_signature_update

from .common import GeoeidCommon

BEYOND_SIGNATURE = "changes the document beyond adding one signature"
TOO_LARGE = "covers too much of the page"
LIMIT = protocol.GEOEID_MAX_SIGNATURE_AREA_PERCENT


def numbers(pdf):
    """Where the catalog, the first page and its content sit in ``pdf``, the free object number, the form fields and the page annotations."""
    reader = PdfFileReader(io.BytesIO(pdf), strict=False)
    root, page = reader.trailer['/Root'], reader.pages[0]
    return SimpleNamespace(
        root_id=reader.trailer.raw_get('/Root').idnum, root=root, page_id=page.indirect_reference.idnum, page=page,
        content_id=page.raw_get('/Contents').idnum, free=int(reader.trailer['/Size']),
        fields=[ref.idnum for ref in (root.get('/AcroForm') or {}).get('/Fields', [])], annots=[ref.idnum for ref in page.get('/Annots', [])])


def references(object_numbers):
    return b' '.join(b'%d 0 R' % number for number in object_numbers)


def rewritten(obj, changes):
    """The dictionary ``obj`` with the entries of ``changes`` ({key: raw value}) replaced or added."""
    buffer = io.BytesIO()
    DictionaryObject({key: obj.raw_get(key) for key in obj if key not in changes}).write_to_stream(buffer, None)
    return buffer.getvalue().rstrip()[:-2] + b''.join(b'%s %s\n' % (key.encode(), value) for key, value in changes.items()) + b'>>'


def increment(pdf, objects, root_id, listed=None):
    """Append a hand-written incremental update: {object number: body bytes}; ``listed`` {object number: offset} replaces or adds table rows."""
    previous = int(re.findall(rb'startxref\s+(\d+)', pdf)[-1])
    size = max(int(number) for number in re.findall(rb'/Size (\d+)', pdf))
    out, offsets = bytearray(pdf + b'\n'), {}
    for number, body in sorted(objects.items()):
        offsets[number] = len(out)
        out += b'%d 0 obj\n' % number + body + b'\nendobj\n'
    offsets.update(listed or {})
    xref = len(out)
    out += b'xref\n' + b''.join(b'%d 1\n%010d 00000 n \n' % (number, offset) for number, offset in sorted(offsets.items()))
    out += b'trailer\n<< /Size %d /Root %d 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n' % (max(size, max(objects) + 1), root_id, previous, xref)
    return bytes(out)


def signature_update(pdf, objects, fields, annots, catalog=None, page=None, listed=None):
    """The update a card app writes: the new ``objects``, the catalog listing ``fields`` and the page listing ``annots`` (object numbers)."""
    was = numbers(pdf)
    form = b'<< /Fields [%s] /SigFlags 3 >>' % references(fields)
    objects = {
        **objects,
        was.root_id: rewritten(was.root, {'/AcroForm': form, **(catalog or {})}),
        was.page_id: rewritten(was.page, {'/Annots': b'[%s]' % references(annots), **(page or {})}),
    }
    return increment(pdf, objects, was.root_id, listed)


def signature_field(page_id, rect=b'0 0 0 0', extra=b''):
    return b'<< /FT /Sig /Type /Annot /Subtype /Widget /F 132 /T (S) /P %d 0 R /Rect [%s] %s >>' % (page_id, rect, extra)


@tagged('post_install', '-at_install')
class TestSignatureUpdate(GeoeidCommon):

    def card_signed(self, pdf):
        return PdfSigner(pdf, self.card_company).sign_pdf(None, 'Sample')

    def one_signature(self, pdf, objects=None, rect=b'0 0 0 0', field_extra=b'', **changes):
        """``pdf`` plus one new signature field, as the card app adds it; ``objects`` and ``changes`` add what a forger would."""
        was = numbers(pdf)
        field = was.free
        objects = {field: signature_field(was.page_id, rect, field_extra), **(objects or {})}
        return signature_update(pdf, objects, was.fields + [field], was.annots + [field], **changes)

    def assertRefused(self, frozen, signed, message=BEYOND_SIGNATURE):
        with self.assertRaisesRegex(CmsVerificationError, message):
            check_signature_update(frozen, signed, LIMIT)

    def rect_covering(self, percent):
        box = numbers(self.pdf_raw).page.mediabox
        return b'0 0 %f %f' % (float(box.width), float(box.height) * percent / 100)

    def test_a_file_signed_by_core_is_accepted(self):
        check_signature_update(self.pdf_raw, self.card_signed(self.pdf_raw), LIMIT)

    def test_a_second_signature_on_top_of_a_signed_file_is_accepted(self):
        first = self.card_signed(self.pdf_raw)
        check_signature_update(first, self.card_signed(first), LIMIT)

    def test_a_hand_made_signature_field_is_accepted(self):
        check_signature_update(self.pdf_raw, self.one_signature(self.pdf_raw), LIMIT)

    def test_page_content_replaced_is_refused(self):
        stream = b'<< /Length 2 >>\nstream\nq\nendstream'
        self.assertRefused(self.pdf_raw, self.one_signature(self.pdf_raw, {numbers(self.pdf_raw).content_id: stream}))

    def test_page_pointed_to_a_new_content_stream_is_refused(self):
        free = numbers(self.pdf_raw).free
        signed = self.one_signature(self.pdf_raw, {free + 1: b'<< /Length 2 >>\nstream\nq\nendstream'}, page={'/Contents': b'%d 0 R' % (free + 1)})
        self.assertRefused(self.pdf_raw, signed)

    def test_an_extra_annotation_is_refused(self):
        was = numbers(self.pdf_raw)
        stamp, field = was.free, was.free + 1
        objects = {stamp: b'<< /Type /Annot /Subtype /Stamp /Rect [0 0 500 500] >>', field: signature_field(was.page_id)}
        self.assertRefused(self.pdf_raw, signature_update(self.pdf_raw, objects, [field], [stamp, field]))

    def test_an_open_action_in_the_catalog_is_refused(self):
        action = {'/OpenAction': b'<< /S /JavaScript /JS (app.alert(1)) >>'}
        self.assertRefused(self.pdf_raw, self.one_signature(self.pdf_raw, catalog=action))

    def test_a_signature_field_with_an_action_is_refused(self):
        self.assertRefused(self.pdf_raw, self.one_signature(self.pdf_raw, field_extra=b'/AA << /E << /S /JavaScript /JS (1) >> >>'))

    def test_two_added_fields_are_refused(self):
        was = numbers(self.pdf_raw)
        objects = {was.free: signature_field(was.page_id), was.free + 1: signature_field(was.page_id)}
        signed = signature_update(self.pdf_raw, objects, [was.free, was.free + 1], [was.free, was.free + 1])
        self.assertRefused(self.pdf_raw, signed)

    def test_an_existing_annotation_removed_is_refused(self):
        first = self.card_signed(self.pdf_raw)
        was = numbers(first)
        self.assertTrue(was.annots)
        field = was.free
        signed = signature_update(first, {field: signature_field(was.page_id)}, was.fields + [field], [field])
        self.assertRefused(first, signed)

    def test_no_field_added_is_refused(self):
        was = numbers(self.pdf_raw)
        self.assertRefused(self.pdf_raw, increment(self.pdf_raw, {was.free: b'(unused)'}, was.root_id))
        self.assertRefused(self.pdf_raw, self.pdf_raw)

    def test_bytes_that_are_not_a_pdf_are_refused(self):
        self.assertRefused(self.pdf_raw, b'not a pdf')
        self.assertRefused(self.pdf_raw, self.pdf_raw + b'garbage')

    def test_a_signature_block_over_the_limit_is_refused_and_one_under_it_is_accepted(self):
        self.assertRefused(self.pdf_raw, self.one_signature(self.pdf_raw, rect=self.rect_covering(LIMIT + 0.1)), TOO_LARGE)
        check_signature_update(self.pdf_raw, self.one_signature(self.pdf_raw, rect=self.rect_covering(LIMIT - 0.1)), LIMIT)

    def test_new_content_behind_a_table_row_that_points_elsewhere_is_refused(self):
        """Readers disagree on a row that points to no object: one keeps the old content, another shows the new one."""
        content = numbers(self.pdf_raw).content_id
        stream = {content: b'<< /Length 2 >>\nstream\nq\nendstream'}
        self.assertRefused(self.pdf_raw, self.one_signature(self.pdf_raw, stream, listed={content: len(self.pdf_raw) - 5}))

    def test_a_table_row_sending_an_object_to_another_old_object_is_refused(self):
        was = numbers(self.pdf_raw)
        other = self.pdf_raw.find(b'\n%d 0 obj' % was.page_id) + 1
        self.assertRefused(self.pdf_raw, self.one_signature(self.pdf_raw, listed={was.content_id: other}))

    def test_content_rewritten_under_another_generation_is_refused(self):
        content = numbers(self.pdf_raw).content_id
        signed = self.one_signature(self.pdf_raw, {content: b'<< /Length 2 >>\nstream\nq\nendstream'})
        offset = signed.find(b'\n%d 0 obj' % content, len(self.pdf_raw)) + 1
        update = signed[len(self.pdf_raw):].replace(b'\n%d 0 obj' % content, b'\n%d 1 obj' % content)
        update = update.replace(b'%010d 00000 n' % offset, b'%010d 00001 n' % offset)
        self.assertRefused(self.pdf_raw, self.pdf_raw + update)

    def test_an_object_marked_free_is_refused(self):
        content = numbers(self.pdf_raw).content_id
        signed = self.one_signature(self.pdf_raw, listed={content: 0})
        self.assertRefused(self.pdf_raw, signed.replace(b'%010d 00000 n' % 0, b'%010d 00001 f' % 0))

    def test_a_template_holding_a_null_value_is_accepted(self):
        was = numbers(self.pdf_raw)
        frozen = increment(self.pdf_raw, {was.root_id: rewritten(was.root, {'/Lang': b'null'})}, was.root_id)
        check_signature_update(frozen, self.one_signature(frozen), LIMIT)

    def test_a_number_rewritten_without_its_decimals_is_accepted(self):
        was = numbers(self.pdf_raw)
        frozen = increment(self.pdf_raw, {was.page_id: rewritten(was.page, {'/UserUnit': b'1.0'})}, was.root_id)
        check_signature_update(frozen, self.one_signature(frozen, page={'/UserUnit': b'1'}), LIMIT)
        self.assertRefused(frozen, self.one_signature(frozen, page={'/UserUnit': b'2'}))

    def test_a_key_written_twice_is_refused(self):
        """Readers disagree on a repeated key: one takes the first value, another the last."""
        was = numbers(self.pdf_raw)
        other = {was.free + 1: b'<< /Length 2 >>\nstream\nq\nendstream'}
        for second_key in (b'/Contents', b'/Cont#65nts'):
            with self.subTest(second_key=second_key):
                contents = b'%d 0 R %s %d 0 R' % (was.content_id, second_key, was.free + 1)
                self.assertRefused(self.pdf_raw, self.one_signature(self.pdf_raw, other, page={'/Contents': contents}))
        self.assertRefused(self.pdf_raw, self.one_signature(self.pdf_raw, rect=b'0 0 1 1] /Rect [0 0 500 800'))

    def test_a_second_catalog_named_in_the_trailer_is_refused(self):
        was = numbers(self.pdf_raw)
        action = rewritten(was.root, {'/OpenAction': b'<< /S /JavaScript /JS (app.alert(1)) >>'})
        signed = self.one_signature(self.pdf_raw, {was.free + 1: action})
        root = b'/Root %d 0 R' % was.root_id
        update = signed[len(self.pdf_raw):].replace(root, root + b' /Root %d 0 R' % (was.free + 1))
        self.assertRefused(self.pdf_raw, self.pdf_raw + update)

    def test_content_hidden_after_the_end_of_a_stream_is_refused(self):
        was = numbers(self.pdf_raw)
        frozen = increment(self.pdf_raw, {was.content_id: b'<< /Length 3 >>\nstream\nq Q\nendstream'}, was.root_id)
        longer = b'q Q\nendstream\n0 0 600 800 re f'
        stream = b'<< /Length %d >>\nstream\n%s' % (len(longer), longer)
        self.assertRefused(frozen, self.one_signature(frozen, {was.content_id: stream}))
