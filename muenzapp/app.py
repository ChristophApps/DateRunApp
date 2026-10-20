import json, html as htmlmod, re, os, io, urllib.request, urllib.parse, datetime, hashlib, hmac
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
# MUENZAPP_DATA: andere Datei zum Testen (damit data.json nicht verändert wird)
DATA_PATH = os.environ.get('MUENZAPP_DATA') or os.path.join(BASE_DIR, 'data.json')
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
        _doc_ver = None
        d = _load_file_doc()
        save_doc(d)
        _redis('SET', REDIS_SEED_KEY, seed)
        return d
    _doc_ver = ver
    return json.loads(raw)

class ConflictError(Exception):
    """Ein anderes Gerät hat inzwischen gespeichert."""

# Speichert nur, wenn online noch derselbe Stand ist wie im Speicher.
# Sonst würde man die Änderung vom anderen Gerät überschreiben.
_SAVE_IF_SAME_VER = '''
local v = redis.call('GET', KEYS[2])
if (v or '') ~= ARGV[2] then return -1 end
redis.call('SET', KEYS[1], ARGV[1])
return redis.call('INCR', KEYS[2])
'''

def save_doc(d: dict) -> None:
    global _doc_ver
    if USE_REDIS:
        res = _redis('EVAL', _SAVE_IF_SAME_VER, '2', REDIS_DOC_KEY, REDIS_VER_KEY,
                     json.dumps(d, ensure_ascii=False, separators=(',', ':')), _doc_ver or '')
        if res == -1:
            raise ConflictError()
        _doc_ver = str(res)
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
# Extra-Zeilen (Varianten) je Land: {Land: {Zeilen-ID: {'base': Jahr, 'n': Nummer, 'label': Name}}}
# Die ID bleibt immer gleich, nur der Name ('label') kann geändert werden.
EXTRA_ROWS = doc.get('extra_rows', {})
# Notizen aus dem Google Sheet je Münze: {Münz-Schlüssel (mit Münzstätte, falls nötig): Text}
COIN_NOTES = doc.get('coin_notes', {})

def _build_coin_years_cache() -> dict:
    cache = {}
    for k in COINS:
        parts = k.split(':')
        if len(parts) >= 2:
            cache.setdefault(parts[0], set()).add(parts[1])
    return cache

_COIN_YEARS = _build_coin_years_cache()

def year_label(cname: str, yr: str) -> str:
    """Angezeigter Name einer Zeile (bei Extra-Zeilen der selbst gewählte Name)."""
    return EXTRA_ROWS.get(cname, {}).get(yr, {}).get('label') or yr

def _sheet_year_key(cname: str, yr: str):
    """Welche Zeile im Google Sheet zu dieser Zeile gehört: '2022' oder '2022+1' (1. Extra-Zeile unter 2022)."""
    if yr.isdigit():
        return yr
    meta = EXTRA_ROWS.get(cname, {}).get(yr)
    if not meta:
        return None
    return f"{meta['base']}+{meta['n']}" if meta['n'] else meta['base']

# Extra-Zeilen aus dem Google Sheet (Stand Oktober 2026), einmalig angelegt.
# (Land, vorhandene Zeile oder None = neu anlegen, Jahr im Sheet, Nummer der Extra-Zeile darunter; 0 = die Jahres-Zeile selbst)
_DEFAULT_EXTRA_ROWS = [
    ('Belgien', None, '2022', 1), ('Finnland', None, '2006', 1), ('Deutschland', None, '2007', 1), ('Deutschland', None, '2008', 1),
    ('Griechenland', 'EFS', '2002', 1), ('Luxemburg', None, '2020', 1), ('Luxemburg', None, '2021', 1),
    ('Luxemburg', '2023 KNM', '2023', 0), ('Luxemburg', '2023 MDP', '2023', 1),
    ('Portugal', None, '2008', 1), ('Spanien', None, '2009', 1), ('Vatikan', None, '2005', 1),
]
# Was die Zeile ist (aus den Notizen im Google Sheet)
_DEFAULT_EXTRA_NOTES = {
    ('Belgien', '2022', 1): '5 Cent von 2022, aber erst 2023 gepr\u00e4gt. Zeichen des Graveurs links neben der Jahreszahl.',
    ('Finnland', '2006', 1): '2 Euro mit neuer Landkarte (Fehlpr\u00e4gung). Nur 55.000 St\u00fcck.',
    ('Deutschland', '2007', 1): '20 Cent aus F (Stuttgart) mit alter Landkarte.',
    ('Deutschland', '2008', 1): '2\u20ac-Gedenkm\u00fcnze 1 aus F (Stuttgart) mit alter Landkarte.',
    ('Griechenland', '2002', 1): 'Im Ausland gepr\u00e4gt: E (Spanien), F (Frankreich), S (Finnland). Der Buchstabe steht im Stern.',
    ('Luxemburg', '2020', 1): '2\u20ac-Gedenkm\u00fcnze 2 mit anderen M\u00fcnzzeichen: L\u00f6we + Br\u00fccke (nicht f\u00fcr den Umlauf).',
    ('Luxemburg', '2021', 1): '2\u20ac-Gedenkm\u00fcnzen mit anderen M\u00fcnzzeichen: Br\u00fccke + Merkur (nicht f\u00fcr den Umlauf).',
    ('Luxemburg', '2023', 0): 'Gepr\u00e4gt in Utrecht (KNM, Niederlande).',
    ('Luxemburg', '2023', 1): 'Gepr\u00e4gt in Paris (Monnaie de Paris). M\u00fcnzzeichen Füllhorn + Nashorn links und rechts der Jahreszahl.',
    ('Portugal', '2008', 1): '1 Euro mit alter Landkarte.',
    ('Spanien', '2009', 1): '2\u20ac-Gedenkm\u00fcnze (gemeinsame Ausgabe) mit gro\u00dfen Sternen.',
    ('Vatikan', '2005', 1): 'Sede Vacante 2005 (nicht f\u00fcr den Umlauf).',
}

def _add_extra_notes() -> bool:
    """Beschreibung bei den Start-Zeilen ergänzen, wo noch keine steht."""
    changed = False
    for cname, rows in EXTRA_ROWS.items():
        for meta in rows.values():
            note = _DEFAULT_EXTRA_NOTES.get((cname, meta['base'], meta['n']))
            if note and 'note' not in meta:
                meta['note'] = note
                changed = True
            mint = _DEFAULT_EXTRA_MINT.get((cname, meta['base'], meta['n']))
            if mint and 'mint' not in meta:
                meta['mint'] = mint
                changed = True
    return changed

# Extra-Zeilen, die es nur bei einer Münzstätte gibt
_DEFAULT_EXTRA_MINT = {('Deutschland', '2007', 1): 'F', ('Deutschland', '2008', 1): 'F'}

# Welche Münzen es in den Extra-Zeilen wirklich gibt (aus dem Google Sheet). Alle anderen = ✕ nie geprägt.
_EXTRA_ROW_COINS = {
    ('Belgien', '2022', 1): ['5c'], ('Finnland', '2006', 1): ['2\u20ac'],
    ('Deutschland', '2007', 1): ['20c'], ('Deutschland', '2008', 1): ['CC1'],
    ('Luxemburg', '2020', 1): ['CC2'], ('Luxemburg', '2021', 1): ['CC1', 'CC2'],
    ('Portugal', '2008', 1): ['1\u20ac'], ('Spanien', '2009', 1): ['CC3'],
    ('Vatikan', '2005', 1): ['1c', '2c', '5c', '10c', '20c', '50c', '1\u20ac', '2\u20ac'],
    ('Griechenland', '2002', 1): ['1c', '2c', '5c', '10c', '20c', '50c', '1\u20ac', '2\u20ac'],
}
_ALL_DENOMS = ['1c', '2c', '5c', '10c', '20c', '50c', '1\u20ac', '2\u20ac', 'CC1', 'CC2', 'CC3']

def _mark_missing_coins_once() -> bool:
    """Einmal: in den Extra-Zeilen alle Münzen, die es dort nicht gibt, auf ✕ nie geprägt setzen.
    Felder mit eigenem Eintrag bleiben. Als ein Schritt, den man mit ↶ zurücknehmen kann."""
    if doc.get('extra_rows_x_done'):
        return False
    done = []
    for cname, rows in EXTRA_ROWS.items():
        c = next((x for x in COUNTRIES if x['name'] == cname), None)
        if not c:
            continue
        for row, meta in rows.items():
            have = _EXTRA_ROW_COINS.get((cname, meta['base'], meta['n']))
            if have is None or row not in get_years(cname):
                continue
            mints = [meta['mint']] if meta.get('mint') else c.get('mint_marks', [])
            for dk in _ALL_DENOMS:
                if dk in have:
                    continue
                keys = [(COINS_MINT, f'{coin_key(cname, row, dk)}:{m}', 'coins_mint') for m in mints] if mints else [(COINS, coin_key(cname, row, dk), 'coins')]
                for store, key, sname in keys:
                    e = store.get(key, {})
                    if coin_value(e) or coin_cell_type(e):
                        continue
                    store.setdefault(key, {})['ct'] = 'x'
                    done.append({'kind': 'ct', 'store': sname, 'key': key, 'prev': '', 'new': 'x'})
    doc['extra_rows_x_done'] = True
    if done:
        UNDO_STACK.append({'type': 'sync', 'label': 'Extra-Zeilen', 'desc': 'Extra-Zeilen: \u2715 nie gepr\u00e4gt', 'changes': done})
    return True

def row_mint(cname: str, yr: str) -> str:
    """Münzstätte, für die diese Extra-Zeile gilt ('' = für alle)."""
    return EXTRA_ROWS.get(cname, {}).get(yr, {}).get('mint', '')

def visible_years(c: dict, mint_arg: str = '') -> list:
    """Jahre eines Landes in der Haupttabelle – Extra-Zeilen einer anderen Münzstätte werden ausgeblendet."""
    yrs = get_years(c['name'])
    mints = c.get('mint_marks', [])
    if not mints:
        return yrs
    active = mint_arg if mint_arg in mints else mints[0]
    return [y for y in yrs if row_mint(c['name'], y) in ('', active)]

def extra_note(cname: str, yr: str) -> str:
    return EXTRA_ROWS.get(cname, {}).get(yr, {}).get('note', '')

