#!/usr/bin/env python3
"""
Shaw-Spell social-preview card renderer.

Serves the 1200x630 PNG behind og:image (see the meta tags in index.cgi).
Same thin-frontend contract as index.cgi: entry data comes from the suggestd
daemon; the only local state is the fonts shipped in fonts/ — Bernie Sans
Beta (the site's house font, covers Latin + Shavian) plus InterAlia for IPA,
which Bernie lacks entirely.
Cards are rendered per request — the og:image URL is version-keyed, so
crawlers and platforms cache by URL and long-lived HTTP caching does the rest.
"""

import io
import os
import re
import sys
from urllib.parse import parse_qs

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# CGI does not guarantee the script's directory is on the path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sitecommon import (  # noqa: E402
    DaemonError, contains_shavian, daemon_request, searched_first,
)

WIDTH, HEIGHT = 1200, 630
# Draw at 2x and downsample for smooth corners and pill edges.
SCALE = 2

MARGIN = 20
CARD_RADIUS = 22
PAD_X, PAD_Y = 56, 44
HEAD_TOP_OFFSET = 12
HEAD_GAP = 36
HEAD_LINE_GAP = 14
BADGE_CLEARANCE = 32
SUB_GAP = 32
PILLS_GAP = 36
PILL_SPACING = 14
PILL_PAD_X, PILL_PAD_Y = 24, 8
FOOTER_CLEARANCE = 24

GRADIENT_FROM = (0x66, 0x7e, 0xea)
GRADIENT_TO = (0x9d, 0x42, 0x68)
INK = '#222'
ACCENT = '#667eea'
SUB_TEXT = '#444'
SUB_MUTED = '#999'
IPA_GREY = '#888'
FOOTER_GREY = '#888'
PILL_BG = '#f0f0ff'
PILL_FG = '#5568d3'

# The brand signature: the leading · is the Shavian naming dot (semantic).
SIGNATURE = '·\U00010456\U00010477-\U00010455\U00010450\U00010467\U00010464 ©joro.io'
SIGNATURE_SIZE = 34
SIGNATURE_COLOR = '#a9a9bd'

MAX_POS_PILLS = 4
MAX_SUB_LINES = 2
MAX_HEAD_LATINS = 3
LARGE_ENTRY_DEFS = 10

SUB_SIZE = 36
# The unlabelled related-entries row: size, not a label, marks it out.
RELATED_SUB_SIZE = 44

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
SANS_FONT = 'BernieSansBetaVF.ttf'
IPA_FONT = 'InterAlia-Regular.otf'
WEIGHT_REGULAR, WEIGHT_MEDIUM = 400, 500


def font_path(filename):
    """PIL's truetype() falls back to searching system font directories by
    basename when the path cannot be opened; refuse that — a missing shipped
    font must be a hard error, never a silent substitute."""
    path = os.path.join(FONT_DIR, filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f'font missing: {path}')
    return path


def load_font(size, weight=WEIGHT_REGULAR):
    font = ImageFont.truetype(font_path(SANS_FONT), size * SCALE)
    # Axis order per fvar: wght, slnt, wdth, opsz. Optical size follows the
    # text size like browser auto optical sizing (opsz is in points, px*0.75).
    font.set_variation_by_axes([weight, 0, 100, min(24, max(8, size * 0.75))])
    return font


def load_ipa_font(size):
    return ImageFont.truetype(font_path(IPA_FONT), size * SCALE)


def unique(items):
    return list(dict.fromkeys(items))


def segment(text, color):
    return (text, color, False)


def ipa_segment(ipa):
    return (f' {ipa}', SUB_MUTED, True)


IPA_SPAN = re.compile(r'(/[^/]+/)')


def group_segments(text):
    """A variant group as segments, its /IPA/ stretches in the IPA font —
    Bernie has no IPA coverage, and the group arrives from the summary as
    one flat string (e.g. '𐑛𐑵𐑟, US /duːz/')."""
    return [(part, SUB_MUTED, bool(i % 2))
            for i, part in enumerate(IPA_SPAN.split(text)) if part]


