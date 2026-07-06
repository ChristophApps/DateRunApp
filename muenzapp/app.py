import json, html as htmlmod, re, os, io
from flask import Flask, request, jsonify, send_file
from openpyxl import load_workbook, Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment

app = Flask(__name__)

EXCEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Date Run Mai2026.xlsx')
BASE_DIR = os.path.dirname(os.path.abspath(__file__)) or '.'
DATA_PATH = os.path.join(BASE_DIR, 'data.json')
MAX_ROW, MAX_COL = 216, 42
EXT_OFFSET = 10000  # offset for extension row references

THEME = {
    0: '000000', 1: 'FFFFFF', 2: '44546A', 3: 'E7E6E6',
    4: '4472C4', 5: 'ED7D31', 6: 'A5A5A5', 7: 'FFC000',
    8: '5B9BD5', 9: '70AD47',
}

def apply_tint(hex_color, tint):
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    if tint >= 0:
        r = int(r + tint * (255 - r))
        g = int(g + tint * (255 - g))
        b = int(b + tint * (255 - b))
    else:
        r = int(r * (1 + tint))
        g = int(g * (1 + tint))
        b = int(b * (1 + tint))
    return f'{max(0,min(255,r)):02X}{max(0,min(255,g)):02X}{max(0,min(255,b)):02X}'

def cell_fill_rgb(cell):
    fill = cell.fill
    if not fill or not fill.fgColor: return None
    fg = fill.fgColor
    if fg.type == 'rgb' and fg.rgb and isinstance(fg.rgb, str) and len(fg.rgb) == 8 and fg.rgb not in ('FF000000', '00000000'):
        return fg.rgb[2:]
    if fg.theme is not None and fg.type == 'theme':
        try:
            ti = int(str(fg.theme))
            if ti == 0 and (fg.tint is None or fg.tint == 0.0):
                return None
            base = THEME.get(ti)
            if base: return apply_tint(base, fg.tint if fg.tint else 0.0)
        except: pass
    return None

def is_dark(hex_color):
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return r * 0.299 + g * 0.587 + b * 0.114 < 140

print("Loading Excel...")
wb = load_workbook(EXCEL_PATH, data_only=True)
ws = wb.active

base_data = {}
fills = {}
for r in range(1, MAX_ROW + 1):
    for c in range(1, MAX_COL + 1):
        cell = ws.cell(row=r, column=c)
        ref = get_column_letter(c) + str(r)
        if cell.value is not None:
            base_data[ref] = str(cell.value)
        frgb = cell_fill_rgb(cell)
        if frgb:
            if frgb in ('3D4B5F', '333F4F', 'AEAAAA', 'D0CECE'):
                frgb = 'FFC7CE'
            if frgb == 'F7CAAC':
                frgb = 'FF8C42'
            fills[ref] = frgb

merges = {}
for m in ws.merged_cells.ranges:
    if m.min_row > MAX_ROW or m.min_col > MAX_COL: continue
    max_row, max_col = min(m.max_row, MAX_ROW), min(m.max_col, MAX_COL)
    if max_row < m.min_row or max_col < m.min_col: continue
    for r in range(m.min_row, max_row + 1):
        for c in range(m.min_col, max_col + 1):
            ref = get_column_letter(c) + str(r)
            if r == m.min_row and c == m.min_col:
                merges[ref] = {'cs': max_col - m.min_col + 1, 'rs': max_row - m.min_row + 1}
            else:
                merges[ref] = {'skip': True}

cols_letters = [get_column_letter(i) for i in range(1, MAX_COL + 1)]

col_types = {}
for cl in cols_letters:
    if cl in ('A', 'O', 'AC'): col_types[cl] = 'year'
    elif cl in ('J', 'X', 'AL'): col_types[cl] = 'inner-gap'
    elif cl in ('N', 'AB', 'AP'): col_types[cl] = 'gap'
    elif cl in ('K', 'L', 'M', 'Y', 'Z', 'AA', 'AM', 'AN', 'AO'): col_types[cl] = 'cc'
    else: col_types[cl] = 'den'

col_widths = {}
for ci in range(1, MAX_COL + 1):
    letter = get_column_letter(ci)
    if letter in ws.column_dimensions and ws.column_dimensions[letter].width is not None:
        w = ws.column_dimensions[letter].width
    else:
        t = col_types.get(letter, 'den')
        if t == 'year': w = 5.5
        elif t == 'gap': w = 5.66
        elif t == 'inner-gap': w = 0.66
        else: w = 2.83
    if col_types.get(letter) in ('den', 'cc'):
        w *= 1.25
    col_widths[letter] = max(w, 0.66)

total_w = sum(max(col_widths[l] * 7.5, 6) for l in cols_letters)

col_to_block = {}
for ci, cl in enumerate(cols_letters):
    if ci < 13: col_to_block[cl] = 'A'
    elif ci < 14: col_to_block[cl] = None
    elif ci < 27: col_to_block[cl] = 'O'
    elif ci < 28: col_to_block[cl] = None
    elif ci < 41: col_to_block[cl] = 'AC'
    else: col_to_block[cl] = None

COUNTRY_HEADERS = {
    (1, 'A'): 'Österreich', (1, 'O'): '', (1, 'AC'): 'Italien',
    (29, 'A'): 'Frankreich', (29, 'O'): 'Spanien', (29, 'AC'): 'Finnland',
    (61, 'A'): 'Belgien', (61, 'O'): 'Niederlande', (61, 'AC'): 'Luxemburg',
    (94, 'A'): 'Irland', (94, 'O'): 'Griechenland', (94, 'AC'): 'Portugal',
    (124, 'A'): 'Slowenien', (124, 'O'): 'Malta', (124, 'AC'): 'Zypern',
    (148, 'A'): 'Slowakei', (148, 'O'): 'Estland', (148, 'AC'): 'Lettland/Latvia',
    (172, 'A'): 'Litauen/Lietuva', (172, 'O'): 'Kroatien', (172, 'AC'): 'Andorra',
    (180, 'O'): 'Bulgarien',
    (189, 'A'): 'San Marino', (189, 'O'): 'Monaca', (189, 'AC'): 'Vatikan',
}

block_countries = {'A': [], 'O': [], 'AC': []}
for (r, bl), name in sorted(COUNTRY_HEADERS.items()):
    block_countries[bl].append((r, name))