def year_cell_html(cname: str, yr: str) -> str:
    """Name der Zeile. Bei Extra-Zeilen mit Beschreibung kann man den Namen antippen."""
    note = extra_note(cname, yr)
    label = htmlmod.escape(year_label(cname, yr))
    if not note:
        return label
    # Name antippen zeigt die Beschreibung
    return (f'<span class="yr-name" data-country="{htmlmod.escape(cname)}" data-row="{htmlmod.escape(yr)}"'
            f' data-note="{htmlmod.escape(note)}" title="{htmlmod.escape(note)}">{label}</span>')

def _add_default_extra_rows() -> bool:
    """Legt die Extra-Zeilen einmal an. Vorhandene (Griechenland EFS, Luxemburg 2023 KNM/MDP) werden nur verknüpft."""
    if 'extra_rows' in doc:
        return False
    names = {c['name'] for c in COUNTRIES}
    for cname, existing, base, n in _DEFAULT_EXTRA_ROWS:
        if cname not in names:
            continue
        if existing:
            # Zeile gibt es schon (z.B. Griechenland \u201eEFS\u201c) \u2013 nur mit dem Sheet verknüpfen
            if existing in get_years(cname):
                EXTRA_ROWS.setdefault(cname, {})[existing] = {'base': base, 'n': n, 'label': existing}
            continue
        row_id = f'{base}+{n}'
        EXTRA_ROWS.setdefault(cname, {})[row_id] = {'base': base, 'n': n, 'label': f'{base} II'}
        elist = EXTENSIONS.setdefault(cname, [])
        if row_id not in elist:
            elist.append(row_id)
            elist.sort(key=_year_sort_key)
    doc['extra_rows'] = EXTRA_ROWS
    return True

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
    parts = ref.split(':')
    if len(parts) == 4 and country_has_mints(cname):
        # Münzstätte steht schon in der Zell-ID (Münzstätten-Blatt)
        return COINS_MINT, ref, cname, True
    use_mint = mint_arg and country_has_mints(cname)
    if use_mint:
        return COINS_MINT, ref + ':' + mint_arg, cname, True
    return COINS, ref, cname, False

UNDO_LIMIT = 200  # so viele Schritte kann man zurück

def save_all():
    global doc, COINS, COINS_MINT, MINTAGE, MINTAGE_MINT, CC_NAMES, IMAGE_LINKS_MINT, COUNTRIES, COUNTRY_YEARS, EXTENSIONS, UNDO_STACK, REDO_STACK, EXTRA_ROWS, COIN_NOTES
    del UNDO_STACK[:-UNDO_LIMIT]
    del REDO_STACK[:-UNDO_LIMIT]
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
    doc['extra_rows'] = EXTRA_ROWS
    doc['coin_notes'] = COIN_NOTES
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

def compute_segments(exclude_country=None, mint_arg=''):
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
        yrs = visible_years(c, mint_arg)
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

def cc_display_name(name: str) -> str:
    """Gedenkmünzen-Name ohne Zusatz wie \u201e[1]\u201c aus dem Google Sheet."""
    return re.sub(r'\s*\[\d+\]\s*$', '', name or '')

def _cell_view(cname, yr_val, dk, mints, mint_arg):
    """Was eine Zelle zeigt: Text, Farbtyp, Hintergrund-Stil, Bild-Link (für die gewählte Münzstätte)."""
    entry = get_coin(cname, yr_val, dk)
    mentry = get_coin(cname, yr_val, dk, mint_arg if mint_arg in mints else None) if mints else {}
    val = coin_value(mentry) or coin_value(entry)
    ct = coin_cell_type(mentry) or coin_cell_type(entry)
    _bg = _compute_cell_color(cname, yr_val, dk, ct=ct)
    sty = ''
    if ct == 'x':
        sty = 'background:#FFC7CE;'
        val = '\u2715'
    elif val and '\u2715' in val:
        sty = 'background:#FFC7CE;'
    elif _bg:
        sty = f'background:#{_bg};'
    img = coin_image(entry) or (coin_image(mentry) if mints else '') or image_url_for(cname, yr_val, dk) or ''
    return val, ct, sty, img


def generate_html(mint_arg='', layout='', sheet_country=''):
    global COINS, COINS_MINT, MINTAGE, CC_NAMES, IMAGE_LINKS_MINT, IMAGE_LINKS
    _js_hash = ''
    try:
        with open(os.path.join(app.static_folder, 'app.js'), 'rb') as _f:
            _js_hash = hashlib.md5(_f.read()).hexdigest()[:8]
    except: pass
    sheet_c = next((c for c in COUNTRIES if c['name'] == sheet_country and c.get('mint_marks')), None) if layout == 'mints' else None
    segments = compute_segments(mint_arg=mint_arg) if not sheet_c else []
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

    _sync_country_options = '<option value="">Alle L\u00e4nder</option>' + ''.join(
        f'<option value="{htmlmod.escape(c["name"])}">{c.get("flag", "")} {htmlmod.escape(c["name"])}</option>'
        for c in sorted(COUNTRIES, key=lambda c: c.get('display_order', 0)) if c.get('image_name_en'))
    _logout_html = '<a class="data-dropdown-item menu-logout" href="/logout">\U0001f6aa Abmelden</a>' if APP_PASSWORD else ''
    h = f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>M\u00fcnzApp</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<link rel="manifest" href="/static/manifest.webmanifest">
<meta name="apple-mobile-web-app-title" content="M\u00fcnzApp">
<meta name="theme-color" content="#003399">
</head>
<body>
<div id="offlineBar">Kein Internet – nur ansehen. Ändern geht erst wieder mit Internet.</div>
<div id="stickyHeader"><div class="topbar">
<span class="tb-btn tb-add" id="qaBtn" title="M\u00fcnze hinzuf\u00fcgen">\u2795<span class="tb-word"> M\u00fcnze</span></span>
<span class="tb-btn tb-switch" id="mobileToggle" role="switch" aria-checked="false" title="Handy-Ansicht: L\u00e4nder untereinander"><span>\U0001f4f1<span class="tb-word"> Handy</span></span><span class="switch"></span></span>
<span class="tb-btn edit-btn" id="editBtn" title="Bearbeiten">\U0001f4dd<span class="tb-word"> Bearbeiten</span></span>
<span class="tb-btn" id="sumBtn" title="Info">\u2139\ufe0f<span class="tb-word"> Info</span></span>
<span class="data-wrap">
<span class="tb-btn" id="moreBtn" title="Export/Import">\u21c5<span class="tb-word"> Export/Import</span> \u25be</span>
<div class="data-dropdown" id="moreDropdown" style="display:none">
  <div class="menu-head">Drucken &amp; Export</div>
  <span class="data-dropdown-item" id="exportPdfBtn">\U0001f5a8\ufe0f PDF / Drucken</span>
  <span class="data-dropdown-item" id="exportXlsxBtn">\U0001f4ca Excel-Datei</span>
  <div class="menu-head">Daten</div>
  <span class="data-dropdown-item" id="dropdownExport">\U0001f4be Sicherung herunterladen</span>
  <span class="data-dropdown-item" id="dropdownImport">\U0001f4e5 Sicherung laden</span>
  {_logout_html}
</div>
</span>
<span class="tb-pair">
<span class="tb-btn" id="undoBtn" title="R\u00fcckg\u00e4ngig">\u21b6</span>
<span class="tb-btn" id="redoBtn" title="Wiederholen">\u21b7</span>
</span>
</div>
<div id="editBar" class="edit-bar">
  <div class="edit-bar-text"><b>\u270f\ufe0f Bearbeiten ist an</b><span id="editHint" class="edit-hint"></span><span class="edit-hint2">Jahre: mit <b>+ Jahr</b> / <b>\u2212 Jahr</b> oben bei jedem Land. Extra-Zeilen (blau umrandet) antippen, um Name und Beschreibung zu \u00e4ndern.</span></div>
  <div class="edit-bar-actions">
    <span class="tb-btn eb-main" id="editCountries">\U0001f30d L\u00e4nder bearbeiten</span>
    <span class="tb-btn eb-main" id="editSync">\U0001f504 Mit Google Sheet synchronisieren</span>
    <span class="tb-btn" id="editCancelCopy" style="display:none">\u2715 Kopieren abbrechen</span>
  </div>
