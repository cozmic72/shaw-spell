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
import json
import os
import socket
import sys
from urllib.parse import parse_qs

from PIL import Image, ImageDraw, ImageFilter, ImageFont


# Unix socket served by suggestd. Must match the path in the systemd unit.
DAEMON_SOCKET = os.environ.get('SHAW_SPELL_SUGGEST_SOCKET',
                               '/run/shaw-spell/suggestd.sock')
DAEMON_TIMEOUT_SEC = 2.0

WIDTH, HEIGHT = 1200, 630
# Draw at 2x and downsample for smooth corners and pill edges.
SCALE = 2

MARGIN = 20
CARD_RADIUS = 22
PAD_X, PAD_Y = 56, 44
HEAD_TOP_OFFSET = 12
HEAD_GAP = 36
SUB_GAP = 32
PILLS_GAP = 36
PILL_SPACING = 14

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

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
SANS_FONT = 'BernieSansBetaVF.ttf'
IPA_FONT = 'InterAlia-Regular.otf'
WEIGHT_REGULAR, WEIGHT_MEDIUM = 400, 500


class DaemonError(Exception):
    pass


def daemon_request(request):
    """Send one JSON request to suggestd, return its JSON response.
    Raises DaemonError on any failure — no fallbacks."""
    payload = (json.dumps(request, ensure_ascii=False) + '\n').encode('utf-8')
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(DAEMON_TIMEOUT_SEC)
        sock.connect(DAEMON_SOCKET)
        sock.sendall(payload)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        sock.close()
    except (OSError, socket.timeout) as exc:
        raise DaemonError(f'cannot reach suggestd: {exc}') from exc

    raw = b''.join(chunks).decode('utf-8').strip()
    if not raw:
        raise DaemonError('empty response from suggestd')
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DaemonError(f'malformed response: {exc}') from exc

    if 'error' in response:
        raise DaemonError(response['error'])
    return response


def contains_shavian(text):
    return any('\U00010450' <= c <= '\U0001047F' for c in text)


def load_font(size, weight=WEIGHT_REGULAR):
    font = ImageFont.truetype(os.path.join(FONT_DIR, SANS_FONT), size * SCALE)
    # Axis order per fvar: wght, slnt, wdth, opsz. Optical size follows the
    # text size like browser auto optical sizing (opsz is in points, px*0.75).
    font.set_variation_by_axes([weight, 0, 100, min(24, max(8, size * 0.75))])
    return font


def load_ipa_font(size):
    return ImageFont.truetype(os.path.join(FONT_DIR, IPA_FONT), size * SCALE)


def unique(items):
    return list(dict.fromkeys(items))


def segment(text, color):
    return (text, color, False)


def ipa_segment(ipa):
    return (f' {ipa}', SUB_MUTED, True)


def form_sub_line(form):
    """One derived-form row as styled (text, colour, is_ipa) segments,
    e.g. 'US: 𐑛𐑵 /duː/' or 'plural: 𐑛𐑿𐑟 /djuːz/ (US)'."""
    prefix = form['label'] or form['variant']
    if not (prefix and form['text']):
        return None
    segments = [segment(f'{prefix}: ', SUB_MUTED), segment(form['text'], INK)]
    if form['ipa']:
        segments.append(ipa_segment(form['ipa']))
    if form['label'] and form['variant']:
        segments.append(segment(f' ({form["variant"]})', SUB_MUTED))
    return segments


def searched_first(word, summaries, shavian_input):
    """The index maps inflections to their lemma's entry, so a searched
    inflection that is also a headword in its own right (e.g. 'spelling'
    under 'spell') arrives mixed in with the lemma's entries. Reorder so
    the word's own entries lead and the card shows the searched form."""
    key = word if shavian_input else word.lower()
    hits, rest = [], []
    for summary in summaries:
        headword = summary['shaw'] if shavian_input else summary['latin'].lower()
        (hits if headword == key else rest).append(summary)
    return hits + rest


