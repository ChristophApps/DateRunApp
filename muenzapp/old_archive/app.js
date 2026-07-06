// ============================================================
// CONFIGURATION
// ============================================================
const DENOMS = ['1c','2c','5c','10c','20c','50c','1','2'];
const COMMEMS = ['CC1','CC2','CCC'];
const ALL_DENOMS = [...DENOMS, ...COMMEMS];

const BLOCKS = [
  { cols: ['\xd6sterreich', null, 'Italien'] },
  { cols: ['Frankreich', 'Spanien', 'Finnland'] },
  { cols: ['Belgien', 'Niederlande', 'Luxemburg'] },
  { cols: ['Irland', 'Griechenland', 'Portugal'] },
  { cols: ['Slowenien', 'Malta', 'Zypern'] },
  { cols: ['Slowakei', 'Estland', 'Lettland'] },
  { cols: ['Litauen', 'Kroatien', 'Andorra'] },
  { cols: [null, 'Bulgarien', null] },
  { cols: ['San Marino', 'Monaco', 'Vatikan'] },
];

function denomLabel(d) {
  if (d === '1') return '\u20ac1';
  if (d === '2') return '\u20ac2';
  return d;
}

// ============================================================
// DATA MODEL
// ============================================================
let data = {};
let firebaseConfig = null;
let firebaseReady = false;
let syncEnabled = false;
let syncTimer = null;

function defaultYear() {
  const o = {};
  ALL_DENOMS.forEach(d => o[d] = '');
  return o;
}

function getData(country, year, denom) {
  return data[country]?.[year]?.[denom] ?? '';
}

function setData(country, year, denom, val) {
  if (!data[country]) data[country] = {};
  if (!data[country][year]) data[country][year] = defaultYear();
  data[country][year][denom] = val;
  save();
}

function getYears(country) {
  return data[country] ? Object.keys(data[country]).sort() : [];
}

function addYear(country, year) {
  year = String(year);
  if (!data[country]) data[country] = {};
  if (!data[country][year]) data[country][year] = defaultYear();
  save();
  render();
}

function removeYear(country, year) {
  year = String(year);
  if (data[country]) {
    delete data[country][year];
    if (Object.keys(data[country]).length === 0) delete data[country];
    save();
    render();
  }
}

function importData(raw) {
  data = {};
  Object.keys(raw).forEach(country => {
    data[country] = {};
    Object.keys(raw[country]).forEach(year => {
      data[country][year] = { ...defaultYear(), ...raw[country][year] };
    });
  });
  save();
  render();
}

// ============================================================
// PERSISTENCE
// ============================================================
function save() {
  try {
    localStorage.setItem('muenzapp_data', JSON.stringify(data));
    if (firebaseConfig) localStorage.setItem('muenzapp_firebase_config', JSON.stringify(firebaseConfig));
  } catch(e) {}
  if (syncEnabled && firebaseReady) scheduleSync();
}

function load() {
  try {
    const d = localStorage.getItem('muenzapp_data');
    if (d) data = JSON.parse(d);
    const fc = localStorage.getItem('muenzapp_firebase_config');
    if (fc) firebaseConfig = JSON.parse(fc);
  } catch(e) {}
}

// ============================================================
// FIREBASE
// ============================================================
function scheduleSync() {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(syncToFirebase, 2000);
}

async function syncToFirebase() {
  if (!firebaseReady || !syncEnabled) return;
  try {
    await firebase.firestore().collection('muenzapp').doc('data').set({
      payload: JSON.stringify(data),
      updated: firebase.firestore.FieldValue.serverTimestamp()
    });
    setSyncStatus('\u2713 Sync');
  } catch(e) {
    setSyncStatus('\u26a0 Sync Error');
  }
}

async function loadFromFirebase() {
  try {
    const doc = await firebase.firestore().collection('muenzapp').doc('data').get();
    if (doc.exists && doc.data().payload) {
      return JSON.parse(doc.data().payload);
    }
  } catch(e) {}
  return null;
}