</div>
<div class="tb-msgs"><span id="msg" class="msg"></span>
<div id="sumOverlay" class="info-modal-overlay"></div>
<div id="sumBreakdown" class="sum-breakdown" style="display:none">
  <button class="close-btn" id="sumClose">&times;</button>
  <h3 class="sum-title">Info</h3>
  <div class="info-tabs" role="tablist">
    <button class="info-tab active" data-tab="tabZahlen" role="tab">\U0001f4ca Zahlen</button>
    <button class="info-tab" data-tab="tabLegende" role="tab">\u2753 Legende</button>
  </div>
  <div class="tab-pane" id="tabLegende" style="display:none">
  <div class="legend-grid">
    <div class="legend-card">
      <h4>Qualit\u00e4t</h4>
      <div class="legend-row"><span class="legend-code">\u2714</span> noch nicht bestimmt</div>
      <div class="legend-row"><span class="legend-code">0</span> UNC (wie neu)</div>
      <div class="legend-row"><span class="legend-code">1</span> gut / sehr gut</div>
      <div class="legend-row"><span class="legend-code">3</span> schlecht</div>
      <div class="legend-row"><span class="legend-code">5</span> sehr schlecht</div>
    </div>
    <div class="legend-card">
      <h4>Herkunft (Zeichen danach)</h4>
      <div class="legend-row"><span class="legend-code">&ndash;</span> selbst gesammelt</div>
      <div class="legend-row"><span class="legend-code">\u00b0</span> aus der Gruppe</div>
      <div class="legend-row"><span class="legend-code">*</span> gekauft</div>
      <div class="legend-note">Mehrere Zeichen in einem Feld = mehrere M\u00fcnzen (z.B. 5\u00b00*)</div>
    </div>
    <div class="legend-card">
      <h4>Farben (Auflage)</h4>
      <div class="legend-row"><span class="legend-swatch" style="background:#C5DEB5"></span> \u00fcber 5 Mio.</div>
      <div class="legend-row"><span class="legend-swatch" style="background:#8EAADB"></span> 2&ndash;5 Mio.</div>
      <div class="legend-row"><span class="legend-swatch" style="background:#FF8C42"></span> 1&ndash;2 Mio.</div>
      <div class="legend-row"><span class="legend-swatch" style="background:#FFE598"></span> bis 1 Mio.</div>
      <div class="legend-row"><span class="legend-swatch" style="background:#FFC7CE"></span> NIFC (nicht f\u00fcr Umlauf) / \u2715 nie gepr\u00e4gt</div>
    </div>
    <div class="legend-card">
      <h4>So geht\u2019s</h4>
      <div class="legend-row">M\u00fcnze antippen \u2192 M\u00fcnze ansehen und \u00e4ndern</div>
      <div class="legend-row">\u2139 beim Land \u2192 Zahlen f\u00fcr dieses Land</div>
      <div class="legend-row">\u2139\ufe0f Info oben \u2192 Zahlen f\u00fcr die ganze Sammlung und diese Legende</div>
      <div class="legend-row">\U0001f4dd Bearbeiten \u2192 schnell \u00e4ndern, kopieren, Jahre, L\u00e4nder und mit dem Google Sheet synchronisieren</div>
      <div class="legend-row">\u21b6 / \u21b7 \u2192 r\u00fcckg\u00e4ngig / wiederholen</div>
      <div class="legend-row">\U0001f4f1 Handy \u2192 L\u00e4nder untereinander</div>
      <div class="legend-row">\u21c5 Export/Import \u2192 PDF, Excel, Sicherung herunterladen und laden</div>
    </div>
  </div>
  <div class="legend-links">
    <a href="https://docs.google.com/spreadsheets/d/1lGbzcTmMfzQjE-7ENMhrSMpMlu859fYCAqH8juDhb40" target="_blank" rel="noopener">Google Sheet &nearr;</a>
    <a href="https://www.eurocollection.co.uk/Euros" target="_blank" rel="noopener">M\u00fcnzbilder (eurocollection.co.uk) &nearr;</a>
  </div>
  </div>
  <div class="tab-pane" id="tabZahlen">
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
      <div id="infoNote" class="info-note" style="display:none"></div>
    </div>
  </div>

  <div class="own-box" id="ownBox">
    <div class="own-head" id="ownHead"></div>
    <div id="infoCoinEntries"></div>
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
<div class="info-modal-overlay" id="qaOverlay"></div>
<div class="app-modal qa-box" id="qaModal" style="display:none">
  <button class="close-btn" id="qaClose">&times;</button>
  <h3 class="modal-title">\u2795 M\u00fcnze hinzuf\u00fcgen</h3>
  <select id="qaCountry" hidden></select><select id="qaYear" hidden></select><select id="qaDenom" hidden></select>
  <div class="qa-sec"><div class="qa-lbl2">Land <b id="qaCountryName"></b></div><div id="qaCountryChips" class="qa-flags"></div></div>
  <div id="qaMintRow" class="qa-row" style="display:none"><span class="qa-lbl">M\u00fcnzst\u00e4tte</span><div id="qaMints" class="qa-chips"></div></div>
  <div class="qa-sec"><div class="qa-lbl2">Jahr</div><div id="qaYearChips" class="qa-grid qa-years"></div></div>
  <div class="qa-sec"><div class="qa-lbl2">M\u00fcnze</div><div id="qaDenomChips" class="qa-grid qa-denoms"></div></div>
  <div id="qaHave" class="qa-have"></div>
  <div class="qa-row"><span class="qa-lbl">Qualit\u00e4t</span><div id="qaQ" class="qa-chips">
    <span class="info-q-btn" data-q="\u2714" title="noch nicht bestimmt">\u2714</span><span class="info-q-btn" data-q="0" title="UNC">0</span><span class="info-q-btn" data-q="1" title="gut / sehr gut">1</span><span class="info-q-btn" data-q="3" title="schlecht">3</span><span class="info-q-btn" data-q="5" title="sehr schlecht">5</span>
  </div></div>
  <div class="qa-row"><span class="qa-lbl">Herkunft</span><div id="qaS" class="qa-chips">
    <span class="qa-src" data-s="">\U0001f64b selbst gesammelt</span><span class="qa-src" data-s="\u00b0">\U0001f465 aus der Gruppe</span><span class="qa-src" data-s="*">\U0001f6d2 gekauft</span>
  </div></div>
  <button class="modal-primary" id="qaSave">Hinzuf\u00fcgen</button>
  <p class="modal-sub" id="qaDone" style="margin:10px 0 0;text-align:center"></p>
</div>
<div class="info-modal-overlay" id="rowOverlay"></div>
<div class="app-modal row-box" id="rowModal" style="display:none">
  <button class="close-btn" id="rowClose">&times;</button>
  <h3 class="modal-title">Extra-Zeile</h3>
  <p class="modal-sub" id="rowWhere"></p>
  <div class="ac-grid">
    <label class="ac-wide">Name<input id="rowLabel" maxlength="30"></label>
    <label class="ac-wide">Was ist das? (erscheint beim Antippen des Namens)<textarea id="rowNote" rows="3" maxlength="300"></textarea></label>
  </div>
  <p class="modal-sub" style="margin-top:8px">Die Verbindung zum Google Sheet bleibt gleich.</p>
  <div class="modal-btns">
    <button class="modal-secondary" id="rowCancel">Abbrechen</button>
    <button class="modal-primary" id="rowSave">Speichern</button>
  </div>
  <button class="row-delete" id="rowDelete">\U0001f5d1\ufe0f Zeile l\u00f6schen</button>
</div>
<div class="row-note-pop" id="rowNotePop" style="display:none"></div>
<div class="info-modal-overlay" id="syncOverlay"></div>
<div class="app-modal sync-box" id="syncModal" style="display:none">
  <button class="close-btn" id="syncClose">&times;</button>
  <h3 class="modal-title">Mit Google Sheet synchronisieren</h3>
  <div id="syncStep1">
    <p class="modal-sub">Die App holt aus deinem Google Sheet: Auflagezahlen, Namen der 2\u20ac-Gedenkm\u00fcnzen, Notizen und neue Zeilen.</p>
    <label class="sync-label">Welches Land?
      <select id="syncCountry">{_sync_country_options}</select>
    </label>
    <div class="sync-warn">
      <b>\u26a0\ufe0f Das kann sich \u00e4ndern</b>
      <ul>
        <li>Wenn sich eine Auflagezahl \u00e4ndert, bekommt das Feld die <b>passende neue Farbe</b> \u2013 auch wenn du die Farbe selbst gew\u00e4hlt hast.</li>
        <li>Auflagezahlen, die du selbst eingetippt hast, werden <b>\u00fcberschrieben</b>, wenn das Sheet eine Zahl hat.</li>
        <li>Namen der Gedenkm\u00fcnzen k\u00f6nnen sich \u00e4ndern.</li>
      </ul>
      <span class="sync-ok">Deine M\u00fcnzen (\u2714, 0, 1\u00b0 \u2026) bleiben gleich. Einzelne \u00c4nderungen kannst du mit \u2715 weglassen.<br>
      Zuerst siehst du alle \u00c4nderungen. Erst mit \u201e\u00dcbernehmen\u201c wird gespeichert \u2013 und mit \u21b6 kannst du alles zur\u00fcck machen.</span>
    </div>
    <p class="modal-sub"><a href="https://docs.google.com/spreadsheets/d/1lGbzcTmMfzQjE-7ENMhrSMpMlu859fYCAqH8juDhb40" target="_blank" rel="noopener">Google Sheet \u00f6ffnen &nearr;</a></p>
    <div class="modal-btns">
      <button class="modal-secondary" id="syncCancel">Abbrechen</button>
      <button class="modal-primary" id="syncPreview">\u00c4nderungen ansehen</button>
    </div>
  </div>
  <div id="syncStep2" style="display:none">
    <div id="syncChecks"></div>
    <p class="modal-sub" id="syncSummary"></p>
    <div class="info-tabs" id="syncTabs"></div>
    <div id="syncList" class="sync-list"></div>
    <div class="modal-btns">
      <button class="modal-secondary" id="syncBack">Zur\u00fcck</button>
      <button class="modal-primary" id="syncConfirm">\u00dcbernehmen</button>
    </div>
  </div>
</div>
''' + ('<div class="flag-bar">\n' if not sheet_c else '<div class="flag-bar" style="display:none">\n')
    for c in sorted(COUNTRIES, key=lambda c: c.get('display_order', 0)):
        flag = c.get('flag', '')
        if not flag:
            continue
        _safe = c['name'].lower().replace('/','_').replace(' ','_')
        h += f'<span class="flag-btn" data-target="c-{c["block"]}-{_safe}" title="{htmlmod.escape(c["name"])}">{flag}</span>\n'
    h += '''</div>
</div>
<div id="rmOverlay" class="info-modal-overlay"></div>
<div id="reorderModal" class="app-modal" style="display:none">
  <button class="close-btn" id="rmClose">&times;</button>
  <h3 class="modal-title">L\u00e4nder bearbeiten</h3>
  <p class="modal-sub">Mit \u25b2 \u25bc verschiebst du ein Land. \u2715 l\u00f6scht es.</p>
  <div id="rmList"></div>
  <div class="modal-section">
    <div class="modal-section-title">Neues Land</div>
    <div class="ac-grid">
      <label class="ac-wide">Name<input id="acName" placeholder="z.B. Kroatien"></label>
      <label>Spalte<select id="acBlock"><option value="A">1. Spalte</option><option value="O">2. Spalte</option><option value="AC">3. Spalte</option></select></label>
      <label>Flagge<input id="acFlag" placeholder="\U0001f1ea\U0001f1fa"></label>
      <label>Bild-Name (englisch)<input id="acImageName" placeholder="z.B. Croatia"></label>
      <label>M\u00fcnzst\u00e4tten<input id="acMints" placeholder="z.B. A,D,F"></label>
    </div>
    <button id="acSave" class="modal-primary">+ Land hinzuf\u00fcgen</button>
  </div>