def card_content(word, summaries, dialect):
    """Distill the matched entry summaries into the card's fixed slots.
    head is (searched-script text, twin-script text, IPA)."""
    shavian_input = contains_shavian(word)
    summaries = searched_first(word, summaries, shavian_input)
    first = summaries[0]

    if shavian_input:
        latins = unique(s['latin'] for s in summaries
                        if s['latin'] and s['shaw'] == first['shaw'])
        head = (first['shaw'], ' · '.join(latins[:MAX_HEAD_LATINS]))
    else:
        head = (first['latin'], first['shaw'])

    subs = []
    if shavian_input:
        defs = [d for s in summaries for d in s['defs']]
        subs = [[segment(f'{n}. ', SUB_MUTED), segment(text, SUB_TEXT)]
                for n, text in enumerate(defs[:MAX_SUB_LINES], start=1)]
    else:
        alternates = unique((s['shaw'], s['ipa']) for s in summaries[1:]
                            if s['shaw'] and s['shaw'] != first['shaw'])
        if alternates:
            line = [segment('also: ', SUB_MUTED)]
            for i, (shaw, ipa) in enumerate(alternates):
                if i:
                    line.append(segment(' · ', SUB_MUTED))
                line.append(segment(shaw, INK))
                if ipa:
                    line.append(ipa_segment(ipa))
            subs.append(line)
        for form in first['forms']:
            if len(subs) >= MAX_SUB_LINES:
                break
            line = form_sub_line(form)
            if line:
                subs.append(line)

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
    pad_x, pad_y = 24 * SCALE, 8 * SCALE
    width = draw.textlength(text, font=font) + 2 * pad_x
    height = ascent + descent + 2 * pad_y
    draw.rounded_rectangle((x, y, x + width, y + height),
                           radius=height // 2, fill=background)
    draw.text((x + pad_x, y + pad_y), text, font=font, fill=foreground)
    return x + width


def head_fonts(draw, content, available_width):
    """Fonts for the headline row, shrunk proportionally if the nominal
    132/68/46 px sizes would overflow the card."""
    sizes = (132, 68, 46)
    loaders = (load_font,
               lambda size: load_font(size, weight=WEIGHT_MEDIUM),
               load_ipa_font)
    fonts = tuple(load(size) for load, size in zip(loaders, sizes))
    texts = content['head']
    gaps = HEAD_GAP * SCALE * (sum(1 for t in texts if t) - 1)
    width = sum(draw.textlength(t, font=f) for t, f in zip(texts, fonts)) + gaps
    if width <= available_width:
        return fonts
    ratio = available_width / width * 0.98
    return tuple(load(max(1, int(size * ratio)))
                 for load, size in zip(loaders, sizes))


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

    # Headline: searched word + twin script + IPA on a shared baseline.
    head_available = badge_left - 24 * SCALE - inner_left
    lead_font, twin_font, ipa_font = head_fonts(draw, content, head_available)
    baseline = head_top + lead_font.getmetrics()[0]
    head_run = [(t, c, f) for t, c, f in zip(
        content['head'], (INK, ACCENT, IPA_GREY),
        (lead_font, twin_font, ipa_font)) if t]
    x = inner_left
    for i, segment in enumerate(head_run):
        if i:
            x += HEAD_GAP * SCALE
        x = draw_run(draw, x, baseline, [segment])
    y = head_top + sum(lead_font.getmetrics())

    sub_font = load_font(36)
    sub_ipa_font = load_ipa_font(36)
    sub_ascent, sub_descent = sub_font.getmetrics()
    for sub in content['subs']:
        y += SUB_GAP * SCALE
        run = truncate_run(
            draw, [(text, color, sub_ipa_font if is_ipa else sub_font)
                   for text, color, is_ipa in sub],
            inner_width)
        draw_run(draw, inner_left, y + sub_ascent, run)
        y += sub_ascent + sub_descent

    if content['pills']:
        y += PILLS_GAP * SCALE
        pill_font = load_font(30)
        x = inner_left
        for text, emphasized in content['pills']:
            pill_width = draw.textlength(text, font=pill_font) + 2 * 24 * SCALE
            if x + pill_width > inner_right:
                break
            background, foreground = ((ACCENT, 'white') if emphasized
                                      else (PILL_BG, PILL_FG))
            x = draw_pill(draw, x, y, text, pill_font,
                          background, foreground) + PILL_SPACING * SCALE

    # Footer: definition count left, brand signature right, shared baseline.
    footer_font = load_font(28)
    signature_font = load_font(SIGNATURE_SIZE)
    footer_baseline = (height - margin - PAD_Y * SCALE
                       - signature_font.getmetrics()[1])
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