async function initFirebase() {
  if (!firebaseConfig) return;
  try {
    if (!firebase.apps.length) firebase.initializeApp(firebaseConfig);
    firebaseReady = true;
    setSyncStatus('\u2026 Sync');
    syncEnabled = true;
    const remote = await loadFromFirebase();
    if (remote && Object.keys(remote).length > 0) {
      // Merge: remote takes precedence
      Object.keys(remote).forEach(c => {
        if (!data[c]) data[c] = {};
        Object.keys(remote[c]).forEach(y => {
          data[c][y] = { ...defaultYear(), ...remote[c][y] };
        });
      });
      save();
      render();
      toast('Cloud data loaded');
    }
    setSyncStatus('\u2713 Sync');
  } catch(e) {
    setSyncStatus('\u2715 Sync');
    firebaseReady = false;
  }
}

function setSyncStatus(text) {
  const el = document.getElementById('sync-status');
  if (el) el.textContent = text;
}

function setupFirebaseFromJson(jsonStr) {
  try {
    const cfg = JSON.parse(jsonStr);
    if (!cfg.projectId || !cfg.apiKey) { toast('Invalid Firebase config'); return false; }
    firebaseConfig = cfg;
    localStorage.setItem('muenzapp_firebase_config', JSON.stringify(cfg));
    toast('Firebase config saved');
    initFirebase();
    return true;
  } catch(e) { toast('Invalid JSON'); return false; }
}

// ============================================================
// RENDERING
// ============================================================
function render() {
  const container = document.getElementById('blocks-container');
  container.innerHTML = '';
  BLOCKS.forEach((block, bi) => {
    const hasContent = block.cols.some(c => c !== null);
    if (!hasContent) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'block';
    // Header
    const header = document.createElement('div');
    header.className = 'block-header';
    const activeCountries = block.cols.filter(c => c !== null);
    block.cols.forEach((country, ci) => {
      const span = document.createElement('span');
      if (country) {
        span.className = 'country-name';
        span.textContent = country;
        span.style.width = (100 / activeCountries.length) + '%';
      } else {
        span.className = 'country-name gap-slot';
        span.textContent = '\u2014';
        span.style.width = (100 / Math.max(activeCountries.length, 1)) + '%';
        span.style.opacity = '0.3';
      }
      header.appendChild(span);
    });
    wrapper.appendChild(header);
    // Table
    const table = document.createElement('table');
    table.className = 'block-table';
    // Thead
    const thead = document.createElement('thead');
    const denomRow = document.createElement('tr');
    const activeColumns = block.cols.map((c, i) => ({ country: c, index: i })).filter(x => x.country !== null);
    activeColumns.forEach((col, ci) => {
      const yearTh = document.createElement('th');
      yearTh.className = 'col-year-header';
      yearTh.textContent = 'Jahr';
      denomRow.appendChild(yearTh);
      DENOMS.forEach(d => {
        const th = document.createElement('th');
        th.className = 'col-denom';
        th.textContent = denomLabel(d);
        denomRow.appendChild(th);
      });
      const gapTh = document.createElement('th');
      gapTh.className = 'col-gap';
      gapTh.style.minWidth = '4px'; gapTh.style.maxWidth = '4px';
      denomRow.appendChild(gapTh);
      COMMEMS.forEach(d => {
        const th = document.createElement('th');
        th.className = 'col-commem';
        th.textContent = d;
        denomRow.appendChild(th);
      });
      if (ci < activeColumns.length - 1) {
        const sep = document.createElement('th');
        sep.className = 'col-gap';
        sep.style.minWidth = '12px'; sep.style.maxWidth = '12px';
        denomRow.appendChild(sep);
      }
    });
    thead.appendChild(denomRow);
    table.appendChild(thead);
    // Tbody: each country has its own independent years
    const tbody = document.createElement('tbody');
    // Get years per country
    const countryYears = activeColumns.map(col => getYears(col.country));
    const maxRows = Math.max(...countryYears.map(ys => ys.length), 0);
    for (let ri = 0; ri < maxRows; ri++) {
      const tr = document.createElement('tr');
      activeColumns.forEach((col, ci) => {
        const country = col.country;
        const year = ri < countryYears[ci].length ? countryYears[ci][ri] : '';
        const yearTd = document.createElement('td');
        yearTd.className = 'col-year';
        yearTd.textContent = year;
        tr.appendChild(yearTd);
        DENOMS.forEach(d => {
          const td = document.createElement('td');
          td.className = 'col-denom';
          if (year) {
            const val = getData(country, year, d);
            td.textContent = val;
            applyCellStyle(td, val);
            td.dataset.country = country;
            td.dataset.year = year;
            td.dataset.denom = d;
            td.addEventListener('click', () => openEditor(td, country, year, d));
          }
          tr.appendChild(td);
        });
        const gapTd = document.createElement('td');
        gapTd.className = 'col-gap';
        gapTd.style.minWidth = '4px'; gapTd.style.maxWidth = '4px';
        tr.appendChild(gapTd);
        COMMEMS.forEach(d => {
          const td = document.createElement('td');
          td.className = 'col-commem';
          if (year) {
            const val = getData(country, year, d);
            td.textContent = val;
            applyCellStyle(td, val);
            td.dataset.country = country;
            td.dataset.year = year;
            td.dataset.denom = d;
            td.addEventListener('click', () => openEditor(td, country, year, d));
          }
          tr.appendChild(td);
        });
        if (ci < activeColumns.length - 1) {
          const sep = document.createElement('td');
          sep.className = 'col-gap';
          sep.style.minWidth = '12px'; sep.style.maxWidth = '12px';
          tr.appendChild(sep);
        }
      });
      tbody.appendChild(tr);
    }
    // Add year row
    if (activeColumns.length > 0) {
      const addRow = document.createElement('tr');
      const addCountry = activeColumns[0].country;
      const addTd = document.createElement('td');
      addTd.className = 'col-year';
      addTd.textContent = '+';
      addTd.style.cursor = 'pointer';
      addTd.style.color = '#3498db';
      addTd.style.fontWeight = 'bold';
      addTd.addEventListener('click', () => openYearAdder(addCountry));
      addRow.appendChild(addTd);
      const colsPerCountry = DENOMS.length + 1 + COMMEMS.length;
      activeColumns.forEach((col, ci) => {
        for (let i = 0; i < colsPerCountry; i++) {
          const td = document.createElement('td');
          td.style.border = 'none';
          addRow.appendChild(td);
        }
        if (ci < activeColumns.length - 1) {
          const sep = document.createElement('td');
          sep.style.border = 'none';
          sep.style.minWidth = '12px';
          addRow.appendChild(sep);
        }
      });
      tbody.appendChild(addRow);
    }
    table.appendChild(tbody);
    wrapper.appendChild(table);
    container.appendChild(wrapper);
  });
}