def form_row(form):
    """One derived form in the dictionary's own row markup:
    text /ipa/ form-label (variant-group)."""
    if not form['text']:
        return None
    row = [segment(form['text'], INK)]
    if form['ipa']:
        row.append(ipa_segment(form['ipa']))
    if form['label']:
        row.append(segment(f' {form["label"]}', SUB_MUTED))
    if form['variant']:
        row += group_segments(f' ({form["variant"]})')
    return row


def related_line(summaries, head_shaw, head_latins):
    """Unlabelled row of the other entries' pairs — their Shavian, plus
    their Latin when the headline doesn't already show it, so a searched
    inflection still names its lemma next to the lemma's definitions."""
    alternates = unique(
        (s['shaw'], '' if s['latin'] in head_latins else s['latin'], s['ipa'])
        for s in summaries if s['shaw'] and s['shaw'] != head_shaw)
    line = []
    for i, (shaw, latin, ipa) in enumerate(alternates):
        if i:
            line.append(segment(' · ', SUB_MUTED))
        line.append(segment(shaw, INK))
        if latin:
            line.append(segment(f' {latin}', ACCENT))
        if ipa:
            line.append(ipa_segment(ipa))
    return line


def card_content(word, summaries, dialect):
    """Distill the matched entry summaries into the card's fixed slots.
    head is (searched-script text, twin-script text, IPA)."""
    shavian_input = contains_shavian(word)
    summaries = searched_first(word, summaries)
    first = summaries[0]

    if shavian_input:
        head_latins = unique(s['latin'] for s in summaries
                             if s['latin'] and s['shaw'] == first['shaw']
                             )[:MAX_HEAD_LATINS]
        head = (first['shaw'], ' · '.join(head_latins))
    else:
        head_latins = [first['latin']]
        head = (first['latin'], first['shaw'])

    subs = []
    related = related_line(summaries[1:], first['shaw'], head_latins)
    if related:
        subs.append((RELATED_SUB_SIZE, related))
    if not shavian_input:
        # The renderer's width truncation bounds this flow.
        flow = []
        for form in first['forms']:
            row = form_row(form)
            if not row:
                continue
            if flow:
                flow.append(segment(' · ', SUB_MUTED))
            flow += row
        if flow:
            subs.append((SUB_SIZE, flow))

    # Whatever room the forms did not want goes to glosses — a definition
    # says more than the footer's bare count. 58% of entries carry at most
    # one form, so on most cards this is space that was going spare.
    # english-shavian summaries carry no `defs`, so those cards show none
    # until build_site_index emits them in that direction too.
    defs = [d for s in summaries for d in s.get('defs', ())]
    subs += [(SUB_SIZE, [segment(f'{n}. ', SUB_MUTED),
                         segment(text, SUB_TEXT)])
             for n, text in
             enumerate(defs[:MAX_SUB_LINES - len(subs)], start=1)]

    pos_names = unique(pos['name'] for s in summaries for pos in s['pos']
                       if pos['name'])
    ndefs = sum(pos['ndefs'] for s in summaries for pos in s['pos'])

    pills = [(name, False) for name in pos_names[:MAX_POS_PILLS]]
    if ndefs >= LARGE_ENTRY_DEFS:
        pills.append((f'… {ndefs} definitions', True))
        footer = 'Large entry — see the full page'
    elif ndefs == 0:
        footer = 'No definitions available'
    else:
        footer = f'{ndefs} definition{"s" if ndefs != 1 else ""}'

    return {
        'head': (*head, first['ipa']),
        'badge': dialect.upper(),
        'subs': subs,
        'pills': pills,
        'footer': footer,
    }


def gradient_background(width, height):
    """CSS linear-gradient(135deg, …): progress is (x + y) / (w + h)."""
    span = width + height
    ramp = Image.new('RGB', (span, 1))
    ramp.putdata([
        tuple(int(a + (b - a) * d / (span - 1))
              for a, b in zip(GRADIENT_FROM, GRADIENT_TO))
        for d in range(span)
    ])
    background = Image.new('RGB', (width, height))
    for y in range(height):
        background.paste(ramp.crop((y, 0, y + width, 1)), (0, y))
    return background


