import io
import json
import os
import re
import zipfile

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import BinaryBytes, file_path
from odoo.tools.image import image_process

LIGHT_URL = '/_custom/gec_brand_kit/brand_variables.scss'
DARK_URL = '/_custom/gec_brand_kit/brand_variables.dark.scss'
APP_NAME_PARAM = 'web.web_app_name'
IMAGE_KEYS = ('logo', 'home_background', 'login_background', 'favicon')

# Fonts bundled in static/fonts (Georgian and Latin letters, SIL OFL); their @font-face rules are in
# static/src/scss/georgian_fonts.scss, always loaded so the form can show a sample before Apply.
BUNDLED_FONTS = {'FiraGO': 'FiraGO', 'Noto_Sans_Georgian': 'Noto Sans Georgian', 'Noto_Serif_Georgian': 'Noto Serif Georgian'}
# Odoo's own font files (web/static/fonts) have no Georgian letters: Georgian text falls back to the system font.
ODOO_FONTS = [
    ('Lato', 'Lato'), ('Roboto', 'Roboto'), ('Open_Sans', 'Open Sans'), ('Montserrat', 'Montserrat'),
    ('Oswald', 'Oswald'), ('Raleway', 'Raleway'), ('Tajawal', 'Tajawal'),
]
SHIPPED_FONTS = list(BUNDLED_FONTS.items()) + ODOO_FONTS
FONT_LABELS = list(BUNDLED_FONTS.items()) + [(key, f'{label} (Latin only)') for key, label in ODOO_FONTS]
SYSTEM_FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Ubuntu, "Noto Sans", Arial, '
    'sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji"'
)
# (kit key, weight, style) -> file style suffix of the shipped Google fonts / Lato files
FONT_STYLES = {
    'regular': (400, 'normal', 'Regular', 'Reg'),
    'bold': (700, 'bold', 'Bold', 'Bol'),
    'italic': (400, 'italic', 'Italic', 'RegIta'),
    'bold_italic': (700, 'italic', 'BoldItalic', 'BolIta'),
}
FONT_FORMATS = {'woff2': 'woff2', 'woff': 'woff', 'ttf': 'truetype'}