function applyCellStyle(td, val) {
  td.className = td.className.split(' ')[0];
  if (!val) { td.classList.add('cell-empty'); return; }
  if (val === '\u2714') { td.classList.add('cell-have'); return; }
  if (val === '\u2715') { td.classList.add('cell-missing'); return; }
  // Check quality numbers
  const first = val.charAt(0);
  if (first === '0') td.classList.add('cell-quality-0');
  else if (first === '1') td.classList.add('cell-quality-1');
  else if (first === '3') td.classList.add('cell-quality-3');
  else if (first === '5') td.classList.add('cell-quality-5');
  else if (val.includes('\u2714')) td.classList.add('cell-have');
  if (val.length > 1 && !val.includes('\u2715')) td.classList.add('cell-has-source');
}

// ============================================================
// CELL EDITOR
// ============================================================
let activeEditorTd = null;
let editorCountry = '';
let editorYear = '';
let editorDenom = '';

function openEditor(td, country, year, denom) {
  activeEditorTd = td;
  editorCountry = country;
  editorYear = year;
  editorDenom = denom;
  const current = getData(country, year, denom);
  document.getElementById('editor-title').textContent = `${country} \u2022 ${year} \u2022 ${denomLabel(denom)}`;
  document.getElementById('editor-preview').textContent = current || '(leer)';
  document.getElementById('editor-input').value = current;
  // Highlight current base
  document.querySelectorAll('.editor-base-btn').forEach(b => {
    const val = b.dataset.val;
    b.classList.toggle('selected', val === current || (val === '' && current === ''));
    b.classList.toggle('selected-base', val === current);
  });
  document.getElementById('editor-modal').classList.add('active');
}