</div>
</div>
<table id="grid" style="width:''' + str(round(total_w, 1)) + '''px''' + (';display:none' if sheet_c else '') + '''">
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
                _yrs = found[0]['years']
                _ya = f'data-block="{bl}" data-country="{htmlmod.escape(cname)}"'
                _left = (f'<span class="c-left-btns"><span class="country-info" {_ya}>\u2139</span>'
                         f'<span class="yr-btn yr-add" {_ya} title="Jahr hinzuf\u00fcgen">+ Jahr</span>'
                         f'<span class="yr-btn yr-rm" {_ya} data-last="{htmlmod.escape(_yrs[-1] if _yrs else "")}" title="Jahr entfernen">\u2212 Jahr</span></span>')
                ckey = bl + '|' + cname
                cst = _country_stats.get(ckey)
                _cst_json = htmlmod.escape(json.dumps(cst)) if cst else '{}'
                _mints = c.get('mint_marks', [])
                _mint_html = ''
                if _mints:
                    _active_mint = mint_arg if mint_arg in _mints else _mints[0]
                    _rm = sorted({m.get('mint') for m in EXTRA_ROWS.get(cname, {}).values() if m.get('mint')})
                    _mint_html = f'<span class="c-mints" data-row-mints="{"".join(_rm)}">' + ''.join(
                        f'<a class="c-mint{" active" if m == _active_mint else ""}" data-mint="{m}" href="?mint={m}">{m}</a>'
                        for m in _mints
                    ) + f'<a class="c-mint c-mint-all" data-country="{htmlmod.escape(cname)}" href="/?layout=mints&amp;country={urllib.parse.quote(cname)}" title="Alle M\u00fcnzst\u00e4tten nebeneinander">Alle</a></span>'
                btn = f'<div class="c-country-inner">{_left}<span class="c-name" data-key="{htmlmod.escape(ckey)}" data-stats=\'{_cst_json}\'>{htmlmod.escape(cname)}</span>{_mint_html}</div>'
                _cs = block_colspan(bl)
                h += f'<td{_id} data-cid="{htmlmod.escape(ckey)}" class="c-country" colspan="{_cs}" style="background:#FF543E;color:#000">{btn}</td>'
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
                _cid = htmlmod.escape(bl + '|' + found[0]['country']['name'])
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
                    h += f'<td data-cid="{_cid}" class="{cls}" style="font-size:7pt;text-align:center;border:1px solid #000">{htmlmod.escape(val) if val else ""}</td>'
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
                    _cid = htmlmod.escape(bl + '|' + cname)
                    for cl in make_block_ordered_cols(bl):
                        if cl == bc['year']:
                            yr_val = yrs[yr_idx] if yr_idx < len(yrs) else ''
                            if yr_val:
                                _ex = yr_val in EXTRA_ROWS.get(cname, {})
                                _exa = f' data-country="{htmlmod.escape(cname)}" data-row="{htmlmod.escape(yr_val)}" title="Extra-Zeile (im Bearbeiten-Modus antippen zum Umbenennen)"' if _ex else ''
                                h += f'<td data-cid="{_cid}" class="c-year{" c-year-extra" if _ex else ""}"{_exa} style="text-align:center;font-size:7pt;border:1px solid #000;background:#eee">{year_cell_html(cname, yr_val)}</td>'
                            else:
                                h += '<td class="gap">&nbsp;</td>'
                        elif cl == bc['igap']:
                            h += f'<td data-cid="{_cid}" class="inner-gap">&nbsp;</td>'
                        else:
                            dk = make_denom_key(cl)
                            yr_val = yrs[yr_idx] if yr_idx < len(yrs) else ''
                            if not yr_val:
                                h += '<td class="gap">&nbsp;</td>'
                                continue
                            val, ct, _sty, _img = _cell_view(cname, yr_val, dk, mints, mint_arg)
                            ref = coin_key(cname, yr_val, dk)
                            _ref_attr = ref
                            _yr_attr = yr_val
                            _denom_attr = dk
                            _cname_attr = cname
                            _ev = htmlmod.escape(val) if val else ''
                            _editable = bool(dk)
                            _ct_attr = ct or ''
                            _xlocked = ' data-xlocked="1"' if ct == 'x' else ''
                            _dct = f' data-ct="{ct}"' if ct else ''
                            _mv = mintage_for(cname, yr_val, dk)
                            _dm = f' data-mintage="{htmlmod.escape(format_mintage_val(_mv))}"' if _mv else ''
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
                            _ccn = cc_display_name(CC_NAMES.get(ref, ''))
                            _dcn = f' data-cc-name="{htmlmod.escape(_ccn)}"' if _ccn else ''
                            _dr = f' data-ref="{_ref_attr}" data-country="{htmlmod.escape(_cname_attr)}" data-block="{bl}" data-year="{_yr_attr}" data-denom="{_denom_attr}"'
                            if _yr_attr in EXTRA_ROWS.get(cname, {}):
                                _dr += f' data-year-label="{htmlmod.escape(year_label(cname, _yr_attr))}"'
                            _note = COIN_NOTES.get(f'{ref}:{mint_arg}' if mints else ref, '')
                            if _note:
                                _dr += f' data-note="{htmlmod.escape(_note)}"'
                            _fullsty = (_sty + ';' if _sty and not _sty.endswith(';') else _sty) + 'font-size:8pt;text-align:center;border:1px solid #000'
                            h += f'<td{_dr} data-cid="{_cid}"{_dct}{_xlocked}{_dm}{_dl}{_dmint}{_dcn} style="{_fullsty}">{_ev}</td>'
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
    if sheet_c:
        h += _mint_sheet_view_html(sheet_c)

    _qa = []
    for c in sorted(COUNTRIES, key=lambda c: c.get('display_order', 0)):
        cn = c['name']
        yrs = get_years(cn)
        _qa.append({'name': cn, 'flag': c.get('flag', ''), 'mints': c.get('mint_marks', []),
                    'years': [[y, year_label(cn, y), row_mint(cn, y)] for y in yrs],
                    'cc': {y: {d: cc_display_name(CC_NAMES.get(coin_key(cn, y, d), '')) for d in ('CC1', 'CC2', 'CC3')
                               if CC_NAMES.get(coin_key(cn, y, d))} for y in yrs}})
    _qa_str = json.dumps(_qa, ensure_ascii=False).replace('</', '<\\/')
    h += f'''<script id="quickData" type="application/json">{_qa_str}</script>
<script id="mintData" type="application/json">{_mint_data_str}</script>
<script id="activeMint" type="text/plain">{htmlmod.escape(mint_arg)}</script>
<script src="/static/app.js?v={_js_hash}"></script>
</body>
</html>'''
    return h


# ─── Vor jeder Anfrage: Daten frisch halten (Redis) ───
# Auf Vercel laufen mehrere Kopien der App. Hat eine andere Kopie gespeichert,
# laden wir das Dokument neu, damit niemand alte Daten überschreibt.

def _apply_doc(d: dict) -> None:
    global doc, COINS, COINS_MINT, MINTAGE, MINTAGE_MINT, CC_NAMES, IMAGE_LINKS_MINT, FILL_COLORS, COUNTRIES, COUNTRY_YEARS, EXTENSIONS, UNDO_STACK, REDO_STACK, _COIN_YEARS, EXTRA_ROWS, COIN_NOTES
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
    EXTRA_ROWS = doc.get('extra_rows', {})
    COIN_NOTES = doc.get('coin_notes', {})
    _COIN_YEARS = _build_coin_years_cache()
    if _add_default_extra_rows() | _add_extra_notes() | _mark_missing_coins_once():
        save_all()

def refresh_doc():
    if not USE_REDIS or request.endpoint in (None, 'static', 'login', 'logout', 'touch_icon', 'favicon', 'service_worker'):
        return
    if _redis('GET', REDIS_VER_KEY) != _doc_ver:
        _apply_doc(load_doc())


# Extra-Zeilen einmal anlegen (passiert nur, solange es sie noch nicht gibt)
if _add_default_extra_rows() | _add_extra_notes() | _mark_missing_coins_once():
    save_all()


@app.errorhandler(ConflictError)
def on_conflict(_e):
    # Neuesten Stand laden und die Anfrage einmal wiederholen
    _apply_doc(load_doc())
    try:
        return app.view_functions[request.endpoint](**(request.view_args or {}))
    except ConflictError:
        _apply_doc(load_doc())
        return jsonify({'ok': False, 'error': 'Gerade auf einem anderen Gerät geändert. Bitte Seite neu laden.'}), 409


# ─── Passwort ───
# Ist APP_PASSWORD gesetzt, muss man sich einmal anmelden (Cookie für 30 Tage).

APP_PASSWORD = os.environ.get('APP_PASSWORD', '')
app.secret_key = os.environ.get('SESSION_SECRET') or hashlib.sha256(('muenzapp:' + APP_PASSWORD).encode()).hexdigest()
app.permanent_session_lifetime = datetime.timedelta(days=30)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = bool(os.environ.get('VERCEL'))

LOGIN_HTML = '''<!doctype html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Anmelden</title>
<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<link rel="manifest" href="/static/manifest.webmanifest">
<meta name="apple-mobile-web-app-title" content="M\u00fcnzApp">
<meta name="theme-color" content="#003399">
<style>body{font-family:system-ui,sans-serif;background:#f4f4f5;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
form{background:#fff;padding:28px;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);width:280px}
h1{font-size:20px;margin:0 0 16px}input,button{width:100%;box-sizing:border-box;padding:10px;font-size:16px;border-radius:8px}
input{border:1px solid #ccc;margin-bottom:12px}button{border:0;background:#222;color:#fff;cursor:pointer}
.err{color:#b00020;font-size:14px;margin:0 0 12px}</style></head><body>
<form method="post"><h1>Münz-App</h1>{err}<input type="password" name="password" placeholder="Passwort" autofocus>
<button type="submit">Anmelden</button></form></body></html>'''

@app.before_request
def require_login():
    if not APP_PASSWORD or request.endpoint in ('static', 'login', 'touch_icon', 'favicon', 'service_worker') or session.get('ok'):
        return refresh_doc()
    if request.path.startswith('/api/'):
        return jsonify({'ok': False, 'error': 'Nicht angemeldet'}), 401
    return redirect('/login')

@app.route('/apple-touch-icon.png')
@app.route('/apple-touch-icon-precomposed.png')
def touch_icon():
    return app.send_static_file('apple-touch-icon.png')

@app.route('/sw.js')
def service_worker():
    # Muss unter / liegen, damit er für die ganze App gilt
    return app.send_static_file('sw.js')