def run_width(draw, run):
    return sum(draw.textlength(text, font=font) for text, _, font in run)


def draw_run(draw, x, baseline, run):
    for text, color, font in run:
        ascent = font.getmetrics()[0]
        draw.text((x, baseline - ascent), text, font=font, fill=color)
        x += draw.textlength(text, font=font)
    return x


def truncate_run(draw, run, max_width):
    """Trim the run's trailing text until it fits, ending it with an
    ellipsis if anything was cut."""
    if run_width(draw, run) <= max_width:
        return run
    run = [list(segment) for segment in run]
    while run and run_width(draw, run) > max_width:
        stripped = run[-1][0].rstrip('…')[:-1]
        if stripped:
            run[-1][0] = stripped + '…'
        else:
            run.pop()
            if run:
                run[-1][0] = run[-1][0].rstrip('…') + '…'
    return [tuple(segment) for segment in run]


def draw_pill(draw, x, y, text, font, background, foreground):
    """Rounded pill with centred text; returns its right edge."""
    ascent, descent = font.getmetrics()
    pad_x, pad_y = PILL_PAD_X * SCALE, PILL_PAD_Y * SCALE
    width = draw.textlength(text, font=font) + 2 * pad_x
    height = ascent + descent + 2 * pad_y
    draw.rounded_rectangle((x, y, x + width, y + height),
                           radius=height // 2, fill=background)
    draw.text((x + pad_x, y + pad_y), text, font=font, fill=foreground)
    return x + width


# Headline nominals (lead / twin / IPA). The twin (translation) is
# deliberately a touch larger than the searched word — it is the answer —
# and the layout keeps that ratio inside TWIN_RATIO_* even when wrapped
# lines are fitted independently.
HEAD_SIZES = (76, 92, 40)
HEAD_COLORS = (INK, ACCENT, IPA_GREY)
HEAD_LOADERS = (load_font,
                lambda size: load_font(size, weight=WEIGHT_MEDIUM),
                load_ipa_font)
TWIN_RATIO_MIN, TWIN_RATIO_MAX = 1.1, 1.25
# The wrap-before-illegible ladder's floors (see layout_head).
ONE_LINE_MIN_SCALE = 0.75
LINE_MIN_SCALE = 0.6
SHARED_TWIN_IPA_MIN_SCALE = 0.8


def head_units(content):
    return [(text, color, loader, size)
            for text, color, loader, size
            in zip(content['head'], HEAD_COLORS, HEAD_LOADERS, HEAD_SIZES)
            if text]


def head_line_run(units, scale):
    return [(text, color, loader(round(size * scale)))
            for text, color, loader, size in units]


def head_gap(scale):
    return round(HEAD_GAP * SCALE * scale)


def head_line_width(draw, run, scale):
    return run_width(draw, run) + head_gap(scale) * (len(run) - 1)


def fit_head_line(draw, units, available, floor):
    """A scale in [floor, 1], close to the largest, at which the units fit
    side by side — or None if even the floor overflows."""
    scale = 1.0
    while True:
        width = head_line_width(draw, head_line_run(units, scale), scale)
        if width <= available:
            return scale
        if scale <= floor:
            return None
        scale = max(floor, scale * available / width * 0.995)


def layout_head(draw, content, first_available, full_available):
    """The headline as fitted (run, scale) lines. One line while a gradual
    shrink keeps it readable; otherwise wrapped, the lead alone on the first
    line (which must clear the badge) and the twin + IPA below on the full
    width. Wrapping trades the unused vertical space for size instead of
    collapsing everything onto an illegible single line. The twin:lead size
    ratio is held inside TWIN_RATIO_* (shrink-only, so fitted lines stay
    fitted), and the share-vs-split choice for the twin + IPA line is made
    against the twin's already-capped scale."""
    units = head_units(content)
    scale = fit_head_line(draw, units, first_available, ONE_LINE_MIN_SCALE)
    if scale is not None:
        plans = [(units, first_available, scale)]
    else:
        lead, rest = units[0], units[1:]
        has_twin = bool(content['head'][1])
        lead_scale = (fit_head_line(draw, [lead], first_available, LINE_MIN_SCALE)
                      or LINE_MIN_SCALE)
        twin_cap = (TWIN_RATIO_MAX * HEAD_SIZES[0] * lead_scale / HEAD_SIZES[1]
                    if has_twin else 1.0)
        shared = (fit_head_line(draw, rest, full_available,
                                SHARED_TWIN_IPA_MIN_SCALE)
                  if len(rest) > 1 else None)
        if shared is not None and min(shared, twin_cap) >= SHARED_TWIN_IPA_MIN_SCALE:
            rest_plans = [(rest, min(shared, twin_cap))]
        else:
            rest_plans = [(row, fit_head_line(draw, row, full_available,
                                              LINE_MIN_SCALE) or LINE_MIN_SCALE)
                          for row in ([unit] for unit in rest)]
            if has_twin and rest_plans:
                row, row_scale = rest_plans[0]
                rest_plans[0] = (row, min(row_scale, twin_cap))
        if has_twin and rest_plans:
            twin_px = HEAD_SIZES[1] * rest_plans[0][1]
            lead_scale = min(lead_scale,
                             twin_px / (TWIN_RATIO_MIN * HEAD_SIZES[0]))
        plans = ([([lead], first_available, lead_scale)]
                 + [(row, full_available, row_scale)
                    for row, row_scale in rest_plans])
    return [(truncate_run(draw, head_line_run(row, row_scale),
                          avail - head_gap(row_scale) * (len(row) - 1)),
             row_scale)
            for row, avail, row_scale in plans]


def render_card(content):
    width, height = WIDTH * SCALE, HEIGHT * SCALE
    margin = MARGIN * SCALE

    image = gradient_background(width, height).convert('RGBA')

    # Shadow approximating CSS box-shadow 0 10px 36px rgba(0,0,0,.3).
    card_box = (margin, margin, width - margin, height - margin)
    shadow = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    shadow_box = (card_box[0], card_box[1] + 10 * SCALE,
                  card_box[2], card_box[3] + 10 * SCALE)
    ImageDraw.Draw(shadow).rounded_rectangle(
        shadow_box, radius=CARD_RADIUS * SCALE, fill=(0, 0, 0, 77))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12 * SCALE))
    image = Image.alpha_composite(image, shadow)

    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(card_box, radius=CARD_RADIUS * SCALE, fill='white')

    inner_left = margin + PAD_X * SCALE
    inner_right = width - margin - PAD_X * SCALE
    inner_width = inner_right - inner_left

    badge_font = load_font(24)
    badge_ascent, badge_descent = badge_font.getmetrics()
    badge_width = (draw.textlength(content['badge'], font=badge_font)
                   + 2 * 18 * SCALE)
    head_top = margin + (PAD_Y + HEAD_TOP_OFFSET) * SCALE
    badge_left = inner_right - badge_width
    badge_height = badge_ascent + badge_descent + 2 * 4 * SCALE
    draw.rounded_rectangle(
        (badge_left, head_top, inner_right, head_top + badge_height),
        radius=badge_height // 2, fill=ACCENT)
    draw.text((badge_left + 18 * SCALE, head_top + 4 * SCALE),
              content['badge'], font=badge_font, fill='white')

    # The footer zone is measured up front: everything above it (subs,
    # pills) is dropped rather than drawn into it when a wrapped headline
    # has eaten the room.
    footer_font = load_font(28)
    signature_font = load_font(SIGNATURE_SIZE)
    footer_baseline = (height - margin - PAD_Y * SCALE
                       - signature_font.getmetrics()[1])
    content_floor = (footer_baseline - FOOTER_CLEARANCE * SCALE
                     - max(footer_font.getmetrics()[0],
                           signature_font.getmetrics()[0]))

    # Headline lines; within a line the segments share a baseline, which
    # must be the tallest font's — the twin outsizes the lead.
    head_first_available = badge_left - BADGE_CLEARANCE * SCALE - inner_left
    y = head_top
    for i, (run, scale) in enumerate(
            layout_head(draw, content, head_first_available, inner_width)):
        if i:
            y += HEAD_LINE_GAP * SCALE
        ascent = max(font.getmetrics()[0] for _, _, font in run)
        descent = max(font.getmetrics()[1] for _, _, font in run)
        x = inner_left
        for j, piece in enumerate(run):
            if j:
                x += head_gap(scale)
            x = draw_run(draw, x, y + ascent, [piece])
        y += ascent + descent

    for size, sub in content['subs']:
        sub_font = load_font(size)
        sub_ipa_font = load_ipa_font(size)
        sub_ascent, sub_descent = (
            max(a, b) for a, b in zip(sub_font.getmetrics(),
                                      sub_ipa_font.getmetrics()))
        if y + SUB_GAP * SCALE + sub_ascent + sub_descent > content_floor:
            break
        y += SUB_GAP * SCALE
        run = truncate_run(
            draw, [(text, color, sub_ipa_font if is_ipa else sub_font)
                   for text, color, is_ipa in sub],
            inner_width)
        draw_run(draw, inner_left, y + sub_ascent, run)
        y += sub_ascent + sub_descent

    if content['pills']:
        pill_font = load_font(30)
        pill_ascent, pill_descent = pill_font.getmetrics()
        pill_height = pill_ascent + pill_descent + 2 * PILL_PAD_Y * SCALE
        if y + PILLS_GAP * SCALE + pill_height <= content_floor:
            y += PILLS_GAP * SCALE
            x = inner_left
            for text, emphasized in content['pills']:
                pill_width = (draw.textlength(text, font=pill_font)
                              + 2 * PILL_PAD_X * SCALE)
                if x + pill_width > inner_right:
                    break
                background, foreground = ((ACCENT, 'white') if emphasized
                                          else (PILL_BG, PILL_FG))
                x = draw_pill(draw, x, y, text, pill_font,
                              background, foreground) + PILL_SPACING * SCALE

    # Footer: definition count left, brand signature right, shared baseline.
    draw_run(draw, inner_left, footer_baseline,
             [(content['footer'], FOOTER_GREY, footer_font)])
    signature_x = inner_right - draw.textlength(SIGNATURE, font=signature_font)
    draw_run(draw, signature_x, footer_baseline,
             [(SIGNATURE, SIGNATURE_COLOR, signature_font)])

    final = image.convert('RGB').resize((WIDTH, HEIGHT), Image.LANCZOS)
    buffer = io.BytesIO()
    final.save(buffer, 'PNG')
    return buffer.getvalue()


def respond_error(status, message):
    sys.stdout.write(f'Status: {status}\n'
                     'Content-Type: text/plain; charset=utf-8\n\n'
                     f'{message}\n')


def main():
    params = parse_qs(os.environ.get('QUERY_STRING', ''))
    word = params.get('word', [''])[0].strip()
    dialect = params.get('dialect', ['gb'])[0]

    if not word:
        respond_error('400 Bad Request', 'missing word parameter')
        return
    if dialect not in ('gb', 'us'):
        respond_error('400 Bad Request', f'unknown dialect: {dialect}')
        return

    direction = ('shavian-english' if contains_shavian(word)
                 else 'english-shavian')
    response = daemon_request({
        'op': 'lookup',
        'dict_type': f'{direction}-{dialect}',
        'word': word,
    })
    if response.get('entry_html') and 'summary' not in response:
        raise DaemonError('lookup hit but no summary in response — '
                          'suggestd predates the summaries data; restart it')
    summaries = response.get('summary')
    if not summaries:
        respond_error('404 Not Found', f'no entry for "{word}"')
        return

    png = render_card(card_content(word, summaries, dialect))

    sys.stdout.write('Content-Type: image/png\n'
                     f'Content-Length: {len(png)}\n'
                     'Cache-Control: public, max-age=31536000, immutable\n\n')
    sys.stdout.flush()
    sys.stdout.buffer.write(png)


if __name__ == '__main__':
    try:
        main()
    except DaemonError as e:
        respond_error('502 Bad Gateway', str(e))
        sys.exit(1)
    except Exception as e:
        respond_error('500 Internal Server Error', f'{type(e).__name__}: {e}')
        sys.exit(1)