function editorSelect(val) {
  document.getElementById('editor-input').value = val;
  editorPreview(val);
  document.querySelectorAll('.editor-base-btn').forEach(b => {
    b.classList.toggle('selected', b.dataset.val === val);
    b.classList.toggle('selected-base', b.dataset.val === val);
  });
}

function editorAppend(suffix) {
  const input = document.getElementById('editor-input');
  let val = input.value;
  if (!val) { val = suffix; }
  else if (val.includes(suffix)) { toast('Already has ' + suffix); return; }
  else { val += suffix; }
  input.value = val;
  editorPreview(val);
}

function editorPreview(val) {
  document.getElementById('editor-preview').textContent = val || '(leer)';
}

function editorApply() {
  const val = document.getElementById('editor-input').value;
  setData(editorCountry, editorYear, editorDenom, val);
  if (activeEditorTd) {
    activeEditorTd.textContent = val;
    applyCellStyle(activeEditorTd, val);
  }
  closeEditor();
}

function editorClear() {
  setData(editorCountry, editorYear, editorDenom, '');
  if (activeEditorTd) {
    activeEditorTd.textContent = '';
    applyCellStyle(activeEditorTd, '');
  }
  closeEditor();
}

function closeEditor() {
  document.getElementById('editor-modal').classList.remove('active');
  activeEditorTd = null;
}

// ============================================================
// YEAR MANAGEMENT
// ============================================================
function openYearAdder(country) {
  if (!country) return;
  document.getElementById('ym-country').value = country;
  document.getElementById('ym-year').value = new Date().getFullYear();
  document.getElementById('year-manager').classList.add('active');
}

function ymAdd() {
  const country = document.getElementById('ym-country').value;
  const year = document.getElementById('ym-year').value;
  if (!country || !year) return;
  addYear(country, year);
  toast(`Added ${year} for ${country}`);
}

function ymRemove() {
  const country = document.getElementById('ym-country').value;
  const year = document.getElementById('ym-year').value;
  if (!country || !year) return;
  if (confirm(`Remove ${year} for ${country}?`)) {
    removeYear(country, year);
    toast(`Removed ${year} for ${country}`);
  }
}

function ymClose() {
  document.getElementById('year-manager').classList.remove('active');
}

// ============================================================
// EXCEL IMPORT
// ============================================================
function importExcel(file) {
  const reader = new FileReader();
  reader.onload = function(e) {
    try {
      const wb = XLSX.read(e.target.result, { type: 'array', cellDates: false });
      const ws = wb.Sheets['alle Länder und Jahre'] || wb.Sheets[wb.SheetNames[0]];
      if (!ws) { toast('No sheet found'); return; }
      const ref = ws['!ref'];
      if (!ref) { toast('Empty sheet'); return; }
      const range = XLSX.utils.decode_range(ref);
      // Read shared strings / values
      const rows = [];
      for (let r = range.s.r; r <= range.e.r; r++) {
        const row = [];
        for (let c = range.s.c; c <= range.e.c; c++) {
          const addr = XLSX.utils.encode_cell({ r, c });
          const cell = ws[addr];
          row.push(cell ? cell.v : '');
        }
        rows.push(row);
      }
      // Parse country blocks
      parseExcelRows(rows);
      toast('Excel imported successfully');
    } catch(err) {
      toast('Import error: ' + err.message);
    }
  };
  reader.readAsArrayBuffer(file);
}