LIGHT_KEYS = ('primary', 'action', 'accent', 'background', 'surface', 'text', 'success', 'warning', 'danger', 'info')
DARK_KEYS = ('primary', 'action', 'background', 'surface', 'text')
# kit color key -> Odoo SCSS variables it drives
BRAND_VARS = {
    'primary': ('$o-enterprise-color', '$o-brand-odoo', '$o-brand-primary'),
    'action': ('$o-enterprise-action-color', '$o-action', '$o-main-link-color'),
}
REQUIRED_KEYS = ('primary', 'action', 'background', 'surface', 'text')
HEX = re.compile(r'^#[0-9A-Fa-f]{6}$')
MIN_CONTRAST = 3.0
FONT_MAGIC = {'woff2': (b'wOF2',), 'woff': (b'wOFF',), 'ttf': (b'\x00\x01\x00\x00', b'true', b'OTTO')}
MAX_FONT = 2 * 1024 * 1024
FONT_FAMILY = re.compile(r'^[\w .\-]{1,64}\Z')
# Ready-made palettes for the editor, all passing the import's 3:1 readability checks: (light, dark).
PALETTES = {
    'gec': ({'primary': '#153749', 'action': '#049978', 'accent': '#F05324', 'background': '#F5F5F0', 'surface': '#FFFFFF', 'text': '#153749'},
            {'primary': '#F05324', 'action': '#049978', 'background': '#0E2230', 'surface': '#153749', 'text': '#F5F5F0'}),
    'ocean': ({'primary': '#0B4F79', 'action': '#0069A6', 'accent': '#00B4D8', 'background': '#F3F8FB', 'surface': '#FFFFFF', 'text': '#10324A'},
              {'primary': '#1F78B4', 'action': '#0069A6', 'background': '#0D1B26', 'surface': '#13283A', 'text': '#E8F1F7'}),
    'forest': ({'primary': '#1E5631', 'action': '#2E7D32', 'accent': '#F9A825', 'background': '#F4F7F2', 'surface': '#FFFFFF', 'text': '#1B2E1C'},
               {'primary': '#2E7D32', 'action': '#2E7D32', 'background': '#0F1A12', 'surface': '#17291B', 'text': '#E6EFE6'}),
    'burgundy': ({'primary': '#7A2230', 'action': '#9E3446', 'accent': '#C9A227', 'background': '#F8F4F2', 'surface': '#FFFFFF', 'text': '#2B1A1D'},
                 {'primary': '#9E3446', 'action': '#A8404F', 'background': '#1A0F11', 'surface': '#2A171B', 'text': '#F2E8EA'}),
    'graphite': ({'primary': '#2F3A45', 'action': '#2B6CB0', 'accent': '#F2994A', 'background': '#F4F5F7', 'surface': '#FFFFFF', 'text': '#1F2933'},
                 {'primary': '#3A4755', 'action': '#2B6CB0', 'background': '#12161B', 'surface': '#1C2229', 'text': '#E4E7EB'}),
    'purple': ({'primary': '#4A2C82', 'action': '#6A40B5', 'accent': '#E0A100', 'background': '#F6F4FA', 'surface': '#FFFFFF', 'text': '#24163F'},
               {'primary': '#6A40B5', 'action': '#7048B8', 'background': '#140E21', 'surface': '#201836', 'text': '#EDE7F6'}),
    'orange': ({'primary': '#A83A00', 'action': '#B84A00', 'accent': '#1F6F8B', 'background': '#FBF6F2', 'surface': '#FFFFFF', 'text': '#2E1A0E'},
               {'primary': '#B84A00', 'action': '#A83A00', 'background': '#1C120B', 'surface': '#2A1B11', 'text': '#F5EBE3'}),
}
PALETTE_LABELS = [
    ('gec', 'Navy & Teal (GEC)'), ('ocean', 'Ocean Blue'), ('forest', 'Forest Green'), ('burgundy', 'Burgundy'),
    ('graphite', 'Graphite'), ('purple', 'Royal Purple'), ('orange', 'Deep Orange'),
]