block_row_type = {'A': {}, 'O': {}, 'AC': {}}
for bl in ['A', 'O', 'AC']:
    for i, (cr, cname) in enumerate(block_countries[bl]):
        next_cr = block_countries[bl][i+1][0] if i+1 < len(block_countries[bl]) else MAX_ROW + 1
        block_row_type[bl][cr] = 'country'
        if next_cr > cr + 2:
            block_row_type[bl][cr+1] = 'colheader'
            for dr in range(cr+2, next_cr):
                block_row_type[bl][dr] = 'data'

YEAR_COL = {'A': 'A', 'O': 'O', 'AC': 'AC'}

# ─── data.json: overrides + extensions ───
def load_doc():
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
            if isinstance(d, dict) and 'overrides' in d:
                return d
    return {'overrides': {}, 'extensions': {}, 'cell_types': {}, 'undo_stack': [], 'mintage': {}, 'image_links': {}}

def save_doc(d):
    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

doc = load_doc()
if 'mintage' not in doc: doc['mintage'] = {}
if 'image_links' not in doc: doc['image_links'] = {}
# overrides: standard cell ref overrides (like "B3": "✔")
# extensions: {"A": {"Österreich": ["2027", "2028"]}, ...}
overrides = doc.get('overrides', {})
extensions = doc.get('extensions', {})
cell_types = doc.get('cell_types', {})
undo_stack = doc.get('undo_stack', [])
mintage_data = doc.get('mintage', {})
image_links = doc.get('image_links', {})

# ─── Load mintage from Google Sheet ───
MINTAGE_GIDS = {'Österreich': 536134290, 'Italien': 1836387929}
MINTAGE_SHEET_NAMES = {'Frankreich': 'France'}  # sheet name fallback when no GID available
MINTAGE_BLOCK = {'Österreich': 'A', 'Italien': 'AC', 'Frankreich': 'A'}
COUNTRY_TO_EC = {'Österreich': 'Austria', 'Italien': 'Italy', 'Frankreich': 'France'}
EC_BASE = 'https://www.eurocollection.co.uk'
# Google Sheet CSV columns (2-12) mapped to denomination labels (same for all blocks)
GS_DENOMS = ['1c','2c','5c','10c','20c','50c','E1','E2','E2 CC 1','E2 CC 2','E2 CC 3']

def block_col_map(bl):
    year_letter = YEAR_COL[bl]
    # Find the 0-based index of year_letter in cols_letters
    yi = cols_letters.index(year_letter)
    # Denom cols: 8 letters starting after year col
    den_start = yi + 1
    den_cols = {}
    for i in range(8):
        den_cols[i + 2] = cols_letters[den_start + i]
    # CC cols: 3 letters after den + inner-gap (skip 1)
    cc_start = den_start + 9
    for i in range(3):
        den_cols[i + 10] = cols_letters[cc_start + i]
    return den_cols

def format_mintage_val(raw):
    raw = raw.strip()
    clean = raw.replace('.', '').replace(',', '')
    if clean.isdigit():
        n = int(clean)
        return f'{n:,}'.replace(',', '.')
    return raw

def load_mintage_sheet(country_name):
    import urllib.request, csv, io
    gid = MINTAGE_GIDS.get(country_name)
    sheet_name = MINTAGE_SHEET_NAMES.get(country_name)
    if not gid and not sheet_name: return {}, {}
    bl = MINTAGE_BLOCK.get(country_name, 'A')
    ec_name = COUNTRY_TO_EC.get(country_name, country_name)
    gs_map = block_col_map(bl)
    doc_id = '1lGbzcTmMfzQjE-7ENMhrSMpMlu859fYCAqH8juDhb40'
    if gid:
        url = f'https://docs.google.com/spreadsheets/d/{doc_id}/export?format=csv&gid={gid}'
    else:
        url = f'https://docs.google.com/spreadsheets/d/{doc_id}/gviz/tq?tqx=out:csv&sheet={urllib.request.quote(sheet_name)}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        raw_text = resp.read().decode('utf-8')
    except:
        return {}, {}
    rows = list(csv.reader(io.StringIO(raw_text)))
    out_m = {}
    out_l = {}
    for ri, parts in enumerate(rows):
        if len(parts) < 13: continue
        year = parts[1].strip()
        if not year.isdigit(): continue
        bl_info = block_countries.get(bl, [])
        found_row = None
        for (cr, cn) in bl_info:
            if cn != country_name: continue
            nxt = bl_info[bl_info.index((cr,cn))+1][0] if bl_info.index((cr,cn))+1 < len(bl_info) else MAX_ROW + 1
            for dr in range(cr + 2, nxt):
                yr = base_data.get(YEAR_COL[bl] + str(dr), '')
                if yr == year:
                    found_row = dr
                    break
            break
        if not found_row:
            yr_idx = int(year) - 2002
            found_row = 3 + yr_idx
        for gs_col, ex_col in gs_map.items():
            raw = parts[gs_col].strip() if gs_col < len(parts) else ''
            if not raw: continue
            ref = ex_col + str(found_row)
            out_m[ref] = format_mintage_val(raw)
            den = GS_DENOMS[gs_col - 2]
            if den and raw.upper() != 'N/A':
                img_path = f'{EC_BASE}/Euros/{ec_name}/{ec_name} {year} {den}.JPG'
                out_l[ref] = img_path
    return out_m, out_l

# Load mintage + image links
for _c in ['Österreich', 'Italien', 'Frankreich']:
    _m, _l = load_mintage_sheet(_c)
    mintage_data.update(_m)
    image_links.update(_l)

def merge_data():
    d = dict(base_data)
    d.update(overrides)
    return d

# ─── Segments: groups of countries sharing a row range ───
# Each segment: (start_row, [(block, country_name)])
SEGMENTS = [
    (1,   [('A', 'Österreich'), ('O', ''),            ('AC', 'Italien')]),
    (29,  [('A', 'Frankreich'), ('O', 'Spanien'),      ('AC', 'Finnland')]),
    (61,  [('A', 'Belgien'),    ('O', 'Niederlande'),   ('AC', 'Luxemburg')]),
    (94,  [('A', 'Irland'),     ('O', 'Griechenland'),  ('AC', 'Portugal')]),
    (124, [('A', 'Slowenien'),  ('O', 'Malta'),         ('AC', 'Zypern')]),
    (148, [('A', 'Slowakei'),   ('O', 'Estland'),       ('AC', 'Lettland/Latvia')]),
    (172, [('A', 'Litauen/Lietuva'), ('O', 'Kroatien'), ('AC', 'Andorra')]),
    (180, [('O', 'Bulgarien')]),
    (189, [('A', 'San Marino'), ('O', 'Monaca'),       ('AC', 'Vatikan')]),
]

