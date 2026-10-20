import json, html as htmlmod, re, os, io, urllib.request, datetime, hashlib, hmac
from flask import Flask, request, jsonify, send_file, session, redirect
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter

app = Flask(__name__)

@app.after_request
def nocache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, 'data.json')
MINTAGE_STATIC_PATH = os.path.join(BASE_DIR, 'mintage_static.json')
SHEET_ID = '1lGbzcTmMfzQjE-7ENMhrSMpMlu859fYCAqH8juDhb40'
SHEET_XLSX_URL = f'https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx'

DENOM_LABEL = {
    'B': '1c', 'C': '2c', 'D': '5c', 'E': '10c', 'F': '20c', 'G': '50c', 'H': '1\u20ac', 'I': '2\u20ac',
    'K': 'CC', 'L': 'CC', 'M': 'CC',
    'P': '1c', 'Q': '2c', 'R': '5c', 'S': '10c', 'T': '20c', 'U': '50c', 'V': '1\u20ac', 'W': '2\u20ac',
    'Y': 'CC', 'Z': 'CC', 'AA': 'CC',
    'AD': '1c', 'AE': '2c', 'AF': '5c', 'AG': '10c', 'AH': '20c', 'AI': '50c', 'AJ': '1\u20ac', 'AK': '2\u20ac',
    'AM': 'CC', 'AN': 'CC', 'AO': 'CC',
}
CC_COL_IDX = {'K': 1, 'L': 2, 'M': 3, 'Y': 1, 'Z': 2, 'AA': 3, 'AM': 1, 'AN': 2, 'AO': 3}
DENOM_CENTS = {'1c': 1, '2c': 2, '5c': 5, '10c': 10, '20c': 20, '50c': 50, '1\u20ac': 100, '2\u20ac': 200, 'CC': 200}
COIN_RE = re.compile(r'[\u2714\d][\u00b0o*]?|\[[^\]]*\]')
_COIN_RE = COIN_RE
IMAGE_BASE = 'https://www.eurocollection.co.uk/Euros'
_CT_COLOR = {'green': 'C5DEB5', 'blue': '8EAADB', 'orange': 'FF8C42', 'yellow': 'FFE598', 'nifc': 'FFC7CE', 'x': 'FFC7CE'}

BLOCK_COLS = {
    'A': {'year': 'A', 'denoms': ['B','C','D','E','F','G','H','I'], 'igap': 'J', 'ccs': ['K','L','M']},
    'O': {'year': 'O', 'denoms': ['P','Q','R','S','T','U','V','W'], 'igap': 'X', 'ccs': ['Y','Z','AA']},
    'AC': {'year': 'AC', 'denoms': ['AD','AE','AF','AG','AH','AI','AJ','AK'], 'igap': 'AL', 'ccs': ['AM','AN','AO']},
}
GAP_COLS = {'A_O': 'N', 'O_AC': 'AB', 'END': 'AP'}

def make_block_ordered_cols(bl: str) -> list:
    bc = BLOCK_COLS[bl]
    return [bc['year']] + bc['denoms'] + [bc['igap']] + bc['ccs']

COLS_ORDER = []
for bl in ('A', 'O', 'AC'):
    COLS_ORDER.extend(make_block_ordered_cols(bl))
    if bl == 'A':
        COLS_ORDER.append(GAP_COLS['A_O'])
    elif bl == 'O':
        COLS_ORDER.append(GAP_COLS['O_AC'])
COLS_ORDER.append(GAP_COLS['END'])

COL_TO_BLOCK = {}
for bl in ('A', 'O', 'AC'):
    for cl in make_block_ordered_cols(bl):
        COL_TO_BLOCK[cl] = bl
for g in GAP_COLS.values():
    COL_TO_BLOCK[g] = None

def make_denom_key(cl: str) -> str:
    dl = DENOM_LABEL.get(cl, '')
    if dl == 'CC':
        return f'CC{CC_COL_IDX.get(cl, 1)}'
    return dl

def is_dark(hex_color: str) -> bool:
    r = int(hex_color[0:2], 16); g = int(hex_color[2:4], 16); b = int(hex_color[4:6], 16)
    return r * 0.299 + g * 0.587 + b * 0.114 < 140

# ─── Speicher: Upstash Redis (Vercel) oder data.json (lokal) ───
# Auf Vercel kann man keine Dateien schreiben. Sind die Upstash-Variablen gesetzt,
# liegt das ganze Dokument in Redis; sonst wie bisher in data.json.

REDIS_URL = (os.environ.get('KV_REST_API_URL') or os.environ.get('UPSTASH_REDIS_REST_URL') or '').rstrip('/')
REDIS_TOKEN = os.environ.get('KV_REST_API_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN') or ''
USE_REDIS = bool(REDIS_URL and REDIS_TOKEN)
REDIS_DOC_KEY = 'muenzapp:doc'
REDIS_VER_KEY = 'muenzapp:ver'

