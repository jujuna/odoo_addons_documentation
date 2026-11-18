import io
import json
import zipfile

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools import BinaryBytes
from odoo.tools.image import image_process

from ..models.gec_brand_kit import (
    DARK_KEYS, FONT_FORMATS, IMAGE_KEYS, FONT_MAGIC, FONT_STYLES, HEX, LIGHT_KEYS, MAX_FONT, REQUIRED_KEYS as REQUIRED, SHIPPED_FONTS,
    UI_STYLES, check_contrast,
)

KIT_FORMAT = 'gec-brand-kit/1'
MAX_ZIP = 20 * 1024 * 1024
MAX_IMAGE = 5 * 1024 * 1024
IMAGE_EXT = {'png', 'jpg', 'jpeg', 'webp'}


class GecBrandKitImport(models.TransientModel):
    _name = 'gec.brand.kit.import'
    _description = 'Import Brand Kit'

    file = fields.Binary('Brand Kit (.zip)', required=True, attachment=False)
    filename = fields.Char()
    apply_now = fields.Boolean('Apply immediately', default=True)

    def _read_zip(self):
        """Return ({name: bytes}, brand dict) after the archive checks: zip, sizes, flat names."""
        content = self.file.content
        if len(content) > MAX_ZIP:
            raise UserError(_("The brand kit is larger than 20 MB."))
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise UserError(_("The brand kit must be a .zip file."))
        entries = {}
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for info in archive.infolist():
                name = info.filename
                if info.is_dir() or name.startswith('__MACOSX/') or name.rsplit('/', 1)[-1].startswith('._') \
                        or name.rsplit('/', 1)[-1] == '.DS_Store':
                    continue
                if '/' in name or '\\' in name or '..' in name:
                    raise UserError(_("The brand kit must be a flat ZIP without folders: \"%s\".", name))
                if info.file_size > MAX_IMAGE:
                    raise UserError(_("\"%s\" is larger than 5 MB.", name))
                entries[name] = archive.read(name)
        if 'brand.json' not in entries:
            raise UserError(_("brand.json is missing from the brand kit."))
        try:
            brand = json.loads(entries.pop('brand.json').decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as e:
            raise UserError(_("brand.json is not valid JSON: %s", e)) from e
        if not isinstance(brand, dict) or brand.get('format') != KIT_FORMAT:
            raise UserError(_("brand.json must have \"format\": \"%s\".", KIT_FORMAT))
        return entries, brand

    def _colors(self, section, keys, required):
        """Validate one color section and return {key: '#RRGGBB'} (upper case)."""
        if not isinstance(section, dict):
            raise UserError(_("\"colors\" and \"dark\" must be objects."))
        unknown = set(section) - set(keys)
        if unknown:
            raise UserError(_("Unknown color keys: %s.", ', '.join(sorted(unknown))))
        for key in required:
            if not section.get(key):
                raise UserError(_("The color \"%s\" is required.", key))
        result = {}
        for key, value in section.items():
            if not isinstance(value, str) or not HEX.match(value):
                raise UserError(_("The color \"%(key)s\" must be #RRGGBB, not \"%(value)s\".", key=key, value=value))
            result[key] = value.upper()
        return result

    def _image(self, entries, name, key):
        """Return a BinaryBytes image from the kit; the logo is converted to PNG (PDF reports cannot read webp)."""
        if name not in entries:
            raise UserError(_("\"%(name)s\" (%(key)s) is referenced in brand.json but missing from the ZIP.", name=name, key=key))
        ext = name.rsplit('.', 1)[-1].lower()
        allowed = IMAGE_EXT | ({'ico'} if key == 'favicon' else set())
        if ext not in allowed:
            raise UserError(_("\"%s\": images must be png, jpg or webp.", name))
        data = entries.pop(name)
        if ext != 'ico':
            try:
                data = image_process(data, verify_resolution=True, output_format='PNG' if key == 'logo' else '')
            except (UserError, ValueError, OSError) as e:
                raise UserError(_("\"%s\" is not a readable image.", name)) from e
        return BinaryBytes(data, filename=name)

    def _font(self, entries, font):
        """Return the kit values for the font: a shipped font name or the kit's own files."""
        empty = {'font': False, 'font_family': False}
        for key in FONT_STYLES:
            empty.update({f'font_{key}': False, f'font_{key}_name': False})
        if font is None:
            return empty
        if isinstance(font, str):
            if font not in dict(SHIPPED_FONTS):
                raise UserError(_("Unknown font \"%(font)s\". Use one of: %(fonts)s, or the kit's own files.",
                                  font=font, fonts=', '.join(dict(SHIPPED_FONTS))))
            return {**empty, 'font': font}
        if not isinstance(font, dict) or not font.get('family') or not isinstance(font.get('files'), dict):
            raise UserError(_("\"font\" must be a font name or {\"family\": ..., \"files\": {...}}."))
        files = font['files']
        if not files.get('regular'):
            raise UserError(_("The font file \"regular\" is required."))
        values = {**empty, 'font_family': str(font['family'])[:64]}
        for key, name in files.items():
            if key not in FONT_STYLES:
                raise UserError(_("Unknown font style \"%s\" (regular, bold, italic, bold_italic).", key))
            if name not in entries:
                raise UserError(_("Font file \"%s\" is missing from the ZIP.", name))
            ext = name.rsplit('.', 1)[-1].lower()
            data = entries.pop(name)
            if ext not in FONT_FORMATS or not data.startswith(FONT_MAGIC[ext]):
                raise UserError(_("\"%s\" is not a woff2, woff or ttf font.", name))
            if len(data) > MAX_FONT:
                raise UserError(_("Font file \"%s\" is larger than 2 MB.", name))
            values[f'font_{key}'] = BinaryBytes(data, filename=name)
            values[f'font_{key}_name'] = name
        return values

    def _parse(self):
        """Validate the whole kit and return the values for gec.brand.kit. Nothing is written here."""
        entries, brand = self._read_zip()
        unknown = set(brand) - {'format', 'name', 'style', 'colors', 'dark', 'font', 'files'}
        if unknown:
            raise UserError(_("Unknown keys in brand.json: %s.", ', '.join(sorted(unknown))))
        light = self._colors(brand.get('colors') or {}, LIGHT_KEYS, REQUIRED)
        dark = self._colors(brand['dark'], DARK_KEYS, ()) if brand.get('dark') else {}
        check_contrast(light, _("Light mode"))
        check_contrast({**{k: light[k] for k in ('primary', 'action')}, **dark}, _("Dark mode"))
        style = brand.get('style', 'strong')
        if style not in dict(UI_STYLES):
            raise UserError(_("\"style\" must be one of: %s.", ', '.join(dict(UI_STYLES))))
        values = {'name': str(brand['name'])[:64] if brand.get('name') else False, 'ui_style': style}
        values.update({f'color_{key}': light.get(key, False) for key in LIGHT_KEYS})
        values.update({f'dark_{key}': dark.get(key, False) for key in DARK_KEYS})
        values.update(self._font(entries, brand.get('font')))
        files = brand.get('files') or {}
        if not isinstance(files, dict) or set(files) - set(IMAGE_KEYS):
            raise UserError(_("\"files\" may only contain %s.", ', '.join(IMAGE_KEYS)))
        for key in IMAGE_KEYS:
            values[key] = self._image(entries, files[key], key) if files.get(key) else False
        if entries:
            raise UserError(_("Files not referenced in brand.json: %s.", ', '.join(sorted(entries))))
        return values

    def action_import(self):
        """Validate the ZIP, store it on the brand kit and apply it when asked."""
        self.ensure_one()
        kit = self.env['gec.brand.kit']._get()
        kit._check_system()
        if not kit:
            raise UserError(_("The brand kit record is missing; upgrade the Brand Kit module."))
        kit.write(self._parse())
        if self.apply_now:
            return kit.action_apply()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'gec.brand.kit',
            'res_id': kit.id,
            'view_mode': 'form',
            'target': 'main',
        }