@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon-32.png')

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
    return generate_html(mint_arg=mint_arg, layout=layout, sheet_country=request.args.get('country', ''))

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

    # Extra-Zeile kann man auch mit ihrem Namen angeben
    for rid, meta in EXTRA_ROWS.get(cname, {}).items():
        if year == meta.get('label') and rid in get_years(cname):
            year = rid
            break
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

    extra_meta = EXTRA_ROWS.get(cname, {}).pop(year, None)
    UNDO_STACK.append({'type': 'remove-year', 'block': bl, 'country': cname, 'year': year, 'deleted': deleted, 'extra_meta': extra_meta})
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

@app.route('/api/extra-row/rename', methods=['POST'])
def rename_extra_row():
    """Namen einer Extra-Zeile ändern. Die Verknüpfung zum Google Sheet bleibt."""
    body = request.get_json(silent=True) or {}
    cname, row_id = body.get('country', ''), body.get('row', '')
    label = (body.get('label') or '').strip()[:30]
    meta = EXTRA_ROWS.get(cname, {}).get(row_id)
    note = (body.get('note') if body.get('note') is not None else (meta or {}).get('note', '')).strip()[:300]
    if not meta:
        return jsonify({'ok': False, 'error': 'Keine Extra-Zeile'}), 404
    if not label:
        return jsonify({'ok': False, 'error': 'Name darf nicht leer sein'}), 400
    taken = {year_label(cname, y) for y in get_years(cname) if y != row_id}
    if label in taken:
        return jsonify({'ok': False, 'error': f'\u201e{label}\u201c gibt es bei {cname} schon'}), 409
    prev, prev_note = meta.get('label', row_id), meta.get('note', '')
    if prev != label or prev_note != note:
        meta['label'], meta['note'] = label, note
        UNDO_STACK.append({'type': 'rename-row', 'country': cname, 'year': row_id, 'prev': prev, 'new': label,
                           'prev_note': prev_note, 'new_note': note})
        REDO_STACK.clear()
        save_all()
    return jsonify({'ok': True, 'label': label, 'note': note})

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
        mkey = ref if ref.count(':') >= 3 else ref + ':' + mint
        prev = action['prev']
        if prev:
            entry = COINS_MINT.setdefault(mkey, {})
            entry['v'] = prev
        elif mkey in COINS_MINT:
            entry = COINS_MINT[mkey]
            entry.pop('v', None)
            if not entry:
                del COINS_MINT[mkey]
    elif action['type'] == 'sync':
        _sync_set(action['changes'], use_new=False)
    elif action['type'] == 'rename-row':
        _m = EXTRA_ROWS.get(action['country'], {}).get(action['year'], {})
        _m['label'], _m['note'] = action['prev'], action.get('prev_note', _m.get('note', ''))
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
        if action.get('extra_meta'):
            EXTRA_ROWS.setdefault(cname, {})[year] = action['extra_meta']
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
        mkey = ref if ref.count(':') >= 3 else ref + ':' + mint
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
        mkey = ref if ref.count(':') >= 3 else ref + ':' + mint
        new_val = action.get('new', '')
        if new_val:
            entry = COINS_MINT.setdefault(mkey, {})
            entry['v'] = new_val
        elif mkey in COINS_MINT:
            entry = COINS_MINT[mkey]
            entry.pop('v', None)
            if not entry:
                del COINS_MINT[mkey]
    elif action['type'] == 'sync':
        _sync_set(action['changes'], use_new=True)
    elif action['type'] == 'rename-row':
        _m = EXTRA_ROWS.get(action['country'], {}).get(action['year'], {})
        _m['label'], _m['note'] = action['new'], action.get('new_note', _m.get('note', ''))
    elif action['type'] == 'add-year':
        cname = action['country']
        year = action['year']
        elist = EXTENSIONS.setdefault(cname, [])
        if year not in elist:
            elist.append(year)
            elist.sort(key=_year_sort_key)
    elif action['type'] == 'remove-year':
        EXTRA_ROWS.get(action['country'], {}).pop(action['year'], None)
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
        mkey = ref if ref.count(':') >= 3 else ref + ':' + mint
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
    elif t == 'sync':
        return action.get('desc') or f"Synchronisieren ({action.get('label', '')})"
    elif t == 'rename-row':
        return f"Zeile \u201e{action['new']}\u201c ({action['country']})"
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

def _country_by_name(name):
    return next((c for c in COUNTRIES if c['name'] == name), None)

def _mint_sheet_view_html(c):
    return ('<div id="sheetView"><a class="sheet-back-btn" href="/">\u2190 Zur\u00fcck zu allen L\u00e4ndern</a>'
            f'<h2 class="sheet-title">{c.get("flag", "")} {htmlmod.escape(c["name"])} \u2013 alle M\u00fcnzst\u00e4tten</h2>'
            + _mint_overview_html(c) + '</div>')

@app.route('/api/mint-sheet')
def api_mint_sheet():
    c = _country_by_name(request.args.get('country', ''))
    if not c or not c.get('mint_marks'):
        return jsonify({'ok': False, 'error': 'Land ohne M\u00fcnzst\u00e4tten'}), 400
    return jsonify({'ok': True, 'html': _mint_sheet_view_html(c)})

@app.route('/api/coin-value')
def api_coin_value():
    """Was in einer Zelle steht (für \u201eM\u00fcnze hinzuf\u00fcgen\u201c)."""
    ref = request.args.get('ref', '')
    if ref.count(':') < 2:
        return jsonify({'ok': False, 'error': 'Ung\u00fcltig'}), 400
    store, key, cname, _ = _resolve_storage(ref, '')
    e = store.get(key, {})
    return jsonify({'ok': True, 'v': coin_value(e), 'ct': coin_cell_type(e)})

@app.route('/api/mint-cells')
def api_mint_cells():
    """Zellen eines Landes für eine Münzstätte – zum Umschalten ohne Neuladen."""
    c = _country_by_name(request.args.get('country', ''))
    if not c or not c.get('mint_marks'):
        return jsonify({'ok': False, 'error': 'Land ohne M\u00fcnzst\u00e4tten'}), 400
    mint_arg = request.args.get('mint', '')
    cname, mints = c['name'], c['mint_marks']
    cells = {}
    for yr in get_years(cname):
        for dk in ['1c', '2c', '5c', '10c', '20c', '50c', '1\u20ac', '2\u20ac', 'CC1', 'CC2', 'CC3']:
            val, ct, sty, img = _cell_view(cname, yr, dk, mints, mint_arg)
            ck = coin_key(cname, yr, dk)
            cells[ck] = {'v': val, 'ct': ct, 'sty': sty, 'img': img, 'note': COIN_NOTES.get(f'{ck}:{mint_arg}', '')}
    return jsonify({'ok': True, 'mint': mint_arg, 'cells': cells})

def _mint_overview_html(c):
    """Münzstätten-Blatt: alle Münzstätten nebeneinander, wie im Excel-Blatt \u201edeutsche Jahre\u201c.
    Jede Zelle hat eine eigene ID mit Münzstätte, damit man sie bearbeiten kann."""
    cname, mints = c['name'], c['mint_marks']
    years = get_years(cname)
    denoms = ['1c', '2c', '5c', '10c', '20c', '50c', '1\u20ac', '2\u20ac']
    esc = htmlmod.escape

    def cell(yr, dk, mm, first):
        only = row_mint(cname, yr)
        if only and only != mm:
            return f'<td class="mo-na{" g1" if first else ""}" title="Nur bei {esc(only)}"></td>'
        e = get_coin(cname, yr, dk, mm)
        val, ct = coin_value(e), coin_cell_type(e)
        bg = _compute_cell_color(cname, yr, dk, mint=mm, ct=ct)
        if ct == 'x':
            val, bg = '\u2715', 'FFC7CE'
        elif val and '\u2715' in val:
            bg = 'FFC7CE'
        cls = ' class="g1"' if first else ''
        sty = f' style="background:#{bg}"' if bg else ''
        attrs = (f' data-ref="{esc(coin_key(cname, yr, dk))}:{esc(mm)}" data-country="{esc(cname)}" data-year="{esc(yr)}"'
                 f' data-denom="{esc(dk)}" data-mint="{esc(mm)}"')
        if yr in EXTRA_ROWS.get(cname, {}):
            attrs += f' data-year-label="{esc(year_label(cname, yr))}"'
        if ct:
            attrs += f' data-ct="{esc(ct)}"'
        if ct == 'x':
            attrs += ' data-xlocked="1"'
        mv = mintage_for(cname, yr, dk, mm)
        if mv:
            attrs += f' data-mintage="{esc(format_mintage_val(mv))}"'
        img = coin_image(e) or image_url_for(cname, yr, dk) or ''
        if img:
            attrs += f' data-link="{esc(img)}"'
        note = COIN_NOTES.get(f'{coin_key(cname, yr, dk)}:{mm}', '')
        if note:
            attrs += f' data-note="{esc(note)}"'
        if dk.startswith('CC'):
            ccn = cc_display_name(CC_NAMES.get(coin_key(cname, yr, dk), ''))
            if ccn:
                attrs += f' data-cc-name="{esc(ccn)}"'
        return f'<td{attrs}{cls}{sty}>{esc(val)}</td>'

    head1 = '<tr><th class="yr"></th>' + ''.join(f'<th class="g1" colspan="{len(mints)}">{esc(d)}</th>' for d in denoms) + '<th class="yr"></th></tr>'
    mint_heads = ''.join(('<th class="g1">' if i == 0 else '<th>') + esc(m) + '</th>' for i, m in enumerate(mints))
    head2 = '<tr><th class="yr"></th>' + mint_heads * len(denoms) + '<th class="yr"></th></tr>'
    rows = ''
    for yr in years:
        rows += f'<tr><th class="yr">{year_cell_html(cname, yr)}</th>'
        for dk in denoms:
            rows += ''.join(cell(yr, dk, mm, i == 0) for i, mm in enumerate(mints))
        rows += f'<th class="yr">{year_cell_html(cname, yr)}</th></tr>'
    main = f'<table class="mo-table"><thead>{head1}{head2}</thead><tbody>{rows}</tbody><tfoot>{head2}{head1}</tfoot></table>'

    cc_rows = ''
    for yr in years:
        for cci in (1, 2, 3):
            dk = f'CC{cci}'
            name = cc_display_name(CC_NAMES.get(coin_key(cname, yr, dk), ''))
            entries = [get_coin(cname, yr, dk, mm) for mm in mints]
            if not name and all(coin_cell_type(e) == 'x' or not coin_value(e) for e in entries):
                continue
            cc_rows += f'<tr><th class="cc-name">{esc(year_label(cname, yr))} {esc(name or dk)}</th>' + ''.join(cell(yr, dk, mm, False) for mm in mints) + '</tr>'
    cc = (f'<table class="mo-table mo-cc"><thead><tr><th class="cc-name">2\u20ac-Gedenkm\u00fcnzen</th>'
          + ''.join(f'<th>{esc(m)}</th>' for m in mints) + f'</tr></thead><tbody>{cc_rows}</tbody></table>')
    return f'<div class="mo-wrap" id="mintSheet">{main}{cc}</div>'