def luminance(color):
    """WCAG relative luminance of '#RRGGBB'."""
    channels = []
    for i in (1, 3, 5):
        c = int(color[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def contrast_pairs(colors):
    """Return (label, ratio) for the readability pairs present in `colors`: text on surface and background,
    white text on the primary and action colors. Shared by the import, the save check and the form panel."""
    pairs = []
    for fg, bg, what in (('text', 'surface', _("Text on surface")), ('text', 'background', _("Text on background"))):
        if colors.get(fg) and colors.get(bg):
            pairs.append((what, contrast(colors[fg], colors[bg])))
    for key, what in (('primary', _("White text on primary")), ('action', _("White text on buttons"))):
        if colors.get(key):
            pairs.append((what, contrast('#FFFFFF', colors[key])))
    return pairs


def check_contrast(colors, label):
    """Refuse colors that make the backend unreadable (WCAG ratio under 3:1)."""
    for what, ratio in contrast_pairs(colors):
        if ratio < MIN_CONTRAST:
            raise UserError(_("%(mode)s: %(what)s is too low (%(ratio).1f:1, at least 3:1 needed).",
                              mode=label, what=what, ratio=ratio))


UI_STYLES = [('standard', 'Colors only'), ('strong', 'Strong'), ('bold', 'Very strong')]
SCHEME_VARS = {
    'background': ('$o-webclient-background-color',),
    'surface': ('$o-view-background-color',),
    'text': ('$o-main-text-color',),
    'success': ('$o-success',),
    'warning': ('$o-warning',),
    'danger': ('$o-danger',),
    'info': ('$o-info',),
}


class GecBrandKit(models.Model):
    _name = 'gec.brand.kit'
    _description = 'Brand Kit'

    name = fields.Char('Application Name', help="Shown as the browser tab title and the installed-app name instead of \"Odoo\".")
    state = fields.Selection([('default', 'Odoo default'), ('applied', 'Applied')], default='default', required=True, readonly=True)
    applied_date = fields.Datetime(readonly=True)
    applied_uid = fields.Many2one('res.users', 'Applied by', readonly=True)
    unapplied_changes = fields.Boolean(compute='_compute_unapplied_changes')
    web_app_name_set = fields.Boolean(readonly=True, help="True when Apply wrote the application name parameter, so Reset may remove it.")

    color_primary = fields.Char('Primary')
    color_action = fields.Char('Action')
    color_accent = fields.Char('Accent', help="Thin highlight lines (top bar, page header, cards, tabs). Defaults to the action color.")
    color_background = fields.Char('Background')
    color_surface = fields.Char('Surface')
    color_text = fields.Char('Text')
    color_success = fields.Char('Success')
    color_warning = fields.Char('Warning')
    color_danger = fields.Char('Danger')
    color_info = fields.Char('Info')
    dark_primary = fields.Char('Dark Primary')
    dark_action = fields.Char('Dark Action')
    dark_background = fields.Char('Dark Background')
    dark_surface = fields.Char('Dark Surface')
    dark_text = fields.Char('Dark Text')

    ui_style = fields.Selection(UI_STYLES, 'Branding Strength', default='strong', required=True,
                                help="Colors only: Odoo's look with the brand colors on buttons and links.\n"
                                     "Strong: also a brand top bar, page header, list headers, form and card accents.\n"
                                     "Very strong: also tinted page backgrounds and solid list headers.")

    palette = fields.Selection(PALETTE_LABELS, 'Ready-made Palette',
                               help="Fills the light and dark colors; each color can still be changed afterwards.")
    readability = fields.Html('Readability', compute='_compute_readability', sanitize=False)
    font_sample = fields.Html(compute='_compute_font_sample', sanitize=False)

    font = fields.Selection(FONT_LABELS, 'Font',
                            help="FiraGO and the Noto fonts contain Georgian letters. Fonts marked \"Latin only\" show "
                                 "Georgian text in the browser's default font.")
    font_family = fields.Char('Kit Font Family')
    font_regular = fields.Binary('Font Regular')
    font_regular_name = fields.Char()
    font_bold = fields.Binary('Font Bold')
    font_bold_name = fields.Char()
    font_italic = fields.Binary('Font Italic')
    font_italic_name = fields.Char()
    font_bold_italic = fields.Binary('Font Bold Italic')
    font_bold_italic_name = fields.Char()

    logo = fields.Image('Logo', max_width=1024, max_height=1024)
    home_background = fields.Image('Home Background', max_width=2560, max_height=1440)
    login_background = fields.Image('Login Background', max_width=2560, max_height=1440,
                                    help="Behind the login box. When empty, the home background is used.")
    favicon = fields.Image('Favicon', max_width=512, max_height=512)

    @api.model
    def _get(self):
        """Return the one brand kit of the database (created by data), or an empty recordset; never creates."""
        return self.search([], limit=1)

    @api.model
    def _get_applied(self):
        """Return the kit with sudo when it is applied, else an empty recordset.

        Every runtime reader (menus, layout, manifest, public routes) goes through this, so an
        imported but not applied kit, or a reset one, changes nothing on screen."""
        kit = self.sudo().with_context(bin_size=True)._get()
        return kit if kit.state == 'applied' else self.browse()

    def _check_system(self):
        if not self.env.is_system():
            raise AccessError(_("Only administrators can change the brand kit."))

    # ------------------------------------------------------------------ editor

    @api.depends('write_date', 'applied_date', 'state')
    def _compute_unapplied_changes(self):
        """True when the kit was saved after the last Apply. Apply writes applied_date in the same transaction
        as the record's write_date, so a gap of a few seconds means a later save."""
        for kit in self:
            kit.unapplied_changes = bool(
                kit.state == 'applied' and kit.write_date and kit.applied_date
                and (kit.write_date - kit.applied_date).total_seconds() > 2
            )

    @api.onchange('palette')
    def _onchange_palette(self):
        """Fill the light and dark colors from the chosen palette; status colors stay as they are."""
        if not self.palette:
            return
        light, dark = PALETTES[self.palette]
        self.update({f'color_{key}': value for key, value in light.items()})
        self.update({f'dark_{key}': value for key, value in dark.items()})

    @api.onchange('font')
    def _onchange_font(self):
        """A font from the list replaces the kit's own font files."""
        if self.font:
            self.update({'font_family': False, **{f'font_{key}': False for key in FONT_STYLES},
                         **{f'font_{key}_name': False for key in FONT_STYLES}})

    @api.onchange('font_family', 'font_regular')
    def _onchange_font_family(self):
        if self.font_family and self.font_regular:
            self.font = False

    def _editor_colors(self, dark=False):
        """Like _colors(), but only valid #RRGGBB values: the form computes run on unsaved input."""
        return {key: value for key, value in self._colors(dark).items() if HEX.match(value)}

    @api.depends(*[f'color_{key}' for key in LIGHT_KEYS], *[f'dark_{key}' for key in DARK_KEYS])
    def _compute_readability(self):
        """Readability panel of the form: one green or red badge per color pair, light and dark mode."""
        for kit in self:
            light = kit._editor_colors()
            rows = []
            dark = {**{k: light[k] for k in ('primary', 'action') if k in light}, **kit._editor_colors(dark=True)}
            for mode, colors in ((_("Light mode"), light), (_("Dark mode"), dark if kit._editor_colors(dark=True) else {})):
                for what, ratio in contrast_pairs(colors):
                    ok = ratio >= MIN_CONTRAST
                    rows.append(Markup(
                        '<div class="d-flex align-items-center gap-2 mb-1">'
                        '<span class="badge %s">%s %.1f:1</span><span>%s — %s</span></div>'
                    ) % ('text-bg-success' if ok else 'text-bg-danger', '✓' if ok else '✗', ratio, mode, what))
            kit.readability = Markup('').join(rows) if rows else False

    @api.depends('font', 'font_family')
    def _compute_font_sample(self):
        """Sample line in the chosen bundled font (its @font-face is always loaded); a note for the others."""
        for kit in self:
            if kit.font in BUNDLED_FONTS:
                kit.font_sample = Markup('<div class="fs-4" style="font-family: \'%s\', sans-serif">%s</div>') % (
                    BUNDLED_FONTS[kit.font], 'ბრენდის სტილი — Brand Style Aa 123')
            elif kit.font:
                kit.font_sample = Markup('<div class="text-muted">%s</div>') % _(
                    "This font has no Georgian letters; Georgian text will use the browser's default font.")
            elif kit.font_family:
                kit.font_sample = Markup('<div class="text-muted">%s</div>') % _(
                    "The kit's own font files are used; the sample shows after Apply.")
            else:
                kit.font_sample = False

    @api.constrains(*[f'color_{key}' for key in LIGHT_KEYS], *[f'dark_{key}' for key in DARK_KEYS])
    def _check_colors(self):
        """Same rules as the import, so a color edited on the form cannot make the backend unreadable."""
        for kit in self:
            for prefix, keys in (('color_', LIGHT_KEYS), ('dark_', DARK_KEYS)):
                for key in keys:
                    value = kit[prefix + key]
                    if value and not HEX.match(value):
                        raise ValidationError(_("The color \"%(field)s\" must be #RRGGBB, not \"%(value)s\".",
                                                field=kit._fields[prefix + key].string, value=value))
            try:
                check_contrast(kit._colors(), _("Light mode"))
                if kit._colors(dark=True):
                    check_contrast({**{k: v for k, v in kit._colors().items() if k in ('primary', 'action')},
                                    **kit._colors(dark=True)}, _("Dark mode"))
            except UserError as e:
                raise ValidationError(e.args[0]) from e

    @api.constrains('font_family', 'font_regular', 'font_bold', 'font_italic', 'font_bold_italic')
    def _check_font_files(self):
        """Uploaded font files must be real woff2, woff or ttf files of at most 2 MB. The family name goes
        into the generated SCSS, so only letters, digits, spaces, dots and dashes are allowed: anything else
        could break the compiled styles of every backend page."""
        for kit in self.with_context(bin_size=False):
            if kit.font_family and not FONT_FAMILY.match(kit.font_family):
                raise ValidationError(_("The font family name may only contain letters, digits, spaces, dots and dashes."))
            for key in FONT_STYLES:
                data = kit[f'font_{key}']
                if not data:
                    continue
                name = kit[f'font_{key}_name'] or ''
                ext = name.rsplit('.', 1)[-1].lower()
                content = data.content
                if ext not in FONT_MAGIC or not content.startswith(FONT_MAGIC[ext]):
                    raise ValidationError(_("\"%s\" is not a woff2, woff or ttf font.", name or key))
                if len(content) > MAX_FONT:
                    raise ValidationError(_("Font file \"%s\" is larger than 2 MB.", name))

    # ------------------------------------------------------------------ SCSS

    def _colors(self, dark=False):
        """Return {key: '#RRGGBB'} of the light colors, or of the dark section (empty dict if none)."""
        prefix, keys = ('dark_', DARK_KEYS) if dark else ('color_', LIGHT_KEYS)
        return {key: self[prefix + key] for key in keys if self[prefix + key]}

    def _font_scss(self):
        """Return the @font-face rules and the font stack line, or '' when the kit sets no font."""
        faces = []
        if self.font_family:
            family = self.font_family.replace('"', '')
            for key, (weight, style, _suffix, _lato) in FONT_STYLES.items():
                name = self[f'font_{key}_name']
                if not self[f'font_{key}'] or not name:
                    continue
                fmt = FONT_FORMATS[name.rsplit('.', 1)[-1].lower()]
                unique = int(self.write_date.timestamp()) if self.write_date else 0
                faces.append((f'/gec_brand_kit/font/{key}?unique={unique}', fmt, weight, style))
        elif self.font in BUNDLED_FONTS:
            return f'$o-font-family-sans-serif: ("{BUNDLED_FONTS[self.font]}", {SYSTEM_FONT_STACK}) !default;'
        elif self.font:
            family = dict(SHIPPED_FONTS)[self.font]
            for key, (weight, style, suffix, lato) in FONT_STYLES.items():
                if self.font == 'Lato':
                    rel = f'web/static/fonts/lato/Lato-{lato}-webfont.ttf'
                else:
                    rel = f'web/static/fonts/google/{self.font}/{self.font}-{suffix}.ttf'
                try:
                    file_path(rel)
                except FileNotFoundError:
                    continue
                faces.append((f'/{rel}', 'truetype', weight, style))
        else:
            return ''
        css_style = {'normal': 'normal', 'bold': 'normal', 'italic': 'italic'}
        lines = [
            f'@font-face {{ font-family: "{family}"; src: url("{url}") format("{fmt}"); '
            f'font-weight: {weight}; font-style: {css_style[style]}; font-display: swap; }}'
            for url, fmt, weight, style in faces
        ]
        lines.append(f'$o-font-family-sans-serif: ("{family}", {SYSTEM_FONT_STACK}) !default;')
        return '\n'.join(lines)

    def _style_scss(self, navbar):
        """Return the variables read by static/src/scss/brand_theme.scss, and for the strong styles the
        enterprise navbar variables (they are `!default` in web_enterprise, so ours win): a brand-colored
        top bar with white entries. `navbar` is the top bar color of this mode."""
        lines = [
            f'$gec-brand-style: {self.ui_style or "standard"} !default;',
            f'$gec-brand-accent: {self.color_accent or self.color_action} !default;',
        ]
        if self.ui_style in ('strong', 'bold'):
            lines += [
                f'$o-navbar-background: {navbar} !default;',
                '$o-navbar-entry-color: rgba(#FFFFFF, .9) !default;',
                '$o-navbar-entry-color--hover: #FFFFFF !default;',
                '$o-navbar-entry-bg--hover: rgba(#FFFFFF, .12) !default;',
                '$o-navbar-brand-color: #FFFFFF !default;',
            ]
        return lines

    def _scss_light(self):
        """Return the generated light variables file.

        It is inserted right before web_enterprise's primary variables, so its `!default` values win.
        In dark bundles the dark file comes first and sets $o-webclient-color-scheme to dark; the guard
        then keeps Odoo's dark backgrounds, text and status colors. The `null !default` lines declare the
        guarded variables at top level (a null still counts as unset for Odoo's later `!default`)."""
        colors = self._colors()
        lines = ['// generated by gec_brand_kit, do not edit']
        for key, names in BRAND_VARS.items():
            lines += [f'{name}: {colors[key]} !default;' for name in names]
        lines += self._style_scss(colors['primary'])
        scheme = {key: value for key, value in colors.items() if key in SCHEME_VARS}
        lines += [f'{name}: null !default;' for key in scheme for name in SCHEME_VARS[key]]
        if scheme:
            lines.append('@if not variable-exists(o-webclient-color-scheme) or $o-webclient-color-scheme == bright {')
            lines += [f'    {name}: {value} !default !global;' for key, value in scheme.items() for name in SCHEME_VARS[key]]
            lines.append('}')
        lines.append(self._font_scss())
        return '\n'.join(lines) + '\n'

    def _scss_dark(self):
        """Return the generated dark variables file: color scheme first, then brand and, when the kit has
        a dark section, its backgrounds and text. Brand colors fall back to the light ones."""
        light, dark = self._colors(), self._colors(dark=True)
        lines = ['// generated by gec_brand_kit, do not edit', '$o-webclient-color-scheme: dark !default;']
        for key, names in BRAND_VARS.items():
            lines += [f'{name}: {dark.get(key) or light[key]} !default;' for name in names]
        lines += self._style_scss(dark.get('surface') or light['primary'])
        for key in ('background', 'surface', 'text'):
            if dark.get(key):
                lines += [f'{name}: {dark[key]} !default;' for name in SCHEME_VARS[key]]
        return '\n'.join(lines) + '\n'

    def _write_scss(self, url, content):
        """Create or update the attachment the ir.asset row points to; its write_date versions the bundle."""
        Attachment = self.env['ir.attachment'].sudo()
        attachment = Attachment.search([('url', '=', url), ('type', '=', 'binary')], limit=1)
        raw = content.encode()
        if attachment:
            attachment.write({'raw': raw})
        else:
            Attachment.create({
                'name': url.rsplit('/', 1)[-1],
                'type': 'binary',
                'mimetype': 'text/scss',
                'url': url,
                'raw': raw,
                'public': False,
                'res_model': self._name,
                'res_id': self.id,
            })

    def _asset_rows(self):
        return self.env.ref('gec_brand_kit.asset_light').sudo() | self.env.ref('gec_brand_kit.asset_dark').sudo()

    # ------------------------------------------------------------------ companies

    def _company_values(self):
        """Values written to every company on Apply and on company creation (logo, report and email colors, font)."""
        values = {
            'primary_color': self.color_primary,
            'secondary_color': self.color_action,
            'email_secondary_color': self.color_action,
        }
        if self.font in dict(self.env['res.company']._fields['font'].selection):
            values['font'] = self.font
        logo = self.with_context(bin_size=False).logo
        if logo:
            # PDF reports cannot read webp, and a logo uploaded on the form is stored as given
            values['logo'] = BinaryBytes(image_process(logo.content, output_format='PNG')) if logo.mimetype == 'image/webp' else logo
        return values

    # ------------------------------------------------------------------ actions

    def action_apply(self):
        """Write the brand into the database: SCSS files, asset rows, companies, app name; then reload."""
        self.ensure_one()
        self._check_system()
        missing = [self._fields[f'color_{key}'].string for key in REQUIRED_KEYS if not self[f'color_{key}']]
        if missing:
            raise UserError(_("Fill in these colors before Apply: %s.", ', '.join(missing)))
        self._write_scss(LIGHT_URL, self._scss_light())
        self._write_scss(DARK_URL, self._scss_dark())
        self._asset_rows().write({'active': True})
        self.env.transaction.invalidate_ormcache('assets')
        self._check_styles_compile()
        self.env['res.company'].sudo().search([]).write(self._company_values())
        Param = self.env['ir.config_parameter'].sudo()
        vals = {'state': 'applied', 'applied_date': fields.Datetime.now(), 'applied_uid': self.env.uid}
        if self.name and (self.web_app_name_set or not Param.get_str(APP_NAME_PARAM)):
            Param.set_str(APP_NAME_PARAM, self.name)
            vals['web_app_name_set'] = True
        self.write(vals)
        self.env.transaction.invalidate_ormcache('assets')
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _check_styles_compile(self):
        """Compile the backend, dark and report styles with the new files before Apply commits. A compile
        error would leave every page unstyled; raising here rolls the whole Apply back instead."""
        errors = []
        for bundle in ('web.assets_web', 'web.assets_web_dark', 'web.report_assets_common'):
            assets = self.env['ir.qweb']._get_asset_bundle(bundle, css=True, js=False)
            assets.css()
            errors += assets.css_errors
        if errors:
            raise UserError(_("The brand could not be applied: Odoo failed to build the styles with it. "
                              "Nothing was changed.\n\n%s", '\n'.join(errors)[:1500]))

    def action_reset(self):
        """Turn the brand off: asset rows inactive, generated files and app name removed. Company fields stay."""
        self.ensure_one()
        self._check_system()
        self._asset_rows().write({'active': False})
        self.env['ir.attachment'].sudo().search([('url', 'in', (LIGHT_URL, DARK_URL))]).unlink()
        if self.web_app_name_set:
            self.env['ir.config_parameter'].sudo().search([('key', '=', APP_NAME_PARAM)]).unlink()
        self.write({'state': 'default', 'applied_date': False, 'applied_uid': False, 'web_app_name_set': False})
        self.env.transaction.invalidate_ormcache('assets')
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_open_import(self):
        self.ensure_one()
        self._check_system()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Import Brand Kit"),
            'res_model': 'gec.brand.kit.import',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_export(self):
        """Download the kit as a ZIP in the import format (brand.json + images + font files)."""
        self.ensure_one()
        self._check_system()
        kit = self.with_context(bin_size=False)
        data = {'format': 'gec-brand-kit/1'}
        if kit.name:
            data['name'] = kit.name
        data['colors'] = kit._colors()
        data['style'] = kit.ui_style
        if kit._colors(dark=True):
            data['dark'] = kit._colors(dark=True)
        files = {}
        if kit.font_family:
            data['font'] = {'family': kit.font_family, 'files': {}}
            for key in FONT_STYLES:
                if kit[f'font_{key}']:
                    name = kit[f'font_{key}_name']
                    data['font']['files'][key] = name
                    files[name] = kit[f'font_{key}'].content
        elif kit.font:
            data['font'] = kit.font
        images = {}
        for key in IMAGE_KEYS:
            if kit[key]:
                ext = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}.get(kit[key].mimetype, 'png')
                name = f'{key}.{ext}'
                images[key] = name
                files[name] = kit[key].content
        if images:
            data['files'] = images
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('brand.json', json.dumps(data, indent=2, ensure_ascii=False))
            for name, content in files.items():
                archive.writestr(os.path.basename(name), content)
        Attachment = self.env['ir.attachment']
        Attachment.search([('res_model', '=', self._name), ('name', '=', 'brand_kit.zip')]).unlink()
        attachment = Attachment.create({
            'name': 'brand_kit.zip',
            'raw': buffer.getvalue(),
            'mimetype': 'application/zip',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {'type': 'ir.actions.act_url', 'url': f'/web/content/{attachment.id}?download=true', 'target': 'self'}