# Enrich segments with end row + last-real-data-row per block
segments = []
for idx, (start, entries) in enumerate(SEGMENTS):
    end = SEGMENTS[idx + 1][0] - 1 if idx + 1 < len(SEGMENTS) else MAX_ROW
    last_data = {}
    for bl, cname in entries:
        if not cname:
            continue
        found = start + 1
        for r in range(end, start + 2, -1):
            if base_data.get(YEAR_COL[bl] + str(r), ''):
                found = r
                break
        last_data[bl] = found
    segments.append({'start': start, 'end': end, 'entries': entries, 'last_data': last_data})

# ─── Generate HTML ───
def generate_html():
    data = merge_data()

    h = f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MünzApp</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js" crossorigin="anonymous"></script>

<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Arial,Calibri,sans-serif;font-size:8pt;padding:10px}}
table{{border-collapse:collapse;white-space:nowrap;table-layout:fixed;width:{total_w:.1f}px}}
td{{border:1px solid #000;padding:1px 3px;text-align:center;vertical-align:middle;font-size:8pt;font-family:Arial;overflow:hidden;height:18px}}
.c-country{{font-family:Calibri;font-size:10pt;font-weight:700;font-style:italic;padding:0;overflow:visible;height:auto}}
.c-country-inner{{display:flex;align-items:center;width:100%;padding:2px 6px;box-sizing:border-box}}
.c-name{{flex:1;text-align:center}}
.c-left-btns{{display:flex;gap:3px;flex-shrink:0}}
.c-country .info-btn{{flex-shrink:0;margin-left:0}}
.c-right-placeholder{{display:inline-block;flex-shrink:0}}
.gap td{{border:none!important}}
.gap{{background:transparent;border:none!important}}
.inner-gap{{background:transparent;border:none!important}}
.add-year{{font-size:7pt;padding:1px 12px;cursor:pointer;margin-left:6px;border:1px solid #999;border-radius:3px;background:#eee;color:#333;user-select:none;vertical-align:middle}}
.add-year:hover{{background:#ddd}}

.msg{{font-size:8pt;padding:4px 8px;margin:4px 0;border-radius:3px;display:none}}
.msg-ok{{background:#d4edda;color:#155724}}
.msg-err{{background:#f8d7da;color:#721c24}}
.undo-btn{{font-size:8pt;padding:4px 12px;cursor:pointer;border:1px solid #999;border-radius:3px;background:#fff3cd;color:#856404;user-select:none;margin-bottom:6px;display:inline-block}}
.undo-btn:hover{{background:#ffe8a1}}
.undo-btn:disabled{{opacity:0.4;cursor:default}}
.edit-btn{{font-size:8pt;padding:4px 12px;cursor:pointer;border:1px solid #999;border-radius:3px;background:#e8f0fe;color:#1a73e8;user-select:none;margin-bottom:6px;display:inline-block;margin-left:6px}}
.edit-btn:hover{{background:#d2e3fc}}
.edit-btn.active{{background:#1a73e8;color:#fff;border-color:#1a73e8}}
.edit-country-btn{{font-size:7pt;padding:1px 12px;cursor:pointer;margin-left:3px;border:1px solid #999;border-radius:3px;background:#e8f0fe;color:#1a73e8;user-select:none;vertical-align:middle}}
.edit-country-btn:hover{{background:#d2e3fc}}
.edit-country-btn.active{{background:#1a73e8;color:#fff;border-color:#1a73e8}}

.ctx-menu{{position:fixed;background:#fff;border:1px solid #888;border-radius:4px;box-shadow:2px 2px 8px rgba(0,0,0,0.2);padding:4px;z-index:999;display:none;font-size:8pt}}
.ctx-item{{padding:3px 8px;cursor:pointer;border-radius:2px;white-space:nowrap;display:inline-block;margin:1px}}
.ctx-item:hover{{outline:1px solid #666}}
.ctx-swatch{{display:inline-block;width:10px;height:10px;border:1px solid #999;margin-right:4px;vertical-align:middle}}
.ctx-highlight{{outline:2px solid #1a73e8;outline-offset:-1px}}
.export-btn{{font-size:8pt;padding:4px 12px;cursor:pointer;border:1px solid #999;border-radius:3px;background:#fff;color:#333;user-select:none;margin-left:6px;display:inline-block}}
.export-btn:hover{{background:#f0f0f0}}
.info-btn{{font-size:7pt;padding:1px 12px;cursor:pointer;margin-left:3px;border:1px solid #999;border-radius:3px;background:#e8f0fe;color:#1a73e8;user-select:none;vertical-align:middle}}
.info-btn:hover{{background:#d2e3fc}}
.info-btn.active{{background:#1a73e8;color:#fff;border-color:#1a73e8}}
.info-modal{{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:#fff;border:2px solid #1a73e8;border-radius:6px;padding:16px;z-index:1000;font-size:9pt;min-width:280px;box-shadow:0 4px 20px rgba(0,0,0,0.3);display:none}}
.info-modal h3{{margin:0 0 8px 0;font-size:10pt;color:#1a73e8}}
.info-modal label{{display:block;margin:4px 0;font-size:8pt}}
.info-modal input{{width:100%;box-sizing:border-box;padding:3px 5px;font-size:8pt;border:1px solid #999;border-radius:3px}}
.info-modal a{{color:#1a73e8}}
.info-modal .close-btn{{float:right;cursor:pointer;font-size:10pt;font-weight:700;color:#666;border:none;background:none;padding:0 4px}}
.info-modal .close-btn:hover{{color:#000}}
.info-modal-overlay{{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.3);z-index:999;display:none}}</style>
</head>
<body>
<div id="msg" class="msg"></div>
<div style="margin-bottom:6px">
<span class="undo-btn" id="undoBtn">↶ Letzte Aktion rückgängig</span>
<span class="export-btn" id="exportPdfBtn">📄 PDF</span>
<span class="export-btn" id="exportXlsxBtn">📊 Excel</span>
</div>
<div class="ctx-menu" id="ctxMenu"></div>
<div class="info-modal-overlay" id="infoOverlay"></div>
<div class="info-modal" id="infoModal">
  <button class="close-btn" id="infoClose">&times;</button>
  <h3 id="infoTitle">Münze</h3>
  <label>Auflagezahl:</label>
  <input type="text" id="infoMintage" placeholder="z.B. 378.400.000">
  <div style="margin-top:6px">
    <a href="#" id="infoLinkBtn" target="_blank" style="font-size:9pt;font-weight:bold;color:#1a73e8">Bild öffnen &nearr;</a>
  </div>
  <div style="margin-top:4px">
    <span id="infoShowLinkToggle" style="font-size:7pt;cursor:pointer;color:#666;text-decoration:underline">Link anzeigen</span>
  </div>
  <div id="infoLinkWrap" style="display:none;margin-top:4px">
    <input type="text" id="infoLink" placeholder="https://...">
  </div>
  <div style="margin-top:8px;text-align:right">
    <button id="infoSave" style="font-size:8pt;padding:4px 12px;cursor:pointer;border:1px solid #1a73e8;border-radius:3px;background:#1a73e8;color:#fff">Speichern</button>
  </div>
</div>
<table>
'''

    for cl in cols_letters:
        px = max(col_widths[cl] * 7.5, 6)
        h += f'<col style="width:{px:.1f}px;min-width:{px:.1f}px">\n'

    # Precompute: for each segment, the global last real data row across all blocks
    seg_last = {}  # seg_start -> global last data row
    for seg in segments:
        s = seg['start']
        if seg['last_data']:
            seg_last[s] = max(seg['last_data'].values())
        else:
            seg_last[s] = s + 1

    # Precompute row -> country name per block
    row_to_country = {}
    for _bl in ['A', 'O', 'AC']:
        for _i, (_cr, _cname) in enumerate(block_countries[_bl]):
            _next = block_countries[_bl][_i+1][0] if _i+1 < len(block_countries[_bl]) else MAX_ROW + 1
            for _r in range(_cr, _next):
                row_to_country[(_r, _bl)] = _cname

    # Render base rows
    for r in range(1, MAX_ROW + 1):
        h += '<tr>'
        for ci, cl in enumerate(cols_letters):
            ref = cl + str(r)
            if ref in merges and merges[ref].get('skip'):
                continue

            cs, rs, val = 1, 1, data.get(ref, '')
            if ref in merges and not merges[ref].get('skip'):
                cs = merges[ref]['cs']; rs = merges[ref]['rs']

            cls = ''
            bg = None
            fc = None
            bl = col_to_block[cl]
            rtype = ''
            editable = False
            btn_btn = ''
            ct = None
            if bl and (col_types.get(cl) in ('den', 'cc') or cl == YEAR_COL.get(bl, '')):
                ct = cell_types.get(ref)

            if bl and r in block_row_type.get(bl, {}):
                rtype = block_row_type[bl][r]
                if rtype == 'country':
                    cls = 'c-country'
                    bg = 'FF543E'
                    fc = '000000'
                    if (r, bl) in COUNTRY_HEADERS:
                        val = COUNTRY_HEADERS[(r, bl)]
                        name = COUNTRY_HEADERS[(r, bl)]
                        if name:
                            if cl == YEAR_COL[bl]:
                                _left = f'<span class="c-left-btns"><span class="add-year" data-block="{bl}" data-country="{htmlmod.escape(name)}">+</span><span class="edit-country-btn" data-block="{bl}" data-country="{htmlmod.escape(name)}">✏️</span></span>'
                                _right = f'<span class="info-btn" data-country="{htmlmod.escape(name)}">ℹ️</span>' if (name in MINTAGE_GIDS or name in MINTAGE_SHEET_NAMES) else '<span class="c-right-placeholder"></span>'
                                btn_btn = f'<div class="c-country-inner">{_left}<span class="c-name">{htmlmod.escape(name)}</span>{_right}</div>'
                        else:
                            btn_btn = ''
                    else:
                        btn_btn = ''
                elif rtype == 'colheader':
                    if val in ('1', '2'):
                        val += ' €'
                elif rtype == 'data':
                    bg = fills.get(ref)

            if bl and rtype == 'data':
                year_ref = YEAR_COL[bl] + str(r)
                if year_ref not in data:
                    cls = 'gap'
                    bg = None
                    fc = None
                    val = ''

            if col_types[cl] in ('gap', 'inner-gap'):
                cls = col_types[cl]
                bg = None
                fc = None

            if rtype == 'data' and cls != 'gap' and col_types.get(cl) in ('den', 'cc'):
                editable = True

            # x-type cell: force value to ✕, never editable
            if ct == 'x':
                val = '✕'
                editable = False

            # Cell type override (user-set background)
            cell_type_color_map = {
                'green': 'C5DEB5', 'blue': '8EAADB', 'orange': 'FF8C42',
                'yellow': 'FFE598', 'nifc': 'FFC7CE', 'x': 'FFC7CE',
            }
            if ct and ct in cell_type_color_map:
                bg = cell_type_color_map[ct]

            sty = ''
            if ct == 'x':
                sty = 'background:#FFC7CE;'
            elif val and '✕' in val:
                sty = 'background:#FFC7CE;'
            elif bg:
                sty += f'background:#{bg};'
                if fc: sty += f'color:#{fc};'
            elif not bg and ref in fills and col_types[cl] not in ('gap', 'inner-gap'):
                sty += f'background:#{fills[ref]};'
                if is_dark(fills[ref]): sty += 'color:#FFF;'

            ev = htmlmod.escape(val) if val else ('&nbsp;' if cls in ('gap', 'inner-gap') else '')
            if btn_btn:
                ev = btn_btn
            colspan = f' colspan="{cs}"' if cs > 1 else ''
            rowspan = f' rowspan="{rs}"' if rs > 1 else ''
            cc = f' class="{cls}"' if cls else ''
            if editable or ct == 'x':
                _cname = htmlmod.escape(row_to_country.get((r, bl), '')) if bl else ''
                _bl2 = bl or ''
                dr = f' data-ref="{ref}" data-country="{_cname}" data-block="{_bl2}"'
            else:
                dr = ''
            dct = f' data-ct="{ct}"' if ct else ''
            xlocked = ' data-xlocked="1"' if ct == 'x' else ''
            ss = f' style="{sty}"' if sty else ''
            dm = ''
            dl = ''
            if ref in mintage_data:
                dm = f' data-mintage="{htmlmod.escape(format_mintage_val(mintage_data[ref]))}"'
            if ref in image_links:
                dl = f' data-link="{htmlmod.escape(image_links[ref])}"'
            h += f'<td{cc}{colspan}{rowspan}{ss}{dr}{dct}{xlocked}{dm}{dl}>{ev}</td>'
        h += '</tr>\n'

        # Check if this row is the global last real data row of any segment
        for seg in segments:
            s = start_r = seg['start']
            if seg_last.get(s) != r:
                continue
            # Collect all extension years from ALL blocks in this segment
            all_ext = {}  # year -> [(block, country_name)]
            for bl, cname in seg['entries']:
                if not cname:
                    continue
                for ey in extensions.get(bl, {}).get(cname, []):
                    all_ext.setdefault(ey, []).append((bl, cname))
            if not all_ext:
                continue

            # Determine base ext row number (unique per segment)
            seg_idx = next(i for i, (st, _) in enumerate(SEGMENTS) if st == s)
            base_ext_row = EXT_OFFSET + s

            for ext_idx, ey in enumerate(sorted(all_ext.keys(), key=lambda y: int(y) if y.isdigit() else y)):
                ext_row = base_ext_row + ext_idx
                # Build a map: block -> True if this block has this year
                ext_blocks = set(bl for bl, _ in all_ext[ey])
                h += '<tr>'
                for ci2, cl2 in enumerate(cols_letters):
                    bl2 = col_to_block[cl2]
                    ct2 = col_types.get(cl2, '')
                    if ct2 in ('gap', 'inner-gap'):
                        h += f'<td class="{ct2}">&nbsp;</td>'
                    elif bl2 and bl2 in ext_blocks:
                        if cl2 == YEAR_COL[bl2]:
                            h += f'<td>{htmlmod.escape(ey)}</td>'
                        elif ct2 in ('den', 'cc'):
                            ref2 = cl2 + str(ext_row)
                            val2 = data.get(ref2, '')
                            ev2 = htmlmod.escape(val2) if val2 else ''
                            h += f'<td data-ref="{ref2}">{ev2}</td>'
                        else:
                            h += '<td></td>'
                    else:
                        h += '<td class="gap">&nbsp;</td>'
                h += '</tr>\n'

    h += '''</table>
<script>
(function() {
  const msgDiv = document.getElementById('msg');
  function showMsg(text, isErr) {
    msgDiv.textContent = text;
    msgDiv.className = 'msg ' + (isErr ? 'msg-err' : 'msg-ok');
    msgDiv.style.display = 'block';
    setTimeout(function(){ msgDiv.style.display = 'none'; }, 3000);
  }

  // ───── Per-country edit mode ─────
  let activeEditCountries = new Set();
  const ctxMenu = document.getElementById('ctxMenu');

  // Context menu items
  const CTX_ITEMS = [
    {type:'green', label:'>5 Mio',     color:'#C5DEB5'},
    {type:'blue',  label:'>2M–5M',    color:'#8EAADB'},
    {type:'orange',label:'>1M–2M',    color:'#FF8C42'},
    {type:'yellow',label:'≤1M',       color:'#FFE598'},
    {type:'nifc',  label:'NIFC',      color:'#FFC7CE'},
    {type:'x',     label:'✕ Nie gepr.',color:'#FFC7CE'},
    {type:'nodata',label:'Keine Daten',color:'#ffffff'},
  ];
  let ctxTarget = null; // the td that was clicked

  function buildCtxMenu() {
    let html = '';
    CTX_ITEMS.forEach(function(item) {
      html += '<span class="ctx-item" data-ctype="' + item.type + '">' +
        '<span class="ctx-swatch" style="background:' + item.color + '"></span>' +
        item.label + '</span>';
    });
    ctxMenu.innerHTML = html;
    ctxMenu.querySelectorAll('.ctx-item').forEach(function(el) {
      el.addEventListener('click', function(e) {
        e.stopPropagation();
        const ctype = this.getAttribute('data-ctype');
        if (ctxTarget) {
          const ref = ctxTarget.getAttribute('data-ref');
          if (ref) {
            // Apply visually immediately (optimistic)
            const colorMap = {'green':'#C5DEB5','blue':'#8EAADB','orange':'#FF8C42','yellow':'#FFE598','nifc':'#FFC7CE','x':'#FFC7CE','nodata':'#ffffff'};
            if (ctype === 'x') {
              ctxTarget.textContent = '✕';
              ctxTarget.setAttribute('data-xlocked','1');
              ctxTarget.contentEditable = 'false';
              ctxTarget.style.background = '#FFC7CE';
            } else if (ctype === 'nodata') {
              ctxTarget.removeAttribute('data-xlocked');
              ctxTarget.style.background = '';
              ctxTarget.style.color = '';
              if (ctxTarget.textContent === '✕') ctxTarget.textContent = '';
            } else {
              ctxTarget.removeAttribute('data-xlocked');
              if (ctxTarget.textContent === '✕' && ctype !== 'x') {
                ctxTarget.textContent = '';
              }
              ctxTarget.style.background = colorMap[ctype] || '';
              ctxTarget.style.color = '';
            }
            ctxTarget.setAttribute('data-ct', ctype);
            // Send type change to server
            const body = {};
            body[ref] = ctype;
            fetch('/api/cell-types', {
              method: 'PATCH',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify(body)
            }).then(function(r){ return r.json(); }).then(function(j){
              if (j.ok) {
                showMsg('Typ geändert: ' + ctype);
              } else {
                showMsg('Fehler: ' + (j.error || ''), true);
              }
            });
          }
        }
        hideCtx();
      });
    });
  }
  buildCtxMenu();

  function showCtx(td, x, y) {
    ctxTarget = td;
    ctxTarget.classList.add('ctx-highlight');
    ctxMenu.style.left = Math.min(x, window.innerWidth - 220) + 'px';
    ctxMenu.style.top = Math.min(y, window.innerHeight - 100) + 'px';
    ctxMenu.style.display = 'block';
  }
  function hideCtx() {
    ctxMenu.style.display = 'none';
    if (ctxTarget) ctxTarget.classList.remove('ctx-highlight');
    ctxTarget = null;
  }
  document.addEventListener('click', function(e) {
    if (!e.target.closest('.ctx-menu')) hideCtx();
  });

  function setEditModeForCountry(block, country, on) {
    const key = block + ':' + country;
    if (on) activeEditCountries.add(key); else activeEditCountries.delete(key);
    document.querySelectorAll('[data-ref][data-block="' + block + '"][data-country="' + CSS.escape(country) + '"]').forEach(function(td){
      if (td.getAttribute('data-xlocked')) {
        td.contentEditable = 'false';
      } else {
        td.contentEditable = on ? 'false' : 'true';
      }
    });
  }

  document.querySelectorAll('.edit-country-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      const block = this.getAttribute('data-block');
      const country = this.getAttribute('data-country');
      const key = block + ':' + country;
      const on = !activeEditCountries.has(key);
      setEditModeForCountry(block, country, on);
      this.classList.toggle('active', on);
    });
  });

  // ───── Info mode (per country) ─────
  let infoMode = false;
  let infoCountry = null;

  function setInfoModeCells(on) {
    document.querySelectorAll('[data-ref]').forEach(function(td) {
      if (td.getAttribute('data-xlocked')) { td.contentEditable = 'false'; return; }
      const _key = (td.getAttribute('data-block') || '') + ':' + (td.getAttribute('data-country') || '');
      if (activeEditCountries.has(_key)) return; // keep ctx-menu mode unchanged
      td.contentEditable = on ? 'false' : 'true';
    });
  }

  document.querySelectorAll('.info-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      const country = this.getAttribute('data-country');
      if (infoMode && infoCountry === country) {
        // Toggle off
        infoMode = false;
        infoCountry = null;
        document.querySelectorAll('.info-btn').forEach(function(b){ b.classList.remove('active'); });
        setInfoModeCells(false);
        return;
      }
      // Activate info mode for this country
      infoMode = true;
      infoCountry = country;
      document.querySelectorAll('.info-btn').forEach(function(b){ b.classList.remove('active'); });
      this.classList.add('active');
      setInfoModeCells(true);
      showMsg('Info-Modus für ' + country + ' aktiv. Klicke auf eine Münze.');
    });
  });

  // Info modal
  const infoModal = document.getElementById('infoModal');
  const infoOverlay = document.getElementById('infoOverlay');
  let infoRef = null;

  function showInfoModal(ref, country, year, denom, mintage, link) {
    infoRef = ref;
    document.getElementById('infoTitle').textContent = country + ' ' + year + ' ' + denom;
    document.getElementById('infoMintage').value = mintage || '';
    var linkBtn = document.getElementById('infoLinkBtn');
    linkBtn.href = link || '#';
    linkBtn.style.display = link ? 'inline' : 'none';
    document.getElementById('infoLink').value = link || '';
    document.getElementById('infoLinkWrap').style.display = 'none';
    infoModal.style.display = 'block';
    infoOverlay.style.display = 'block';
  }
  function hideInfoModal() {
    infoModal.style.display = 'none';
    infoOverlay.style.display = 'none';
    infoRef = null;
  }
  document.getElementById('infoClose').addEventListener('click', hideInfoModal);
  infoOverlay.addEventListener('click', hideInfoModal);
  document.getElementById('infoShowLinkToggle').addEventListener('click', function() {
    var wrap = document.getElementById('infoLinkWrap');
    wrap.style.display = wrap.style.display === 'none' ? 'block' : 'none';
    this.textContent = wrap.style.display === 'block' ? 'Link verbergen' : 'Link anzeigen';
  });

  document.getElementById('infoSave').addEventListener('click', function() {
    if (!infoRef) return;
    var mintage = document.getElementById('infoMintage').value.trim();
    var link = document.getElementById('infoLink').value.trim();
    var body = {};
    body[infoRef] = {mintage: mintage, link: link};
    fetch('/api/coin-info', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    }).then(function(r){ return r.json(); }).then(function(j){
      if (j.ok) {
        showMsg('Gespeichert');
        hideInfoModal();
      } else {
        showMsg('Fehler: ' + (j.error || ''), true);
      }
    });
  });

  // Update td click to also handle info mode
  // (the click handler is defined below, we'll modify it)

  // ───── Autosave for editable cells ─────
  let saveTimer = null;
  const pending = {};
  function savePending() {
    const keys = Object.keys(pending);
    if (!keys.length) return;
    const data = JSON.parse(JSON.stringify(pending));
    Object.keys(pending).forEach(k => delete pending[k]);
    fetch('/api/cells', {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    }).then(r => r.json()).then(j => {
      if (j.ok) showMsg('Gespeichert (' + j.saved + ')');
    }).catch(() => {});
  }
  function scheduleSave(ref, value) {
    pending[ref] = value;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(savePending, 400);
  }

  document.querySelectorAll('[data-ref]').forEach(function(td) {
    const xlocked = td.getAttribute('data-xlocked');
    // x-locked cells are never editable
    if (xlocked) {
      td.contentEditable = 'false';
    } else {
      td.contentEditable = 'true';
    }
    td.addEventListener('focus', function() {
      this._origVal = this.textContent.trim();
    });
    td.addEventListener('blur', function() {
      const _key = (this.getAttribute('data-block') || '') + ':' + (this.getAttribute('data-country') || '');
      if (activeEditCountries.has(_key)) return;  // don't save while in edit mode
      // If cell was x-locked, revert value
      if (this.getAttribute('data-xlocked')) {
        this.textContent = '✕';
        return;
      }
      const ref = this.getAttribute('data-ref');
      let val = this.textContent.trim();
      if (!val) { this.innerHTML = '&nbsp;'; val = ''; }
      if (ref && val !== (this._origVal || '')) scheduleSave(ref, val);
    });
    td.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        this.blur();
      }
    });
    td.addEventListener('paste', function(e) {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData('text/plain');
      document.execCommand('insertText', false, text);
    });
    // In edit mode, click opens context menu. In info mode, opens info modal.
    td.addEventListener('click', function(e) {
      if (!this.getAttribute('data-ref')) return;
      const _cellKey = (this.getAttribute('data-block') || '') + ':' + (this.getAttribute('data-country') || '');
      if (activeEditCountries.has(_cellKey)) {
        e.preventDefault();
        e.stopPropagation();
        showCtx(this, e.clientX, e.clientY);
      } else if (infoMode) {
        e.preventDefault();
        e.stopPropagation();
        var ref = this.getAttribute('data-ref');
        var country = infoCountry;
        // Determine year and denomination from the cell context
        var row = this.parentElement;
        var yrEl = row.querySelector('td:first-child');
        var year = yrEl ? yrEl.textContent.trim() : '';
        // Denom from column header
        var colIdx = Array.prototype.indexOf.call(row.children, this);
        var headerRow = document.querySelector('tr:nth-child(2)');
        var denom = '';
        if (headerRow && headerRow.children[colIdx]) {
          denom = headerRow.children[colIdx].textContent.trim();
        }
        // Look up mintage + link from data attributes if present, or from initial server data
        var mintage = this.getAttribute('data-mintage') || '';
        var link = this.getAttribute('data-link') || '';
        showInfoModal(ref, country, year, denom, mintage, link);
      }
    });
  });

  // Undo button
  document.getElementById('undoBtn').addEventListener('click', function() {
    this.textContent = '↶ wird rückgängig gemacht...';
    this.style.pointerEvents = 'none';
    fetch('/api/undo', {method: 'POST'})
      .then(r => r.json())
      .then(j => {
        if (j.ok) {
          showMsg('Letzte Aktion rückgängig gemacht. Seite wird neu geladen...');
          setTimeout(function(){ location.reload(); }, 800);
        } else {
          showMsg('Fehler: ' + (j.error || 'unbekannt'), true);
          this.textContent = '↶ Letzte Aktion rückgängig';
          this.style.pointerEvents = '';
        }
      })
      .catch(function(e){ showMsg('Fehler: ' + e, true); this.textContent = '↶ Letzte Aktion rückgängig'; this.style.pointerEvents = ''; });
  });

  // ───── Export buttons ─────
  document.getElementById('exportPdfBtn').addEventListener('click', function() {
    showMsg('PDF wird erstellt...');
    const el = document.querySelector('table');
    if (!el) return;
    const opt = {
      margin:       5,
      filename:     'muenzapp.pdf',
      image:        {type: 'jpeg', quality: 0.98},
      html2canvas:  {scale: 2, useCORS: true, letterRendering: true, logging: false},
      jsPDF:        {unit: 'mm', format: 'a3', orientation: 'landscape'}
    };
    html2pdf().set(opt).from(el).save().then(function(){
      showMsg('PDF exportiert');
    }).catch(function(e){
      showMsg('Fehler: ' + e, true);
    });
  });

  document.getElementById('exportXlsxBtn').addEventListener('click', function() {
    showMsg('Excel wird erstellt...');
    window.location.href = '/api/export/xlsx';
  });

  // Add Year button logic
  document.querySelectorAll('.add-year').forEach(btn => {
    btn.addEventListener('click', function() {
      const block = this.getAttribute('data-block');
      const country = this.getAttribute('data-country');
      if (!block || !country) return;
      fetch('/api/next-year?block=' + encodeURIComponent(block) + '&country=' + encodeURIComponent(country))
        .then(r => r.json())
        .then(j => {
          const year = prompt('Jahr eingeben f\u00fcr ' + country + ':', j.nextYear || '2027');
          if (!year) return;
          return fetch('/api/add-year', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({block: block, country: country, year: year})
          });
        })
        .then(r => r && r.json())
        .then(j => {
          if (j && j.ok) {
            showMsg('Jahr ' + j.year + ' hinzugef\u00fcgt. Seite wird neu geladen...');
            setTimeout(function(){ location.reload(); }, 1000);
          } else if (j && j.error) {
            showMsg('Fehler: ' + j.error, true);
          }
        })
        .catch(function(e){ showMsg('Fehler: ' + e, true); });
    });
  });

})();
</script>
</body>
</html>'''

    return h

# ─── Routes ───

@app.route('/')
@app.route('/index.html')
def index():
    return generate_html()

@app.route('/api/cells', methods=['PATCH'])
def patch_cells():
    global overrides, doc, undo_stack
    updates = request.get_json(silent=True) or {}
    data = merge_data()
    for ref, new_val in updates.items():
        prev = data.get(ref, '')
        if prev != new_val:
            undo_stack.append({'type': 'cell', 'ref': ref, 'prev': prev})
    overrides.update(updates)
    doc['overrides'] = overrides
    doc['undo_stack'] = undo_stack
    save_doc(doc)
    return jsonify({'ok': True, 'saved': len(updates)})

@app.route('/api/data', methods=['GET'])
def get_data():
    return jsonify(merge_data())

@app.route('/api/cell-types', methods=['PATCH'])
def patch_cell_types():
    global cell_types, doc, undo_stack
    updates = request.get_json(silent=True) or {}
    for ref, new_ct in updates.items():
        prev = cell_types.get(ref, '')
        if prev != new_ct:
            undo_stack.append({'type': 'cell-type', 'ref': ref, 'prev': prev, 'new': new_ct})
    cell_types.update(updates)
    doc['cell_types'] = cell_types
    doc['undo_stack'] = undo_stack
    save_doc(doc)
    return jsonify({'ok': True, 'saved': len(updates)})

@app.route('/api/add-year', methods=['POST'])
def add_year():
    global extensions, doc, undo_stack
    body = request.get_json(silent=True) or {}
    bl = body.get('block')
    cname = body.get('country')
    year = body.get('year', '')
    if not bl or not cname or not year:
        return jsonify({'error': 'Missing block, country, or year'}), 400

    found = any(cn == cname for (_, b), cn in COUNTRY_HEADERS.items() if b == bl)
    if not found:
        return jsonify({'error': 'Country not found in this block'}), 404

    ebl = extensions.setdefault(bl, {})
    elist = ebl.setdefault(cname, [])
    if year in elist:
        return jsonify({'error': 'Year already added'}), 409
    undo_stack.append({'type': 'add-year', 'block': bl, 'country': cname, 'year': year})
    elist.append(year)
    elist.sort(key=lambda y: int(y) if y.isdigit() else y)
    doc['extensions'] = extensions
    doc['undo_stack'] = undo_stack
    save_doc(doc)
    return jsonify({'ok': True, 'year': year})

@app.route('/api/undo', methods=['POST'])
def undo():
    global overrides, extensions, doc, undo_stack
    if not undo_stack:
        return jsonify({'error': 'Nothing to undo'}), 400
    action = undo_stack.pop()
    if action['type'] == 'cell':
        ref = action['ref']
        prev = action['prev']
        if prev:
            overrides[ref] = prev
        elif ref in overrides:
            del overrides[ref]
        doc['overrides'] = overrides
    elif action['type'] == 'add-year':
        bl, cname, year = action['block'], action['country'], action['year']
        elist = extensions.get(bl, {}).get(cname, [])
        if year in elist:
            elist.remove(year)
        if not elist:
            extensions.get(bl, {}).pop(cname, None)
        if not extensions.get(bl):
            extensions.pop(bl, None)
        doc['extensions'] = extensions
    elif action['type'] == 'cell-type':
        ref = action['ref']
        prev = action['prev']
        if prev:
            cell_types[ref] = prev
        elif ref in cell_types:
            del cell_types[ref]
        doc['cell_types'] = cell_types
    doc['undo_stack'] = undo_stack
    save_doc(doc)
    return jsonify({'ok': True, 'undone': action['type']})

@app.route('/api/next-year', methods=['GET'])
def next_year():
    bl = request.args.get('block', '')
    cname = request.args.get('country', '')
    max_y = 0
    # Check base data
    for i, (cr, cn2) in enumerate(block_countries.get(bl, [])):
        if cn2 == cname:
            next_cr = block_countries[bl][i+1][0] if i+1 < len(block_countries[bl]) else MAX_ROW + 1
            for dr in range(cr + 2, next_cr):
                yv = base_data.get(YEAR_COL[bl] + str(dr), '')
                if yv and yv.isdigit():
                    max_y = max(max_y, int(yv))
            break
    # Check extensions
    for ey in extensions.get(bl, {}).get(cname, []):
        if ey.isdigit():
            max_y = max(max_y, int(ey))
    return jsonify({'nextYear': str(max_y + 1) if max_y else '2027'})

@app.route('/api/coin-info', methods=['PATCH'])
def patch_coin_info():
    global mintage_data, image_links, doc
    updates = request.get_json(silent=True) or {}
    mintage_data.update({k: v.get('mintage', '') for k, v in updates.items() if isinstance(v, dict)})
    image_links.update({k: v.get('link', '') for k, v in updates.items() if isinstance(v, dict)})
    doc['mintage'] = mintage_data
    doc['image_links'] = image_links
    save_doc(doc)
    return jsonify({'ok': True})

@app.route('/api/export/xlsx', methods=['GET'])
def export_xlsx():
    data = merge_data()
    wb = Workbook()
    ws = wb.active
    ws.title = 'M\u00fcnzApp'

    # Column widths (approximate from col_widths)
    for ci, cl in enumerate(cols_letters, 1):
        w = max(col_widths[cl], 0.66)
        ws.column_dimensions[get_column_letter(ci)].width = w * 1.6

    # Styles
    thin_black = Border(left=Side(style='thin',color='000000'),
                        right=Side(style='thin',color='000000'),
                        top=Side(style='thin',color='000000'),
                        bottom=Side(style='thin',color='000000'))
    def cell_fill(hex_color):
        return PatternFill(start_color=hex_color, end_color=hex_color, fill_type='solid') if hex_color else PatternFill(fill_type=None)
    cell_type_fills = {
        'green':  cell_fill('C5DEB5'),
        'blue':   cell_fill('8EAADB'),
        'orange': cell_fill('FF8C42'),
        'yellow': cell_fill('FFE598'),
        'nifc':   cell_fill('FFC7CE'),
        'x':      cell_fill('FFC7CE'),
        'nodata': PatternFill(fill_type=None),
    }
    red_fill = cell_fill('FF543E')
    cen = Alignment(horizontal='center', vertical='center', wrapText=False)
    left_ali = Alignment(horizontal='left', vertical='center', wrapText=False)

    row_num = 0
    for r in range(1, MAX_ROW + 1):
        row_num += 1
        empty = True
        for ci, cl in enumerate(cols_letters, 1):
            ref = cl + str(r)
            if ref in merges and merges[ref].get('skip'):
                continue
            cs, rs = 1, 1
            if ref in merges and not merges[ref].get('skip'):
                cs = merges[ref]['cs']; rs = merges[ref]['rs']
            val = data.get(ref, '')
            bl = col_to_block[cl]
            ct2 = col_types.get(cl, '')
            rtype = ''
            ct = None
            if bl and (ct2 in ('den', 'cc') or cl == YEAR_COL.get(bl, '')):
                ct = cell_types.get(ref)
            if bl and r in block_row_type.get(bl, {}):
                rtype = block_row_type[bl][r]
            cell = ws.cell(row=row_num, column=ci)
            cell.alignment = cen
            cell.border = thin_black
            if rtype == 'country':
                cell.value = val
                cell.fill = red_fill
                cell.font = Font(bold=True, italic=True, size=10, name='Calibri')
                cell.alignment = left_ali
                if cs > 1 or rs > 1:
                    ws.merge_cells(start_row=row_num, start_column=ci,
                                   end_row=row_num + rs - 1, end_column=ci + cs - 1)
                empty = False
            elif rtype == 'colheader':
                if val in ('1', '2'):
                    val += ' \u20ac'
                cell.value = val
                cell.font = Font(size=8, name='Arial')
                empty = False
            elif rtype == 'data':
                if ct == 'x':
                    val = '\u2715'
                year_ref = YEAR_COL[bl] + str(r) if bl else ''
                is_gap = bool(bl and year_ref and year_ref not in data)
                if ct2 in ('gap', 'inner-gap') or is_gap:
                    cell.border = Border()
                    continue
                cell.value = val
                cell.font = Font(size=8, name='Arial')
                cell.alignment = cen
                if ct and ct in cell_type_fills:
                    cell.fill = cell_type_fills[ct]
                elif ref in fills:
                    cell.fill = cell_fill(fills[ref])
                empty = False
            else:
                if ct2 in ('gap', 'inner-gap'):
                    cell.border = Border()
                    continue
        if empty:
            blank = True
            for ci2, cl2 in enumerate(cols_letters, 1):
                ref2 = cl2 + str(r)
                bl2 = col_to_block[cl2]
                ct2 = col_types.get(cl2, '')
                if not bl2 or ct2 in ('gap', 'inner-gap'):
                    continue
                if ref2 in data and data[ref2].strip():
                    blank = False
                    break
            if blank:
                continue

    # Extension rows
    for seg in segments:
        s = seg['start']
        all_ext = {}
        for bl, cname in seg['entries']:
            if not cname: continue
            for ey in extensions.get(bl, {}).get(cname, []):
                all_ext.setdefault(ey, []).append((bl, cname))
        if not all_ext:
            continue
        seg_idx = next(i for i, (st, _) in enumerate(SEGMENTS) if st == s)
        base_ext_row = EXT_OFFSET + s
        for ext_idx, ey in enumerate(sorted(all_ext.keys(), key=lambda y: int(y) if y.isdigit() else y)):
            row_num += 1
            ext_row = base_ext_row + ext_idx
            ext_blocks = set(bl for bl, _ in all_ext[ey])
            for ci, cl in enumerate(cols_letters, 1):
                bl2 = col_to_block[cl]
                ct2 = col_types.get(cl, '')
                cell = ws.cell(row=row_num, column=ci)
                cell.alignment = cen
                cell.font = Font(size=8, name='Arial')
                if ct2 in ('gap', 'inner-gap'):
                    cell.border = Border()
                    continue
                if bl2 and bl2 in ext_blocks:
                    if cl == YEAR_COL[bl2]:
                        cell.value = ey
                        cell.border = thin_black
                    elif ct2 in ('den', 'cc'):
                        ref = cl + str(ext_row)
                        v = data.get(ref, '')
                        cell.value = v
                        cell.border = thin_black
                        if ref in fills:
                            cell.fill = cell_fill(fills[ref])
                        ct = cell_types.get(ref)
                        if ct and ct in cell_type_fills:
                            cell.fill = cell_type_fills[ct]
                else:
                    cell.border = Border()

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='muenzapp.xlsx')



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, debug=True)