@app.route('/api/export/xlsx', methods=['GET'])
def export_xlsx():
    mint_arg = request.args.get('mint', '')
    segments = compute_segments()
    wb = Workbook()
    ws = wb.active
    ws.title = 'alle L\u00e4nder und Jahre'

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
                                _y = yrs[yr_idx]
                                cell.value = int(_y) if _y.isdigit() else year_label(cname, _y)
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
                                if mints:
                                    # Länder mit Münzstätten: Daten stehen im eigenen Blatt
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


    # Gap after last segment
    row_num += 1
    for ci in range(1, len(COLS_ORDER) + 1):
        ws.cell(row=row_num, column=ci).border = no_border

    # Zweites Blatt je Land mit Münzstätten (wie \u201edeutsche Jahre\u201c)
    for c in COUNTRIES:
        if c.get('mint_marks'):
            _write_mint_sheet(wb, c, cell_fill)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name='muenzapp.xlsx')

def _write_mint_sheet(wb, c, cell_fill):
    """Blatt mit allen Münzstätten nebeneinander, aufgebaut wie im eigenen Excel (\u201edeutsche Jahre\u201c)."""
    cname, mints = c['name'], c['mint_marks']
    ws = wb.create_sheet('deutsche Jahre' if cname == 'Deutschland' else f'{cname} M\u00fcnzst\u00e4tten'[:31])
    years = get_years(cname)
    denoms = ['1c', '2c', '5c', '10c', '20c', '50c', '1\u20ac', '2\u20ac']
    n = len(mints)
    thin = Side(style='thin', color='000000')
    thick = Side(style='medium', color='000000')
    cen = Alignment(horizontal='center', vertical='center')
    font = Font(size=8, name='Arial')
    bold = Font(size=8, name='Arial', bold=True)
    gray = cell_fill('EEEEEE')
    last_col = 2 + n * len(denoms)           # Jahr rechts
    head_row, mint_row, first = 3, 4, 5

    def box(cell, left_thick=False):
        cell.border = Border(left=thick if left_thick else thin, right=thin, top=thin, bottom=thin)

    def coin_cell(cell, yr, dk, mm, left_thick=False):
        e = get_coin(cname, yr, dk, mm)
        val, ct = coin_value(e), coin_cell_type(e)
        bg = _compute_cell_color(cname, yr, dk, mint=mm, ct=ct)
        if ct == 'x':
            val, bg = '\u2715', 'FFC7CE'
        elif val and '\u2715' in val:
            bg = 'FFC7CE'
        cell.value = val or None
        cell.font, cell.alignment = font, cen
        if bg:
            cell.fill = cell_fill(bg)
        box(cell, left_thick)

    def header(r_denom, r_mint):
        for di, d in enumerate(denoms):
            c1 = 2 + di * n
            ws.merge_cells(start_row=r_denom, start_column=c1, end_row=r_denom, end_column=c1 + n - 1)
            hc = ws.cell(r_denom, c1, d)
            hc.font, hc.alignment = bold, cen
            for k in range(n):
                box(ws.cell(r_denom, c1 + k), k == 0)
                mc = ws.cell(r_mint, c1 + k, mints[k])
                mc.font, mc.alignment = bold, cen
                box(mc, k == 0)
        for col in (1, last_col):
            for r in (r_denom, r_mint):
                box(ws.cell(r, col))
                ws.cell(r, col).fill = gray

    header(head_row, mint_row)
    for yi, yr in enumerate(years):
        r = first + yi
        for col in (1, last_col):
            yc = ws.cell(r, col, int(yr) if yr.isdigit() else year_label(cname, yr))
            yc.font, yc.alignment, yc.fill = bold, cen, gray
            box(yc)
        for di, dk in enumerate(denoms):
            for k, mm in enumerate(mints):
                coin_cell(ws.cell(r, 2 + di * n + k), yr, dk, mm, k == 0)
    end = first + len(years)
    header(end + 1, end)   # unten: erst Münzstätten, dann Werte (wie im eigenen Excel)

    # Rechts: 2€-Gedenkmünzen
    name_col = last_col + 2
    ws.cell(2, name_col, 'NAME').font = bold
    box(ws.cell(2, name_col))
    for k, mm in enumerate(mints):
        mc = ws.cell(2, name_col + 1 + k, mm)
        mc.font, mc.alignment = bold, cen
        box(mc)
    r = 3
    for yr in years:
        for cci in (1, 2, 3):
            dk = f'CC{cci}'
            name = cc_display_name(CC_NAMES.get(coin_key(cname, yr, dk), ''))
            entries = [get_coin(cname, yr, dk, mm) for mm in mints]
            if not name and all(coin_cell_type(e) == 'x' or not coin_value(e) for e in entries):
                continue
            nc = ws.cell(r, name_col, f'{year_label(cname, yr)} {name or dk}')
            nc.font = font
            box(nc)
            for k, mm in enumerate(mints):
                coin_cell(ws.cell(r, name_col + 1 + k), yr, dk, mm)
            r += 1

    # Spaltenbreiten wie im eigenen Excel
    ws.column_dimensions['A'].width = 5.2
    ws.column_dimensions[get_column_letter(last_col)].width = 5.2
    for col in range(2, last_col):
        ws.column_dimensions[get_column_letter(col)].width = 3.2
    ws.column_dimensions[get_column_letter(last_col + 1)].width = 2
    ws.column_dimensions[get_column_letter(name_col)].width = 30
    for k in range(n):
        ws.column_dimensions[get_column_letter(name_col + 1 + k)].width = 4
    ws.freeze_panes = ws.cell(first, 2)


@app.route('/api/export/data-json', methods=['GET'])
def export_data_json():
    # Komplette Sicherung: ganzes Dokument, gleiches Format wie muenzapp/data.json
    fname = f'muenzapp-sicherung-{datetime.date.today().isoformat()}.json'
    return (json.dumps(doc, ensure_ascii=False, indent=2),
            200, {'Content-Type': 'application/json; charset=utf-8', 'Content-Disposition': f'attachment; filename="{fname}"'})

@app.route('/api/import/data', methods=['POST'])
def import_data():
    global doc, COINS, COINS_MINT, MINTAGE, MINTAGE_MINT, CC_NAMES, IMAGE_LINKS_MINT, FILL_COLORS, COUNTRIES, COUNTRY_YEARS, EXTENSIONS, UNDO_STACK, REDO_STACK, EXTRA_ROWS, COIN_NOTES
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
        'countries': list, 'country_years': dict, 'extensions': dict, 'extra_rows': dict, 'coin_notes': dict,
    }
    targets = ['coins','coins_mint','mintage','mintage_mint','cc_coin_names','image_links_mint','countries','country_years','extensions','fill_colors','extra_rows','coin_notes']
    # Teile einer vollen Sicherung, die beim Laden nicht übernommen werden
    ignored = ('version', 'undo_stack', 'redo_stack')
    for k in payload:
        if k not in targets and k not in ignored:
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
    EXTRA_ROWS = doc.get('extra_rows', {})
    COIN_NOTES = doc.get('coin_notes', {})
    # Alte .txt-Sicherung: Auflagen stehen in den Münz-Einträgen.
    # Volle Sicherung hat eigene Listen – dann die alten Kopien nicht nehmen.
    if 'mintage' not in payload:
        for k, v in COINS.items():
            if isinstance(v, dict) and 'm' in v:
                MINTAGE[k] = v['m']
    if 'mintage_mint' not in payload:
        for k, v in COINS_MINT.items():
            if isinstance(v, dict) and 'm' in v:
                MINTAGE_MINT[k] = v['m']
    doc['mintage'] = MINTAGE
    doc['mintage_mint'] = MINTAGE_MINT
    if 'cc_coin_names' not in payload:
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

@app.route('/api/sync/preview', methods=['POST'])
def api_sync_preview():
    """Google Sheet lesen und zeigen, was sich ändern würde – speichert nichts."""
    country = (request.get_json(silent=True) or {}).get('country', '')
    try:
        changes, missing, checks = _sync_changes(country)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    return jsonify({'ok': True, 'changes': changes, 'missing_rows': missing, 'checks': checks})

@app.route('/api/sync/apply', methods=['POST'])
def api_sync_apply():
    """Genau die gezeigten Änderungen speichern – als ein Schritt, den man mit ↶ zurücknehmen kann."""
    body = request.get_json(silent=True) or {}
    stores = {'m': MINTAGE, 'mm': MINTAGE_MINT, 'cc': CC_NAMES, 'note': COIN_NOTES}
    done = []
    names = {c['name'] for c in COUNTRIES}
    # Neue Zeilen zuerst anlegen
    for ch in body.get('changes', []):
        if ch.get('kind') != 'row':
            continue
        cname, row = ch.get('country', ''), str(ch.get('row', ''))
        if cname not in names or not row or row in get_years(cname):
            continue
        meta = None
        if '+' in row:
            base, n = row.split('+')
            meta = {'base': base, 'n': int(n), 'label': (ch.get('label') or row)[:30], 'note': (ch.get('note') or '')[:300]}
            if ch.get('mint'):
                meta['mint'] = str(ch['mint'])[:3]
            if isinstance(ch.get('coins'), list):
                meta['coins'] = [str(x) for x in ch['coins']][:11]
        _create_row(cname, row, meta)
        done.append({'kind': 'row', 'key': f'{cname}:{row}', 'country': cname, 'row': row, 'meta': meta, 'prev': '', 'new': row})
    for ch in body.get('changes', []):
        if ch.get('kind') == 'row':
            continue
        key, new = ch.get('key', ''), ch.get('new', '')
        if not isinstance(key, str) or key.count(':') < 2 or not isinstance(new, str) or not new:
            continue
        if ch.get('kind') == 'ct':
            # Zellfarbe setzen (in den Münzen, nicht in den Auflagen)
            if new not in ('green', 'blue', 'orange', 'yellow', 'nifc', 'x'):
                continue
            coins = COINS_MINT if ch.get('store') == 'coins_mint' else COINS
            prev = coins.get(key, {}).get('ct', '')
            if prev == new:
                continue
            coins.setdefault(key, {})['ct'] = new
            done.append({'kind': 'ct', 'store': 'coins_mint' if coins is COINS_MINT else 'coins', 'key': key, 'prev': prev, 'new': new})
            continue
        store = stores.get(ch.get('kind'))
        if store is None:
            continue
        prev = store.get(key, '')
        if prev == new:
            continue
        store[key] = new
        done.append({'kind': ch['kind'], 'key': key, 'prev': prev, 'new': new})
    if done:
        UNDO_STACK.append({'type': 'sync', 'label': body.get('label', '') or 'alle L\u00e4nder', 'changes': done})
        REDO_STACK.clear()
        save_all()
    return jsonify({'ok': True, 'count': len(done)})

