(function() {
  const msgDiv = document.getElementById('msg');
  function showMsg(text, isErr) {
    msgDiv.textContent = text;
    msgDiv.className = 'msg ' + (isErr ? 'msg-err' : 'msg-ok');
    msgDiv.style.display = 'block';
    setTimeout(function(){ msgDiv.style.display = 'none'; }, 3000);
  }

  function getActiveMint() {
    var el = document.getElementById('activeMint');
    if (el) {
      var m = el.textContent.trim();
      if (m) return m;
    }
    var m = window.location.search.match(/[?&]mint=([^&]*)/);
    return m ? m[1] : '';
  }

  function apiUrl(path) {
    var mint = getActiveMint();
    return mint ? path + '?mint=' + encodeURIComponent(mint) : path;
  }

  // ───── Legend panel toggle ─────
  document.getElementById('moreLegend').addEventListener('click', function() {
    var panel = document.getElementById('legendPanel');
    panel.style.display = panel.style.display === 'none' ? 'flex' : 'none';
  });

  // ───── Missing list modal ─────

  // ───── Missing-coin highlight mode ─────
  let missingMode = false;
  function updateMissingCell(td) {
    if (!missingMode) { td.classList.remove('cell-missing', 'cell-has'); return; }
    if (td.getAttribute('data-xlocked')) { td.classList.remove('cell-missing'); td.classList.add('cell-has'); return; }
    var val = (td.textContent || '').replace(/\u00a0/g, '').trim();
    if (!val) { td.classList.add('cell-missing'); td.classList.remove('cell-has'); }
    else { td.classList.remove('cell-missing'); td.classList.add('cell-has'); }
  }
  function refreshMissingHighlight() {
    document.querySelectorAll('[data-ref]').forEach(updateMissingCell);
  }
  document.getElementById('moreMissing').addEventListener('click', function() {
    missingMode = !missingMode;
    document.body.classList.toggle('missing-mode', missingMode);
    refreshMissingHighlight();
  });

  // ───── Edit mode ─────
  let editMode = false;
  let copySourceRef = null;
  let clickTimer = null;
  let wasDrag = false;
  let dragCells = null;
  let editPopupRefs = null;

  document.getElementById('editBtn').addEventListener('click', function() {
    editMode = !editMode;
    this.classList.toggle('active', editMode);
    document.body.classList.toggle('edit-mode', editMode);
    var hint = document.getElementById('editHint');
    if (editMode) {
      hint.textContent = '\uD83D\uDCDD Einfachklick = Popup, Doppelklick = Quelle w\u00e4hlen';
      hint.classList.add('show');
      copySourceRef = null;
      document.querySelectorAll('.edit-source, .edit-target').forEach(function(el) {
        el.classList.remove('edit-source', 'edit-target');
      });
    } else {
      hint.classList.remove('show');
      copySourceRef = null;
      hideEditPopup();
      document.querySelectorAll('.edit-source, .edit-target').forEach(function(el) {
        el.classList.remove('edit-source', 'edit-target');
      });
    }
  });

  // ───── Drag: copy-paste (source selected) or batch select (no source) ─────
  document.addEventListener('mousedown', function(e) {
    if (!editMode) return;
    var td = e.target.closest('[data-ref]');
    if (!td || !td.getAttribute('data-denom')) return;
    if (copySourceRef) {
      // Copy-paste drag
      dragCells = new Set();
      wasDrag = false;
      var startRef = td.getAttribute('data-ref');
      dragCells.add(startRef);
      td.classList.add('edit-target');
      function onMouseOver(ev) {
        var t = ev.target.closest('[data-ref]');
        if (!t || !t.getAttribute('data-denom')) return;
        var ref = t.getAttribute('data-ref');
        if (!dragCells.has(ref)) { dragCells.add(ref); t.classList.add('edit-target'); }
      }
      function onMouseUp() {
        document.removeEventListener('mouseover', onMouseOver);
        document.removeEventListener('mouseup', onMouseUp);
        if (dragCells && dragCells.size > 1) {
          wasDrag = true;
          var refs = Array.from(dragCells);
          pasteCells(copySourceRef, refs);
        }
        document.querySelectorAll('.edit-target').forEach(function(el) { el.classList.remove('edit-target'); });
        dragCells = null;
      }
      document.addEventListener('mouseover', onMouseOver);
      document.addEventListener('mouseup', onMouseUp);
      return;
    }
    // Batch selection drag (no source selected)
    hideEditPopup();
    editPopupRefs = new Set();
    wasDrag = false;
    var startRef = td.getAttribute('data-ref');
    editPopupRefs.add(startRef);
    td.classList.add('edit-selected');
    function onMouseOver(ev) {
      var t = ev.target.closest('[data-ref]');
      if (!t || !t.getAttribute('data-denom')) return;
      var ref = t.getAttribute('data-ref');
      if (!editPopupRefs.has(ref)) { editPopupRefs.add(ref); t.classList.add('edit-selected'); }
    }
    function onMouseUp() {
      document.removeEventListener('mouseover', onMouseOver);
      document.removeEventListener('mouseup', onMouseUp);
      if (editPopupRefs && editPopupRefs.size > 1) {
        wasDrag = true;
        showEditPopup();
      } else {
        editPopupRefs = null;
        document.querySelectorAll('.edit-selected').forEach(function(el) { el.classList.remove('edit-selected'); });
      }
    }
    document.addEventListener('mouseover', onMouseOver);
    document.addEventListener('mouseup', onMouseUp);
  });

  function pasteCells(sourceRef, targetRefs) {
    var filtered = targetRefs.filter(function(r) {
      if (r === sourceRef) return false;
      var td = document.querySelector('[data-ref="' + r + '"]');
      return td && td.getAttribute('data-denom');
    });
    if (!filtered.length) return;
    fetch(apiUrl('/api/copy-cell'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({source_ref: sourceRef, target_refs: filtered})
    }).then(function(r) { return r.json(); }).then(function(j) {
      if (j.ok) {
        var srcTd = document.querySelector('[data-ref="' + sourceRef + '"]');
        var srcCt = srcTd ? srcTd.getAttribute('data-ct') : '';
        var srcText = srcTd ? (srcTd.getAttribute('data-vp-val') || srcTd.textContent.trim()) : '';
        var colorMap = {green:'#C5DEB5',blue:'#8EAADB',orange:'#FF8C42',yellow:'#FFE598',nifc:'#FFC7CE',x:'#FFC7CE'};
        var bgColor = '';
        if (srcCt && colorMap[srcCt]) {
          bgColor = colorMap[srcCt];
        } else if (srcTd) {
          bgColor = srcTd.style.backgroundColor;
          if (!bgColor || bgColor === 'rgba(0, 0, 0, 0)' || bgColor === 'transparent') {
            bgColor = window.getComputedStyle(srcTd).backgroundColor;
          }
        }
        filtered.forEach(function(ref) {
          var td = document.querySelector('[data-ref="' + ref + '"]');
          if (!td) return;
          td.style.background = bgColor;
          td.setAttribute('data-ct', srcCt || '');
          if (srcCt === 'x') {
            td.textContent = '\u2715'; td.setAttribute('data-xlocked','1'); td.contentEditable='false';
          } else {
            td.removeAttribute('data-xlocked');
            if (td.textContent === '\u2715') td.textContent = '';
            td.textContent = srcText;
            td.setAttribute('data-vp-val', srcText);
          }
          updateMissingCell(td);
        });
        refreshBreakdown();
        refreshUndoPreview();
        showMsg(filtered.length + ' Zellen kopiert');
      } else {
        showMsg('Kopier-Fehler: ' + (j.error || ''), true);
      }
    }).catch(function() { showMsg('Netzwerkfehler', true); });
  }

  function toggleCopySource(td, ref) {
    if (copySourceRef === ref) {
      copySourceRef = null;
      td.classList.remove('edit-source');
      document.getElementById('editHint').textContent = '\uD83D\uDCDD Einfachklick = Popup, Doppelklick = Quelle w\u00e4hlen';
      return;
    }
    hideEditPopup();
    document.querySelectorAll('.edit-source').forEach(function(el) { el.classList.remove('edit-source'); });
    copySourceRef = ref;
    td.classList.add('edit-source');
    document.getElementById('editHint').textContent = 'Quelle: ' + ref + ' \u2014 Klick = Kopieren, Drag = Bereich kopieren';
  }

  function hexToRgb(hex) {
    var m = hex.match(/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
    return m ? 'rgb(' + parseInt(m[1],16) + ', ' + parseInt(m[2],16) + ', ' + parseInt(m[3],16) + ')' : '';
  }

  // ───── Edit popup ─────
  var POPUP_COLORS = [
    {type:'green',  color:'#C5DEB5', title:'>5 Mio.'},
    {type:'blue',   color:'#8EAADB', title:'>2-5 Mio.'},
    {type:'orange', color:'#FF8C42', title:'>1-2 Mio.'},
    {type:'yellow', color:'#FFE598', title:'\u22641 Mio.'},
    {type:'nifc',   color:'#FFC7CE', title:'NIFC'},
    {type:'x',      color:'#FFC7CE', title:'nicht gepr\u00e4gt'},
    {type:'nodata', color:'#fff',    title:'unbekannt'},
  ];
  var popupEl = null;
  var popupSelectedType = null;

  function showEditPopup() {
    var refs = editPopupRefs;
    if (!refs || !refs.size) return;
    var singleCell = refs.size === 1;
    var firstTd = document.querySelector('[data-ref="' + Array.from(refs)[0] + '"]');
    if (!firstTd) return;
    if (!popupEl) {
      popupEl = document.createElement('div');
      popupEl.className = 'edit-popup';
      document.body.appendChild(popupEl);
    }
    popupSelectedType = '';
    if (singleCell) {
      popupSelectedType = firstTd.getAttribute('data-ct') || '';
      if (!popupSelectedType) {
        var bg = (firstTd.style.backgroundColor || '').toLowerCase();
        if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
          var xRgb = hexToRgb('#FFC7CE');
          if (bg === xRgb && firstTd.textContent.trim() === '\u2715') {
            popupSelectedType = 'x';
          } else {
            for (var i = 0; i < POPUP_COLORS.length; i++) {
              var c = POPUP_COLORS[i];
              if (c.type !== 'x' && hexToRgb(c.color) === bg) {
                popupSelectedType = c.type; break;
              }
            }
          }
        }
      }
    }
    var title = singleCell ? 'Zelle bearbeiten' : refs.size + ' Zellen bearbeiten';
    var val = singleCell ? (firstTd.getAttribute('data-vp-val') || firstTd.textContent.trim()) : '';
    var colorsHtml = POPUP_COLORS.map(function(c) {
      var active = (c.type === popupSelectedType) || (c.type === 'nodata' && !popupSelectedType);
      var label = c.type === 'x' ? '\u2715' : '';
      return `<span class="popup-color-btn${active ? ' active' : ''}" data-ctype="${c.type}"` +
        ` style="background:${c.color}${label ? ';display:inline-flex;align-items:center;justify-content:center;font-weight:bold;color:#000;font-size:7pt' : ''}"` +
        ` title="${c.title}">${label}</span>`;
    }).join('');
    popupEl.innerHTML = `<div class="popup-title">${title}</div>` +
      `<input type="text" id="popupInput" value="${val.replace(/"/g, '&quot;')}" placeholder="M\u00fcnztext (\u2714, 0, 1\u00b0...)">` +
      `<div class="popup-colors">${colorsHtml}</div>` +
      '<button id="popupSave">Speichern</button>';
    var lastRef = Array.from(refs)[refs.size - 1];
    var lastTd = document.querySelector('[data-ref="' + lastRef + '"]');
    if (lastTd) {
      var rect = lastTd.getBoundingClientRect();
      popupEl.style.left = Math.min(rect.left, window.innerWidth - 230) + 'px';
      popupEl.style.top = (rect.bottom + 4) + 'px';
    }
    popupEl.style.display = 'block';
    var inp = document.getElementById('popupInput');
    if (inp) { inp.focus(); inp.select(); }
    popupEl.querySelectorAll('.popup-color-btn').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        popupSelectedType = this.getAttribute('data-ctype');
        popupEl.querySelectorAll('.popup-color-btn').forEach(function(b) { b.classList.remove('active'); });
        this.classList.add('active');
      });
    });
    document.getElementById('popupSave').addEventListener('click', function(e) {
      e.stopPropagation();
      saveEditPopup();
    });
    document.getElementById('popupInput').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') { e.preventDefault(); saveEditPopup(); }
    });
    setTimeout(function() {
      document.addEventListener('click', popupOutsideClick);
    }, 10);
  }

  function popupOutsideClick(e) {
    if (popupEl && !popupEl.contains(e.target) && !e.target.closest('[data-ref]')) {
      hideEditPopup();
    }
  }

  function saveEditPopup() {
    if (!editPopupRefs || !editPopupRefs.size || !popupEl) return;
    var refs = Array.from(editPopupRefs);
    var inp = document.getElementById('popupInput');
    var val = inp ? inp.value.trim() : '';
    var body = {refs: refs};
    var hasColor = popupSelectedType !== null && popupSelectedType !== undefined;
    var hasText = inp !== null;
    if (hasColor) body.cell_type = popupSelectedType === 'nodata' ? '' : popupSelectedType;
    if (hasText) body.coin_value = val;
    if (!hasColor && !hasText) { hideEditPopup(); return; }
    var colorMap = {green:'#C5DEB5',blue:'#8EAADB',orange:'#FF8C42',yellow:'#FFE598',nifc:'#FFC7CE',x:'#FFC7CE'};
    fetch(apiUrl('/api/batch-edit'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    }).then(function(r){ return r.json(); }).then(function(j) {
      if (j.ok) {
        var bg = colorMap[popupSelectedType] || '';
        refs.forEach(function(ref) {
          var td = document.querySelector('[data-ref="' + ref + '"]');
          if (!td) return;
          if (hasColor) {
            td.style.background = bg;
            td.setAttribute('data-ct', popupSelectedType === 'nodata' ? '' : popupSelectedType);
            if (popupSelectedType === 'x') {
              td.textContent = '\u2715'; td.setAttribute('data-xlocked','1');
            } else {
              td.removeAttribute('data-xlocked');
              if (td.textContent === '\u2715') td.textContent = '';
            }
          }
          if (hasText && td.getAttribute('data-ct') !== 'x') {
            td.textContent = val;
            td.setAttribute('data-vp-val', val);
          }
          updateMissingCell(td);
        });
        refreshBreakdown();
        refreshUndoPreview();
        showMsg('Gespeichert');
      } else {
        showMsg('Fehler: ' + (j.error || ''), true);
      }
    }).catch(function(){ showMsg('Netzwerkfehler', true); });
    hideEditPopup();
  }

  function hideEditPopup() {
    if (popupEl) popupEl.style.display = 'none';
    document.removeEventListener('click', popupOutsideClick);
    if (editPopupRefs) {
      editPopupRefs.forEach(function(ref) {
        var td = document.querySelector('[data-ref="' + ref + '"]');
        if (td) td.classList.remove('edit-selected');
      });
      editPopupRefs = null;
    }
  }

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      if (editPopupRefs) { hideEditPopup(); e.preventDefault(); }
      if (copySourceRef) {
        var td = document.querySelector('[data-ref="' + copySourceRef + '"]');
        if (td) td.classList.remove('edit-source');
        copySourceRef = null;
        document.getElementById('editHint').textContent = '\uD83D\uDCDD Einfachklick = Popup, Doppelklick = Quelle w\u00e4hlen';
        e.preventDefault();
      }
    }
  });


  // Info modal
  const infoModal = document.getElementById('infoModal');
  const infoOverlay = document.getElementById('infoOverlay');
  const infoTitle = document.getElementById('infoTitle');
  let infoRef = null;
  let infoColorType = null;
  let infoOrigCellType = null;

  const QUALITY_LABELS = {
    '\u2714': 'Qualität noch nicht bestimmt',
    '0': 'UNC',
    '1': 'Gute / sehr gute Qualität',
    '3': 'Schlechte Qualität',
    '5': 'Sehr schlechte Qualität',
  };
  const SOURCE_LABELS = {
    '\u00b0': 'Aus der Gruppe',
    'o': 'Aus der Gruppe',
    '*': 'Gekauft',
    '': 'Selbst gesammelt',
  };
  function parseCoinEntries(val) {
    if (!val || val === '\u2715' || val === '\u00d7') return [];
    var entries = [];
    var re = /(\u2714|\\d)([\u00b0o*]?)/g;
    var m;
    while ((m = re.exec(val)) !== null) {
      var q = m[1], s = m[2];
      if (q in QUALITY_LABELS) {
        entries.push({ quality: QUALITY_LABELS[q], source: SOURCE_LABELS[s] !== undefined ? SOURCE_LABELS[s] : 'Selbst gesammelt' });
      }
    }
    return entries;
  }

  function vpParseRaw(val) {
    if (!val || val === '\u2715' || val === '\u00d7') return [];
    var entries = [];
    var re = /(\u2714|\d)([\u00b0o*]?)|\[([^\]]*)\]/g;
    var m;
    while ((m = re.exec(val)) !== null) {
      if (m[1] !== undefined) {
        entries.push({ q: m[1], s: m[2] || '' });
      } else if (m[3] !== undefined) {
        entries.push({ text: m[3] });
      }
    }
    return entries;
  }
  function vpSerialize(entries) {
    return entries.map(function(e) {
      if (e.text) return '[' + e.text + ']';
      return e.q + (e.s || '');
    }).join('');
  }

  // ───── Info modal color picker ─────
  const INFO_COLOR_ITEMS = [
    {type:'green',  label:'>5 Mio',     color:'#C5DEB5'},
    {type:'blue',   label:'>2-5 Mio',   color:'#8EAADB'},
    {type:'orange', label:'>1-2 Mio',   color:'#FF8C42'},
    {type:'yellow', label:'≤1 Mio',     color:'#FFE598'},
    {type:'nifc',   label:'NIFC',       color:'#FFC7CE'},
    {type:'x',      label:'nicht geprägt', color:'#FFC7CE'},
    {type:'nodata', label:'unbekannt',   color:'#fff'},
  ];
  function buildInfoColorPicker(currentType) {
    infoColorType = currentType || '';
    infoOrigCellType = currentType || '';
    var picker = document.getElementById('infoColorPicker');
    picker.innerHTML = INFO_COLOR_ITEMS.map(function(item) {
      var isCur = (item.type === currentType) || (item.type === 'nodata' && !currentType);
      return `<span class="info-color-btn" data-icolor="${item.type}" title="${item.label}"` +
        ` style="display:inline-flex;align-items:center;gap:3px;cursor:pointer;border:1px solid #aaa;border-radius:3px;padding:2px 5px;font-size:7pt;${isCur ? 'outline:2px solid #1a73e8;outline-offset:1px;' : ''}">` +
        `<span style="display:inline-block;width:10px;height:10px;background:${item.color};border:1px solid #888;flex-shrink:0"></span>${item.label}</span>`;
    }).join('');
    picker.querySelectorAll('.info-color-btn').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        var t = this.getAttribute('data-icolor');
        infoColorType = (t === 'nodata') ? '' : t;
        picker.querySelectorAll('.info-color-btn').forEach(function(b) {
          b.style.outline = ''; b.style.outlineOffset = '';
        });
        this.style.outline = '2px solid #1a73e8';
        this.style.outlineOffset = '1px';
      });
    });
  }

  let infoCoinEntries = [];
  let infoPendingQ = null;

  function infoRenderEntries() {
    var entriesDiv = document.getElementById('infoCoinEntries');
    var addDiv = document.getElementById('infoCoinAdd');
    if (infoCoinEntries.length) {
      entriesDiv.innerHTML = infoCoinEntries.map(function(e, i) {
        var inner;
        if (e.text) {
          inner = `<span class="coin-entry-quality">${htmlEsc(e.text)}</span>`;
        } else {
          var ql = QUALITY_LABELS[e.q] || e.q;
          var sl = SOURCE_LABELS[e.s] !== undefined ? SOURCE_LABELS[e.s] : 'Selbst gesammelt';
          inner = `<span class="coin-entry-quality">${ql}</span> &mdash; <span class="coin-entry-source">${sl}</span>`;
        }
        return `<div class="coin-entry">${inner}<span class="vp-entry-del" data-idx="${i}">&times;</span></div>`;
      }).join('');
      entriesDiv.querySelectorAll('.vp-entry-del').forEach(function(el) {
        el.addEventListener('click', function(e) {
          e.stopPropagation();
          var idx = parseInt(this.getAttribute('data-idx'), 10);
          infoCoinEntries.splice(idx, 1);
          infoRenderEntries();
        });
      });
      addDiv.style.display = 'block';
    } else {
      entriesDiv.innerHTML = '<div class="vp-empty">Keine Münzen erfasst</div>';
      addDiv.style.display = 'block';
    }
  }

  function htmlEsc(s) {
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(s));
    return d.innerHTML;
  }

  function showInfoModal(ref, country, year, denom, mintage, link, cellVal, ccName, cellType) {
    infoRef = ref;
    document.getElementById('infoTitle').textContent = country + ' ' + year + ' ' + denom;
    var imgEl = document.getElementById('infoCoinImg');
    var linkEl = document.getElementById('infoCoinLink');
    if (link) {
      imgEl.onerror = function() { this.style.display = 'none'; };
      imgEl.src = link;
      imgEl.style.display = 'block';
      imgEl.parentElement.parentElement.style.display = 'flex';
      linkEl.href = link;
    } else {
      imgEl.removeAttribute('src');
      imgEl.style.display = 'none';
      imgEl.parentElement.parentElement.style.display = 'none';
      linkEl.href = '#';
    }
    document.getElementById('infoMintage').value = mintage || '';
    var ccNameDiv = document.getElementById('infoCCName');
    if (ccName) {
      document.getElementById('infoCCNameText').textContent = ccName;
      ccNameDiv.style.display = 'block';
    } else {
      ccNameDiv.style.display = 'none';
    }
    // URL edit button for CC coins
    var urlEditRow = document.getElementById('infoURLEditRow');
    var urlInputRow = document.getElementById('infoURLInputRow');
    var urlInput = document.getElementById('infoURLInput');
    if (urlEditRow && urlInputRow && urlInput) {
      if (link) {
        urlEditRow.style.display = 'block';
        urlInputRow.style.display = 'none';
        urlInput.value = link;
      } else {
        urlEditRow.style.display = 'none';
        urlInputRow.style.display = 'none';
      }
    }
    // Coin entries
    infoCoinEntries = vpParseRaw(cellVal || '');
    infoPendingQ = null;
    document.getElementById('infoCoinSourceRow').style.display = 'none';
    document.getElementById('infoCustomInputRow').style.display = 'none';
    infoRenderEntries();
    buildInfoColorPicker(cellType || '');
    infoModal.style.display = 'block';
    infoOverlay.style.display = 'block';
  }

  // URL edit button handler
  document.getElementById('infoURLEditBtn').addEventListener('click', function() {
    var urlInputRow = document.getElementById('infoURLInputRow');
    var urlEditRow = document.getElementById('infoURLEditRow');
    if (urlInputRow) urlInputRow.style.display = 'block';
    if (urlEditRow) urlEditRow.style.display = 'none';
  });

  document.getElementById('infoCoinQualityRow').querySelectorAll('.info-q-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      var q = this.getAttribute('data-q');
      if (q) {
        infoPendingQ = q;
        document.getElementById('infoCoinSourceRow').style.display = 'flex';
        document.getElementById('infoCustomInputRow').style.display = 'none';
      }
    });
  });
  document.getElementById('infoCustomBtn').addEventListener('click', function(e) {
    e.stopPropagation();
    infoPendingQ = null;
    document.getElementById('infoCoinSourceRow').style.display = 'none';
    document.getElementById('infoCustomInputRow').style.display = 'flex';
    document.getElementById('infoCustomInput').value = '';
    document.getElementById('infoCustomInput').focus();
  });
  document.getElementById('infoCoinSourceRow').querySelectorAll('.info-s-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      if (!infoPendingQ) return;
      infoCoinEntries.push({ q: infoPendingQ, s: this.getAttribute('data-s') });
      infoPendingQ = null;
      document.getElementById('infoCoinSourceRow').style.display = 'none';
      infoRenderEntries();
    });
  });
  function infoAddCustom() {
    var inp = document.getElementById('infoCustomInput');
    var txt = inp.value.trim();
    if (txt) {
      infoCoinEntries.push({ text: txt });
      inp.value = '';
      document.getElementById('infoCustomInputRow').style.display = 'none';
      infoRenderEntries();
    }
  }
  document.getElementById('infoCustomAddBtn').addEventListener('click', function(e) {
    e.stopPropagation();
    infoAddCustom();
  });
  document.getElementById('infoCustomInput').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') { e.preventDefault(); infoAddCustom(); }
  });
  // ───── (modal mint switching removed) ─────

  function hideInfoModal() {
    infoModal.style.display = 'none';
    infoOverlay.style.display = 'none';
    infoRef = null;
  }
  document.getElementById('infoClose').addEventListener('click', hideInfoModal);
  infoOverlay.addEventListener('click', hideInfoModal);

  function formatMintage(raw) {
    raw = (raw || '').trim();
    var clean = raw.replace(/[.,]/g, '');
    if (clean.length && /^[0-9]+$/.test(clean)) {
      return clean.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    }
    return raw;
  }

  function infoSaveStep(step) {
    if (step === 0) {
      // Save cell color type if changed
      var newCt = infoColorType != null ? infoColorType : '';
      var origCt = infoOrigCellType != null ? infoOrigCellType : '';
      if (newCt !== origCt) {
        var td = document.querySelector('[data-ref="' + infoRef + '"]');
        var colorMap = {green:'#C5DEB5',blue:'#8EAADB',orange:'#FF8C42',yellow:'#FFE598',nifc:'#FFC7CE',x:'#FFC7CE'};
        if (td) {
          if (newCt === 'x') {
            td.textContent = '\u2715'; td.setAttribute('data-xlocked','1'); td.contentEditable='false'; td.style.background='#FFC7CE';
          } else {
            td.removeAttribute('data-xlocked');
            if (td.textContent === '\u2715') td.textContent = '';
            td.style.background = colorMap[newCt] || '';
            td.contentEditable = 'false';
          }
          td.setAttribute('data-ct', newCt);
          updateMissingCell(td);
        }
        var ctBody = {}; ctBody[infoRef] = newCt || 'nodata';
        fetch(apiUrl('/api/cell-types'), {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(ctBody)})
          .then(function(r){ return r.json(); }).then(function(j){ if (!j.ok) showMsg('Farbe-Fehler: '+(j.error||''), true); infoSaveStep(1); refreshBreakdown(); })
          .catch(function(){ showMsg('Netzwerkfehler', true); infoSaveStep(1); });
      } else {
        infoSaveStep(1);
      }
    } else if (step === 1) {
      // Save coin entries if changed
      var td = document.querySelector('[data-ref="' + infoRef + '"]');
      var newVal = vpSerialize(infoCoinEntries);
      var origVal = td ? (td.getAttribute('data-vp-val') || td.textContent.trim()) : '';
      if (origVal === '\u2715') origVal = '';
      if (newVal !== origVal) {
        if (td) {
          td.textContent = newVal;
          td.setAttribute('data-vp-val', newVal);
          updateMissingCell(td);
        }
        var cellBody = {};
        cellBody[infoRef] = newVal;
        fetch(apiUrl('/api/cells'), {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(cellBody)})
          .then(function(r){ return r.json(); }).then(function(){ infoSaveStep(2); refreshBreakdown(); refreshUndoPreview(); })
          .catch(function(){ showMsg('Netzwerkfehler', true); infoSaveStep(2); });
      } else {
        infoSaveStep(2);
      }
    } else if (step === 2) {
      // Save mintage
      var mintage = document.getElementById('infoMintage').value.trim();
      var td = document.querySelector('[data-ref="' + infoRef + '"]');
      var urlInput = document.getElementById('infoURLInput');
      var urlInputRow = document.getElementById('infoURLInputRow');
      var link = '';
      if (urlInputRow && urlInputRow.style.display !== 'none' && urlInput) {
        link = urlInput.value.trim();
      } else if (td) {
        var activeMint = getActiveMint();
        if (activeMint) {
          link = td.getAttribute('data-link-mint-' + activeMint) || td.getAttribute('data-link') || '';
        } else {
          link = td.getAttribute('data-link') || '';
        }
      }
      var infoBody = {};
      infoBody[infoRef] = {mintage: mintage, link: link};
      fetch(apiUrl('/api/coin-info'), {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(infoBody)
      }).then(function(r){ return r.json(); }).then(function(j){
        if (j.ok) {
          if (td) {
            if (mintage) td.setAttribute('data-mintage', formatMintage(mintage));
            else td.removeAttribute('data-mintage');
            td.setAttribute('data-link', link);
          }
          refreshBreakdown();
          showMsg('Gespeichert');
          hideInfoModal();
        } else {
          showMsg('Fehler: ' + (j.error || ''), true);
        }
      }).catch(function(){ showMsg('Netzwerkfehler', true); });
    }
  }

  document.getElementById('infoSave').addEventListener('click', function() {
    if (!infoRef) return;
    infoSaveStep(0);
  });

  document.querySelectorAll('[data-ref]').forEach(function(td) {
    td.contentEditable = 'false';
    td.addEventListener('click', function(e) {
      if (!this.getAttribute('data-ref')) return;
      if (wasDrag) { wasDrag = false; return; }
      hideEditPopup();
      var ref = this.getAttribute('data-ref');
      if (editMode) {
        if (!this.getAttribute('data-denom')) return;
        if (copySourceRef) {
          if (ref === copySourceRef) {
            toggleCopySource(this, ref);
            return;
          }
          e.preventDefault();
          e.stopPropagation();
          pasteCells(copySourceRef, [ref]);
          return;
        }
        if (clickTimer) {
          clearTimeout(clickTimer); clickTimer = null;
          e.preventDefault();
          e.stopPropagation();
          toggleCopySource(this, ref);
          return;
        }
        var selfRef = ref;
        clickTimer = setTimeout(function() {
          clickTimer = null;
          if (!editMode || copySourceRef) return;
          editPopupRefs = new Set([selfRef]);
          showEditPopup();
        }, 250);
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      var country = this.getAttribute('data-country') || '';
      var year = this.getAttribute('data-year') || '';
      var denom = this.getAttribute('data-denom') || '';
      var activeMint = getActiveMint();
      var mintage = this.getAttribute('data-mintage') || '';
      if (activeMint) {
        var mintMintage = this.getAttribute('data-mint-' + activeMint) || '';
        if (mintMintage && mintMintage !== 'N/A') mintage = mintMintage;
      }
      var link = this.getAttribute('data-link') || '';
      if (activeMint) {
        var mintLink = this.getAttribute('data-link-mint-' + activeMint) || '';
        if (mintLink) link = mintLink;
      }
      var cellVal = this.textContent.trim();
      var ccName = this.getAttribute('data-cc-name') || '';
      var cellType = this.getAttribute('data-ct') || '';
      if (!cellType) {
        var bg = this.style.backgroundColor;
        if (bg) {
          var rgbMatch = bg.match(/\d+/g);
          if (rgbMatch && rgbMatch.length >= 3) {
            var r = parseInt(rgbMatch[0]), g = parseInt(rgbMatch[1]), b = parseInt(rgbMatch[2]);
            var key = r + ',' + g + ',' + b;
            if (key === '255,199,206' && this.textContent.trim() === '\u2715') {
              cellType = 'x';
            } else {
              var revColors = {'197,222,181':'green','142,170,219':'blue','255,140,66':'orange','255,229,152':'yellow','255,199,206':'nifc'};
              if (revColors[key]) cellType = revColors[key];
            }
          }
        }
      }
      showInfoModal(ref, country, year, denom, mintage, link, cellVal, ccName, cellType);
    });
  });

  // Sync button — re-import mintage from the Google Sheet
  document.getElementById('moreSync').addEventListener('click', function() {
    document.getElementById('syncOverlay').style.display = 'block';
    document.getElementById('syncModal').style.display = 'block';
  });
  document.getElementById('syncOverlay').addEventListener('click', function() {
    document.getElementById('syncOverlay').style.display = 'none';
    document.getElementById('syncModal').style.display = 'none';
  });
  document.getElementById('syncCancel').addEventListener('click', function() {
    document.getElementById('syncOverlay').style.display = 'none';
    document.getElementById('syncModal').style.display = 'none';
  });
  document.getElementById('syncConfirm').addEventListener('click', function() {
    document.getElementById('syncOverlay').style.display = 'none';
    document.getElementById('syncModal').style.display = 'none';
    var btn = document.getElementById('moreSync');
    btn.style.opacity = '0.6';
    btn.style.pointerEvents = 'none';
    btn.textContent = '\U0001f504 Synchronisiere...';
    showMsg('Auflagezahlen werden aus Google Sheet geladen...');
    fetch('/api/sync', {method: 'POST'})
      .then(function(r){ return r.json(); })
      .then(function(j){
        if (j.ok) {
          showMsg('Sync fertig: ' + j.count + ' Auflagezahlen importiert. Seite wird neu geladen...');
          setTimeout(function(){ location.reload(); }, 900);
        } else {
          showMsg('Sync-Fehler: ' + (j.error || 'unbekannt'), true);
          btn.style.opacity = '';
          btn.style.pointerEvents = '';
          btn.textContent = '\U0001f504 Auflagezahlen syncen';
        }
      })
      .catch(function(e){
        showMsg('Sync-Fehler: ' + e, true);
        btn.style.opacity = '';
        btn.style.pointerEvents = '';
        btn.textContent = '\U0001f504 Auflagezahlen syncen';
      });
  });

  // Undo / Redo
  let undoDesc = '';
  let redoDesc = '';

  function refreshUndoPreview() {
    fetch('/api/undo-preview').then(function(r){ return r.json(); }).then(function(j){
      undoDesc = j.desc || '';
      document.getElementById('undoBtn').textContent = undoDesc ? '\u21b6 ' + undoDesc : '\u21b6 Letzte Aktion r\u00fcckg\u00e4ngig';
    });
    fetch('/api/redo-preview').then(function(r){ return r.json(); }).then(function(j){
      redoDesc = j.desc || '';
      document.getElementById('redoBtn').textContent = redoDesc ? '\u21b7 ' + redoDesc : '\u21b7 Wiederholen';
    });
  }

  refreshUndoPreview();

  document.getElementById('undoBtn').addEventListener('click', function() {
    if (!undoDesc) return;
    if (!confirm(undoDesc + ' r\u00fcckg\u00e4ngig machen?')) return;
    this.textContent = '\u21b6 wird r\u00fcckg\u00e4ngig gemacht...';
    this.style.pointerEvents = 'none';
    fetch('/api/undo', {method: 'POST'})
      .then(function(r){ return r.json(); })
      .then(function(j) {
        if (j.ok) {
          showMsg('R\u00fcckg\u00e4ngig gemacht. Seite wird neu geladen...');
          if (j.ref) { sessionStorage.setItem('undoRef', j.ref); }
          refreshBreakdown();
          setTimeout(function(){ location.reload(); }, 800);
        } else {
          showMsg('Fehler: ' + (j.error || 'unbekannt'), true);
          document.getElementById('undoBtn').textContent = '\u21b6 ' + undoDesc;
          document.getElementById('undoBtn').style.pointerEvents = '';
        }
      })
      .catch(function(e){ showMsg('Fehler: ' + e, true); document.getElementById('undoBtn').textContent = '\u21b6 ' + undoDesc; document.getElementById('undoBtn').style.pointerEvents = ''; });
  });

  document.getElementById('redoBtn').addEventListener('click', function() {
    if (!redoDesc) return;
    if (!confirm(redoDesc + ' wiederholen?')) return;
    this.textContent = '\u21b7 wird wiederholt...';
    this.style.pointerEvents = 'none';
    fetch('/api/redo', {method: 'POST'})
      .then(function(r){ return r.json(); })
      .then(function(j) {
        if (j.ok) {
          showMsg('Wiederholt. Seite wird neu geladen...');
          if (j.ref) { sessionStorage.setItem('undoRef', j.ref); }
          setTimeout(function(){ location.reload(); }, 800);
        } else {
          showMsg('Fehler: ' + (j.error || 'unbekannt'), true);
          document.getElementById('redoBtn').textContent = '\u21b7 ' + redoDesc;
          document.getElementById('redoBtn').style.pointerEvents = '';
        }
      })
      .catch(function(e){ showMsg('Fehler: ' + e, true); document.getElementById('redoBtn').textContent = '\u21b7 ' + redoDesc; document.getElementById('redoBtn').style.pointerEvents = ''; });
  });

  // Scroll to cell after undo/redo (stored ref from sessionStorage)
  window.addEventListener('load', function() {
    var ref = sessionStorage.getItem('undoRef');
    if (ref) {
      sessionStorage.removeItem('undoRef');
      var cell = document.querySelector('[data-ref="' + ref + '"]');
      if (cell) {
        cell.scrollIntoView({ block: 'center' });
        cell.style.transition = 'background 1s';
        var origBg = cell.style.backgroundColor;
        cell.style.backgroundColor = '#fffaaa';
        setTimeout(function() { cell.style.backgroundColor = origBg || ''; }, 1500);
      }
    }
  });

  // ───── Export buttons ─────
  document.getElementById('exportPdfBtn').addEventListener('click', function() {
    showMsg('PDF wird erstellt...');
    window.print();
  });

  document.getElementById('exportXlsxBtn').addEventListener('click', function() {
    showMsg('Excel wird erstellt...');
    var isSplit = window.location.search.indexOf('layout=split') !== -1;
    window.location.href = isSplit ? '/api/export/xlsx?layout=split' : '/api/export/xlsx';
  });

  // Print Layout button
  document.getElementById('morePrintLayout').addEventListener('click', function() {
    window.open('/?layout=split', '_blank');
  });

  // ───── Daten dropdown (Export / Import) ─────
  function closeDataDropdown() {
    var dd = document.getElementById('dataDropdown');
    if (dd) dd.style.display = 'none';
  }
  document.getElementById('dataBtn').addEventListener('click', function(e) {
    e.stopPropagation();
    var dd = document.getElementById('dataDropdown');
    dd.style.display = dd.style.display === 'none' ? 'block' : 'none';
  });
  document.addEventListener('click', function(e) {
    if (!e.target.closest('#dataBtn') && !e.target.closest('#dataDropdown')) {
      closeDataDropdown();
    }
    if (!e.target.closest('#moreBtn') && !e.target.closest('#moreDropdown')) {
      var md = document.getElementById('moreDropdown');
      if (md) md.style.display = 'none';
    }
  });
  document.getElementById('moreBtn').addEventListener('click', function(e) {
    e.stopPropagation();
    var md = document.getElementById('moreDropdown');
    md.style.display = md.style.display === 'none' ? 'block' : 'none';
  });
  document.getElementById('dropdownExport').addEventListener('click', function() {
    closeDataDropdown();
    showMsg('Daten-Export wird gestartet...');
    window.location.href = '/api/export/data';
  });
  document.getElementById('dropdownImport').addEventListener('click', function() {
    closeDataDropdown();
    var inp = document.createElement('input');
    inp.type = 'file';
    inp.accept = '.txt,.json';
    inp.addEventListener('change', function() {
      if (!inp.files || !inp.files[0]) return;
      var file = inp.files[0];
      var reader = new FileReader();
      reader.onload = function(e) {
        var content = e.target.result;
        fetch('/api/import/data', {method:'POST', headers:{'Content-Type':'application/json'}, body:content})
          .then(function(r){ return r.json(); })
          .then(function(j){
            if (j.ok) {
              showMsg('Import erfolgreich. Seite wird neu geladen...');
              setTimeout(function(){ location.reload(); }, 800);
            } else {
              showMsg('Import-Fehler: ' + (j.error || ''), true);
            }
          })
          .catch(function(err){ showMsg('Import-Fehler: ' + err, true); });
      };
      reader.readAsText(file);
    });
    inp.click();
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
            refreshBreakdown();
            refreshUndoPreview();
            setTimeout(function(){ location.reload(); }, 1000);
          } else if (j && j.error) {
            showMsg('Fehler: ' + j.error, true);
          }
        })
        .catch(function(e){ showMsg('Fehler: ' + e, true); });
    });
  });

  // ───── Country info popup ─────
  function closeAllCountryPopups() {
    document.querySelectorAll('.country-popup').forEach(function(el) { el.remove(); });
  }
  document.querySelectorAll('.country-info').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      if (this.parentElement.querySelector('.country-popup')) {
        closeAllCountryPopups();
        return;
      }
      closeAllCountryPopups();
      var statsEl = this.parentElement.parentElement.querySelector('.c-name');
      var statsRaw = statsEl ? statsEl.getAttribute('data-stats') : null;
      if (!statsRaw) return;
      var stats;
      try { stats = JSON.parse(statsRaw); } catch(e) { return; }
      var popup = document.createElement('div');
      popup.className = 'country-popup';
      var regPct = stats.regTotal ? Math.round(100 * stats.regFilled / stats.regTotal) : 0;
      var ccPct = stats.ccTotal ? Math.round(100 * stats.ccFilled / stats.ccTotal) : 0;
      var nifcPct = stats.nifcTotal ? Math.round(100 * stats.nifcFilled / stats.nifcTotal) : 0;
      const _dOrder = ['1c','2c','5c','10c','20c','50c','1\u20ac','2\u20ac'];
      const _dCents = {'1c':1,'2c':2,'5c':5,'10c':10,'20c':20,'50c':50,'1\u20ac':100,'2\u20ac':200,'CC':200};
      const _denomRow = (d, cls) => {
        const cnt = (stats.denom && stats.denom[d]) || 0;
        const rf = (stats.denomRegFilled && stats.denomRegFilled[d]) || 0;
        const rt = (stats.denomRegTotal && stats.denomRegTotal[d]) || 0;
        const nf = (stats.denomNifcFilled && stats.denomNifcFilled[d]) || 0;
        const nt = (stats.denomNifcTotal && stats.denomNifcTotal[d]) || 0;
        const mr = rt - rf, mn = nt - nf;
        const vs = (cnt * _dCents[d] / 100).toLocaleString('de-DE', {minimumFractionDigits:2, maximumFractionDigits:2});
        return `<tr${cls || ''}><td>${d}</td><td>${cnt}</td><td style="text-align:center"><span style="color:#c00">${mr}</span></td><td style="text-align:center"><span style="color:#c00">${mn}</span></td><td>\u20ac${vs}</td></tr>`;
      };
      let html = `<div class="country-popup-stats">
  <div class="country-popup-badge country-popup-badge-reg"><div class="country-popup-badge-label">Regul\u00e4r</div><div class="country-popup-badge-num">${stats.regFilled}/${stats.regTotal}</div><div class="country-popup-badge-pct">${regPct}%</div></div>${stats.ccTotal ? `<div class="country-popup-badge country-popup-badge-cc"><div class="country-popup-badge-label">CC</div><div class="country-popup-badge-num">${stats.ccFilled}/${stats.ccTotal}</div><div class="country-popup-badge-pct">${ccPct}%</div></div>` : ''}${stats.nifcTotal ? `<div class="country-popup-badge country-popup-badge-nifc"><div class="country-popup-badge-label">NIFC</div><div class="country-popup-badge-num">${stats.nifcFilled}/${stats.nifcTotal}</div><div class="country-popup-badge-pct">${nifcPct}%</div></div>` : ''}</div><table>
  <tr><th>Nominal</th><th>Anzahl</th><th style="color:#c00">\u2715 reg.</th><th style="color:#c00">\u2715 NIFC</th><th>Wert</th></tr>`;
      for (const d of _dOrder) {
        const cnt = (stats.denom && stats.denom[d]) || 0;
        const rf = (stats.denomRegFilled && stats.denomRegFilled[d]) || 0;
        const rt = (stats.denomRegTotal && stats.denomRegTotal[d]) || 0;
        const nf = (stats.denomNifcFilled && stats.denomNifcFilled[d]) || 0;
        const nt = (stats.denomNifcTotal && stats.denomNifcTotal[d]) || 0;
        const mr = rt - rf, mn = nt - nf;
        if (!cnt && !mr && !mn) continue;
        html += _denomRow(d, '');
      }
      const ccCnt = (stats.denom && stats.denom['CC']) || 0;
      const crf = (stats.denomRegFilled && stats.denomRegFilled['CC']) || 0;
      const crt = (stats.denomRegTotal && stats.denomRegTotal['CC']) || 0;
      const cnf = (stats.denomNifcFilled && stats.denomNifcFilled['CC']) || 0;
      const cntt = (stats.denomNifcTotal && stats.denomNifcTotal['CC']) || 0;
      const cmr = crt - crf, cmn = cntt - cnf;
      if (ccCnt || stats.ccTotal || cntt) {
        html += _denomRow('CC', ' class="country-popup-cc"');
      }
      let totalMissReg = 0, totalMissNifc = 0;
      for (const d of _dOrder) {
        const rt = (stats.denomRegTotal && stats.denomRegTotal[d]) || 0;
        const rf = (stats.denomRegFilled && stats.denomRegFilled[d]) || 0;
        const nt = (stats.denomNifcTotal && stats.denomNifcTotal[d]) || 0;
        const nf = (stats.denomNifcFilled && stats.denomNifcFilled[d]) || 0;
        totalMissReg += rt - rf;
        totalMissNifc += nt - nf;
      }
      const ccRT = (stats.denomRegTotal && stats.denomRegTotal['CC']) || 0;
      const ccRF = (stats.denomRegFilled && stats.denomRegFilled['CC']) || 0;
      const ccNT = (stats.denomNifcTotal && stats.denomNifcTotal['CC']) || 0;
      const ccNF = (stats.denomNifcFilled && stats.denomNifcFilled['CC']) || 0;
      totalMissReg += ccRT - ccRF;
      totalMissNifc += ccNT - ccNF;
      const totalStr = (stats.totalCents / 100).toLocaleString('de-DE', {minimumFractionDigits:2, maximumFractionDigits:2});
      html += `<tr class="country-popup-total"><td>Gesamt</td><td></td><td style="text-align:center"><span style="color:#c00">${totalMissReg}</span></td><td style="text-align:center"><span style="color:#c00">${totalMissNifc}</span></td><td>\u20ac${totalStr}</td></tr></table>`;
      popup.innerHTML = html;
      var blk = this.getAttribute('data-block');
      var ctry = this.getAttribute('data-country');
      var addBtn = document.createElement('span');
      addBtn.className = 'add-year';
      addBtn.textContent = '+ Jahr hinzuf\u00fcgen';
      addBtn.setAttribute('data-block', blk);
      addBtn.setAttribute('data-country', ctry);
      addBtn.addEventListener('click', function() {
        var b = this.getAttribute('data-block'), c = this.getAttribute('data-country');
        if (!b || !c) return;
        fetch('/api/next-year?block=' + encodeURIComponent(b) + '&country=' + encodeURIComponent(c))
          .then(function(r){ return r.json(); })
          .then(function(j){
            var y = prompt('Jahr eingeben f\u00fcr ' + c + ':', j.nextYear || '2027');
            if (!y) return;
            return fetch('/api/add-year', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({block:b, country:c, year:y})});
          })
          .then(function(r){ return r && r.json(); })
          .then(function(j){
            if (j && j.ok) {
              showMsg('Jahr ' + j.year + ' hinzugef\u00fcgt. Seite wird neu geladen...');
              refreshBreakdown();
              refreshUndoPreview();
              setTimeout(function(){ location.reload(); }, 1000);
            } else if (j && j.error) {
              showMsg('Fehler: ' + j.error, true);
            }
          })
          .catch(function(e){ showMsg('Fehler: ' + e, true); });
      });
      var rmBtn = document.createElement('span');
      rmBtn.className = 'add-year';
      rmBtn.textContent = '\u2013 Jahr entfernen';
      rmBtn.style.marginLeft = '6px';
      rmBtn.setAttribute('data-block', blk);
      rmBtn.setAttribute('data-country', ctry);
      rmBtn.addEventListener('click', function() {
        var b = this.getAttribute('data-block'), c = this.getAttribute('data-country');
        if (!b || !c) return;
        var y = prompt('Jahr entfernen f\u00fcr ' + c + ':');
        if (!y) return;
        fetch('/api/remove-year', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({block:b, country:c, year:y})})
          .then(function(r){ return r.json(); })
          .then(function(j){
            if (j && j.ok) {
              showMsg('Jahr ' + j.year + ' entfernt. Seite wird neu geladen...');
              refreshBreakdown();
              refreshUndoPreview();
              setTimeout(function(){ location.reload(); }, 1000);
            } else if (j && j.error) {
              showMsg('Fehler: ' + j.error, true);
            }
          })
          .catch(function(e){ showMsg('Fehler: ' + e, true); });
      });
      var addWrap = document.createElement('div');
      addWrap.style.cssText = 'text-align:center;margin-top:8px;padding-top:8px;border-top:1px solid #eee';
      addWrap.appendChild(addBtn);
      addWrap.appendChild(rmBtn);
      popup.appendChild(addWrap);
      this.parentElement.appendChild(popup);
    });
  });
  document.addEventListener('click', function(e) {
    if (!e.target.closest('.country-info') && !e.target.closest('.country-popup')) {
      closeAllCountryPopups();
    }
  });

  function renderGlobalStats(j) {
    var el = document.getElementById('sumBreakdownStats');
    if (!el) return;
    var g = j.globalCellStats || {};
    function pct(f, t) { return t ? Math.floor(100 * (f||0) / t) : 0; }
    el.innerHTML =
      `<div class="country-popup-badge country-popup-badge-reg"><div class="country-popup-badge-label">Regul\u00e4r</div><div class="country-popup-badge-num">${g.regFilled||0}/${g.regTotal||0}</div><div class="country-popup-badge-pct">${pct(g.regFilled, g.regTotal)}%</div></div>` +
      `<div class="country-popup-badge country-popup-badge-cc"><div class="country-popup-badge-label">CC</div><div class="country-popup-badge-num">${g.ccFilled||0}/${g.ccTotal||0}</div><div class="country-popup-badge-pct">${pct(g.ccFilled, g.ccTotal)}%</div></div>` +
      `<div class="country-popup-badge country-popup-badge-nifc"><div class="country-popup-badge-label">NIFC</div><div class="country-popup-badge-num">${g.nifcFilled||0}/${g.nifcTotal||0}</div><div class="country-popup-badge-pct">${pct(g.nifcFilled, g.nifcTotal)}%</div></div>`;
  }

  // ───── Live breakdown refresh ─────
  function refreshBreakdown() {
    fetch(apiUrl('/api/breakdown'))
      .then(function(r){ return r.json(); })
      .then(function(j) {
        if (!j || !j.breakdown) return;
        var sb = document.getElementById('sumBtn');
        var table = document.querySelector('#sumBreakdown table');
        if (!sb || !table) return;
        var total = j.totalCents;
        var totalStr = (total / 100).toLocaleString('de-DE', {minimumFractionDigits:2, maximumFractionDigits:2});
        renderGlobalStats(j);
        var header = table.querySelector('tr:first-child');
        table.innerHTML = '';
        if (header) table.appendChild(header);
        j.breakdown.forEach(function(item) {
          var vs = (item.cents / 100).toLocaleString('de-DE', {minimumFractionDigits:2, maximumFractionDigits:2});
          var rd = (j.regDenomStats && j.regDenomStats[item.label]) ? j.regDenomStats[item.label] : null;
          var nd = (j.nifcDenomStats && j.nifcDenomStats[item.label]) ? j.nifcDenomStats[item.label] : null;
          var missReg = (item.label === 'CC' && j.globalCellStats) ? (j.globalCellStats.ccTotal - j.globalCellStats.ccFilled) : (rd ? rd.total - rd.filled : 0);
          var missNifc = nd ? nd.total - nd.filled : 0;
          var tr = document.createElement('tr');
          if (item.label === 'CC') tr.className = 'country-popup-cc';
          tr.innerHTML = '<td>' + item.label + '</td><td>' + item.count + '</td><td style="text-align:center"><span style="color:#c00">' + missReg + '</span></td><td style="text-align:center"><span style="color:#c00">' + missNifc + '</span></td><td>\u20AC' + vs + '</td>';
          table.appendChild(tr);
        });
        // Compute total missing
        var totalMissReg = 0, totalMissNifc = 0;
        j.breakdown.forEach(function(item) {
          var rd = (j.regDenomStats && j.regDenomStats[item.label]) ? j.regDenomStats[item.label] : null;
          var nd = (j.nifcDenomStats && j.nifcDenomStats[item.label]) ? j.nifcDenomStats[item.label] : null;
          var mr = (item.label === 'CC' && j.globalCellStats) ? (j.globalCellStats.ccTotal - j.globalCellStats.ccFilled) : (rd ? rd.total - rd.filled : 0);
          totalMissReg += mr;
          totalMissNifc += nd ? nd.total - nd.filled : 0;
        });
        var tr = document.createElement('tr');
        tr.className = 'sum-breakdown-total';
        tr.innerHTML = '<td>Gesamt</td><td></td><td style="text-align:center"><span style="color:#c00">' + totalMissReg + '</span></td><td style="text-align:center"><span style="color:#c00">' + totalMissNifc + '</span></td><td>\u20AC' + totalStr + '</td>';
        table.appendChild(tr);
        // Update per-country stats for live refresh
        if (j.countryStats) {
          document.querySelectorAll('.c-name').forEach(function(el) {
            var key = el.getAttribute('data-key');
            if (!key) return;
            var stats = j.countryStats[key];
            if (stats) {
              el.setAttribute('data-stats', JSON.stringify(stats));
            }
          });
        }
      });
  }

  // ───── Sum breakdown toggle ─────
  document.getElementById('sumBtn').addEventListener('click', function() {
    var p = document.getElementById('sumBreakdown');
    p.style.display = p.style.display === 'none' ? 'block' : 'none';
  });

  // ───── Flag bar country jump ─────
  document.querySelectorAll('.flag-btn').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      var targetId = this.getAttribute('data-target');
      var el = document.getElementById(targetId);
      if (!el) return;
      var header = document.getElementById('stickyHeader');
      var offset = header ? header.offsetHeight : 0;
      var rect = el.getBoundingClientRect();
      window.scrollBy({top: rect.top - offset, behavior: 'smooth'});
    });
  });



  // ───── Delete country ─────
  document.addEventListener('click', function(e) {
    var del = e.target.closest('.c-del');
    if (!del) return;
    e.stopPropagation();
    var cname = del.getAttribute('data-country');
    if (!cname) return;
    if (!confirm('Land "' + cname + '" wirklich l\u00f6schen? Alle zugeh\u00f6rigen M\u00fcnzdaten werden entfernt.')) return;
    fetch('/api/countries/' + encodeURIComponent(cname), {
      method: 'DELETE'
    }).then(function(r) { return r.json(); }).then(function(j) {
      if (j.ok) {
        showMsg('Land "' + cname + '" gel\u00f6scht. Seite wird neu geladen...');
        setTimeout(function() { location.reload(); }, 800);
      } else {
        showMsg('Fehler: ' + (j.error || ''), true);
      }
    }).catch(function(e) { showMsg('Fehler: ' + e, true); });
  });

  // ───── Reorder Modal (✏️ Länder) ─────
  function openReorderModal() {
    fetch('/api/countries').then(function(r) { return r.json(); }).then(function(countries) {
      var html = '';
      countries.forEach(function(c, i) {
        html += `<div class="rm-row" data-name="${c.name.replace(/"/g, '&quot;')}">`;
        html += `<span class="rm-flag">${c.flag || ''}</span>`;
        html += `<span class="rm-name">${c.name}</span>`;
        html += `<button class="rm-up"${i === 0 ? ' disabled' : ''}>\u25b2</button>`;
        html += `<button class="rm-down"${i === countries.length - 1 ? ' disabled' : ''}>\u25bc</button>`;
        html += '<button class="rm-del">\u2715</button></div>';
      });
      document.getElementById('rmList').innerHTML = html;
      document.getElementById('reorderModal').style.display = 'block';
      // ▲ handler — grid-based: A→AC prev, O→A same, AC→O same
      document.querySelectorAll('.rm-up').forEach(function(btn, i) {
        btn.addEventListener('click', function() {
          if (i === 0) return;
          var cname = countries[i].name;
          fetch('/api/countries/move-grid', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: cname, direction: 'up'})
          }).then(function(r) { return r.json(); }).then(function(j) {
            if (j.ok) location.reload();
            else showMsg('Fehler: ' + (j.error || ''), true);
          }).catch(function(e) { showMsg('Fehler: ' + e, true); });
        });
      });
      // ▼ handler — grid-based: A→O same, O→AC same, AC→A next
      document.querySelectorAll('.rm-down').forEach(function(btn, i) {
        btn.addEventListener('click', function() {
          if (i === countries.length - 1) return;
          var cname = countries[i].name;
          fetch('/api/countries/move-grid', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: cname, direction: 'down'})
          }).then(function(r) { return r.json(); }).then(function(j) {
            if (j.ok) location.reload();
            else showMsg('Fehler: ' + (j.error || ''), true);
          }).catch(function(e) { showMsg('Fehler: ' + e, true); });
        });
      });
      // ✕ handler
      document.querySelectorAll('.rm-del').forEach(function(btn, i) {
        btn.addEventListener('click', function() {
          var cname = countries[i].name;
          if (!confirm('Land "' + cname + '" wirklich l\u00f6schen?')) return;
          fetch('/api/countries/' + encodeURIComponent(cname), {method: 'DELETE'})
            .then(function(r) { return r.json(); })
            .then(function(j) {
              if (j.ok) { showMsg('Gel\u00f6scht. Seite wird neu geladen...'); setTimeout(function() { location.reload(); }, 500); }
              else { showMsg('Fehler: ' + (j.error || ''), true); }
            }).catch(function(e) { showMsg('Fehler: ' + e, true); });
        });
      });
    }).catch(function(e) { showMsg('Fehler: ' + e, true); });
  }

  document.getElementById('moreCountries').addEventListener('click', openReorderModal);
  document.getElementById('rmClose').addEventListener('click', function() {
    document.getElementById('reorderModal').style.display = 'none';
  });
  // Close modal on overlay click
  document.getElementById('reorderModal').addEventListener('click', function(e) {
    if (e.target === this) this.style.display = 'none';
  });
  // Add country
  document.getElementById('acSave').addEventListener('click', function() {
    var name = document.getElementById('acName').value.trim();
    if (!name) { showMsg('Name erforderlich', true); return; }
    var block = document.getElementById('acBlock').value;
    var flag = document.getElementById('acFlag').value.trim();
    var imageName = document.getElementById('acImageName').value.trim();
    var mintsRaw = document.getElementById('acMints').value.trim();
    var mintsArr = mintsRaw ? mintsRaw.split(',').map(function(s) { return s.trim(); }).filter(function(s) { return s; }) : [];
    fetch('/api/countries', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name, block: block, flag: flag, image_name_en: imageName, mint_marks: mintsArr})
    }).then(function(r) { return r.json(); }).then(function(j) {
      if (j.ok) { showMsg('"' + name + '" hinzugef\u00fcgt. Seite wird neu geladen...'); setTimeout(function() { location.reload(); }, 500); }
      else { showMsg('Fehler: ' + (j.error || ''), true); }
    }).catch(function(e) { showMsg('Fehler: ' + e, true); });
  });

  // Hide more button when already in split mode
  if (window.location.search.indexOf('layout=split') !== -1) {
    var moreBtn = document.getElementById('moreBtn');
    if (moreBtn) moreBtn.style.display = 'none';
  }

})();