function parseExcelRows(rows) {
  const rawData = {};
  // Map known countries to their column positions
  // The Excel has countries starting at specific rows and column positions
  const countryMap = [
    { name: '\xd6sterreich', col: 0, row: 1 },
    { name: 'Italien', col: 28, row: 1 },
    { name: 'Frankreich', col: 0, row: 29 },
    { name: 'Spanien', col: 14, row: 29 },
    { name: 'Finnland', col: 28, row: 29 },
    { name: 'Belgien', col: 0, row: 61 },
    { name: 'Niederlande', col: 14, row: 61 },
    { name: 'Luxemburg', col: 28, row: 61 },
    { name: 'Irland', col: 0, row: 94 },
    { name: 'Griechenland', col: 14, row: 94 },
    { name: 'Portugal', col: 28, row: 94 },
    { name: 'Slowenien', col: 0, row: 124 },
    { name: 'Malta', col: 14, row: 124 },
    { name: 'Zypern', col: 28, row: 124 },
    { name: 'Slowakei', col: 0, row: 148 },
    { name: 'Estland', col: 14, row: 148 },
    { name: 'Lettland', col: 28, row: 148 },
    { name: 'Litauen', col: 0, row: 172 },
    { name: 'Kroatien', col: 14, row: 172 },
    { name: 'Bulgarien', col: 14, row: 180 },
    { name: 'Andorra', col: 28, row: 172 },
    { name: 'San Marino', col: 0, row: 189 },
    { name: 'Monaco', col: 14, row: 189 },
    { name: 'Vatikan', col: 28, row: 189 },
  ];
  // Column indices for each block (0-indexed from XLSX)
  // Block starting at col 0: year=col0, denoms=col1-8, gap=col9, commems=col10-12
  // Block starting at col 14: year=col14, denoms=col15-22, gap=col23, commems=col24-26
  // Block starting at col 28: year=col28, denoms=col29-36, gap=col37, commems=col38-40
  const DENOM_COLS_BLOCK0 = [1,2,3,4,5,6,7,8];
  const COMMEM_COLS_BLOCK0 = [10,11,12];
  const DENOM_COLS_BLOCK14 = [15,16,17,18,19,20,21,22];
  const COMMEM_COLS_BLOCK14 = [24,25,26];
  const DENOM_COLS_BLOCK28 = [29,30,31,32,33,34,35,36];
  const COMMEM_COLS_BLOCK28 = [38,39,40];

  countryMap.forEach(({ name, col, row: startRow }) => {
    const isBlock0 = col === 0;
    const isBlock14 = col === 14;
    const isBlock28 = col === 28;
    const denomCols = isBlock0 ? DENOM_COLS_BLOCK0 : isBlock14 ? DENOM_COLS_BLOCK14 : DENOM_COLS_BLOCK28;
    const commemCols = isBlock0 ? COMMEM_COLS_BLOCK0 : isBlock14 ? COMMEM_COLS_BLOCK14 : COMMEM_COLS_BLOCK28;
    const yearCol = col;
    // Data starts 2 rows below the header (header row + denom row)
    let dataStart = startRow + 1; // denom row
    // Find first data row: look for a cell that looks like a year number (2002-2099)
    for (let r = startRow + 1; r < Math.min(startRow + 5, rows.length); r++) {
      const row = rows[r];
      const val = row[yearCol];
      if (val !== undefined && val !== '' && val !== null) {
        const num = parseInt(String(val).trim());
        if (num >= 1999 && num <= 2099) {
          dataStart = r;
          break;
        }
      }
    }
    // Read data rows
    for (let r = dataStart; r < rows.length; r++) {
      const row = rows[r];
      const yearVal = row[yearCol];
      if (yearVal === undefined || yearVal === null || yearVal === '') break;
      const yearStr = String(yearVal).trim();
      const yearNum = parseInt(yearStr);
      if (isNaN(yearNum) || yearNum < 1999 || yearNum > 2099) {
        // Check if this is another country header
        if (typeof yearVal === 'string' && yearVal.length > 2 && !yearVal.includes('\u2714') && !yearVal.includes('\u2715')) break;
        // Skip non-year values
        continue;
      }
      if (!rawData[name]) rawData[name] = {};
      if (!rawData[name][yearStr]) rawData[name][yearStr] = {};
      denomCols.forEach((dc, i) => {
        const val = row[dc] !== undefined && row[dc] !== null ? String(row[dc]) : '';
        rawData[name][yearStr][DENOMS[i]] = val;
      });
      commemCols.forEach((cc, i) => {
        const val = row[cc] !== undefined && row[cc] !== null ? String(row[cc]) : '';
        rawData[name][yearStr][COMMEMS[i]] = val;
      });
    }
  });
  importData(rawData);
}