def _create_row(cname, row, meta):
    elist = EXTENSIONS.setdefault(cname, [])
    if row not in elist:
        elist.append(row)
        elist.sort(key=_year_sort_key)
    if meta:
        EXTRA_ROWS.setdefault(cname, {})[row] = dict(meta)

def _drop_row(cname, row):
    elist = EXTENSIONS.get(cname, [])
    if row in elist:
        elist.remove(row)
    if not elist:
        EXTENSIONS.pop(cname, None)
    EXTRA_ROWS.get(cname, {}).pop(row, None)

def _sync_set(changes, use_new):
    """Für Rückgängig/Wiederholen: Werte einer Synchronisierung setzen."""
    stores = {'m': MINTAGE, 'mm': MINTAGE_MINT, 'cc': CC_NAMES, 'note': COIN_NOTES}
    for ch in changes:
        if ch['kind'] == 'row':
            if use_new:
                _create_row(ch['country'], ch['row'], ch.get('meta'))
            else:
                _drop_row(ch['country'], ch['row'])
            continue
        val = ch['new'] if use_new else ch['prev']
        if ch['kind'] == 'ct':
            coins = COINS_MINT if ch.get('store') == 'coins_mint' else COINS
            if val:
                coins.setdefault(ch['key'], {})['ct'] = val
            elif ch['key'] in coins:
                coins[ch['key']].pop('ct', None)
                if not coins[ch['key']]:
                    del coins[ch['key']]
            continue
        store = stores[ch['kind']]
        if val:
            store[ch['key']] = val
        else:
            store.pop(ch['key'], None)

def _mintage_color(val):
    if str(val or '').strip().upper() == 'NIFC':
        return 'FFC7CE'   # nicht für den Umlauf
    clean = str(val or '').replace('.', '').replace(',', '')
    if not clean.isdigit():
        return ''
    n = int(clean)
    if n > 5000000: return 'C5DEB5'
    if n > 2000000: return '8EAADB'
    if n > 1000000: return 'FF8C42'
    if n > 0: return 'FFE598'
    return ''