def _redis(*cmd):
    body = json.dumps(list(cmd), ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(REDIS_URL, data=body, method='POST', headers={
        'Authorization': f'Bearer {REDIS_TOKEN}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        res = json.loads(resp.read().decode('utf-8'))
    if 'error' in res:
        raise RuntimeError(f"Redis: {res['error']}")
    return res.get('result')

def _load_file_doc() -> dict:
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

REDIS_SEED_KEY = 'muenzapp:seed'

def _file_hash() -> str:
    if not os.path.exists(DATA_PATH):
        return ''
    with open(DATA_PATH, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()

_doc_ver = None  # Stand des Dokuments, das gerade im Speicher ist

def load_doc() -> dict:
    global _doc_ver
    if not USE_REDIS:
        return _load_file_doc()
    raw = _redis('GET', REDIS_DOC_KEY)
    ver = _redis('GET', REDIS_VER_KEY)
    seed = _file_hash()
    # Erster Start, oder neue data.json und online noch nichts geändert (Stand 1):
    # data.json als Startdaten nach Redis kopieren
    if raw is None or (ver == '1' and _redis('GET', REDIS_SEED_KEY) != seed):
        _redis('DEL', REDIS_VER_KEY)
        d = _load_file_doc()
        save_doc(d)
        _redis('SET', REDIS_SEED_KEY, seed)
        return d
    _doc_ver = ver
    return json.loads(raw)

def save_doc(d: dict) -> None:
    global _doc_ver
    if USE_REDIS:
        _redis('SET', REDIS_DOC_KEY, json.dumps(d, ensure_ascii=False, separators=(',', ':')))
        _doc_ver = str(_redis('INCR', REDIS_VER_KEY))
        return
    tmp = DATA_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_PATH)

doc = load_doc()

COINS = doc.get('coins', {})
COINS_MINT = doc.get('coins_mint', {})
MINTAGE = doc.get('mintage', {})
MINTAGE_MINT = doc.get('mintage_mint', {})
CC_NAMES = doc.get('cc_coin_names', {})
IMAGE_LINKS_MINT = doc.get('image_links_mint', {})
FILL_COLORS = doc.get('fill_colors', {})
COUNTRIES = doc.get('countries', [])
COUNTRY_YEARS = doc.get('country_years', {})
EXTENSIONS = doc.get('extensions', {})
UNDO_STACK = doc.get('undo_stack', [])
REDO_STACK = doc.get('redo_stack', [])

def _build_coin_years_cache() -> dict:
    cache = {}
    for k in COINS:
        parts = k.split(':')
        if len(parts) >= 2:
            cache.setdefault(parts[0], set()).add(parts[1])
    return cache

_COIN_YEARS = _build_coin_years_cache()

def get_country_from_ref(ref: str) -> str:
    parts = ref.split(':')
    return parts[0] if len(parts) >= 3 else ''

def country_has_mints(cname: str) -> bool:
    for c in COUNTRIES:
        if c['name'] == cname:
            return bool(c.get('mint_marks', []))
    return False

def _resolve_storage(ref: str, mint_arg=None) -> tuple:
    cname = get_country_from_ref(ref)
    use_mint = mint_arg and country_has_mints(cname)
    if use_mint:
        return COINS_MINT, ref + ':' + mint_arg, cname, True
    return COINS, ref, cname, False

def save_all():
    global doc, COINS, COINS_MINT, MINTAGE, MINTAGE_MINT, CC_NAMES, IMAGE_LINKS_MINT, COUNTRIES, COUNTRY_YEARS, EXTENSIONS, UNDO_STACK, REDO_STACK
    doc['coins'] = COINS
    doc['coins_mint'] = COINS_MINT
    doc['mintage'] = MINTAGE
    doc['mintage_mint'] = MINTAGE_MINT
    doc['cc_coin_names'] = CC_NAMES
    doc['image_links_mint'] = IMAGE_LINKS_MINT
    doc['fill_colors'] = FILL_COLORS
    doc['countries'] = COUNTRIES
    doc['country_years'] = COUNTRY_YEARS
    doc['extensions'] = EXTENSIONS
    doc['undo_stack'] = UNDO_STACK
    doc['redo_stack'] = REDO_STACK
    save_doc(doc)

def coin_key(cname: str, year: str, denom: str) -> str:
    return f'{cname}:{year}:{denom}'

def mint_coin_key(cname: str, year: str, denom: str, mint: str) -> str:
    return f'{cname}:{year}:{denom}:{mint}'

def get_coin(cname: str, year: str, denom: str, mint=None) -> dict:
    if mint:
        mk = mint_coin_key(cname, year, denom, mint)
        if mk in COINS_MINT:
            return COINS_MINT[mk]
    return COINS.get(coin_key(cname, year, denom), {})

def set_coin(cname: str, year: str, denom: str, mint: str, value: str, cell_type: str, image_url: str):
    if mint:
        mk = mint_coin_key(cname, year, denom, mint)
        entry = COINS_MINT.get(mk, {})
        if value:
            entry['v'] = value
        else:
            entry.pop('v', None)
        if cell_type:
            entry['ct'] = cell_type
        else:
            entry.pop('ct', None)
        if image_url:
            entry['img'] = image_url
        else:
            entry.pop('img', None)
        if entry:
            COINS_MINT[mk] = entry
        else:
            COINS_MINT.pop(mk, None)
    else:
        ck = coin_key(cname, year, denom)
        entry = COINS.get(ck, {})
        if value:
            entry['v'] = value
        else:
            entry.pop('v', None)
        if cell_type:
            entry['ct'] = cell_type
        else:
            entry.pop('ct', None)
        if image_url:
            entry['img'] = image_url
        else:
            entry.pop('img', None)
        if entry:
            COINS[ck] = entry
        else:
            COINS.pop(ck, None)

def _year_sort_key(y: str) -> tuple:
    if y.isdigit():
        return (0, int(y), '')
    m = re.match(r'^(\d+)', y)
    if m:
        return (0, int(m.group(1)), y)
    _custom = {'EFS': 2002}
    if y in _custom:
        return (0, _custom[y], y)
    return (1, y, '')

def get_years(cname: str) -> list:
    base = COUNTRY_YEARS.get(cname, [])
    ext = EXTENSIONS.get(cname, [])
    coin_yrs = _COIN_YEARS.get(cname, set())
    return sorted(set(base) | set(ext) | coin_yrs, key=_year_sort_key)

def format_mintage_val(raw) -> str:
    if not raw:
        return ''
    clean = str(raw).replace('.', '').replace(',', '')
    if clean.isdigit():
        n = int(clean)
        return f'{n:,}'.replace(',', '.')
    return str(raw)

def mintage_for(cname: str, year: str, denom: str, mint=None) -> str:
    if mint:
        mk = mint_coin_key(cname, year, denom, mint)
        if mk in MINTAGE_MINT:
            return MINTAGE_MINT[mk]
    ck = coin_key(cname, year, denom)
    return MINTAGE.get(ck, '')

def image_url_for(cname: str, year: str, denom: str, cl=None):
    eng = None
    for c in COUNTRIES:
        if c['name'] == cname:
            eng = c.get('image_name_en', '')
            break
    if not eng:
        return None
    if denom == '1\u20ac':
        dpart = 'E1'
    elif denom == '2\u20ac' or (denom and denom.startswith('CC')):
        dpart = 'E2 CC ' + (denom[-1] if denom.startswith('CC') else '1')
    elif denom == '1c':
        dpart = '1c'
    elif denom == '2c':
        dpart = '2c'
    elif denom == '5c':
        dpart = '5c'
    elif denom == '10c':
        dpart = '10c'
    elif denom == '20c':
        dpart = '20c'
    elif denom == '50c':
        dpart = '50c'
    else:
        dpart = denom
    return f'{IMAGE_BASE}/{eng}/{eng} {year} {dpart}.JPG'

def image_url_for_cl(cname, year, cl):
    dl = DENOM_LABEL.get(cl, '')
    if not dl:
        return None
    if dl == 'CC':
        cc_idx = CC_COL_IDX.get(cl, 1)
        dk = f'CC{cc_idx}'
    else:
        dk = dl
    return image_url_for(cname, year, dk)

def coin_value(coin_entry) -> str:
    return (coin_entry or {}).get('v', '')

def coin_cell_type(coin_entry) -> str:
    return (coin_entry or {}).get('ct', '')

def coin_image(coin_entry) -> str:
    return (coin_entry or {}).get('img', '')

def compute_segments(exclude_country=None):
    ordered = sorted(COUNTRIES, key=lambda c: c.get('display_order', 0))
    segments = []
    cur_row = 1
    # Greedy: each segment gets the next unassigned country from each block
    # Iterate through all countries in display_order, place into first segment
    # that doesn't have that block yet
    for c in ordered:
        if exclude_country and c['name'] == exclude_country:
            continue
        bl = c.get('block', 'A')
        if bl not in ('A', 'O', 'AC'):
            continue
        yrs = get_years(c['name'])
        placed = False
        for seg in segments:
            existing_blocks = {e['block'] for e in seg['entries']}
            if bl not in existing_blocks:
                seg['entries'].append({'block': bl, 'country': c, 'years': yrs})
                seg['max_years'] = max(seg['max_years'], len(yrs))
                placed = True
                break
        if not placed:
            segments.append({
                'entries': [{'block': bl, 'country': c, 'years': yrs}],
                'max_years': len(yrs)
            })
    # Reorder entries within each segment to A, O, AC order
    for seg in segments:
        order_map = {'A': 0, 'O': 1, 'AC': 2}
        seg['entries'].sort(key=lambda e: order_map.get(e['block'], 9))
    # Assign start rows
    for seg in segments:
        seg['start'] = cur_row
        cur_row += 2 + seg['max_years']
    return segments

def _compute_cell_color(cname, year, denom, mint=None, ct=None):
    global FILL_COLORS
    if ct == 'x':
        return 'FFC7CE'
    if ct and ct in _CT_COLOR:
        return _CT_COLOR[ct]
    ck = coin_key(cname, year, denom)
    if ck in FILL_COLORS:
        return FILL_COLORS[ck]
    m = mintage_for(cname, year, denom, mint)
    if m:
        clean = str(m).replace('.', '').replace(',', '')
        if clean.isdigit():
            n = int(clean)
            if n > 5000000:
                return 'C5DEB5'
            elif n > 2000000:
                return '8EAADB'
            elif n > 1000000:
                return 'FF8C42'
            elif n > 0:
                return 'FFE598'
            else:
                return ''
    return ''

def _compute_all_stats(mint_arg=''):
    _denom_val_cents = {'1c':1,'2c':2,'5c':5,'10c':10,'20c':20,'50c':50,'1\u20ac':100,'2\u20ac':200,'CC':200}
    _denom_counts = {'1c':0,'2c':0,'5c':0,'10c':0,'20c':0,'50c':0,'1\u20ac':0,'2\u20ac':0,'CC':0}
    _country_cell_stats = {}
    _country_stats = {}
    _reg_denom = {}
    _nifc_denom = {}
    _init_cs2 = lambda ck: _country_cell_stats.setdefault(ck, {'regFilled':0,'regTotal':0,'ccFilled':0,'ccTotal':0,'nifcFilled':0,'nifcTotal':0,'denomRegFilled':{},'denomRegTotal':{},'denomNifcFilled':{},'denomNifcTotal':{}})

    for c in COUNTRIES:
        cname = c['name']
        bl = c['block']
        ckey = bl + '|' + cname
        mints = c.get('mint_marks', [])
        yrs = get_years(cname)
        for yr in yrs:
            for dk in ['1c','2c','5c','10c','20c','50c','1\u20ac','2\u20ac','CC1','CC2','CC3']:
                is_cc = dk.startswith('CC')
                dl = dk if not is_cc else 'CC'
                if mints:
                    for mm in mints:
                        mentry = get_coin(cname, yr, dk, mm)
                        mval = coin_value(mentry)
                        mct = coin_cell_type(mentry)
                        mval_str = mval.strip() if isinstance(mval, str) else ''
                        if mval_str in ('\u2715', '\u00d7') or mct == 'x':
                            continue
                        is_nifc = mct == 'nifc'
                        has_coin = bool(mval_str)
                        cs2 = _init_cs2(ckey)
                        if is_nifc:
                            cs2['nifcTotal'] += 1
                            if has_coin: cs2['nifcFilled'] += 1
                            nd = _nifc_denom.setdefault(dl, {'filled':0,'total':0})
                            nd['total'] += 1
                            if has_coin: nd['filled'] += 1
                            cs2['denomNifcTotal'][dl] = cs2['denomNifcTotal'].get(dl, 0) + 1
                            if has_coin: cs2['denomNifcFilled'][dl] = cs2['denomNifcFilled'].get(dl, 0) + 1
                        elif is_cc:
                            cs2['ccTotal'] += 1
                            if has_coin: cs2['ccFilled'] += 1
                            cs2['denomRegTotal']['CC'] = cs2['denomRegTotal'].get('CC', 0) + 1
                            if has_coin: cs2['denomRegFilled']['CC'] = cs2['denomRegFilled'].get('CC', 0) + 1
                        else:
                            cs2['regTotal'] += 1
                            if has_coin: cs2['regFilled'] += 1
                            rd = _reg_denom.setdefault(dl, {'filled':0,'total':0})
                            rd['total'] += 1
                            if has_coin: rd['filled'] += 1
                            cs2['denomRegTotal'][dl] = cs2['denomRegTotal'].get(dl, 0) + 1
                            if has_coin: cs2['denomRegFilled'][dl] = cs2['denomRegFilled'].get(dl, 0) + 1
                        if has_coin:
                            cnt = len(COIN_RE.findall(mval_str))
                            _denom_counts[dl] += cnt
                            cs = _country_stats.setdefault(ckey, {'denom':{},'totalCents':0})
                            cs['denom'][dl] = cs['denom'].get(dl,0)+cnt
                            cs['totalCents'] += cnt*_denom_val_cents[dl]
                else:
                    entry = get_coin(cname, yr, dk)
                    val = coin_value(entry)
                    ct = coin_cell_type(entry)
                    val_str = val.strip() if isinstance(val, str) else ''
                    if val_str in ('\u2715', '\u00d7') or ct == 'x':
                        continue
                    fl = _compute_cell_color(cname, yr, dk, ct=ct)
                    is_light_red = (fl == 'FFC7CE')
                    has_coin = bool(val_str)
                    cs2 = _init_cs2(ckey)
                    if is_light_red:
                        cs2['nifcTotal'] += 1
                        if has_coin: cs2['nifcFilled'] += 1
                        nd = _nifc_denom.setdefault(dl, {'filled':0,'total':0})
                        nd['total'] += 1
                        if has_coin: nd['filled'] += 1
                        cs2['denomNifcTotal'][dl] = cs2['denomNifcTotal'].get(dl, 0) + 1
                        if has_coin: cs2['denomNifcFilled'][dl] = cs2['denomNifcFilled'].get(dl, 0) + 1
                    elif is_cc:
                        cs2['ccTotal'] += 1
                        if has_coin: cs2['ccFilled'] += 1
                        cs2['denomRegTotal']['CC'] = cs2['denomRegTotal'].get('CC', 0) + 1
                        if has_coin: cs2['denomRegFilled']['CC'] = cs2['denomRegFilled'].get('CC', 0) + 1
                    else:
                        cs2['regTotal'] += 1
                        if has_coin: cs2['regFilled'] += 1
                        rd = _reg_denom.setdefault(dl, {'filled':0,'total':0})
                        rd['total'] += 1
                        if has_coin: rd['filled'] += 1
                        cs2['denomRegTotal'][dl] = cs2['denomRegTotal'].get(dl, 0) + 1
                        if has_coin: cs2['denomRegFilled'][dl] = cs2['denomRegFilled'].get(dl, 0) + 1
                    if has_coin:
                        cnt = len(COIN_RE.findall(val_str))
                        _denom_counts[dl] += cnt
                        cs = _country_stats.setdefault(ckey, {'denom':{},'totalCents':0})
                        cs['denom'][dl] = cs['denom'].get(dl,0)+cnt
                        cs['totalCents'] += cnt*_denom_val_cents[dl]

    _total_cents = sum(_denom_counts[d] * _denom_val_cents[d] for d in _denom_counts)
    _global_cell = {'regFilled':0,'regTotal':0,'ccFilled':0,'ccTotal':0,'nifcFilled':0,'nifcTotal':0}
    for cs2 in _country_cell_stats.values():
        for k in _global_cell:
            _global_cell[k] += cs2.get(k, 0)
    for ckey, csdata in _country_cell_stats.items():
        _country_stats.setdefault(ckey, {}).update(csdata)
    return {
        'denom_counts': _denom_counts, 'country_cell_stats': _country_cell_stats,
        'country_stats': _country_stats, 'reg_denom': _reg_denom,
        'nifc_denom': _nifc_denom, 'global_cell': _global_cell,
        'total_cents': _total_cents,
        'denom_val_cents': _denom_val_cents,
    }

def generate_html(mint_arg='', layout=''):
    global COINS, COINS_MINT, MINTAGE, CC_NAMES, IMAGE_LINKS_MINT, IMAGE_LINKS
    _js_hash = ''
    try:
        with open(os.path.join(app.static_folder, 'app.js'), 'rb') as _f:
            _js_hash = hashlib.md5(_f.read()).hexdigest()[:8]
    except: pass
    split_germany = layout == 'split'
    segments = compute_segments()
    _S = _compute_all_stats(mint_arg)
    _denom_counts = _S['denom_counts']
    _country_cell_stats = _S['country_cell_stats']
    _country_stats = _S['country_stats']
    _reg_denom = _S['reg_denom']
    _nifc_denom = _S['nifc_denom']
    _global_cell = _S['global_cell']
    _total_cents = _S['total_cents']
    _denom_val_cents = _S['denom_val_cents']

    _total_str = f'{_total_cents / 100:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    _reg_pct = int(_global_cell["regFilled"] / _global_cell["regTotal"] * 100) if _global_cell["regTotal"] else 0
    _cc_pct = int(_global_cell["ccFilled"] / _global_cell["ccTotal"] * 100) if _global_cell["ccTotal"] else 0
    _nifc_pct = int(_global_cell["nifcFilled"] / _global_cell["nifcTotal"] * 100) if _global_cell["nifcTotal"] else 0
    _global_cell_html = (
        f'<div class="country-popup-badge country-popup-badge-reg">'
        f'<div class="country-popup-badge-label">Regul\u00e4r</div>'
        f'<div class="country-popup-badge-num">{_global_cell["regFilled"]}/{_global_cell["regTotal"]}</div>'
        f'<div class="country-popup-badge-pct">{_reg_pct}%</div></div>'
        f'<div class="country-popup-badge country-popup-badge-cc">'
        f'<div class="country-popup-badge-label">CC</div>'
        f'<div class="country-popup-badge-num">{_global_cell["ccFilled"]}/{_global_cell["ccTotal"]}</div>'
        f'<div class="country-popup-badge-pct">{_cc_pct}%</div></div>'
        f'<div class="country-popup-badge country-popup-badge-nifc">'
        f'<div class="country-popup-badge-label">NIFC</div>'
        f'<div class="country-popup-badge-num">{_global_cell["nifcFilled"]}/{_global_cell["nifcTotal"]}</div>'
        f'<div class="country-popup-badge-pct">{_nifc_pct}%</div></div>'
    )
    _denom_order = ['1c', '2c', '5c', '10c', '20c', '50c', '1\u20ac', '2\u20ac', 'CC']
    _total_miss_reg = 0
    _total_miss_nifc = 0
    _breakdown_rows = ''
    for d in _denom_order:
        c = _denom_counts[d]
        rd = _reg_denom.get(d, {})
        nd = _nifc_denom.get(d, {})
        _miss_reg = rd.get('total', 0) - rd.get('filled', 0) if d != 'CC' else (_global_cell['ccTotal'] - _global_cell['ccFilled'])
        _miss_nifc = nd.get('total', 0) - nd.get('filled', 0)
        if c == 0 and not _miss_reg and not _miss_nifc:
            continue
        _v = c * _denom_val_cents[d]
        _vs = f'{_v / 100:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        _cls = ' class="country-popup-cc"' if d == 'CC' else ''
        _breakdown_rows += f'<tr{_cls}><td>{d}</td><td>{c}</td><td style="text-align:center"><span style="color:#c00">{_miss_reg}</span></td><td style="text-align:center"><span style="color:#c00">{_miss_nifc}</span></td><td>\u20ac{_vs}</td></tr>\n'
        _total_miss_reg += _miss_reg
        _total_miss_nifc += _miss_nifc

    _col_widths = {
        'A':5.5, 'B':3.75, 'C':3.5400390625, 'D':3.5375, 'E':3.5375, 'F':3.5375, 'G':3.5375, 'H':3.5375, 'I':3.5375,
        'J':0.6640625, 'K':3.5400390625, 'L':3.5375, 'M':3.5375, 'N':5.6640625, 'O':5.1640625,
        'P':3.5400390625, 'Q':3.5375, 'R':3.5375, 'S':3.75, 'T':3.5375, 'U':3.5375, 'V':3.5375, 'W':3.5400390625,
        'X':0.6640625, 'Y':3.5400390625, 'Z':3.5375, 'AA':3.5375, 'AB':5.6640625, 'AC':5.1640625,
        'AD':3.5400390625, 'AE':3.5375, 'AF':3.5375, 'AG':3.5375, 'AH':3.5375, 'AI':3.5400390625, 'AJ':3.5400390625, 'AK':3.75,
        'AL':0.6640625, 'AM':3.5400390625, 'AN':3.5375, 'AO':3.5375, 'AP':5.66,
    }
    total_w = sum(max(_col_widths[l] * 7.5, 6) for l in _col_widths)

    h = f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>M\u00fcnzApp</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div id="stickyHeader"><div style="margin-bottom:6px">
<span class="undo-btn" id="undoBtn">\u21b6 Letzte Aktion r\u00fcckg\u00e4ngig</span>
<span class="redo-btn" id="redoBtn">\u21b7 Wiederholen</span>
<span class="export-btn" id="exportPdfBtn">\U0001f5a8\ufe0f PDF</span>
<span class="export-btn" id="exportXlsxBtn">\U0001f4ca Excel</span>
<span class="data-wrap" style="position:relative;display:inline-block;margin-left:6px">
<span class="export-btn" id="dataBtn">\U0001f4e4 Daten \u25be</span>
<div class="data-dropdown" id="dataDropdown" style="display:none">
  <span class="data-dropdown-item" id="dropdownExport">\U0001f4e4 Exportieren</span>
  <span class="data-dropdown-item" id="dropdownImport">\U0001f4e5 Importieren</span>
</div>
</span>
<span class="edit-btn" id="editBtn">\U0001f4dd Bearbeiten</span>
<span id="editHint" class="edit-hint"></span>
<span class="export-btn" id="sumBtn">Info</span>
<span class="data-wrap" style="position:relative;display:inline-block;margin-left:6px">
<span class="export-btn" id="moreBtn">Mehr \u25be</span>
<div class="data-dropdown" id="moreDropdown" style="display:none">
  <span class="data-dropdown-item" id="morePrintLayout">\U0001f4d6 Print-Layout</span>
  <span class="data-dropdown-item" id="moreLegend">\u2753 Legende</span>
  <span class="data-dropdown-item" id="moreMissing">\U0001f50d Fehlende anzeigen</span>
  <span class="data-dropdown-item" id="moreSync">\U0001f504 Auflagezahlen syncen</span>
  <span class="data-dropdown-item" id="moreCountries">\u270f L\u00e4nder</span>
</div>
</span>
<span id="msg" class="msg"></span>
<div id="sumBreakdown" class="sum-breakdown" style="display:none">
  <div class="sum-breakdown-body">
    <table>
      <tr><th>Nominal</th><th>Anzahl</th><th style="color:#c00">\u2715 reg.</th><th style="color:#c00">\u2715 NIFC</th><th>Wert</th></tr>
      {_breakdown_rows}
      <tr class="sum-breakdown-total"><td>Gesamt</td><td></td><td style="text-align:center"><span style="color:#c00">{_total_miss_reg}</span></td><td style="text-align:center"><span style="color:#c00">{_total_miss_nifc}</span></td><td>\u20ac{_total_str}</td></tr>
    </table>
    <div id="sumBreakdownStats" class="sum-breakdown-badges">{_global_cell_html}</div>
  </div>
</div>
</div>
<div id="legendPanel" class="legend-panel" style="display:none">
  <div class="legend-col">
    <h4>Qualit\u00e4t</h4>
    <div class="legend-row"><span class="legend-code">\u2714</span> Qualit\u00e4t noch nicht bestimmt</div>
    <div class="legend-row"><span class="legend-code">0</span> UNC</div>
    <div class="legend-row"><span class="legend-code">1</span> Gute / sehr gute Qualit\u00e4t</div>
    <div class="legend-row"><span class="legend-code">3</span> Schlechte Qualit\u00e4t</div>
    <div class="legend-row"><span class="legend-code">5</span> Sehr schlechte Qualit\u00e4t</div>
  </div>
  <div class="legend-col">
    <h4>Herkunft (Suffix)</h4>
    <div class="legend-row"><span class="legend-code">&ndash;</span> Selbst gesammelt</div>
    <div class="legend-row"><span class="legend-code">\u00b0 / o</span> Aus der Gruppe</div>
    <div class="legend-row"><span class="legend-code">*</span> Gekauft</div>
    <div class="legend-row" style="color:#888">Mehrere Codes in einer Zelle = mehrere M\u00fcnzen (z.B. 5\u00b00*)</div>
  </div>
  <div class="legend-col">
    <h4>Zellfarben (Auflagegr\u00f6\u00dfe)</h4>
    <div class="legend-row"><span class="legend-swatch" style="background:#C5DEB5"></span> &gt; 5 Mio.</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#8EAADB"></span> 2&ndash;5 Mio.</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#FF8C42"></span> 1&ndash;2 Mio.</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#FFE598"></span> &le; 1 Mio.</div>
    <div class="legend-row"><span class="legend-swatch" style="background:#FFC7CE"></span> NIFC / nie gepr\u00fcft / \u2715 nie ausgegeben</div>
  </div>
  <div class="legend-col">
    <h4>Bedienung</h4>
    <div class="legend-row">Klick auf M\u00fcnzzelle &rarr; M\u00fcnze verwalten (Qualit\u00e4t, Quelle, Bild)</div>
    <div class="legend-row">\u2139-L\u00e4nderbutton &rarr; L\u00e4nderstatistik (Anzahl, Fehlende, Wert)</div>
    <div class="legend-row">\u2139-Button oben &rarr; Gesamtstatistik \u00fcber alle L\u00e4nder</div>
    <div class="legend-row">\U0001f50d Fehlende &rarr; rot markiert nicht besessene M\u00fcnzen</div>
    <div class="legend-row">\U0001f504 Auflagezahlen syncen &rarr; l\u00e4dt Auflagezahlen aus Google Sheet</div>
    <div class="legend-row">\U0001f5a8\ufe0f PDF &rarr; druckt die Tabelle (ohne Bedienelemente)</div>
    <div class="legend-row">\U0001f4ca Excel &rarr; exportiert als Excel-Datei</div>
    <div class="legend-row">\U0001f4e4 Daten \u25be Exportieren &rarr; sichert alle Daten als .txt</div>
    <div class="legend-row">\U0001f4e4 Daten \u25be Importieren &rarr; stellt gesicherte Daten wieder her</div>
    <div class="legend-row">\u21b6 / \u21b7 &rarr; \u00c4nderungen r\u00fcckg\u00e4ngig machen / wiederholen</div>
    <div class="legend-row">\U0001f4dd Bearbeiten &rarr; Modus: Einfachklick = Popup, Doppelklick = Quelle w\u00e4hlen</div>
    <div class="legend-row">Im Bearbeiten-Modus: Zellen markieren (Drag) &rarr; Popup mit Farbauswahl + Texteingabe</div>
  </div>
  <div class="legend-col" style="flex:0 0 100%;max-width:100%">
    <h4>\u00dcber die App</h4>
    <div class="legend-row" style="max-width:100%">Diese App verwaltet eine pers\u00f6nliche Eurom\u00fcnzen-Sammlung. Die Daten liegen als <code>data.json</code> auf dem Server.</div>
    <div class="legend-row" style="max-width:100%"><a href="https://docs.google.com/spreadsheets/d/1lGbzcTmMfzQjE-7ENMhrSMpMlu859fYCAqH8juDhb40" target="_blank" rel="noopener">Google Sheet &nearr;</a></div>
    <div class="legend-row" style="max-width:100%"><a href="https://www.eurocollection.co.uk/Euros" target="_blank" rel="noopener">M\u00fcnzbilder (eurocollection.co.uk) &nearr;</a></div>
  </div>
</div>
<div class="info-modal-overlay" id="infoOverlay"></div>
<div class="info-modal" id="infoModal">
  <button class="close-btn" id="infoClose">&times;</button>

  <div class="info-header">
    <div class="info-header-img">
      <a id="infoCoinLink" href="#" target="_blank" style="display:contents">
        <img id="infoCoinImg" src="" style="display:none">
      </a>
    </div>
    <div class="info-header-text">
      <h3 id="infoTitle">M\u00fcnze</h3>
      <div id="infoCCName" class="info-cc-name" style="display:none">
        <span style="color:#888">M\u00fcnzname:</span> <strong id="infoCCNameText"></strong>
      </div>
      <div id="infoCoinEntries" style="margin-top:6px"></div>
    </div>
  </div>

  <div id="infoURLEditRow" style="display:none;margin:8px 0;text-align:center">
    <span style="font-size:8pt;cursor:pointer;color:#1a73e8;text-decoration:underline;user-select:none" id="infoURLEditBtn">\u270f Bild-URL bearbeiten</span>
  </div>
  <div id="infoURLInputRow" style="display:none;margin:8px 0">
    <input type="text" id="infoURLInput" placeholder="Bild-URL (z.B. https://...)" style="width:100%;box-sizing:border-box;padding:6px 8px;font-size:9pt;border:1px solid #ccc;border-radius:5px">
  </div>

  <div id="infoCoinAdd" style="display:none">
      <div class="info-add-label">Neue M\u00fcnze hinzuf\u00fcgen:</div>
      <div id="infoCoinQualityRow" class="info-btn-row">
        <span class="info-q-btn" data-q="\u2714">\u2714</span>
        <span class="info-q-btn" data-q="0">0</span>
        <span class="info-q-btn" data-q="1">1</span>
        <span class="info-q-btn" data-q="3">3</span>
        <span class="info-q-btn" data-q="5">5</span>
        <span class="info-q-btn info-custom-btn" id="infoCustomBtn">\u270f\ufe0f</span>
      </div>
      <div id="infoCoinSourceRow" class="info-btn-row" style="display:none">
        <span class="info-s-btn" data-s="">Selbst</span>
        <span class="info-s-btn" data-s="\u00b0">Gruppe</span>
        <span class="info-s-btn" data-s="*">Gekauft</span>
      </div>
      <div id="infoCustomInputRow" class="info-custom-row" style="display:none">
        <input type="text" id="infoCustomInput" placeholder="Eigener Text (z.B. Proof, Fehlpr\u00e4gung...)" maxlength="50">
        <span class="info-custom-add" id="infoCustomAddBtn">+</span>
      </div>
    </div>

  <div class="info-section">
    <div class="info-section-title">Auflage &amp; Farbe</div>
    <label>Auflagezahl</label>
    <input type="text" id="infoMintage" placeholder="z.B. 378.400.000">
    <div style="margin-top:8px">
      <div id="infoColorPicker" style="display:flex;flex-wrap:wrap;gap:4px"></div>
    </div>
  </div>

  <button id="infoSave">Speichern</button>
</div>
<div class="sync-modal-overlay" id="syncOverlay"></div>
<div class="sync-modal" id="syncModal">
  <div class="sync-modal-title">Auflagezahlen syncen?</div>
  <p style="margin:6px 0">Die aktuellen Auflagezahlen werden aus der Google-Tabelle geladen:</p>
  <p style="margin:6px 0;word-break:break-all"><a href="https://docs.google.com/spreadsheets/d/1lGbzcTmMfzQjE-7ENMhrSMpMlu859fYCAqH8juDhb40" target="_blank" rel="noopener">Google Sheet \u00f6ffnen &nearr;</a></p>
  <p style="margin:6px 0;">Manuell bearbeitete Zahlen werden nicht \u00fcberschrieben.</p>
  <div style="display:flex;gap:8px;margin-top:12px">
    <button class="sync-modal-btn sync-modal-btn-cancel" id="syncCancel">Abbrechen</button>
    <button class="sync-modal-btn sync-modal-btn-confirm" id="syncConfirm">Sync starten</button>
  </div>
</div>
<div class="flag-bar">
'''
    for c in sorted(COUNTRIES, key=lambda c: c.get('display_order', 0)):
        flag = c.get('flag', '')
        if not flag:
            continue
        _safe = c['name'].lower().replace('/','_').replace(' ','_')
        h += f'<span class="flag-btn" data-target="c-{c["block"]}-{_safe}" title="{htmlmod.escape(c["name"])}">{flag}</span>\n'
    h += '''</div>
</div>
<div id="reorderModal" style="display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:#fff;border:2px solid #1a73e8;border-radius:8px;padding:16px;z-index:1000;font-size:9pt;width:min(92vw,450px);max-height:80vh;overflow-y:auto;box-shadow:0 4px 24px rgba(0,0,0,0.2)">
  <span id="rmClose" style="position:absolute;top:4px;right:8px;border:none;background:none;font-size:14pt;cursor:pointer">&times;</span>
  <h3 style="margin:0 0 10px;font-size:11pt;color:#1a73e8">L\u00e4nder verwalten</h3>
  <div id="rmList"></div>
  <hr style="border:none;border-top:1px solid #eee;margin:10px 0">
  <div style="display:flex;gap:4px;flex-wrap:wrap">
    <input id="acName" placeholder="Name" style="flex:1;min-width:80px;padding:4px 6px;font-size:9pt;border:1px solid #ccc;border-radius:3px">
    <select id="acBlock" style="padding:4px;font-size:9pt;border:1px solid #ccc;border-radius:3px"><option value="A">1.</option><option value="O">2.</option><option value="AC">3.</option></select>
    <input id="acFlag" placeholder="\U0001f1ea\U0001f1fa" style="width:40px;padding:4px;font-size:9pt;border:1px solid #ccc;border-radius:3px;text-align:center">
    <input id="acImageName" placeholder="Bild" style="flex:1;min-width:60px;padding:4px 6px;font-size:9pt;border:1px solid #ccc;border-radius:3px">
    <input id="acMints" placeholder="M\u00fcnzst\u00e4tten" style="flex:1;min-width:60px;padding:4px 6px;font-size:9pt;border:1px solid #ccc;border-radius:3px">
    <button id="acSave" style="padding:4px 10px;font-size:9pt;border:1px solid #1a73e8;border-radius:3px;background:#1a73e8;color:#fff;cursor:pointer">+</button>
  </div>
</div>
</div>
<table style="width:''' + str(round(total_w, 1)) + '''px">
'''
    for cl in COLS_ORDER:
        px = max(_col_widths.get(cl, 3.5) * 7.5, 6)
        h += f'<col style="width:{px:.1f}px;min-width:{px:.1f}px">\n'

    # Render rows
    _last_dr_blk = {}
    def block_colspan(bl):
        return len(make_block_ordered_cols(bl))

    for seg in segments:
        entries = seg['entries']
        max_years = seg['max_years']
        seg_start = seg['start']

        # Determine preceding gap check (check if any block's last data row was prev row)
        _need_gap = False
        for bl in ('A', 'O', 'AC'):
            if _last_dr_blk.get(bl, 0) == seg_start - 1:
                found_bl = [e for e in entries if e['block'] == bl]
                if found_bl:
                    _need_gap = True
                    break
        if _need_gap:
            h += '<tr>'
            for _ci in range(len(COLS_ORDER)):
                h += '<td class="gap">&nbsp;</td>'
            h += '</tr>\n'

        # Country header row (rowspan 2 to cover country + col header)
        h += '<tr>'
        col_idx = 0
        for bl in ('A', 'O', 'AC'):
            found = [e for e in entries if e['block'] == bl]
            bc = BLOCK_COLS[bl]
            if found:
                c = found[0]['country']
                cname = c['name']
                _id = f' id="c-{bl}-{cname.lower().replace("/","_").replace(" ","_")}"'
                _left = f'<span class="c-left-btns"><span class="country-info" data-block="{bl}" data-country="{htmlmod.escape(cname)}">\u2139</span></span>'
                ckey = bl + '|' + cname
                cst = _country_stats.get(ckey)
                _cst_json = htmlmod.escape(json.dumps(cst)) if cst else '{}'
                _mints = c.get('mint_marks', [])
                _mint_html = ''
                if _mints and not (split_germany and cname == 'Deutschland'):
                    _active_mint = mint_arg if mint_arg in _mints else _mints[0]
                    _mint_html = '<span class="c-mints">' + ''.join(
                        f'<a class="c-mint{" active" if m == _active_mint else ""}" data-mint="{m}" href="?mint={m}">{m}</a>'
                        for m in _mints
                    ) + '</span>'
                _del_btn = f'<span class="c-del" data-country="{htmlmod.escape(cname)}" style="font-size:9pt;cursor:pointer;margin-left:4px;user-select:none;opacity:0.3;color:#c00;" title="Land l\u00f6schen">\u2715</span>'
                btn = f'<div class="c-country-inner">{_left}<span class="c-name" data-key="{htmlmod.escape(ckey)}" data-stats=\'{_cst_json}\'>{htmlmod.escape(cname)}</span>{_mint_html}{_del_btn}</div>'
                _cs = block_colspan(bl)
                h += f'<td{_id} class="c-country" colspan="{_cs}" style="background:#FF543E;color:#000">{btn}</td>'
            else:
                _cs = block_colspan(bl)
                h += f'<td class="gap" colspan="{_cs}">&nbsp;</td>'
            # Gap columns
            if bl == 'A':
                h += f'<td class="gap" style="width:{max(_col_widths.get(GAP_COLS["A_O"],2)*7.5,6):.1f}px">&nbsp;</td>'
            elif bl == 'O':
                h += f'<td class="gap" style="width:{max(_col_widths.get(GAP_COLS["O_AC"],2)*7.5,6):.1f}px">&nbsp;</td>'
        h += '</tr>\n'

        # Column header row
        h += '<tr>'
        for bl in ('A', 'O', 'AC'):
            bc = BLOCK_COLS[bl]
            found = [e for e in entries if e['block'] == bl]
            if found:
                for cl in make_block_ordered_cols(bl):
                    ct = 'colheader'
                    dl = DENOM_LABEL.get(cl, '')
                    val = dl
                    if val in ('1', '2'):
                        val += ' \u20ac'
                    cls = ''
                    if cl == bc['year']:
                        val = ''
                        cls = 'year-connector'
                    elif cl == bc['igap']:
                        val = ''
                        cls = 'inner-gap'
                    h += f'<td class="{cls}" style="font-size:7pt;text-align:center;border:1px solid #000">{htmlmod.escape(val) if val else ""}</td>'
            else:
                for cl in make_block_ordered_cols(bl):
                    h += '<td class="gap">&nbsp;</td>'
            if bl == 'A':
                h += '<td class="gap">&nbsp;</td>'
            elif bl == 'O':
                h += '<td class="gap">&nbsp;</td>'
        h += '</tr>\n'

        # Data rows
        for yr_idx in range(max_years):
            h += '<tr>'
            for bl in ('A', 'O', 'AC'):
                found = [e for e in entries if e['block'] == bl]
                bc = BLOCK_COLS[bl]
                if found:
                    c = found[0]['country']
                    cname = c['name']
                    mints = c.get('mint_marks', [])
                    yrs = found[0]['years']
                    for cl in make_block_ordered_cols(bl):
                        if cl == bc['year']:
                            yr_val = yrs[yr_idx] if yr_idx < len(yrs) else ''
                            if yr_val:
                                h += f'<td style="text-align:center;font-size:7pt;border:1px solid #000;background:#eee">{htmlmod.escape(yr_val)}</td>'
                            else:
                                h += '<td class="gap">&nbsp;</td>'
                        elif cl == bc['igap']:
                            h += '<td class="inner-gap">&nbsp;</td>'
                        else:
                            dk = make_denom_key(cl)
                            yr_val = yrs[yr_idx] if yr_idx < len(yrs) else ''
                            if not yr_val:
                                h += '<td class="gap">&nbsp;</td>'
                                continue
                            if split_germany and cname == 'Deutschland':
                                h += '<td class="gap">&nbsp;</td>'
                                continue
                            entry = get_coin(cname, yr_val, dk)
                            mval = ''
                            mct = ''
                            if mints:
                                mentry = get_coin(cname, yr_val, dk, mint_arg if mint_arg in mints else None)
                                mval = coin_value(mentry)
                                mct = coin_cell_type(mentry)
                            val = mval if mval else coin_value(entry)
                            ct = mct if mct else coin_cell_type(entry)
                            ref = coin_key(cname, yr_val, dk)
                            _ref_attr = ref
                            _yr_attr = yr_val
                            _denom_attr = dk
                            _cname_attr = cname
                            _bg = _compute_cell_color(cname, yr_val, dk, ct=ct)
                            _sty = ''
                            if ct == 'x':
                                _sty = 'background:#FFC7CE;'
                                val = '\u2715'
                            elif val and '\u2715' in val:
                                _sty = 'background:#FFC7CE;'
                            elif _bg:
                                _sty = f'background:#{_bg};'
                            _ev = htmlmod.escape(val) if val else ''
                            _editable = bool(dk)
                            _ct_attr = ct or ''
                            _xlocked = ' data-xlocked="1"' if ct == 'x' else ''
                            _dct = f' data-ct="{ct}"' if ct else ''
                            _mv = mintage_for(cname, yr_val, dk)
                            _dm = f' data-mintage="{htmlmod.escape(format_mintage_val(_mv))}"' if _mv else ''
                            _img = coin_image(entry)
                            if not _img and mints:
                                mentry = get_coin(cname, yr_val, dk, mint_arg if mint_arg in mints else None)
                                _img = coin_image(mentry)
                            _dl = ''
                            if not _img:
                                url = image_url_for(cname, yr_val, dk)
                                if url:
                                    _img = url
                            _dl = f' data-link="{htmlmod.escape(_img)}"' if _img else ''
                            # Mint-specific data attrs
                            _dmint = ''
                            if mints:
                                mint_parts = []
                                for mm in mints:
                                    mm_v = mintage_for(cname, yr_val, dk, mm)
                                    if mm_v:
                                        mint_parts.append(f'data-mint-{mm}="{htmlmod.escape(format_mintage_val(mm_v))}"')
                                    mm_img = get_coin(cname, yr_val, dk, mm)
                                    mm_img_url = coin_image(mm_img)
                                    if mm_img_url:
                                        mint_parts.append(f'data-link-mint-{mm}="{htmlmod.escape(mm_img_url)}"')
                                if mint_parts:
                                    _dmint = ' ' + ' '.join(mint_parts)
                            _ccn = CC_NAMES.get(ref, '')
                            _dcn = f' data-cc-name="{htmlmod.escape(_ccn)}"' if _ccn else ''
                            _dr = f' data-ref="{_ref_attr}" data-country="{htmlmod.escape(_cname_attr)}" data-block="{bl}" data-year="{_yr_attr}" data-denom="{_denom_attr}"'
                            _fullsty = (_sty + ';' if _sty and not _sty.endswith(';') else _sty) + 'font-size:8pt;text-align:center;border:1px solid #000'
                            h += f'<td{_dr}{_dct}{_xlocked}{_dm}{_dl}{_dmint}{_dcn} style="{_fullsty}">{_ev}</td>'
                else:
                    for cl in make_block_ordered_cols(bl):
                        h += '<td class="gap">&nbsp;</td>'
                if bl == 'A':
                    h += '<td class="gap">&nbsp;</td>'
                elif bl == 'O':
                    h += '<td class="gap">&nbsp;</td>'
            h += '</tr>\n'

        # Track last data row
        for bl in ('A', 'O', 'AC'):
            found = [e for e in entries if e['block'] == bl]
            if found and found[0]['years']:
                _last_dr_blk[bl] = seg_start + 1 + len(found[0]['years'])

    # Mint data JSON
    _mint_data = {}
    for c in COUNTRIES:
        if c.get('mint_marks'):
            cname = c['name']
            yrs = get_years(cname)
            for yr in yrs:
                for dk in ['1c','2c','5c','10c','20c','50c','1\u20ac','2\u20ac','CC1','CC2','CC3']:
                    entry = get_coin(cname, yr, dk)
                    _val = coin_value(entry)
                    _ct = coin_cell_type(entry)
                    _img = coin_image(entry)
                    _mv = mintage_for(cname, yr, dk)
                    for mm in c['mint_marks']:
                        mentry = get_coin(cname, yr, dk, mm)
                        mval = coin_value(mentry)
                        mct = coin_cell_type(mentry)
                        mimg = coin_image(mentry)
                        mmv = mintage_for(cname, yr, dk, mm)
                        ref = coin_key(cname, yr, dk)
                        if mval:
                            _mint_data.setdefault('overrides_mint', {})[ref + '|' + mm] = mval
                        if mct:
                            _mint_data.setdefault('cell_types_mint', {})[ref + '|' + mm] = mct
                        if mimg:
                            _mint_data.setdefault('image_links_mint', {})[ref + '|' + mm] = mimg
                        if mmv:
                            _mint_data.setdefault('mintage_mint', {})[ref + '|' + mm] = mmv
    if _mint_data:
        _mint_data['mints'] = {c['name']: c['mint_marks'] for c in COUNTRIES if c.get('mint_marks')}
        _mint_data['active_mint'] = mint_arg
    _mint_data_str = json.dumps(_mint_data, ensure_ascii=False) if _mint_data else '{}'

    h += '</table>\n'

    if split_germany:
        germany = next((c for c in COUNTRIES if c['name'] == 'Deutschland'), None)
        if germany:
            mints = germany.get('mint_marks', [])
            bl = germany['block']
            bc = BLOCK_COLS[bl]
            germany_years = get_years('Deutschland')
            _gcols = make_block_ordered_cols(bl)

            def _mint_table_html(mm):
                _gw = sum(max(_col_widths.get(cl, 3.5) * 7.5, 6) for cl in _gcols)
                tbl = f'<table style="width:{round(_gw,1)}px">\n'
                for cl in _gcols:
                    px = max(_col_widths.get(cl, 3.5) * 7.5, 6)
                    tbl += f'<col style="width:{px:.1f}px;min-width:{px:.1f}px">\n'
                _blabel = f'Deutschland \u2013 M\u00fcnzst\u00e4tte {mm}'
                _cs = block_colspan(bl)
                tbl += f'<tr><td class="c-country" colspan="{_cs}" style="background:#FF543E;color:#000"><div class="c-country-inner"><span class="c-name">{htmlmod.escape(_blabel)}</span></div></td></tr>\n'
                tbl += '<tr>'
                for cl in _gcols:
                    dl = DENOM_LABEL.get(cl, '')
                    val = dl
                    if val in ('1', '2'):
                        val += ' \u20ac'
                    cls = ''
                    if cl == bc['year']:
                        val = ''
                        cls = 'year-connector'
                    elif cl == bc['igap']:
                        val = ''
                        cls = 'inner-gap'
                    tbl += f'<td class="{cls}" style="font-size:7pt;text-align:center;border:1px solid #000">{htmlmod.escape(val) if val else ""}</td>'
                tbl += '</tr>\n'
                for yr_val in germany_years:
                    tbl += '<tr>'
                    for cl in _gcols:
                        if cl == bc['year']:
                            tbl += f'<td style="text-align:center;font-size:7pt;border:1px solid #000;background:#eee">{htmlmod.escape(yr_val)}</td>'
                        elif cl == bc['igap']:
                            tbl += '<td class="inner-gap">&nbsp;</td>'
                        else:
                            dk = make_denom_key(cl)
                            mentry = get_coin('Deutschland', yr_val, dk, mm)
                            val = coin_value(mentry)
                            ct = coin_cell_type(mentry)
                            _bg = _compute_cell_color('Deutschland', yr_val, dk, mint=mm, ct=ct)
                            _sty = ''
                            if ct == 'x':
                                _sty = 'background:#FFC7CE;'
                                val = '\u2715'
                            elif val and '\u2715' in val:
                                _sty = 'background:#FFC7CE;'
                            elif _bg:
                                _sty = f'background:#{_bg};'
                            _ev = htmlmod.escape(val) if val else ''
                            _fullsty = (_sty + ';' if _sty and not _sty.endswith(';') else _sty) + 'font-size:8pt;text-align:center;border:1px solid #000'
                            tbl += f'<td style="{_fullsty}">{_ev}</td>'
                    tbl += '</tr>\n'
                tbl += '</table>'
                return tbl

            for mm in mints:
                h += f'<div class="mint-box">{_mint_table_html(mm)}</div>\n'

    h += f'''<script id="mintData" type="application/json">{_mint_data_str}</script>
<script id="activeMint" type="text/plain">{htmlmod.escape(mint_arg)}</script>
<script src="/static/app.js?v={_js_hash}"></script>
</body>
</html>'''
    return h


# ─── Vor jeder Anfrage: Daten frisch halten (Redis) ───
# Auf Vercel laufen mehrere Kopien der App. Hat eine andere Kopie gespeichert,
# laden wir das Dokument neu, damit niemand alte Daten überschreibt.

def _apply_doc(d: dict) -> None:
    global doc, COINS, COINS_MINT, MINTAGE, MINTAGE_MINT, CC_NAMES, IMAGE_LINKS_MINT, FILL_COLORS, COUNTRIES, COUNTRY_YEARS, EXTENSIONS, UNDO_STACK, REDO_STACK, _COIN_YEARS
    doc = d
    COINS = doc.get('coins', {})
    COINS_MINT = doc.get('coins_mint', {})
    MINTAGE = doc.get('mintage', {})
    MINTAGE_MINT = doc.get('mintage_mint', {})
    CC_NAMES = doc.get('cc_coin_names', {})
    IMAGE_LINKS_MINT = doc.get('image_links_mint', {})
    FILL_COLORS = doc.get('fill_colors', {})
    COUNTRIES = doc.get('countries', [])
    COUNTRY_YEARS = doc.get('country_years', {})
    EXTENSIONS = doc.get('extensions', {})
    UNDO_STACK = doc.get('undo_stack', [])
    REDO_STACK = doc.get('redo_stack', [])
    _COIN_YEARS = _build_coin_years_cache()

def refresh_doc():
    if not USE_REDIS or request.endpoint in (None, 'static', 'login', 'logout'):
        return
    if _redis('GET', REDIS_VER_KEY) != _doc_ver:
        _apply_doc(load_doc())


# ─── Passwort ───
# Ist APP_PASSWORD gesetzt, muss man sich einmal anmelden (Cookie für 30 Tage).

APP_PASSWORD = os.environ.get('APP_PASSWORD', '')
app.secret_key = os.environ.get('SESSION_SECRET') or hashlib.sha256(('muenzapp:' + APP_PASSWORD).encode()).hexdigest()
app.permanent_session_lifetime = datetime.timedelta(days=30)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = bool(os.environ.get('VERCEL'))

LOGIN_HTML = '''<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Anmelden</title>
<style>body{font-family:system-ui,sans-serif;background:#f4f4f5;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
form{background:#fff;padding:28px;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);width:280px}
h1{font-size:20px;margin:0 0 16px}input,button{width:100%;box-sizing:border-box;padding:10px;font-size:16px;border-radius:8px}
input{border:1px solid #ccc;margin-bottom:12px}button{border:0;background:#222;color:#fff;cursor:pointer}
.err{color:#b00020;font-size:14px;margin:0 0 12px}</style></head><body>
<form method="post"><h1>Münz-App</h1>{err}<input type="password" name="password" placeholder="Passwort" autofocus>
<button type="submit">Anmelden</button></form></body></html>'''

@app.before_request
def require_login():
    if not APP_PASSWORD or request.endpoint in ('static', 'login') or session.get('ok'):
        return refresh_doc()
    if request.path.startswith('/api/'):
        return jsonify({'ok': False, 'error': 'Nicht angemeldet'}), 401
    return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    err = ''
    if request.method == 'POST':
        if APP_PASSWORD and hmac.compare_digest(request.form.get('password', ''), APP_PASSWORD):
            session.permanent = True
            session['ok'] = True
            return redirect('/')
        err = '<p class="err">Falsches Passwort.</p>'
    return LOGIN_HTML.replace('{err}', err)

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# ─── Routes ───

@app.route('/')
@app.route('/index.html')
def index():
    mint_arg = request.args.get('mint', '')
    layout = request.args.get('layout', '')
    if not mint_arg:
        for c in COUNTRIES:
            if c.get('mint_marks'):
                mint_arg = c['mint_marks'][0]
                break
    return generate_html(mint_arg=mint_arg, layout=layout)

@app.route('/api/cells', methods=['PATCH'])
def patch_cells():
    global COINS, COINS_MINT, UNDO_STACK, REDO_STACK
    updates = request.get_json(silent=True) or {}
    mint_arg = request.args.get('mint', '')
    for ref, new_val in updates.items():
        store, store_key, cname, is_mint = _resolve_storage(ref, mint_arg)
        p = ref.split(':')
        yr = p[1] if len(p) > 1 else ''
        dk = p[2] if len(p) > 2 else ''
        prev = store.get(store_key, {}).get('v', '')
        if prev != new_val:
            atype = 'cell_mint' if is_mint else 'cell'
            UNDO_STACK.append({'type': atype, 'ref': store_key, 'mint': mint_arg or '', 'prev': prev, 'new': new_val, 'country': cname, 'year': yr, 'denom': dk})
        if new_val:
            entry = store.setdefault(store_key, {})
            entry['v'] = new_val
        elif store_key in store:
            entry = store[store_key]
            entry.pop('v', None)
            if not entry:
                del store[store_key]
    REDO_STACK.clear()
    save_all()
    return jsonify({'ok': True, 'saved': len(updates)})

@app.route('/api/cell-types', methods=['PATCH'])
def patch_cell_types():
    global COINS, COINS_MINT, UNDO_STACK, REDO_STACK
    updates = request.get_json(silent=True) or {}
    mint_arg = request.args.get('mint', '')
    for ref, new_ct in updates.items():
        parts = ref.rsplit(':', 1)
        is_mint = len(parts) == 2 and parts[1] and len(parts[1]) == 1 and parts[1].isalpha()
        if is_mint:
            key = parts[0]
            mint = parts[1]
            p = key.rsplit(':', 2)
            cname = p[0] if len(p) > 0 else ''
            yr = p[1] if len(p) > 1 else ''
            dk = p[2] if len(p) > 2 else ''
            mkey = key + ':' + mint
            prev = COINS_MINT.get(mkey, {}).get('ct', '')
            if prev != new_ct:
                UNDO_STACK.append({'type': 'cell-type-mint', 'ref': ref, 'mint': mint, 'prev': prev, 'new': new_ct, 'country': cname, 'year': yr, 'denom': dk})
            if new_ct and new_ct != 'nodata':
                entry = COINS_MINT.setdefault(mkey, {})
                entry['ct'] = new_ct
            else:
                entry = COINS_MINT.get(mkey, {})
                entry.pop('ct', None)
                if not entry:
                    COINS_MINT.pop(mkey, None)
        else:
            store, store_key, cname, is_mint = _resolve_storage(ref, mint_arg)
            p = ref.split(':')
            yr = p[1] if len(p) > 1 else ''
            dk = p[2] if len(p) > 2 else ''
            prev = store.get(store_key, {}).get('ct', '')
            if prev != new_ct:
                atype = 'cell-type-mint' if is_mint else 'cell-type'
                UNDO_STACK.append({'type': atype, 'ref': store_key, 'mint': mint_arg or '', 'prev': prev, 'new': new_ct, 'country': cname, 'year': yr, 'denom': dk})
            if new_ct and new_ct != 'nodata':
                entry = store.setdefault(store_key, {})
                entry['ct'] = new_ct
            elif store_key in store:
                entry = store[store_key]
                entry.pop('ct', None)
                if not entry:
                    del store[store_key]
    REDO_STACK.clear()
    save_all()
    return jsonify({'ok': True, 'saved': len(updates)})

@app.route('/api/copy-cell', methods=['POST'])
def copy_cell():
    global COINS, COINS_MINT, UNDO_STACK, REDO_STACK
    body = request.get_json(silent=True) or {}
    mint_arg = request.args.get('mint', '')
    source = body.get('source_ref', '')
    targets = body.get('target_refs', [])
    if not source or not targets:
        return jsonify({'error': 'Missing source_ref or target_refs'}), 400

    def parse_ref(ref):
        parts = ref.rsplit(':', 1)
        if len(parts) == 2 and parts[1] and len(parts[1]) == 1 and parts[1].isalpha():
            return parts[0], parts[1]
        return ref, None

    src_key, src_mint = parse_ref(source)
    p = src_key.rsplit(':', 2)
    src_cname = p[0] if len(p) > 0 else ''
    src_yr = p[1] if len(p) > 1 else ''
    src_dk = p[2] if len(p) > 2 else ''

    src_entry = get_coin(src_cname, src_yr, src_dk, src_mint)
    src_val = coin_value(src_entry)
    src_ct = coin_cell_type(src_entry)

    for ref in targets:
        if ref == source:
            continue
        tgt_key, tgt_mint = parse_ref(ref)
        p2 = tgt_key.rsplit(':', 2)
        tgt_cname = p2[0] if len(p2) > 0 else ''
        tgt_yr = p2[1] if len(p2) > 1 else ''
        tgt_dk = p2[2] if len(p2) > 2 else ''

        if tgt_mint:
            mkey = tgt_key + ':' + tgt_mint
            prev_val = COINS_MINT.get(mkey, {}).get('v', '')
            prev_ct = COINS_MINT.get(mkey, {}).get('ct', '')
            if src_val != prev_val:
                UNDO_STACK.append({'type': 'cell_mint', 'ref': ref, 'mint': tgt_mint, 'prev': prev_val, 'new': src_val, 'country': tgt_cname, 'year': tgt_yr, 'denom': tgt_dk})
            if src_ct != prev_ct:
                UNDO_STACK.append({'type': 'cell-type-mint', 'ref': ref, 'mint': tgt_mint, 'prev': prev_ct, 'new': src_ct, 'country': tgt_cname, 'year': tgt_yr, 'denom': tgt_dk})
            entry = COINS_MINT.setdefault(mkey, {})
            if src_val:
                entry['v'] = src_val
            else:
                entry.pop('v', None)
            if src_ct:
                entry['ct'] = src_ct
            else:
                entry.pop('ct', None)
            if not entry:
                COINS_MINT.pop(mkey, None)
        else:
            tgt_store, tgt_store_key, tgt_cname2, is_mint = _resolve_storage(ref, mint_arg)
            prev_val = tgt_store.get(tgt_store_key, {}).get('v', '')
            prev_ct = tgt_store.get(tgt_store_key, {}).get('ct', '')
            tgt_p = ref.split(':')
            tgt_yr2 = tgt_p[1] if len(tgt_p) > 1 else ''
            tgt_dk2 = tgt_p[2] if len(tgt_p) > 2 else ''
            if src_val != prev_val:
                atype = 'cell_mint' if is_mint else 'cell'
                UNDO_STACK.append({'type': atype, 'ref': tgt_store_key, 'mint': mint_arg or '', 'prev': prev_val, 'new': src_val, 'country': tgt_cname2, 'year': tgt_yr2, 'denom': tgt_dk2})
            if src_ct != prev_ct:
                atype = 'cell-type-mint' if is_mint else 'cell-type'
                UNDO_STACK.append({'type': atype, 'ref': tgt_store_key, 'mint': mint_arg or '', 'prev': prev_ct, 'new': src_ct, 'country': tgt_cname2, 'year': tgt_yr2, 'denom': tgt_dk2})
            entry = tgt_store.setdefault(tgt_store_key, {})
            if src_val:
                entry['v'] = src_val
            else:
                entry.pop('v', None)
            if src_ct:
                entry['ct'] = src_ct
            else:
                entry.pop('ct', None)
            if not entry:
                del tgt_store[tgt_store_key]
    REDO_STACK.clear()
    save_all()
    return jsonify({'ok': True, 'copied': len(targets)})

@app.route('/api/batch-edit', methods=['POST'])
def batch_edit():
    global COINS, COINS_MINT, UNDO_STACK, REDO_STACK
    body = request.get_json(silent=True) or {}
    mint_arg = request.args.get('mint', '')
    refs = body.get('refs', [])
    new_ct = body.get('cell_type')
    new_val = body.get('coin_value')
    has_ct = 'cell_type' in body
    has_val = 'coin_value' in body
    if not refs or (not has_ct and not has_val):
        return jsonify({'error': 'Provide refs and cell_type and/or coin_value'}), 400

    for ref in refs:
        parts = ref.rsplit(':', 1)
        is_mint = len(parts) == 2 and parts[1] and len(parts[1]) == 1 and parts[1].isalpha()

        if is_mint:
            key = parts[0]
            mint = parts[1]
            mkey = key + ':' + mint
            p = key.rsplit(':', 2)
            cname = p[0] if len(p) > 0 else ''
            yr = p[1] if len(p) > 1 else ''
            dk = p[2] if len(p) > 2 else ''
            if has_ct:
                prev_ct = COINS_MINT.get(mkey, {}).get('ct', '')
                if prev_ct != new_ct:
                    UNDO_STACK.append({'type': 'cell-type-mint', 'ref': ref, 'mint': mint, 'prev': prev_ct, 'new': new_ct or '', 'country': cname, 'year': yr, 'denom': dk})
                if new_ct and new_ct != 'nodata':
                    entry = COINS_MINT.setdefault(mkey, {})
                    entry['ct'] = new_ct
                else:
                    entry = COINS_MINT.get(mkey, {})
                    entry.pop('ct', None)
                    if not entry:
                        COINS_MINT.pop(mkey, None)
            if has_val:
                prev_val = COINS_MINT.get(mkey, {}).get('v', '')
                if prev_val != new_val:
                    UNDO_STACK.append({'type': 'cell_mint', 'ref': ref, 'mint': mint, 'prev': prev_val, 'new': new_val or '', 'country': cname, 'year': yr, 'denom': dk})
                if new_val:
                    entry = COINS_MINT.setdefault(mkey, {})
                    entry['v'] = new_val
                else:
                    entry = COINS_MINT.get(mkey, {})
                    entry.pop('v', None)
                    if not entry:
                        COINS_MINT.pop(mkey, None)
        else:
            store, store_key, cname, is_mint = _resolve_storage(ref, mint_arg)
            p = ref.split(':')
            yr = p[1] if len(p) > 1 else ''
            dk = p[2] if len(p) > 2 else ''
            if has_ct:
                prev_ct = store.get(store_key, {}).get('ct', '')
                if prev_ct != new_ct:
                    atype = 'cell-type-mint' if is_mint else 'cell-type'
                    UNDO_STACK.append({'type': atype, 'ref': store_key, 'mint': mint_arg or '', 'prev': prev_ct, 'new': new_ct or '', 'country': cname, 'year': yr, 'denom': dk})
                if new_ct and new_ct != 'nodata':
                    entry = store.setdefault(store_key, {})
                    entry['ct'] = new_ct
                elif store_key in store:
                    entry = store[store_key]
                    entry.pop('ct', None)
                    if not entry:
                        del store[store_key]
            if has_val:
                prev_val = store.get(store_key, {}).get('v', '')
                if prev_val != new_val:
                    atype = 'cell_mint' if is_mint else 'cell'
                    UNDO_STACK.append({'type': atype, 'ref': store_key, 'mint': mint_arg or '', 'prev': prev_val, 'new': new_val or '', 'country': cname, 'year': yr, 'denom': dk})
                if new_val:
                    entry = store.setdefault(store_key, {})
                    entry['v'] = new_val
                elif store_key in store:
                    entry = store[store_key]
                    entry.pop('v', None)
                    if not entry:
                        del COINS[key]
    REDO_STACK.clear()
    save_all()
    return jsonify({'ok': True, 'updated': len(refs)})

@app.route('/api/add-year', methods=['POST'])
def add_year():
    global EXTENSIONS, UNDO_STACK, REDO_STACK
    body = request.get_json(silent=True) or {}
    bl = body.get('block')
    cname = body.get('country')
    year = body.get('year', '')
    if not bl or not cname or not year:
        return jsonify({'error': 'Missing block, country, or year'}), 400

    found = any(c['name'] == cname for c in COUNTRIES)
    if not found:
        return jsonify({'error': 'Country not found'}), 404

    elist = EXTENSIONS.setdefault(cname, [])
    if year in elist:
        return jsonify({'error': 'Year already added'}), 409
    UNDO_STACK.append({'type': 'add-year', 'block': bl, 'country': cname, 'year': year})
    REDO_STACK.clear()
    elist.append(year)
    elist.sort(key=_year_sort_key)
    # Auto-generate image links for the new year
    cname_en = ''
    for c in COUNTRIES:
        if c['name'] == cname:
            cname_en = c.get('image_name_en', '')
            break
    if cname_en:
        for dk in ['1c','2c','5c','10c','20c','50c','1\u20ac','2\u20ac','CC1','CC2','CC3']:
            ck = coin_key(cname, year, dk)
            if ck not in COINS or not coin_image(COINS.get(ck, {})):
                url = image_url_for(cname, year, dk)
                if url:
                    entry = COINS.setdefault(ck, {})
                    if not entry.get('img'):
                        entry['img'] = url

    save_all()
    return jsonify({'ok': True, 'year': year})

@app.route('/api/remove-year', methods=['POST'])
def remove_year():
    global EXTENSIONS, UNDO_STACK, REDO_STACK, COINS, COINS_MINT, MINTAGE, MINTAGE_MINT, CC_NAMES, IMAGE_LINKS_MINT, _COIN_YEARS
    body = request.get_json(silent=True) or {}
    bl = body.get('block')
    cname = body.get('country')
    year = body.get('year', '')
    if not bl or not cname or not year:
        return jsonify({'error': 'Missing block, country, or year'}), 400

    found = any(c['name'] == cname for c in COUNTRIES)
    if not found:
        return jsonify({'error': 'Country not found'}), 404

    prefix = cname + ':' + year

    # Save deleted data for undo
    deleted = {}
    for d, name in [(COINS, 'coins'), (MINTAGE, 'mintage'), (COINS_MINT, 'coins_mint'),
                    (MINTAGE_MINT, 'mintage_mint'), (IMAGE_LINKS_MINT, 'image_links_mint')]:
        entries = {k: v for k, v in d.items() if k.startswith(prefix + ':')}
        if entries:
            deleted[name] = entries
    cc_entries = {k: v for k, v in CC_NAMES.items() if k.startswith(prefix + ':')}
    if cc_entries:
        deleted['cc_names'] = cc_entries

    UNDO_STACK.append({'type': 'remove-year', 'block': bl, 'country': cname, 'year': year, 'deleted': deleted})
    REDO_STACK.clear()

    # Remove from extensions
    elist = EXTENSIONS.get(cname, [])
    if year in elist:
        elist.remove(year)
    if not elist:
        EXTENSIONS.pop(cname, None)

    # Delete all coin data for this country + year
    for d in (COINS, MINTAGE):
        for k in list(d.keys()):
            if k.startswith(prefix + ':'):
                del d[k]
    for d in (COINS_MINT, MINTAGE_MINT, IMAGE_LINKS_MINT):
        for k in list(d.keys()):
            if k.startswith(prefix + ':'):
                del d[k]
    for k in list(CC_NAMES.keys()):
        if k.startswith(prefix + ':'):
            del CC_NAMES[k]

    # Rebuild coin years cache
    _COIN_YEARS = _build_coin_years_cache()

    save_all()
    return jsonify({'ok': True, 'year': year})

@app.route('/api/next-year', methods=['GET'])
def next_year():
    bl = request.args.get('block', '')
    cname = request.args.get('country', '')
    max_y = 0
    for y in COUNTRY_YEARS.get(cname, []):
        if y.isdigit():
            max_y = max(max_y, int(y))
    for ey in EXTENSIONS.get(cname, []):
        if ey.isdigit():
            max_y = max(max_y, int(ey))
    return jsonify({'nextYear': str(max_y + 1) if max_y else '2027'})

@app.route('/api/coin-info', methods=['PATCH'])
def patch_coin_info():
    global COINS, COINS_MINT, MINTAGE, MINTAGE_MINT, IMAGE_LINKS_MINT
    mint_arg = request.args.get('mint', '')
    updates = request.get_json(silent=True) or {}
    for ref, info in updates.items():
        if isinstance(info, dict):
            link = info.get('link', '')
            mintage_val = info.get('mintage', '')
            parts = ref.rsplit(':', 1)
            is_mint = len(parts) == 2 and parts[1] and len(parts[1]) == 1 and parts[1].isalpha() and parts[0].count(':') >= 2
            if is_mint:
                key = parts[0]
                mint = parts[1]
                mkey = key + ':' + mint
                if mintage_val:
                    MINTAGE_MINT[mkey] = mintage_val
                else:
                    MINTAGE_MINT.pop(mkey, None)
                if link:
                    mentry = COINS_MINT.setdefault(mkey, {})
                    mentry['img'] = link
                elif mkey in COINS_MINT:
                    mentry = COINS_MINT.get(mkey, {})
                    mentry.pop('img', None)
                    if not mentry:
                        COINS_MINT.pop(mkey, None)
            else:
                store, store_key, cname, use_mint = _resolve_storage(ref, mint_arg)
                mnkey = store_key
                mmkey = store_key
                if use_mint:
                    if mintage_val:
                        MINTAGE_MINT[mmkey] = mintage_val
                    else:
                        MINTAGE_MINT.pop(mmkey, None)
                    if link:
                        mentry = COINS_MINT.setdefault(mmkey, {})
                        mentry['img'] = link
                    elif mmkey in COINS_MINT:
                        mentry = COINS_MINT.get(mmkey, {})
                        mentry.pop('img', None)
                        if not mentry:
                            COINS_MINT.pop(mmkey, None)
                else:
                    if mintage_val:
                        MINTAGE[ref] = mintage_val
                    else:
                        MINTAGE.pop(ref, None)
                    if link:
                        entry = COINS.setdefault(ref, {})
                        entry['img'] = link
                    elif ref in COINS:
                        entry = COINS[ref]
                        entry.pop('img', None)
                        if not entry:
                            del COINS[ref]
    save_all()
    return jsonify({'ok': True})

@app.route('/api/undo', methods=['POST'])
def undo():
    global UNDO_STACK, REDO_STACK, COINS, COINS_MINT, EXTENSIONS, MINTAGE, MINTAGE_MINT, IMAGE_LINKS_MINT, CC_NAMES, _COIN_YEARS
    if not UNDO_STACK:
        return jsonify({'error': 'Nothing to undo'}), 400
    action = UNDO_STACK.pop()
    REDO_STACK.append(action)
    if action['type'] == 'cell':
        ref = action['ref']
        prev = action['prev']
        if prev:
            entry = COINS.setdefault(ref, {})
            entry['v'] = prev
        elif ref in COINS:
            entry = COINS[ref]
            entry.pop('v', None)
            if not entry:
                del COINS[ref]
    elif action['type'] == 'cell_mint':
        ref = action['ref']
        mint = action.get('mint', '')
        mkey = ref + ':' + mint
        prev = action['prev']
        if prev:
            entry = COINS_MINT.setdefault(mkey, {})
            entry['v'] = prev
        elif mkey in COINS_MINT:
            entry = COINS_MINT[mkey]
            entry.pop('v', None)
            if not entry:
                del COINS_MINT[mkey]
    elif action['type'] == 'add-year':
        cname = action['country']
        year = action['year']
        elist = EXTENSIONS.get(cname, [])
        if year in elist:
            elist.remove(year)
        if not elist:
            EXTENSIONS.pop(cname, None)
    elif action['type'] == 'remove-year':
        cname = action['country']
        year = action['year']
        deleted = action.get('deleted', {})
        elist = EXTENSIONS.setdefault(cname, [])
        if year not in elist:
            elist.append(year)
            elist.sort(key=_year_sort_key)
        # Restore deleted data
        _map = {'coins': COINS, 'mintage': MINTAGE, 'coins_mint': COINS_MINT,
                'mintage_mint': MINTAGE_MINT, 'image_links_mint': IMAGE_LINKS_MINT}
        for name, entries in deleted.items():
            if name in _map:
                _map[name].update(entries)
            elif name == 'cc_names':
                CC_NAMES.update(entries)
        _COIN_YEARS = _build_coin_years_cache()
    elif action['type'] == 'cell-type':
        ref = action['ref']
        prev = action['prev']
        if prev and prev != 'nodata':
            entry = COINS.setdefault(ref, {})
            entry['ct'] = prev
        elif ref in COINS:
            entry = COINS[ref]
            entry.pop('ct', None)
            if not entry:
                del COINS[ref]
    elif action['type'] == 'cell-type-mint':
        ref = action['ref']
        mint = action.get('mint', '')
        mkey = ref + ':' + mint
        prev = action['prev']
        if prev and prev != 'nodata':
            entry = COINS_MINT.setdefault(mkey, {})
            entry['ct'] = prev
        elif mkey in COINS_MINT:
            entry = COINS_MINT[mkey]
            entry.pop('ct', None)
            if not entry:
                del COINS_MINT[mkey]
    save_all()
    return jsonify({'ok': True, 'undone': action['type'], 'ref': action.get('ref', '')})

@app.route('/api/redo', methods=['POST'])
def redo():
    global UNDO_STACK, REDO_STACK, COINS, COINS_MINT, EXTENSIONS, MINTAGE, MINTAGE_MINT, IMAGE_LINKS_MINT, CC_NAMES, _COIN_YEARS
    if not REDO_STACK:
        return jsonify({'error': 'Nothing to redo'}), 400
    action = REDO_STACK.pop()
    UNDO_STACK.append(action)
    if action['type'] == 'cell':
        ref = action['ref']
        new_val = action.get('new', '')
        if new_val:
            entry = COINS.setdefault(ref, {})
            entry['v'] = new_val
        elif ref in COINS:
            entry = COINS[ref]
            entry.pop('v', None)
            if not entry:
                del COINS[ref]
    elif action['type'] == 'cell_mint':
        ref = action['ref']
        mint = action.get('mint', '')
        mkey = ref + ':' + mint
        new_val = action.get('new', '')
        if new_val:
            entry = COINS_MINT.setdefault(mkey, {})
            entry['v'] = new_val
        elif mkey in COINS_MINT:
            entry = COINS_MINT[mkey]
            entry.pop('v', None)
            if not entry:
                del COINS_MINT[mkey]
    elif action['type'] == 'add-year':
        cname = action['country']
        year = action['year']
        elist = EXTENSIONS.setdefault(cname, [])
        if year not in elist:
            elist.append(year)
            elist.sort(key=_year_sort_key)
    elif action['type'] == 'remove-year':
        cname = action['country']
        year = action['year']
        prefix = cname + ':' + year
        elist = EXTENSIONS.get(cname, [])
        if year in elist:
            elist.remove(year)
        if not elist:
            EXTENSIONS.pop(cname, None)
        for d in (COINS, MINTAGE):
            for k in list(d.keys()):
                if k.startswith(prefix + ':'):
                    del d[k]
        for d in (COINS_MINT, MINTAGE_MINT, IMAGE_LINKS_MINT):
            for k in list(d.keys()):
                if k.startswith(prefix + ':'):
                    del d[k]
        for k in list(CC_NAMES.keys()):
            if k.startswith(prefix + ':'):
                del CC_NAMES[k]
        _COIN_YEARS = _build_coin_years_cache()
    elif action['type'] == 'cell-type':
        ref = action['ref']
        new_ct = action['new']
        if new_ct and new_ct != 'nodata':
            entry = COINS.setdefault(ref, {})
            entry['ct'] = new_ct
        elif ref in COINS:
            entry = COINS[ref]
            entry.pop('ct', None)
            if not entry:
                del COINS[ref]
    elif action['type'] == 'cell-type-mint':
        ref = action['ref']
        mint = action.get('mint', '')
        mkey = ref + ':' + mint
        new_ct = action['new']
        if new_ct and new_ct != 'nodata':
            entry = COINS_MINT.setdefault(mkey, {})
            entry['ct'] = new_ct
        elif mkey in COINS_MINT:
            entry = COINS_MINT[mkey]
            entry.pop('ct', None)
            if not entry:
                del COINS_MINT[mkey]
    save_all()
    return jsonify({'ok': True, 'redone': action['type'], 'ref': action.get('ref', '')})

def _action_desc(action):
    t = action['type']
    cn = action.get('country', '')
    yr = action.get('year', '')
    dl = action.get('denom', '')
    mint = action.get('mint', '')
    parts = [p for p in (cn, dl, yr) if p]
    base = ' '.join(parts) if parts else action.get('ref', t)
    if t in ('cell', 'cell-type', 'cell_mint', 'cell-type-mint'):
        if mint:
            base += f' ({mint})'
        return base
    elif t == 'add-year':
        return f"Jahr {action['year']} ({action['country']})"
    elif t == 'remove-year':
        return f"Jahr {action['year']} entfernen ({action['country']})"
    return t

@app.route('/api/undo-preview', methods=['GET'])
def undo_preview():
    if not UNDO_STACK:
        return jsonify({'desc': ''})
    return jsonify({'desc': _action_desc(UNDO_STACK[-1])})

@app.route('/api/redo-preview', methods=['GET'])
def redo_preview():
    if not REDO_STACK:
        return jsonify({'desc': ''})
    return jsonify({'desc': _action_desc(REDO_STACK[-1])})

@app.route('/api/breakdown')
def api_breakdown():
    mint_arg = request.args.get('mint', '')
    _S = _compute_all_stats(mint_arg)
    _rows = [{'label': d, 'count': _S['denom_counts'][d], 'cents': _S['denom_counts'][d] * _S['denom_val_cents'][d]}
             for d in ('1c','2c','5c','10c','20c','50c','1\u20ac','2\u20ac','CC')
             if _S['denom_counts'][d]]
    return jsonify({
        'breakdown': _rows, 'totalCents': _S['total_cents'],
        'countryStats': _S['country_stats'], 'globalCellStats': _S['global_cell'],
        'regDenomStats': _S['reg_denom'], 'nifcDenomStats': _S['nifc_denom'],
    })

@app.route('/api/missing')
def api_missing():
    _missing = []
    for c in COUNTRIES:
        cname = c['name']
        bl = c['block']
        mints = c.get('mint_marks', [])
        yrs = get_years(cname)
        for yr in yrs:
            for dk in ['1c','2c','5c','10c','20c','50c','1\u20ac','2\u20ac']:
                entry = get_coin(cname, yr, dk)
                val = coin_value(entry)
                ct = coin_cell_type(entry)
                if ct == 'nifc' or ct == 'x':
                    continue
                fl = _compute_cell_color(cname, yr, dk, ct=ct)
                if fl == 'FFC7CE':
                    continue
                if not val or val.strip() in ('\u2715', '\u00d7'):
                    _missing.append({'block': bl, 'country': cname, 'year': yr, 'denom': dk})
    _missing.sort(key=lambda x: (x['country'], x['year'], x['denom']))
    return jsonify({'missing': _missing})

@app.route('/api/export/xlsx', methods=['GET'])
def export_xlsx():
    mint_arg = request.args.get('mint', '')
    layout = request.args.get('layout', '')
    split_germany = layout == 'split'
    segments = compute_segments()
    wb = Workbook()
    ws = wb.active
    ws.title = 'M\u00fcnzApp'

    thin_black = Border(left=Side(style='thin',color='000000'), right=Side(style='thin',color='000000'), top=Side(style='thin',color='000000'), bottom=Side(style='thin',color='000000'))
    no_border = Border()
    def cell_fill(hex_color):
        return PatternFill(start_color=hex_color, end_color=hex_color, fill_type='solid') if hex_color else PatternFill(fill_type=None)
    _ct_fills = {
        'green': cell_fill('C5DEB5'), 'blue': cell_fill('8EAADB'), 'orange': cell_fill('FF8C42'),
        'yellow': cell_fill('FFE598'), 'nifc': cell_fill('FFC7CE'), 'x': cell_fill('FFC7CE'),
    }
    red_fill = cell_fill('FF543E')
    gray_fill = cell_fill('EEEEEE')
    cen = Alignment(horizontal='center', vertical='center', wrapText=False)
    left_ali = Alignment(horizontal='left', vertical='center', wrapText=False)

    def col_for_code(blk, code):
        return COLS_ORDER.index(code) + 1 if code in COLS_ORDER else None

    def block_colspan(bl):
        return len(make_block_ordered_cols(bl))

    # Column widths to match HTML
    _col_widths = {
        'A':5.5, 'B':3.75, 'C':3.54, 'D':3.54, 'E':3.54, 'F':3.54, 'G':3.54, 'H':3.54, 'I':3.54,
        'J':0.66, 'K':3.54, 'L':3.54, 'M':3.54, 'N':5.66, 'O':5.16,
        'P':3.54, 'Q':3.54, 'R':3.54, 'S':3.75, 'T':3.54, 'U':3.54, 'V':3.54, 'W':3.54,
        'X':0.66, 'Y':3.54, 'Z':3.54, 'AA':3.54, 'AB':5.66, 'AC':5.16,
        'AD':3.54, 'AE':3.54, 'AF':3.54, 'AG':3.54, 'AH':3.54, 'AI':3.54, 'AJ':3.54, 'AK':3.75,
        'AL':0.66, 'AM':3.54, 'AN':3.54, 'AO':3.54, 'AP':5.66,
    }
    for code, w in _col_widths.items():
        if code in COLS_ORDER:
            ws.column_dimensions[code].width = max(w * 0.75, 1.5)

    row_num = 0
    _last_dr_blk = {}
    for seg in segments:
        entries = seg['entries']
        max_years = seg['max_years']
        seg_start = row_num + 1

        # Gap row between segments if needed
        _need_gap = False
        for bl in ('A', 'O', 'AC'):
            if _last_dr_blk.get(bl, 0) == seg_start - 1:
                if any(e['block'] == bl for e in entries):
                    _need_gap = True
                    break
        if _need_gap:
            row_num += 1
            for ci in range(1, len(COLS_ORDER) + 1):
                ws.cell(row=row_num, column=ci).border = no_border

        row_num += 1
        # Country header row — merge across block columns like HTML colspan
        for bl in ('A', 'O', 'AC'):
            bc = BLOCK_COLS[bl]
            found = [e for e in entries if e['block'] == bl]
            yr_col = col_for_code(bl, bc['year'])
            span = block_colspan(bl)
            if found:
                c = found[0]['country']
                start_col = yr_col
                end_col = yr_col + span - 1
                ws.merge_cells(start_row=row_num, start_column=start_col, end_row=row_num, end_column=end_col)
                cell = ws.cell(row=row_num, column=start_col)
                cell.value = c['name']
                cell.fill = red_fill
                cell.font = Font(bold=True, italic=True, size=10, name='Calibri')
                cell.alignment = left_ali
                cell.border = thin_black
                # Apply border to all cells in merge range
                for cc in range(start_col, end_col + 1):
                    ws.cell(row=row_num, column=cc).border = thin_black
            else:
                for cc in range(yr_col, yr_col + span):
                    ws.cell(row=row_num, column=cc).border = no_border
            # Gap column after block
            if bl == 'A':
                ws.cell(row=row_num, column=col_for_code(None, GAP_COLS['A_O'])).border = no_border
            elif bl == 'O':
                ws.cell(row=row_num, column=col_for_code(None, GAP_COLS['O_AC'])).border = no_border

        row_num += 1
        # Column header row
        for bl in ('A', 'O', 'AC'):
            bc = BLOCK_COLS[bl]
            found = [e for e in entries if e['block'] == bl]
            yr_col = col_for_code(bl, bc['year'])
            for cl in make_block_ordered_cols(bl):
                ci = col_for_code(bl, cl)
                cell = ws.cell(row=row_num, column=ci)
                dl = DENOM_LABEL.get(cl, '')
                if cl == bc['year']:
                    # Year connector — keep empty with no border, like HTML year-connector
                    cell.border = thin_black
                    cell.fill = PatternFill(fill_type=None)
                elif cl == bc['igap']:
                    cell.border = no_border
                else:
                    cell.value = (dl + ' \u20ac') if dl in ('1','2') else dl
                    cell.font = Font(size=8, name='Arial')
                    cell.alignment = cen
                    cell.border = thin_black
            if bl == 'A':
                ws.cell(row=row_num, column=col_for_code(None, GAP_COLS['A_O'])).border = no_border
            elif bl == 'O':
                ws.cell(row=row_num, column=col_for_code(None, GAP_COLS['O_AC'])).border = no_border

        # Data rows
        for yr_idx in range(max_years):
            row_num += 1
            for bl in ('A', 'O', 'AC'):
                bc = BLOCK_COLS[bl]
                found = [e for e in entries if e['block'] == bl]
                yr_col = col_for_code(bl, bc['year'])
                if found:
                    c = found[0]['country']
                    cname = c['name']
                    mints = c.get('mint_marks', [])
                    yrs = found[0]['years']
                    active_mint = mint_arg if mint_arg in mints else (mints[0] if mints else None)
                    for cl in make_block_ordered_cols(bl):
                        ci = col_for_code(bl, cl)
                        cell = ws.cell(row=row_num, column=ci)
                        cell.alignment = cen
                        if cl == bc['year']:
                            if yr_idx < len(yrs):
                                cell.value = yrs[yr_idx]
                                cell.font = Font(size=8, name='Arial')
                                cell.fill = gray_fill
                                cell.border = thin_black
                            else:
                                cell.border = no_border
                        elif cl == bc['igap']:
                            cell.border = no_border
                        else:
                            dk = make_denom_key(cl)
                            if yr_idx < len(yrs):
                                yr_val = yrs[yr_idx]
                                if split_germany and cname == 'Deutschland':
                                    cell.font = Font(size=8, name='Arial')
                                    cell.border = thin_black
                                else:
                                    entry = get_coin(cname, yr_val, dk)
                                    mval = ''
                                    mct = ''
                                    if mints and active_mint:
                                        mentry = get_coin(cname, yr_val, dk, active_mint)
                                        mval = coin_value(mentry)
                                        mct = coin_cell_type(mentry)
                                    val = mval if mval else coin_value(entry)
                                    ct = mct if mct else coin_cell_type(entry)
                                    if ct == 'x':
                                        cell.value = '\u2715'
                                    elif val:
                                        cell.value = val
                                    cell.font = Font(size=8, name='Arial')
                                    cell.border = thin_black
                                    if ct in _ct_fills:
                                        cell.fill = _ct_fills[ct]
                                    else:
                                        bg = _compute_cell_color(cname, yr_val, dk, ct=ct)
                                        if bg:
                                            cell.fill = cell_fill(bg)
                            else:
                                cell.border = no_border
                else:
                    span = block_colspan(bl)
                    for cc in range(yr_col, yr_col + span):
                        ws.cell(row=row_num, column=cc).border = no_border
                if bl == 'A':
                    ws.cell(row=row_num, column=col_for_code(None, GAP_COLS['A_O'])).border = no_border
                elif bl == 'O':
                    ws.cell(row=row_num, column=col_for_code(None, GAP_COLS['O_AC'])).border = no_border

        # Track last data row for gap detection
        for bl in ('A', 'O', 'AC'):
            found = [e for e in entries if e['block'] == bl]
            if found and found[0]['years']:
                _last_dr_blk[bl] = row_num

    # ── Germany mint sections (split layout, 3+2 grid) ──
    if split_germany:
        germany = next((c for c in COUNTRIES if c['name'] == 'Deutschland'), None)
        if germany:
            bl = germany['block']
            bc = BLOCK_COLS[bl]
            mints = germany.get('mint_marks', [])
            germany_years = get_years('Deutschland')
            bl_cols = make_block_ordered_cols(bl)
            bl_yr_col = col_for_code(bl, bc['year'])
            bl_span = block_colspan(bl)

            col_gap = 1
            mint_width = bl_span
            col_offsets = [1 - bl_yr_col, 1 - bl_yr_col + mint_width + col_gap, 1 - bl_yr_col + 2 * (mint_width + col_gap)]
            rows_per_mint = 3 + len(germany_years)  # gap + header + col_header + data

            # Top gap row
            row_num += 1
            grid_base = row_num

            def _write_mint_grid_cell(mm, co, base_r):
                # Gap row
                for cl in bl_cols:
                    ci = col_for_code(bl, cl) + co
                    ws.cell(row=base_r, column=ci).border = no_border
                # Country header
                hr = base_r + 1
                sc = bl_yr_col + co
                ec = sc + mint_width - 1
                ws.merge_cells(start_row=hr, start_column=sc, end_row=hr, end_column=ec)
                cell = ws.cell(row=hr, column=sc)
                cell.value = f'Deutschland \u2013 M\u00fcnzst\u00e4tte {mm}'
                cell.fill = red_fill
                cell.font = Font(bold=True, italic=True, size=10, name='Calibri')
                cell.alignment = left_ali
                cell.border = thin_black
                for cc in range(sc, ec + 1):
                    ws.cell(row=hr, column=cc).border = thin_black
                # Column header
                chr = base_r + 2
                for cl in bl_cols:
                    ci = col_for_code(bl, cl) + co
                    cell = ws.cell(row=chr, column=ci)
                    dl = DENOM_LABEL.get(cl, '')
                    if cl == bc['year']:
                        cell.border = thin_black
                        cell.fill = PatternFill(fill_type=None)
                    elif cl == bc['igap']:
                        cell.border = no_border
                    else:
                        cell.value = (dl + ' \u20ac') if dl in ('1','2') else dl
                        cell.font = Font(size=8, name='Arial')
                        cell.alignment = cen
                        cell.border = thin_black
                # Data rows
                for yi, yr_val in enumerate(germany_years):
                    dr = base_r + 3 + yi
                    for cl in bl_cols:
                        ci = col_for_code(bl, cl) + co
                        cell = ws.cell(row=dr, column=ci)
                        cell.alignment = cen
                        if cl == bc['year']:
                            cell.value = yr_val
                            cell.font = Font(size=8, name='Arial')
                            cell.fill = gray_fill
                            cell.border = thin_black
                        elif cl == bc['igap']:
                            cell.border = no_border
                        else:
                            dk = make_denom_key(cl)
                            mentry = get_coin('Deutschland', yr_val, dk, mm)
                            val = coin_value(mentry)
                            ct = coin_cell_type(mentry)
                            if ct == 'x':
                                cell.value = '\u2715'
                            elif val:
                                cell.value = val
                            cell.font = Font(size=8, name='Arial')
                            cell.border = thin_black
                            if ct in _ct_fills:
                                cell.fill = _ct_fills[ct]
                            else:
                                bg = _compute_cell_color('Deutschland', yr_val, dk, mint=mm, ct=ct)
                                if bg:
                                    cell.fill = cell_fill(bg)

            # Row 1: A, D, F
            for idx, mm in enumerate(['A', 'D', 'F']):
                _write_mint_grid_cell(mm, col_offsets[idx], grid_base)
            # Row 2: G, J
            row2_base = grid_base + rows_per_mint
            for idx, mm in enumerate(['G', 'J']):
                _write_mint_grid_cell(mm, col_offsets[idx], row2_base)

            row_num = row2_base + rows_per_mint - 1

    # Gap after last segment
    row_num += 1
    for ci in range(1, len(COLS_ORDER) + 1):
        ws.cell(row=row_num, column=ci).border = no_border

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='muenzapp.xlsx')

_DENOM_SORT = {d: i for i, d in enumerate(['1c','2c','5c','10c','20c','50c','1\u20ac','2\u20ac','CC1','CC2','CC3'])}

def _coin_sort_key(item):
    k = item[0]
    country, year, denom = k.rsplit(':', 2)
    try:
        iy = int(year)
    except ValueError:
        iy = 9999
    return (country, iy, _DENOM_SORT.get(denom, 99))

@app.route('/api/export/data', methods=['GET'])
def export_data():
    out_coins = {}
    for k, v in sorted(COINS.items(), key=_coin_sort_key):
        entry = dict(v)
        if k in MINTAGE:
            entry['m'] = MINTAGE[k]
        denom = k.rsplit(':', 2)[2]
        if denom.startswith('CC'):
            ccn = CC_NAMES.get(k)
            if ccn:
                entry['cn'] = ccn
        out_coins[k] = entry
    out_coins_mint = {}
    for k, v in sorted(COINS_MINT.items(), key=_coin_sort_key):
        entry = dict(v)
        if k in MINTAGE_MINT:
            entry['m'] = MINTAGE_MINT[k]
        denom = k.rsplit(':', 2)[2]
        if denom.startswith('CC'):
            ccn = CC_NAMES.get(k)
            if ccn:
                entry['cn'] = ccn
        out_coins_mint[k] = entry
    payload = {
        'coins': out_coins,
        'coins_mint': out_coins_mint,
        'extensions': EXTENSIONS,
        'countries': COUNTRIES,
        'country_years': COUNTRY_YEARS,
    }
    fname = f'muenzapp-backup-{datetime.date.today().isoformat()}.txt'
    return (json.dumps(payload, ensure_ascii=False, indent=2),
            200, {'Content-Type': 'text/plain; charset=utf-8', 'Content-Disposition': f'attachment; filename="{fname}"'})

@app.route('/api/import/data', methods=['POST'])
def import_data():
    global doc, COINS, COINS_MINT, MINTAGE, MINTAGE_MINT, CC_NAMES, IMAGE_LINKS_MINT, FILL_COLORS, COUNTRIES, COUNTRY_YEARS, EXTENSIONS, UNDO_STACK, REDO_STACK
    raw = request.get_data(as_text=True)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return jsonify({'ok': False, 'error': 'Ung\u00fcltiges JSON'}), 400
    if not isinstance(payload, dict):
        return jsonify({'ok': False, 'error': 'Erwartet ein JSON-Objekt'}), 400

    _expected_types = {
        'coins': dict, 'coins_mint': dict, 'mintage': dict, 'mintage_mint': dict,
        'cc_coin_names': dict, 'image_links_mint': dict, 'fill_colors': dict,
        'countries': list, 'country_years': dict, 'extensions': dict,
    }
    targets = ['coins','coins_mint','mintage','mintage_mint','cc_coin_names','image_links_mint','countries','country_years','extensions','fill_colors']
    for k in payload:
        if k not in targets:
            return jsonify({'ok': False, 'error': f'Unbekannter Schl\u00fcssel: {k}'}), 400
    for k in targets:
        if k in payload:
            expected = _expected_types.get(k)
            if expected and not isinstance(payload[k], expected):
                return jsonify({'ok': False, 'error': f'{k}: erwartet {expected.__name__}, bekam {type(payload[k]).__name__}'}), 400
            doc[k] = payload[k]
    doc['undo_stack'] = []
    doc['redo_stack'] = []
    COINS = doc.get('coins', {})
    COINS_MINT = doc.get('coins_mint', {})
    MINTAGE = doc.get('mintage', {})
    MINTAGE_MINT = doc.get('mintage_mint', {})
    CC_NAMES = doc.get('cc_coin_names', {})
    IMAGE_LINKS_MINT = doc.get('image_links_mint', {})
    FILL_COLORS = doc.get('fill_colors', {})
    COUNTRIES = doc.get('countries', [])
    COUNTRY_YEARS = doc.get('country_years', {})
    EXTENSIONS = doc.get('extensions', {})
    UNDO_STACK = doc.get('undo_stack', [])
    REDO_STACK = doc.get('redo_stack', [])
    # Extract mintage from coin entries (new-format export compatibility)
    for k, v in COINS.items():
        if isinstance(v, dict) and 'm' in v:
            MINTAGE[k] = v['m']
    for k, v in COINS_MINT.items():
        if isinstance(v, dict) and 'm' in v:
            MINTAGE_MINT[k] = v['m']
    doc['mintage'] = MINTAGE
    doc['mintage_mint'] = MINTAGE_MINT
    # Extract CC names from coin entries (new-format export compatibility)
    for k, v in COINS.items():
        if isinstance(v, dict) and 'cn' in v:
            CC_NAMES[k] = v['cn']
    for k, v in COINS_MINT.items():
        if isinstance(v, dict) and 'cn' in v:
            CC_NAMES[k] = v['cn']
    doc['cc_coin_names'] = CC_NAMES
    global _COIN_YEARS
    _COIN_YEARS = _build_coin_years_cache()
    save_doc(doc)
    return jsonify({'ok': True})


# ─── Country CRUD ───

@app.route('/api/countries', methods=['POST'])
def create_country():
    global COUNTRIES
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    bl = data.get('block', 'A')
    flag = data.get('flag', '')
    if not name:
        return jsonify({'error': 'Name required'}), 400
    if any(c['name'] == name for c in COUNTRIES):
        return jsonify({'error': 'Country already exists'}), 409
    max_order = max((c.get('display_order', 0) for c in COUNTRIES), default=-1) + 1
    new_c = {
        'name': name,
        'block': bl,
        'all_blocks': [bl],
        'flag': flag,
        'mint_marks': data.get('mint_marks', []),
        'image_name_en': data.get('image_name_en', ''),
        'display_order': max_order,
    }
    COUNTRIES.append(new_c)
    COUNTRY_YEARS[name] = []
    save_all()
    return jsonify({'ok': True, 'country': new_c})

@app.route('/api/countries', methods=['GET'])
def list_countries():
    ordered = sorted(COUNTRIES, key=lambda c: c.get('display_order', 0))
    return jsonify([{
        'name': c['name'],
        'block': c.get('block', 'A'),
        'display_order': c.get('display_order', 0),
        'flag': c.get('flag', ''),
    } for c in ordered])

@app.route('/api/countries/move-grid', methods=['POST'])
def move_country_grid():
    global COUNTRIES
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    direction = data.get('direction')
    if not name or direction not in ('up', 'down'):
        return jsonify({'error': 'Invalid request'}), 400

    c = next((c for c in COUNTRIES if c['name'] == name), None)
    if not c:
        return jsonify({'error': 'Not found'}), 404

    # Build sections using same greedy as compute_segments
    ordered = sorted(COUNTRIES, key=lambda x: x.get('display_order', 0))
    sections = []
    for cc in ordered:
        blk = cc.get('block', 'A')
        if blk not in ('A', 'O', 'AC'):
            continue
        placed = False
        for seg in sections:
            if blk not in seg:
                seg[blk] = cc['name']
                placed = True
                break
        if not placed:
            sections.append({blk: cc['name']})

    c_block = c['block']
    c_section_idx = None
    for i, seg in enumerate(sections):
        if seg.get(c_block) == c['name']:
            c_section_idx = i
            break
    if c_section_idx is None:
        return jsonify({'error': 'Country not in any section'}), 400

    # Find target based on grid rules
    target_name = None
    if direction == 'up':
        if c_block == 'A' and c_section_idx > 0:
            target_name = sections[c_section_idx - 1].get('AC')
        elif c_block == 'O':
            target_name = sections[c_section_idx].get('A')
        elif c_block == 'AC':
            target_name = sections[c_section_idx].get('O')
    else:  # down
        if c_block == 'A':
            target_name = sections[c_section_idx].get('O')
        elif c_block == 'O':
            target_name = sections[c_section_idx].get('AC')
        elif c_block == 'AC' and c_section_idx < len(sections) - 1:
            target_name = sections[c_section_idx + 1].get('A')

    if not target_name:
        return jsonify({'error': 'Cannot move further'}), 400

    target = next((c2 for c2 in COUNTRIES if c2['name'] == target_name), None)
    if not target:
        return jsonify({'error': 'Target not found'}), 404

    # Swap display_order AND block
    c['display_order'], target['display_order'] = target['display_order'], c['display_order']
    c['block'], target['block'] = target['block'], c['block']
    for cc in (c, target):
        ab = cc.get('all_blocks', [cc['block']])
        if cc['block'] not in ab:
            ab.append(cc['block'])
        cc['all_blocks'] = ab
    COUNTRIES.sort(key=lambda x: x.get('display_order', 0))
    save_all()
    return jsonify({'ok': True})

@app.route('/api/countries/<name>', methods=['DELETE'])
def delete_country(name):
    global COUNTRIES, COINS, COINS_MINT, MINTAGE, MINTAGE_MINT, CC_NAMES
    old_len = len(COUNTRIES)
    COUNTRIES = [c for c in COUNTRIES if c['name'] != name]
    if len(COUNTRIES) == old_len:
        return jsonify({'error': 'Not found'}), 404
    # Clean up related data
    for k in list(COINS.keys()):
        if k.startswith(name + ':'):
            del COINS[k]
    for k in list(COINS_MINT.keys()):
        if k.startswith(name + ':'):
            del COINS_MINT[k]
    for k in list(MINTAGE.keys()):
        if k.startswith(name + ':'):
            del MINTAGE[k]
    for k in list(MINTAGE_MINT.keys()):
        if k.startswith(name + ':'):
            del MINTAGE_MINT[k]
    for k in list(CC_NAMES.keys()):
        if k.startswith(name + ':'):
            del CC_NAMES[k]
    COUNTRY_YEARS.pop(name, None)
    EXTENSIONS.pop(name, None)
    save_all()
    return jsonify({'ok': True})

@app.route('/api/data', methods=['GET'])
def get_data():
    return jsonify({})  # Not used by frontend anymore


# ─── Sync (mintage) ───

@app.route('/api/sync', methods=['POST'])
def api_sync():
    try:
        n = sync_mintage_from_sheet()
        return jsonify({'ok': True, 'count': n})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

def sync_mintage_from_sheet():
    global MINTAGE, MINTAGE_MINT, CC_NAMES
    req = urllib.request.Request(SHEET_XLSX_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw = resp.read()
    wb = load_workbook(io.BytesIO(raw), data_only=True)

    tab_index = {}
    _mint_tab_map = {}
    for tab in wb.sheetnames:
        ws = wb[tab]
        hr = _find_header_row(ws)
        col_map = _build_column_map(ws)
        if not col_map:
            continue
        d = {}
        for r in range(3, ws.max_row + 1):
            yv = ws.cell(r, 2).value
            try:
                year = int(float(yv))
            except (ValueError, TypeError):
                continue
            for (dl, cci), scol in col_map.items():
                s = _sheet_cell_str(ws.cell(r, scol).value)
                if s:
                    d[(year, dl, cci)] = s
        tab_index[tab] = d
        parts = tab.rsplit(' ', 1)
        if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha():
            base, mint = parts
            _mint_tab_map.setdefault(base, {})[mint.upper()] = tab

    # Build English name -> country data
    name_to_country = {}
    for c in COUNTRIES:
        eng = c.get('image_name_en', '')
        if eng:
            name_to_country[eng] = c

    new_mintage = dict(MINTAGE)
    new_mintage_mint = dict(MINTAGE_MINT)
    new_cc_names = dict(CC_NAMES)

    result = {}
    result_mint = {}
    for c in COUNTRIES:
        cname = c['name']
        bl = c['block']
        eng = c.get('image_name_en', '')
        if not eng:
            continue
        tab_name = eng
        mints = c.get('mint_marks', [])
        yrs = get_years(cname)
        for yr in yrs:
            if not yr.isdigit():
                continue
            year_int = int(yr)
            for dk in ['1c','2c','5c','10c','20c','50c','1\u20ac','2\u20ac']:
                ck = coin_key(cname, yr, dk)
                if tab_name in tab_index:
                    val = tab_index[tab_name].get((year_int, dk, 0))
                    if val:
                        new_mintage[ck] = val
                if tab_name in _mint_tab_map:
                    for mint, mtab in _mint_tab_map[tab_name].items():
                        if mtab in tab_index:
                            mval = tab_index[mtab].get((year_int, dk, 0))
                            if mval:
                                new_mintage_mint[ck + ':' + mint] = mval
            # CC columns
            for cci in [1, 2, 3]:
                dk = f'CC{cci}'
                ck = coin_key(cname, yr, dk)
                if tab_name in tab_index:
                    val = tab_index[tab_name].get((year_int, 'CC', cci))
                    if val:
                        new_mintage[ck] = val
                if tab_name in _mint_tab_map:
                    for mint, mtab in _mint_tab_map[tab_name].items():
                        if mtab in tab_index:
                            mval = tab_index[mtab].get((year_int, 'CC', cci))
                            if mval:
                                new_mintage_mint[ck + ':' + mint] = mval

    # CC names
    _cc_name_headers = {
        'Commemorative Coin 1': 1, 'Commemorative Coin 2': 2, 'Commemorative Coin 3': 3,
        'Common-Issue Commemorative': 3, 'Commemorative coin 1': 1, 'Commemorative coin 2': 2,
        'Commemorative coin 3': 3, 'Common-issue commemorative': 3}
    _cc_tab_names = {}
    for tab in wb.sheetnames:
        effective_tab = tab
        parts = tab.rsplit(' ', 1)
        if len(parts) == 2 and len(parts[1]) == 1 and parts[1].isalpha():
            effective_tab = parts[0]
            if effective_tab in _cc_tab_names:
                continue
        ws = wb[tab]
        hr = _find_header_row(ws)
        name_cols = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(hr, c).value
            if isinstance(v, str) and v.strip() in _cc_name_headers:
                name_cols[_cc_name_headers[v.strip()]] = c
        if not name_cols:
            continue
        d = {}
        for r in range(3, ws.max_row + 1):
            yv = ws.cell(r, 2).value
            try:
                year = int(float(yv))
            except (ValueError, TypeError):
                continue
            for cci, scol in name_cols.items():
                v = ws.cell(r, scol).value
                if v and isinstance(v, str) and v.strip():
                    stripped = v.strip()
                    if stripped not in ('N/A', 'n/a', 'N / A', 'N.A.', '-', '???', '?'):
                        d[(year, cci)] = stripped
        if d:
            _cc_tab_names[effective_tab] = d
    for c in COUNTRIES:
        cname = c['name']
        eng = c.get('image_name_en', '')
        if not eng or eng not in _cc_tab_names:
            continue
        cc_data = _cc_tab_names[eng]
        yrs = get_years(cname)
        for yr in yrs:
            if not yr.isdigit():
                continue
            for cci in [1, 2, 3]:
                name_val = cc_data.get((int(yr), cci))
                if name_val:
                    new_cc_names[coin_key(cname, yr, f'CC{cci}')] = name_val

    MINTAGE.clear()
    MINTAGE.update(new_mintage)
    MINTAGE_MINT.clear()
    MINTAGE_MINT.update(new_mintage_mint)
    CC_NAMES.clear()
    CC_NAMES.update(new_cc_names)
    save_all()
    return len(new_mintage)


def _find_header_row(ws):
    _header_map = {
        '1 cent': ('1c',0), '1 cents': ('1c',0), '2 cent': ('2c',0), '2 cents': ('2c',0),
        '5 cent': ('5c',0), '5 cents': ('5c',0), '10 cent': ('10c',0), '10 cents': ('10c',0),
        '20 cent': ('20c',0), '20 cents': ('20c',0), '50 cent': ('50c',0), '50 cents': ('50c',0),
        '1 Euro': ('1\u20ac',0), '1 euro': ('1\u20ac',0), '2 Euro': ('2\u20ac',0), '2 Euros': ('2\u20ac',0), '2 euros': ('2\u20ac',0),
        'CC 1': ('CC',1), 'CC1': ('CC',1), 'CC 2': ('CC',2), 'CC2': ('CC',2),
        'CC 3': ('CC',3), 'CC3': ('CC',3), 'CC Common': ('CC',3), 'CCC': ('CC',3),}
    for r in range(1, 6):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.strip() in _header_map:
                return r
    return 2

def _build_column_map(ws):
    hr = _find_header_row(ws)
    _header_map = {
        '1 cent': ('1c',0), '1 cents': ('1c',0), '2 cent': ('2c',0), '2 cents': ('2c',0),
        '5 cent': ('5c',0), '5 cents': ('5c',0), '10 cent': ('10c',0), '10 cents': ('10c',0),
        '20 cent': ('20c',0), '20 cents': ('20c',0), '50 cent': ('50c',0), '50 cents': ('50c',0),
        '1 Euro': ('1\u20ac',0), '1 euro': ('1\u20ac',0), '2 Euro': ('2\u20ac',0), '2 Euros': ('2\u20ac',0), '2 euros': ('2\u20ac',0),
        'CC 1': ('CC',1), 'CC1': ('CC',1), 'CC 2': ('CC',2), 'CC2': ('CC',2),
        'CC 3': ('CC',3), 'CC3': ('CC',3), 'CC Common': ('CC',3), 'CCC': ('CC',3),}
    col_map = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(hr, c).value
        if isinstance(v, str) and v.strip() in _header_map:
            col_map[_header_map[v.strip()]] = c
    return col_map

def _sheet_cell_str(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else str(v)
    if isinstance(v, int):
        return str(v)
    return str(v).strip()


# ─── Add the legend panel, info modal, sync modal HTML (included in generate_html) ───

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    debug = os.environ.get('FLASK_DEBUG', '').lower() in ('1', 'true')
    app.run(host='0.0.0.0', port=port, debug=debug)