// ============================================================
// EXCEL EXPORT
// ============================================================
function exportExcel() {
  const wb = XLSX.utils.book_new();
  const wsData = [];
  // Build the Excel rows matching original format
  // Row 1: country headers
  const row1 = [];
  const row2 = [];
  const denomLabels = ['1c','2c','5c','10c','20c','50c','\u20ac1','\u20ac2','','CC1','CC2','CCC'];
  const allCountries = [];
  const countryColPos = {};
  BLOCKS.forEach(block => {
    block.cols.forEach((country, ci) => {
      if (!country) return;
      const colStart = ci === 0 ? 0 : ci === 1 ? 14 : 28;
      allCountries.push({ name: country, colStart });
      countryColPos[country] = colStart;
    });
  });
  // Group countries by their row block position
  const countryBlocks = BLOCKS.map(block => block.cols.filter(c => c !== null));
  // Actually let's do it row by row matching the Excel layout
  // Build a simpler matrix
  const matrix = [];
  // Header row
  const headerRow = new Array(42).fill('');
  const denomRow = new Array(42).fill('');
  // Fill country headers based on block positions
  BLOCKS.forEach(block => {
    block.cols.forEach((country, ci) => {
      if (!country) return;
      const colStart = ci === 0 ? 0 : ci === 1 ? 14 : 28;
      headerRow[colStart] = country;
      denomRow[colStart] = 'Jahr';
      DENOMS.forEach((d, i) => denomRow[colStart + 1 + i] = d);
      denomRow[colStart + 9] = ''; // gap
      COMMEMS.forEach((d, i) => denomRow[colStart + 10 + i] = d);
    });
  });
  matrix.push(headerRow);
  matrix.push(denomRow);
  // Data rows: find max years across all countries
  const maxYears = Math.max(...allCountries.map(c => getYears(c.name).length));
  const minYear = Math.min(...allCountries.map(c => {
    const y = getYears(c.name);
    return y.length ? parseInt(y[0]) : 2099;
  }));
  const maxYear = Math.max(...allCountries.map(c => {
    const y = getYears(c.name);
    return y.length ? parseInt(y[y.length - 1]) : 0;
  }));
  for (let y = minYear; y <= maxYear; y++) {
    const row = new Array(42).fill('');
    BLOCKS.forEach(block => {
      block.cols.forEach((country, ci) => {
        if (!country) return;
        const colStart = ci === 0 ? 0 : ci === 1 ? 14 : 28;
        const years = getYears(country);
        if (years.includes(String(y))) {
          row[colStart] = y;
          DENOMS.forEach((d, i) => {
            row[colStart + 1 + i] = getData(country, String(y), d);
          });
          COMMEMS.forEach((d, i) => {
            row[colStart + 10 + i] = getData(country, String(y), d);
          });
        }
      });
    });
    if (row.some(c => c !== '')) matrix.push(row);
  }
  // Add legend rows
  matrix.push([]);
  matrix.push(['', '', 'Pr\u00e4gung <= 1 Millionen']);
  matrix.push(['', '', 'Pr\u00e4gung  \xfcber 1Million bis 2 Millionen', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '0', 'UNC', '', '', '', '', '', '', '', '', '', 'x', 'selbst gesammelt']);
  matrix.push(['', '', 'Pr\u00e4gung \xfcber 2 Million bis 5 Millionen', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '1', 'gute/sehr gute Qualit\u00e4t', '', '', '', '', '', '', '', '', '', 'x\u00b0', 'von wem aus M\xfcnzgruppe']);
  matrix.push(['', '', 'Pr\u00e4gung \xfcber 5 Millionen', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '3', 'schlechte/meh Qualit\u00e4t', '', '', '', '', '', '', '', '', '', 'xy\u00b0', 'selbst gesammelt & von wem aus M\xfcnzgruppe']);
  matrix.push(['', '', 'Pr\u00e4gung unbekannt', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '5', 'sehr schlechte Qualit\u00e4t', '', '', '', '', '', '', '', '', '', 'x*', 'gekaufte M\xfcnzen']);
  matrix.push(['', '', 'NIFC (never intended for circulation)', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 'xy*', 'selbst gesammelt & gekauft']);
  matrix.push(['\u2715', 'nicht gepr\u00e4gt', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 'x\u00b0y*', 'von wem aus M\xfcnzgruppe & gekauft']);
  matrix.push(['', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', '', 'xyz\u2019', 'gesammelt & von wem aus M\xfcnzgruppe & gekauft']);
  matrix.push([]);
  matrix.push(['', 'x/y/z in der dritten Spalte stehen f\xfcr die jewelige Qualit\xe4t in der zweiten Spalte']);
  matrix.push([]);
  matrix.push(['', 'Pr\u00e4gungszahlen:', '']);
  matrix.push(['', '', 'https://www.2euro-overview.eu/auflagen.php?land=nl']);
  matrix.push(['', '', 'https://docs.google.com/spreadsheets/d/1lGbzcTmMfzQjE-7ENMhrSMpMlu859fYCAqH8juDhb40/htmlview#']);
  matrix.push(['', '', 'https://www.euro-coins.info/info/mintage/germany.html']);

  const ws = XLSX.utils.aoa_to_sheet(matrix);
  // Column widths
  ws['!cols'] = [
    { wch: 6 }, { wch: 4 }, { wch: 4 }, { wch: 4 }, { wch: 5 }, { wch: 5 }, { wch: 5 }, { wch: 4 }, { wch: 4 },
    { wch: 4 }, { wch: 4 }, { wch: 4 }, { wch: 4 },
    { wch: 2 },
    { wch: 6 }, { wch: 4 }, { wch: 4 }, { wch: 4 }, { wch: 5 }, { wch: 5 }, { wch: 5 }, { wch: 4 }, { wch: 4 },
    { wch: 4 }, { wch: 4 }, { wch: 4 }, { wch: 4 },
    { wch: 2 },
    { wch: 6 }, { wch: 4 }, { wch: 4 }, { wch: 4 }, { wch: 5 }, { wch: 5 }, { wch: 5 }, { wch: 4 }, { wch: 4 },
    { wch: 4 }, { wch: 4 }, { wch: 4 }, { wch: 4 },
  ];
  XLSX.utils.book_append_sheet(wb, ws, 'alle L\u00e4nder und Jahre');
  XLSX.writeFile(wb, 'Date Run.xlsx');
  toast('Excel exported');
}

// ============================================================
// JSON EXPORT / IMPORT (for manual sync)
// ============================================================
function exportJSON() {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'muenzapp_data.json';
  a.click();
  URL.revokeObjectURL(a.href);
}

function importJSON(file) {
  const reader = new FileReader();
  reader.onload = function(e) {
    try {
      const d = JSON.parse(e.target.result);
      importData(d);
      toast('JSON imported');
    } catch(err) {
      toast('Invalid JSON file');
    }
  };
  reader.readAsText(file);
}

// ============================================================
// LEGEND TOGGLE
// ============================================================
function toggleLegend() {
  document.getElementById('legend-panel').classList.toggle('active');
}

// ============================================================
// TOAST
// ============================================================
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove('show'), 2500);
}