def _sync_changes(country_name=''):
    """Liest das Google Sheet und gibt die Unterschiede zurück (alt \u2192 neu). Speichert nichts."""
    sel_countries = [c for c in COUNTRIES if not country_name or c['name'] == country_name]
    MINTAGE_NOW, MINTAGE_MINT_NOW, CC_NOW = dict(MINTAGE), dict(MINTAGE_MINT), dict(CC_NAMES)
    req = urllib.request.Request(SHEET_XLSX_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw = resp.read()
    wb = load_workbook(io.BytesIO(raw), data_only=True)

    tab_index = {}
    note_index = {}
    _mint_tab_map = {}
    tab_cols = {}      # Blatt -> erkannte Spalten
    tab_years = {}     # Blatt -> Liste der Jahre (auch doppelte)
    for tab in wb.sheetnames:
        ws = wb[tab]
        hr = _find_header_row(ws)
        col_map = _build_column_map(ws)
        if not col_map:
            continue
        d = {}
        nd = {}
        mapped = set(col_map.values())
        last_year, n_extra = None, 0
        tab_cols[tab] = set(col_map)
        tab_years[tab] = []
        for r in range(3, ws.max_row + 1):
            yv = ws.cell(r, 2).value
            try:
                ykey = str(int(float(yv)))
                last_year, n_extra = ykey, 0
                tab_years[tab].append(ykey)
            except (ValueError, TypeError):
                # Zeile ohne Jahr direkt unter einem Jahr = Variante (z.B. Belgien 5c 2022, geprägt 2023)
                if yv is None and last_year and any(_sheet_cell_str(ws.cell(r, sc).value) for sc in col_map.values()):
                    n_extra += 1
                    ykey = f'{last_year}+{n_extra}'
                else:
                    if yv is not None:
                        last_year = None   # Text in Spalte B: Tabelle ist zu Ende
                    continue
            for (dl, cci), scol in col_map.items():
                s = _sheet_cell_str(ws.cell(r, scol).value)
                if s:
                    d[(ykey, dl, cci)] = s
                note = _sheet_note(ws, r, scol, hr, mapped)
                if note:
                    nd[(ykey, dl, cci)] = note
        tab_index[tab] = d
        note_index[tab] = nd
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

    new_mintage = {}
    new_mintage_mint = {}
    new_cc_names = {}
    new_notes = {}

    # Zeilen, die im Sheet stehen, aber in der App fehlen (neues Jahr oder neue Extra-Zeile)
    roman = {1: 'II', 2: 'III', 3: 'IV', 4: 'V', 5: 'VI'}
    virtual = {}      # Land -> {Zeilen-ID: Sheet-Schlüssel}
    new_rows = []
    for c in sel_countries:
        eng = c.get('image_name_en', '')
        if not eng:
            continue
        tabs = [eng] + list(_mint_tab_map.get(eng, {}).values())
        have = {_sheet_year_key(c['name'], y) for y in get_years(c['name'])}
        found = {}
        for t in tabs:
            for (yk, dl, cci) in tab_index.get(t, {}):
                found.setdefault(yk, set()).add(t)
        for yk in sorted(found, key=_year_sort_key):
            if yk in have:
                continue
            if '+' in yk:
                base, n = yk.split('+')
                n = int(n)
                label = f'{base} {roman.get(n, str(n + 1))}'
                notes = [v for t in tabs for (k, _dl, _cc), v in note_index.get(t, {}).items() if k == yk]
                note = notes[0] if notes else ''
            else:
                base, n, label, note = yk, 0, yk, ''
            virtual.setdefault(c['name'], {})[yk] = yk
            only = ''
            mint_tabs = {v: k for k, v in _mint_tab_map.get(eng, {}).items()}
            if n and len(found[yk]) == 1 and next(iter(found[yk])) in mint_tabs:
                only = mint_tabs[next(iter(found[yk]))]
            coins_now = set()
            for t in ([_mint_tab_map.get(eng, {}).get(only)] if only else tabs):
                coins_now |= _row_coins(tab_index.get(t, {}), yk)
            new_rows.append({'kind': 'row', 'key': f"{c['name']}:{yk}", 'country': c['name'], 'year': yk, 'row': yk,
                             'coins': sorted(coins_now),
                             'base': base, 'n': n, 'label': label, 'note': note, 'denom': '', 'mint': only,
                             'old': '', 'new': label, 'year_label': label + (f' (nur {only})' if only else '')})

    def years_of(cname):
        return get_years(cname) + list(virtual.get(cname, {}))

    def ykey_of(cname, yr):
        return virtual.get(cname, {}).get(yr) or _sheet_year_key(cname, yr)

    result = {}
    result_mint = {}
    for c in sel_countries:
        cname = c['name']
        bl = c['block']
        eng = c.get('image_name_en', '')
        if not eng:
            continue
        tab_name = eng
        mints = c.get('mint_marks', [])
        yrs = years_of(cname)
        for yr in yrs:
            year_int = ykey_of(cname, yr)
            if not year_int:
                continue
            # Notizen zu den Münzen dieser Zeile
            for dk in ['1c','2c','5c','10c','20c','50c','1\u20ac','2\u20ac','CC1','CC2','CC3']:
                dl, cci = ('CC', int(dk[2])) if dk.startswith('CC') else (dk, 0)
                if mints and tab_name in _mint_tab_map:
                    for mint, mtab in _mint_tab_map[tab_name].items():
                        nt = note_index.get(mtab, {}).get((year_int, dl, cci))
                        if nt:
                            new_notes[coin_key(cname, yr, dk) + ':' + mint] = nt
                else:
                    nt = note_index.get(tab_name, {}).get((year_int, dl, cci))
                    if nt:
                        new_notes[coin_key(cname, yr, dk)] = nt
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
    for c in sel_countries:
        cname = c['name']
        eng = c.get('image_name_en', '')
        if not eng or eng not in _cc_tab_names:
            continue
        cc_data = _cc_tab_names[eng]
        yrs = years_of(cname)
        for yr in yrs:
            if not yr.isdigit():
                continue
            for cci in [1, 2, 3]:
                name_val = cc_data.get((int(yr), cci))
                if name_val:
                    new_cc_names[coin_key(cname, yr, f'CC{cci}')] = name_val

    changes = []
    hex_to_type = {v: k for k, v in _CT_COLOR.items() if k in ('green', 'blue', 'orange', 'yellow', 'nifc')}

    for kind, new_d, now in (('m', new_mintage, MINTAGE_NOW), ('mm', new_mintage_mint, MINTAGE_MINT_NOW)):
        for key, val in new_d.items():
            val = format_mintage_val(val)
            old = now.get(key, '')
            changed = not (val == old or format_mintage_val(old) == val)
            parts = key.split(':')
            cname, yr, dk = parts[0], parts[1], parts[2]
            mint = parts[3] if len(parts) > 3 else ''
            if changed:
                changes.append({'kind': kind, 'key': key, 'country': cname, 'year': yr, 'denom': dk, 'mint': mint, 'old': old, 'new': val})
            # Farbe folgt der neuen Auflage – auch wenn sie selbst gewählt war.
            # Steht im Sheet "NIFC", bekommt das Feld die Farbe NIFC – auch wenn die Zahl gleich geblieben ist.
            c_new = _mintage_color(val)
            if not c_new or (not changed and c_new != 'FFC7CE'):
                continue
            if mint:
                store, ekey = 'coins_mint', key
                cur_ct = coin_cell_type(COINS_MINT.get(key, {}))
                c_old = _compute_cell_color(cname, yr, dk, mint=mint, ct=cur_ct)
            else:
                store, ekey = 'coins', key
                cur_ct = coin_cell_type(COINS.get(key, {}))
                c_old = _compute_cell_color(cname, yr, dk, ct=cur_ct)
            if c_old != c_new:
                changes.append({'kind': 'ct', 'store': store, 'key': ekey, 'for_key': key, 'country': cname, 'year': yr,
                                'denom': dk, 'mint': mint, 'old': cur_ct, 'new': hex_to_type[c_new],
                                'old_type': hex_to_type.get(c_old, ''), 'color_old': c_old, 'color_new': c_new})
    for key, val in new_notes.items():
        old = COIN_NOTES.get(key, '')
        if val != old:
            parts = key.split(':')
            changes.append({'kind': 'note', 'key': key, 'country': parts[0], 'year': parts[1], 'denom': parts[2],
                            'mint': parts[3] if len(parts) > 3 else '', 'old': old, 'new': val})
    for key, val in new_cc_names.items():
        old = CC_NOW.get(key, '')
        if val != old:
            cname, yr, dk = key.split(':')[:3]
            changes.append({'kind': 'cc', 'key': key, 'country': cname, 'year': yr, 'denom': dk, 'mint': '', 'old': old, 'new': val})
    missing = []   # neue Zeilen werden jetzt als eigene Änderung angeboten
    new_labels = {(r['country'], r['row']): r['label'] for r in new_rows}
    for ch in changes:
        if (ch['country'], ch['year']) in new_labels:
            ch['year_label'] = new_labels[(ch['country'], ch['year'])] + ' (neu)'
            ch['new_row'] = f"{ch['country']}:{ch['year']}"
        else:
            ch['year_label'] = year_label(ch['country'], ch['year'])
        ch['year_num'] = _year_sort_key(ch['year'])[1] if isinstance(_year_sort_key(ch['year'])[1], int) else 9999
    for r in new_rows:
        if not r['n']:
            continue
        c = next(x for x in sel_countries if x['name'] == r['country'])
        eng = c.get('image_name_en', '')
        mints = [r['mint']] if r['mint'] else c.get('mint_marks', [])
        for dk in _ALL_DENOMS:
            dl, cci = ('CC', int(dk[2])) if dk.startswith('CC') else (dk, 0)
            for m in (mints or ['']):
                tab = _mint_tab_map.get(eng, {}).get(m) if m else eng
                val = tab_index.get(tab, {}).get((r['row'], dl, cci), '')
                if val and val.upper() != 'N/A':
                    continue
                key = f"{coin_key(r['country'], r['row'], dk)}:{m}" if m else coin_key(r['country'], r['row'], dk)
                changes.append({'kind': 'ct', 'store': 'coins_mint' if m else 'coins', 'key': key, 'for_key': key,
                                'country': r['country'], 'year': r['row'], 'denom': dk, 'mint': m, 'old': '', 'new': 'x',
                                'old_type': '', 'color_old': '', 'color_new': 'FFC7CE',
                                'year_label': r['label'] + ' (neu)', 'new_row': r['key'], 'year_num': _year_sort_key(r['row'])[1]})
    order = {c['name']: c.get('display_order', 0) for c in COUNTRIES}
    changes.sort(key=lambda c: (order.get(c['country'], 99), _year_sort_key(c['year']), c['denom'], c['mint'], c['kind']))
    for r in new_rows:
        r['year_num'] = _year_sort_key(r['year'])[1]
    checks = _sync_checks(sel_countries, country_name, wb.sheetnames, tab_index, tab_cols, tab_years, _mint_tab_map)
    return new_rows + changes, missing, checks


_EXPECTED_COLS = {('1c', 0): '1 cent', ('2c', 0): '2 cents', ('5c', 0): '5 cents', ('10c', 0): '10 cents',
                  ('20c', 0): '20 cents', ('50c', 0): '50 cents', ('1\u20ac', 0): '1 Euro', ('2\u20ac', 0): '2 Euros',
                  ('CC', 1): 'CC 1', ('CC', 2): 'CC 2', ('CC', 3): 'CC Common'}

def _row_coins(tab_d, ykey):
    """Welche Münzen in einer Sheet-Zeile einen Wert haben (ohne N/A)."""
    out = set()
    for (yk, dl, cci), v in tab_d.items():
        if yk == ykey and v.strip().upper() != 'N/A':
            out.add(f'CC{cci}' if dl == 'CC' else dl)
    return out

def _sync_checks(sel_countries, country_name, sheetnames, tab_index, tab_cols, tab_years, mint_tab_map):
    """Prüft, ob App und Google Sheet zusammenpassen. Gibt Liste von {'level': 'error'|'warn', 'text': ...} zurück."""
    out = []
    def err(t): out.append({'level': 'error', 'text': t})
    def warn(t): out.append({'level': 'warn', 'text': t})
    denom_name = {'1\u20ac': '1\u20ac', '2\u20ac': '2\u20ac', 'CC1': 'Gedenk 1', 'CC2': 'Gedenk 2', 'CC3': 'Gedenk 3'}
    used_tabs = set()
    for c in sel_countries:
        cname, eng = c['name'], c.get('image_name_en', '')
        if not eng:
            warn(f'{cname}: kein \u201eBild-Name (englisch)\u201c \u2013 Land wird nicht geladen.')
            continue
        mints = c.get('mint_marks', [])
        tabs = list(mint_tab_map.get(eng, {}).values()) if mints else [eng]
        if mints:
            for m in mints:
                if m not in mint_tab_map.get(eng, {}):
                    err(f'{cname}: Blatt \u201e{eng} {m}\u201c fehlt im Sheet \u2013 M\u00fcnzst\u00e4tte {m} wird nicht geladen.')
        elif eng not in sheetnames:
            err(f'{cname}: kein Blatt \u201e{eng}\u201c im Sheet \u2013 Land wird nicht geladen.')
            continue
        for t in tabs:
            used_tabs.add(t)
            if t not in tab_cols:
                err(f'{cname}: im Blatt \u201e{t}\u201c wurden keine M\u00fcnz-Spalten erkannt.')
                continue
            miss = [h for k, h in _EXPECTED_COLS.items() if k not in tab_cols[t]]
            if miss:
                err(f'{cname}: Spalten fehlen im Blatt \u201e{t}\u201c: {", ".join(miss)} \u2013 diese werden nicht geladen.')
            dup = sorted({y for y in tab_years[t] if tab_years[t].count(y) > 1})
            if dup:
                err(f'{cname}: Jahr doppelt im Blatt \u201e{t}\u201c: {", ".join(dup)} \u2013 bitte im Sheet pr\u00fcfen.')
        # Jahre der App, die im Sheet fehlen
        sheet_years = set()
        for t in tabs:
            sheet_years.update(tab_years.get(t, []))
        app_years = [y for y in get_years(cname) if y.isdigit()]
        gone = [y for y in app_years if y not in sheet_years]
        if gone and sheet_years:
            warn(f'{cname}: diese Jahre gibt es in der App, aber nicht im Sheet: {", ".join(gone)}.')
        # Extra-Zeilen: sieht die Zeile im Sheet noch so aus wie erwartet?
        for row, meta in EXTRA_ROWS.get(cname, {}).items():
            if not meta.get('n') or row not in get_years(cname):
                continue
            yk = f"{meta['base']}+{meta['n']}"
            label = meta.get('label', row)
            row_tabs = [mint_tab_map.get(eng, {}).get(meta['mint'])] if meta.get('mint') else tabs
            now = set()
            exists = False
            for t in row_tabs:
                if t in tab_index:
                    if any(k[0] == yk for k in tab_index[t]):
                        exists = True
                    now |= _row_coins(tab_index[t], yk)
            if not exists:
                warn(f'{cname} \u201e{label}\u201c: diese Extra-Zeile gibt es im Sheet nicht mehr (unter {meta["base"]}).')
                continue
            expect = meta.get('coins')
            if expect is None:
                expect = _EXTRA_ROW_COINS.get((cname, meta['base'], meta['n']))
            if expect is not None and set(expect) != now:
                show = lambda xs: ', '.join(denom_name.get(x, x) for x in sorted(xs, key=_ALL_DENOMS.index)) or 'nichts'
                warn(f'{cname} \u201e{label}\u201c sieht im Sheet anders aus: erwartet {show(expect)}, jetzt {show(now)}. '
                     f'Vielleicht wurde im Sheet eine Zeile eingef\u00fcgt \u2013 bitte pr\u00fcfen.')
    if not country_name:
        bases = set()
        for t in sheetnames:
            if t in tab_cols:
                parts = t.rsplit(' ', 1)
                bases.add(parts[0] if len(parts) == 2 and len(parts[1]) == 1 else t)
        names = {c.get('image_name_en') for c in COUNTRIES}
        for b in sorted(bases - names):
            warn(f'Blatt \u201e{b}\u201c im Sheet passt zu keinem Land in der App.')
    return out

def _clean_note(text):
    return ' '.join(str(text or '').split())

def _sheet_note(ws, r, scol, hr, mapped):
    """Notiz zu einer Münze im Sheet: Kommentar der Zelle, dazu die Nachbar-Spalte ohne eigene Überschrift
    (bei Griechenland steht dort der Buchstabe der Münzstätte mit eigener Notiz)."""
    parts = []
    c = ws.cell(r, scol)
    if c.comment:
        parts.append(_clean_note(c.comment.text))
    nb = scol + 1
    if nb not in mapped and ws.cell(hr, nb).value in (None, ''):
        nc = ws.cell(r, nb)
        letter = _sheet_cell_str(nc.value) if nc.value is not None else ''
        nnote = _clean_note(nc.comment.text) if nc.comment else ''
        if letter and len(letter) <= 3 and nnote:
            parts.append(f'{letter} \u00b7 {nnote}')
        elif nnote:
            parts.append(nnote)
    uniq = []
    for p in parts:
        if p and not any(p in q or q.endswith(p) for q in uniq):
            uniq.append(p)
    return ' \u2014 '.join(uniq)

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