// ============================================================
// INIT
// ============================================================
document.addEventListener('DOMContentLoaded', function() {
  load();
  // Populate year manager country select
  const sel = document.getElementById('ym-country');
  BLOCKS.forEach(block => {
    block.cols.forEach(c => {
      if (c) { const opt = document.createElement('option'); opt.value = c; opt.textContent = c; sel.appendChild(opt); }
    });
  });
  // Set current year
  document.getElementById('ym-year').value = new Date().getFullYear();
  // Render
  render();
  // Init Firebase
  if (firebaseConfig) setTimeout(initFirebase, 500);
  // Service worker
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
  // File input handlers
  document.getElementById('excel-import-input').addEventListener('change', function(e) {
    if (e.target.files[0]) importExcel(e.target.files[0]);
    e.target.value = '';
  });
  document.getElementById('json-import-input').addEventListener('change', function(e) {
    if (e.target.files[0]) importJSON(e.target.files[0]);
    e.target.value = '';
  });
  // Firebase setup
  document.getElementById('fb-save-btn').addEventListener('click', function() {
    const json = document.getElementById('fb-config-text').value;
    setupFirebaseFromJson(json);
  });
  // Close modal on overlay click
  document.getElementById('editor-modal').addEventListener('click', function(e) {
    if (e.target === this) closeEditor();
  });
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeEditor();
  });
});
