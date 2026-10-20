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

  // ───── Handy-Ansicht: jedes Land untereinander ─────
  var MOBILE_KEY = 'muenzapp:mobile';
  var mobilePref = null;
  try { mobilePref = localStorage.getItem(MOBILE_KEY); } catch(e) {}
  if (mobilePref === null) {
    var mc = document.cookie.match(/(?:^|; )muenzapp_mobile=([01])/);
    if (mc) mobilePref = mc[1];
  }
  // Ohne eigene Wahl: auf kleinen Bildschirmen automatisch an
  var onMintSheet = !!document.getElementById('mintSheet');
  if (onMintSheet) document.body.classList.add('on-sheet');
  var mobileOn = !onMintSheet && (mobilePref === '1' || (mobilePref === null && window.innerWidth < 700));

  function buildMobileView() {
    var grid = document.getElementById('grid');
    if (!grid) return;
    // Zellen nach Land und Zeile sammeln (Reihenfolge wie auf der Seite)
    var byCountry = new Map();
    grid.querySelectorAll('td[data-cid]').forEach(function(td) {
      var cid = td.getAttribute('data-cid');
      if (!byCountry.has(cid)) byCountry.set(cid, new Map());
      var rows = byCountry.get(cid);
      if (!rows.has(td.parentNode)) rows.set(td.parentNode, []);
      rows.get(td.parentNode).push(td);
    });
    var widths = [13].concat([7.5,7.5,7.5,7.5,7.5,7.5,7.5,7.5], [3], [8,8,8]);
    var list = document.createElement('div');
    list.id = 'mobileList';
    byCountry.forEach(function(rows) {
      var tbl = document.createElement('table');
      tbl.className = 'm-table';
      var cg = document.createElement('colgroup');
      widths.forEach(function(w) { var c = document.createElement('col'); c.style.width = w + '%'; cg.appendChild(c); });
      tbl.appendChild(cg);
      rows.forEach(function(tds) {
        // Zeilen ohne Jahr (nur Lücke) weglassen
        if (tds.every(function(td) { return td.classList.contains('inner-gap'); })) return;
        var tr = document.createElement('tr');
        tds.forEach(function(td) { tr.appendChild(td); });
        tbl.appendChild(tr);
      });
      var card = document.createElement('div');
      card.className = 'm-card';
      card.appendChild(tbl);
      list.appendChild(card);
    });
    grid.parentNode.insertBefore(list, grid);
    grid.style.display = 'none';
    document.body.classList.add('mobile-view');
  }
  if (mobileOn) buildMobileView();

  (function() {
    var item = document.getElementById('mobileToggle');
    if (!item) return;
    if (onMintSheet) { item.style.display = 'none'; return; }
    item.classList.toggle('on', mobileOn);
    item.setAttribute('aria-checked', mobileOn ? 'true' : 'false');
    item.addEventListener('click', function(e) {
      e.stopPropagation();
      item.classList.toggle('on', !mobileOn);
      var v = mobileOn ? '0' : '1';
      try { localStorage.setItem(MOBILE_KEY, v); } catch(e) {}
      document.cookie = 'muenzapp_mobile=' + v + '; max-age=31536000; path=/; SameSite=Lax';
      location.reload();
    });
  })();

  // ───── Legend panel toggle ─────
  function showModal(id, overlayId, on) {
    document.getElementById(id).style.display = on ? 'block' : 'none';
    document.getElementById(overlayId).style.display = on ? 'block' : 'none';
  }
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') showModal('reorderModal', 'rmOverlay', false);
  });

  // Beim Bearbeiten: Info, Handy, Menü und Länder-Info sperren
  document.addEventListener('click', function(e) {
    if (!document.body.classList.contains('edit-mode')) return;
    if (e.target.closest('#sumBtn, #mobileToggle, #moreBtn, .country-info, .c-mint-all')) {
      e.stopPropagation();
      e.preventDefault();
    }
  }, true);

  // ───── Edit mode ─────
  let editMode = false;
  let copySourceRef = null;
  let clickTimer = null;
  let wasDrag = false;
  let dragCells = null;
  let editPopupRefs = null;

  function setEditHint() {
    var hint = document.getElementById('editHint');
    var cancel = document.getElementById('editCancelCopy');
    if (copySourceRef) {
      hint.textContent = 'Kopieren: Tippe auf die Felder, wo es hin soll (oder ziehe dar\u00fcber).';
      cancel.style.display = '';
    } else {
      hint.textContent = 'Tippen = M\u00fcnze \u00e4ndern \u00b7 Doppelt tippen = zum Kopieren w\u00e4hlen \u00b7 Ziehen = mehrere w\u00e4hlen';
      cancel.style.display = 'none';
    }
  }

  document.getElementById('editBtn').addEventListener('click', function() {
    editMode = !editMode;
    this.classList.toggle('active', editMode);
    this.innerHTML = editMode ? '\u2713<span class="tb-word"> Fertig</span>' : '\uD83D\uDCDD<span class="tb-word"> Bearbeiten</span>';
    document.body.classList.toggle('edit-mode', editMode);
    var hint = document.getElementById('editHint');
    if (editMode) {
      // Alles andere zu: Menü, Info und Länder-Popups schließen
      document.getElementById('moreDropdown').style.display = 'none';
      document.getElementById('sumBreakdown').style.display = 'none';
      document.getElementById('sumOverlay').style.display = 'none';
      document.querySelectorAll('.country-popup').forEach(function(el) { el.remove(); });
      hint.classList.add('show');
      copySourceRef = null;
      setEditHint();
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

  document.getElementById('editCancelCopy').addEventListener('click', function() {
    document.querySelectorAll('.edit-source').forEach(function(el) { el.classList.remove('edit-source'); });
    copySourceRef = null;
    setEditHint();
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
      setEditHint();
      return;
    }
    hideEditPopup();
    document.querySelectorAll('.edit-source').forEach(function(el) { el.classList.remove('edit-source'); });
    copySourceRef = ref;
    td.classList.add('edit-source');
    setEditHint();
  }

  function hexToRgb(hex) {
    var m = hex.match(/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
    return m ? 'rgb(' + parseInt(m[1],16) + ', ' + parseInt(m[2],16) + ', ' + parseInt(m[3],16) + ')' : '';
  }

  // ───── Edit popup ─────
  var POPUP_COLORS = [
    {type:'green',  color:'#C5DEB5', title:'\u00fcber 5 Mio.'},
    {type:'blue',   color:'#8EAADB', title:'2\u20135 Mio.'},
    {type:'orange', color:'#FF8C42', title:'1\u20132 Mio.'},
    {type:'yellow', color:'#FFE598', title:'bis 1 Mio.'},
    {type:'nifc',   color:'#FFC7CE', title:'NIFC (nicht f\u00fcr Umlauf)'},
    {type:'x',      color:'#FFC7CE', title:'\u2715 nie gepr\u00e4gt'},
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
      return `<span class="popup-color-btn${active ? ' active' : ''}" data-ctype="${c.type}" title="${c.title}">` +
        `<span class="pc-dot" style="background:${c.color}"></span>${c.title}</span>`;
    }).join('');
    popupEl.innerHTML = `<div class="popup-title">${title}</div>` +
      `<input type="text" id="popupInput" value="${val.replace(/"/g, '&quot;')}" placeholder="M\u00fcnztext (\u2714, 0, 1\u00b0...)">` +
      `<div class="popup-colors-head">Farbe = wie viele gepr\u00e4gt wurden (Auflage)</div>` +
      `<div class="popup-colors">${colorsHtml}</div>` +
      '<button id="popupSave">Speichern</button>';
    var lastRef = Array.from(refs)[refs.size - 1];
    var lastTd = document.querySelector('[data-ref="' + lastRef + '"]');
    popupEl.style.display = 'block';
    if (lastTd) {
      // Neben der Zelle zeigen, aber immer ganz im Bild
      var rect = lastTd.getBoundingClientRect();
      var pw = popupEl.offsetWidth, ph = popupEl.offsetHeight;
      var top = rect.bottom + 4;
      if (top + ph > window.innerHeight - 8) top = Math.max(8, rect.top - ph - 4);
      popupEl.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - pw - 8)) + 'px';
      popupEl.style.top = top + 'px';
    }
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
        setEditHint();
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
    {type:'green',  label:'\u00fcber 5 Mio.', color:'#C5DEB5'},
    {type:'blue',   label:'2\u20135 Mio.',   color:'#8EAADB'},
    {type:'orange', label:'1\u20132 Mio.',   color:'#FF8C42'},
    {type:'yellow', label:'bis 1 Mio.',      color:'#FFE598'},
    {type:'nifc',   label:'NIFC (nicht f\u00fcr Umlauf)', color:'#FFC7CE'},
    {type:'x',      label:'\u2715 nie gepr\u00e4gt', color:'#FFC7CE'},
    {type:'nodata', label:'unbekannt',   color:'#fff'},
  ];
  function buildInfoColorPicker(currentType) {
    infoColorType = currentType || '';
    infoOrigCellType = currentType || '';
    var picker = document.getElementById('infoColorPicker');
    picker.innerHTML = INFO_COLOR_ITEMS.map(function(item) {
      var isCur = (item.type === currentType) || (item.type === 'nodata' && !currentType);
      return `<span class="info-color-btn${isCur ? ' cur' : ''}" data-icolor="${item.type}" title="${item.label}">` +
        `<span class="info-color-swatch" style="background:${item.color}"></span>${item.label}</span>`;
    }).join('');
    picker.querySelectorAll('.info-color-btn').forEach(function(btn) {
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        var t = this.getAttribute('data-icolor');
        infoColorType = (t === 'nodata') ? '' : t;
        picker.querySelectorAll('.info-color-btn').forEach(function(b) { b.classList.remove('cur'); });
        this.classList.add('cur');
      });
    });
  }

  let infoCoinEntries = [];
  let infoPendingQ = null;

  function infoRenderEntries() {
    var entriesDiv = document.getElementById('infoCoinEntries');
    var addDiv = document.getElementById('infoCoinAdd');
    var n = infoCoinEntries.length;
    // Überschrift: Habe ich die Münze?
    document.getElementById('ownHead').innerHTML = n
      ? '🪙 In meiner Sammlung: <b>' + n + (n === 1 ? ' Münze' : ' Münzen') + '</b>'
      : 'Noch nicht in meiner Sammlung';
    document.getElementById('ownBox').classList.toggle('own-none', !n);
    var addLabel = addDiv.querySelector('.info-add-label');
    if (addLabel) addLabel.textContent = n ? 'Weitere Münze hinzufügen:' : 'Münze zur Sammlung hinzufügen:';
    var SOURCE_ICON = {'°': '👥', 'o': '👥', '*': '🛒', '': '🙋'};
    entriesDiv.innerHTML = infoCoinEntries.map(function(e, i) {
      var badge, title, sub;
      if (e.text) {
        badge = '✏️';
        title = htmlEsc(e.text);
        sub = 'eigener Text';
      } else {
        var src = SOURCE_LABELS[e.s] !== undefined ? e.s : '';
        badge = htmlEsc(e.q + (src === 'o' ? '\u00b0' : src));   // z.B. 0*, 1°
        title = QUALITY_LABELS[e.q] || htmlEsc(e.q);
        sub = SOURCE_ICON[src] + ' ' + SOURCE_LABELS[src];
      }
      return '<div class="own-coin"><span class="own-num">#' + (i + 1) + '</span>' +
        '<span class="own-q q-' + htmlEsc(e.q || 'x') + '">' + badge + '</span>' +
        '<div class="own-text"><b>' + title + '</b><span>' + sub + '</span></div>' +
        '<span class="vp-entry-del" data-idx="' + i + '" title="Diese Münze aus der Sammlung entfernen">&times;</span></div>';
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
  }

  function htmlEsc(s) {
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(s));
    return d.innerHTML;
  }

  function showInfoModal(ref, country, year, denom, mintage, link, cellVal, ccName, cellType) {
    infoRef = ref;
    var infoTd = document.querySelector('[data-ref="' + ref + '"]');
    var infoMint = infoTd ? infoTd.getAttribute('data-mint') : '';
    if (infoTd && infoTd.getAttribute('data-year-label')) year = infoTd.getAttribute('data-year-label');
    document.getElementById('infoTitle').textContent = country + ' ' + year + ' ' + denom + (infoMint ? ' \u2013 ' + infoMint : '');
    var noteBox = document.getElementById('infoNote');
    var noteTxt = infoTd ? (infoTd.getAttribute('data-note') || '') : '';
    noteBox.innerHTML = noteTxt ? '<b>Notiz aus dem Google Sheet</b><br>' + htmlEsc(noteTxt) : '';
    noteBox.style.display = noteTxt ? '' : 'none';
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

  function bindCell(td) {
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
  }
  document.querySelectorAll('[data-ref]').forEach(bindCell);

  // Sync button — re-import mintage from the Google Sheet
  // ───── Auflagezahlen laden: erst ansehen, dann übernehmen ─────
  var syncChanges = [];
  var syncMissing = [];
  var syncChecks = [];
  // Prüfung: passen App und Google Sheet zusammen?
  function renderSyncChecks() {
    var box = document.getElementById('syncChecks');
    var errs = syncChecks.filter(function(c) { return c.level === 'error'; });
    var warns = syncChecks.filter(function(c) { return c.level === 'warn'; });
    if (!syncChecks.length) {
      box.innerHTML = '<div class="sync-check ok">\u2713 Pr\u00fcfung: Alles passt \u2013 L\u00e4nder, Spalten, Jahre und Extra-Zeilen stimmen mit dem Google Sheet \u00fcberein.</div>';
      return;
    }
    var list = function(xs) { return '<ul>' + xs.map(function(c) { return '<li>' + htmlEsc(c.text) + '</li>'; }).join('') + '</ul>'; };
    box.innerHTML = (errs.length ? '<div class="sync-check err"><b>\u26d4 Pr\u00fcfung: ' + errs.length + ' Problem' + (errs.length > 1 ? 'e' : '') + '</b>' + list(errs) + '</div>' : '') +
      (warns.length ? '<div class="sync-check warn"><b>\u26a0\ufe0f Bitte pr\u00fcfen (' + warns.length + ')</b>' + list(warns) + '</div>' : '');
  }
  function syncStep(n) {
    document.getElementById('syncStep1').style.display = n === 1 ? '' : 'none';
    document.getElementById('syncStep2').style.display = n === 2 ? '' : 'none';
  }
  function showSync(on) {
    document.getElementById('syncModal').style.display = on ? 'block' : 'none';
    document.getElementById('syncOverlay').style.display = on ? 'block' : 'none';
    if (on) syncStep(1);
  }
  document.getElementById('editSync').addEventListener('click', function() { showSync(true); });
  document.getElementById('syncOverlay').addEventListener('click', function() { showSync(false); });
  document.getElementById('syncCancel').addEventListener('click', function() { showSync(false); });
  document.getElementById('syncClose').addEventListener('click', function() { showSync(false); });
  document.getElementById('syncBack').addEventListener('click', function() { syncStep(1); });

  function colorDot(hex) {
    return '<span class="pc-dot" style="background:#' + (hex || 'fff') + '"></span>';
  }
  var COLOR_WORD = {green: 'über 5 Mio.', blue: '2–5 Mio.', orange: '1–2 Mio.', yellow: 'bis 1 Mio.', nifc: 'NIFC', x: '✕ nie geprägt', nodata: 'unbekannt'};
  var syncTab = 'auflage';
  var SYNC_TABS = [['neu', 'Neue Zeilen'], ['auflage', 'Auflagezahlen'], ['farbe', 'Farben'], ['name', 'Namen'], ['notiz', 'Notizen']];
  // Sortieren nach Land, Jahr oder Münze (Klick auf die Spalte, nochmal = umgekehrt)
  var syncSort = {col: 'land', dir: 1};
  var COIN_ORDER = ['1c', '2c', '5c', '10c', '20c', '50c', '1\u20ac', '2\u20ac', 'CC1', 'CC2', 'CC3'];
  function yearNum(c) { if (c.year_num !== undefined) return c.year_num; var m = /^(\d+)/.exec(c.year || ''); return m ? +m[1] : 9999; }
  function syncOrder() {
    var idx = syncChanges.map(function(_, i) { return i; });
    var col = syncSort.col, dir = syncSort.dir;
    idx.sort(function(a, b) {
      var x = syncChanges[a], y = syncChanges[b], r = 0;
      var byLand = a - b;  // Server liefert schon in Länder-Reihenfolge
      var byYear = yearNum(x) - yearNum(y) || (x.year < y.year ? -1 : x.year > y.year ? 1 : 0);
      var byCoin = COIN_ORDER.indexOf(x.denom) - COIN_ORDER.indexOf(y.denom) || (x.mint < y.mint ? -1 : x.mint > y.mint ? 1 : 0);
      if (col === 'jahr') r = byYear || byCoin || byLand;
      else if (col === 'muenze') r = byCoin || byYear || byLand;
      else r = byLand;
      return r * dir;
    });
    return idx;
  }
  function sortHead(col, label) {
    var arrow = syncSort.col === col ? (syncSort.dir > 0 ? ' \u25b2' : ' \u25bc') : '';
    return '<th class="sync-sort' + (arrow ? ' on' : '') + '" data-sort="' + col + '">' + label + arrow + '</th>';
  }
  function tabOf(c) {
    return {cc: 'name', ct: 'farbe', note: 'notiz', row: 'neu'}[c.kind] || 'auflage';
  }
  // Zeile weggelassen? Dann auch alles, was in dieser neuen Zeile stehen würde
  function rowSkipped(c) {
    if (!c.new_row) return false;
    return syncChanges.some(function(r) { return r.kind === 'row' && r.key === c.new_row && r.skip; });
  }

  function renderSyncList() {
    var changes = syncChanges;
    var count = {neu: 0, auflage: 0, farbe: 0, name: 0, notiz: 0}, on = {neu: 0, auflage: 0, farbe: 0, name: 0, notiz: 0};
    changes.forEach(function(c) { var t = tabOf(c); count[t]++; if (!c.skip && !rowSkipped(c)) on[t]++; });
    var total = changes.filter(function(c) { return !c.skip && !rowSkipped(c); }).length;
    var miss = syncMissing.length
      ? '<div class="sync-miss">⚠️ Im Google Sheet gibt es Extra-Zeilen, die in der App fehlen – diese werden <b>nicht</b> übernommen: ' +
        syncMissing.map(function(m) { return htmlEsc(m.country) + ' (unter ' + htmlEsc(m.after) + (m.n > 1 ? ', Nr. ' + m.n : '') + ')'; }).join(', ') + '</div>'
      : '';
    document.getElementById('syncSummary').innerHTML = (changes.length
      ? '<b>' + total + '</b> von ' + changes.length + ' Änderungen werden übernommen. Noch ist nichts gespeichert.'
      : 'Keine Änderungen – alles ist schon aktuell.') + miss;
    document.getElementById('syncTabs').innerHTML = changes.length ? SYNC_TABS.filter(function(t) { return count[t[0]] > 0; }).map(function(t) {
      return '<button class="info-tab' + (t[0] === syncTab ? ' active' : '') + '" data-stab="' + t[0] + '">' + t[1] + ' (' + on[t[0]] + (on[t[0]] !== count[t[0]] ? '/' + count[t[0]] : '') + ')</button>';
    }).join('') : '';
    var rows = [];
    syncOrder().forEach(function(i) {
      var c = changes[i];
      if (tabOf(c) !== syncTab) return;
      var coin = c.denom.indexOf('CC') === 0 ? '2€ Gedenk ' + c.denom.slice(2) : c.denom;
      var oldTxt, newTxt;
      if (c.kind === 'row') {
        coin = (c.n ? 'Extra-Zeile unter ' + c.base : 'neues Jahr') + (c.mint ? ' (nur ' + c.mint + ')' : '');
        oldTxt = '<i>fehlt</i>';
        newTxt = htmlEsc(c.label) + (c.note ? '<div class="sync-note">' + htmlEsc(c.note) + '</div>' : '');
      } else if (c.kind === 'note') {
        oldTxt = c.old ? '<span class="sync-note">' + htmlEsc(c.old) + '</span>' : '<i>keine</i>';
        newTxt = '<span class="sync-note">' + htmlEsc(c.new) + '</span>';
      } else if (c.kind === 'ct') {
        oldTxt = colorDot(c.color_old) + ' ' + (c.old ? (COLOR_WORD[c.old] || htmlEsc(c.old)) + ' <i>(selbst gewählt)</i>' : (COLOR_WORD[c.old_type] || 'keine'));
        newTxt = colorDot(c.color_new) + ' ' + COLOR_WORD[c.new];
      } else {
        oldTxt = c.old ? htmlEsc(c.old) : '<i>leer</i>';
        newTxt = htmlEsc(c.new);
      }
      var off = c.skip || rowSkipped(c);
      rows.push('<tr class="' + (off ? 'sync-skip' : '') + '"><td>' + htmlEsc(c.country) + '</td><td>' + htmlEsc(c.year_label || c.year) + '</td><td>' + htmlEsc(coin) +
        (c.mint ? ' (' + htmlEsc(c.mint) + ')' : '') + '</td><td class="sync-old">' + oldTxt + '</td><td class="sync-new">' + newTxt +
        '</td><td><button class="sync-x" data-i="' + i + '" title="' + (c.skip ? 'Doch übernehmen' : 'Nicht übernehmen') + '">' + (c.skip ? '↺' : '✕') + '</button></td></tr>');
    });
    document.getElementById('syncList').innerHTML = changes.length
      ? (rows.length ? '<table><thead><tr>' + sortHead('land', 'Land') + sortHead('jahr', 'Jahr') + sortHead('muenze', 'M\u00fcnze') + '<th>Alt</th><th>Neu</th><th></th></tr></thead><tbody>' + rows.join('') + '</tbody></table>'
                     : '<p class="modal-sub" style="padding:12px">Hier ändert sich nichts.</p>')
      : '';
    var btn = document.getElementById('syncConfirm');
    btn.style.display = total ? '' : 'none';
    btn.textContent = total ? total + ' Änderungen übernehmen' : 'Übernehmen';
  }
  document.getElementById('syncTabs').addEventListener('click', function(e) {
    var t = e.target.closest('.info-tab');
    if (!t) return;
    syncTab = t.getAttribute('data-stab');
    renderSyncList();
  });
  document.getElementById('syncList').addEventListener('click', function(e) {
    var h = e.target.closest('.sync-sort');
    if (h) {
      var col = h.getAttribute('data-sort');
      syncSort = syncSort.col === col ? {col: col, dir: -syncSort.dir} : {col: col, dir: 1};
      renderSyncList();
      return;
    }
    var x = e.target.closest('.sync-x');
    if (!x) return;
    var c = syncChanges[+x.getAttribute('data-i')];
    c.skip = !c.skip;
    renderSyncList();
  });

  document.getElementById('syncPreview').addEventListener('click', function() {
    var btn = this;
    var country = document.getElementById('syncCountry').value;
    btn.disabled = true;
    btn.textContent = 'Lädt Google Sheet…';
    fetch('/api/sync/preview', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({country: country})})
      .then(function(r) { return r.json(); })
      .then(function(j) {
        if (!j.ok) throw new Error(j.error || 'unbekannt');
        syncChanges = j.changes;
        syncMissing = j.missing_rows || [];
        syncChecks = j.checks || [];
        renderSyncChecks();
        syncTab = 'auflage';
        for (var k = 0; k < SYNC_TABS.length; k++) {
          if (syncChanges.some(function(c) { return tabOf(c) === SYNC_TABS[k][0]; })) { syncTab = SYNC_TABS[k][0]; break; }
        }
        renderSyncList();
        syncStep(2);
      })
      .catch(function(e) { showMsg('Fehler beim Laden: ' + e.message, true); })
      .then(function() { btn.disabled = false; btn.textContent = 'Änderungen ansehen'; });
  });

  function syncPayload() {
    var out = [];
    var mintageOn = {};
    syncChanges.forEach(function(c) { if (c.kind !== 'ct' && !c.skip && !rowSkipped(c)) mintageOn[c.key] = true; });
    syncChanges.forEach(function(c) {
      if (rowSkipped(c)) return;
      if (c.kind === 'row') { if (!c.skip) out.push({kind: 'row', country: c.country, row: c.row, label: c.label, note: c.note, mint: c.mint, coins: c.coins}); return; }
      if (!c.skip) { out.push({kind: c.kind, key: c.key, store: c.store, new: c.new}); return; }
      // Farbe weggelassen, Auflage aber übernommen: alte Farbe festhalten, damit sie sich nicht trotzdem ändert
      if (c.kind === 'ct' && !c.old && c.old_type && mintageOn[c.for_key]) {
        out.push({kind: 'ct', key: c.key, store: c.store, new: c.old_type});
      }
    });
    return out;
  }
  document.getElementById('syncConfirm').addEventListener('click', function() {
    var btn = this;
    if (syncChecks.length && !confirm('Die Pr\u00fcfung hat ' + syncChecks.length + ' Hinweis' + (syncChecks.length > 1 ? 'e' : '') +
        ' gefunden (oben in der Liste).\n\nTrotzdem \u00fcbernehmen?')) return;
    var sel = document.getElementById('syncCountry');
    var label = sel.value || 'alle Länder';
    btn.disabled = true;
    btn.textContent = 'Speichert…';
    fetch('/api/sync/apply', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({label: label, changes: syncPayload()})})
      .then(function(r) { return r.json(); })
      .then(function(j) {
        if (!j.ok) throw new Error(j.error || 'unbekannt');
        showSync(false);
        showMsg(j.count + ' Änderungen gespeichert. Rückgängig mit ↶. Seite wird neu geladen...');
        setTimeout(function() { location.reload(); }, 1200);
      })
      .catch(function(e) { showMsg('Fehler beim Speichern: ' + e.message, true); })
      .then(function() { btn.disabled = false; btn.textContent = 'Übernehmen'; });
  });

  // Undo / Redo
  let undoDesc = '';
  let redoDesc = '';

  function setTbLabel(id, icon, text, title) {
    var b = document.getElementById(id);
    b.innerHTML = '';
    b.appendChild(document.createTextNode(icon));
    if (text) {
      var l = document.createElement('span');
      l.className = 'tb-label';
      l.textContent = ' ' + text;
      b.appendChild(l);
    }
    b.title = title;
    b.classList.toggle('tb-off', !text);
  }

  function refreshUndoPreview() {
    fetch('/api/undo-preview').then(function(r){ return r.json(); }).then(function(j){
      undoDesc = j.desc || '';
      setTbLabel('undoBtn', '\u21b6', undoDesc, undoDesc ? 'R\u00fcckg\u00e4ngig: ' + undoDesc : 'Nichts zum R\u00fcckg\u00e4ngigmachen');
    });
    fetch('/api/redo-preview').then(function(r){ return r.json(); }).then(function(j){
      redoDesc = j.desc || '';
      setTbLabel('redoBtn', '\u21b7', redoDesc, redoDesc ? 'Wiederholen: ' + redoDesc : 'Nichts zum Wiederholen');
    });
  }

  refreshUndoPreview();

  document.getElementById('undoBtn').addEventListener('click', function() {
    if (!undoDesc) return;
    if (!confirm(undoDesc + ' r\u00fcckg\u00e4ngig machen?')) return;
    setTbLabel('undoBtn', '\u21b6', 'wird r\u00fcckg\u00e4ngig gemacht...', '');
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
          setTbLabel('undoBtn', '\u21b6', undoDesc, '');
          document.getElementById('undoBtn').style.pointerEvents = '';
        }
      })
      .catch(function(e){ showMsg('Fehler: ' + e, true); setTbLabel('undoBtn', '\u21b6', undoDesc, ''); document.getElementById('undoBtn').style.pointerEvents = ''; });
  });

  document.getElementById('redoBtn').addEventListener('click', function() {
    if (!redoDesc) return;
    if (!confirm(redoDesc + ' wiederholen?')) return;
    setTbLabel('redoBtn', '\u21b7', 'wird wiederholt...', '');
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
          setTbLabel('redoBtn', '\u21b7', redoDesc, '');
          document.getElementById('redoBtn').style.pointerEvents = '';
        }
      })
      .catch(function(e){ showMsg('Fehler: ' + e, true); setTbLabel('redoBtn', '\u21b7', redoDesc, ''); document.getElementById('redoBtn').style.pointerEvents = ''; });
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
  // PDF wie Excel: erst alle Länder (Münzstätten-Länder leer), dann je ein eigenes Blatt
  document.getElementById('exportPdfBtn').addEventListener('click', function() {
    showMsg('PDF wird erstellt...');
    var countries = [];
    document.querySelectorAll('#grid .c-mint-all, #mobileList .c-mint-all').forEach(function(a) {
      var c = a.getAttribute('data-country');
      if (countries.indexOf(c) < 0) countries.push(c);
    });
    Promise.all(countries.map(function(c) {
      return fetch('/api/mint-sheet?country=' + encodeURIComponent(c)).then(function(r) { return r.json(); });
    })).then(function(results) {
      var box = document.createElement('div');
      box.id = 'printSheets';
      results.forEach(function(j) { if (j.ok) box.insertAdjacentHTML('beforeend', '<div class="print-sheet">' + j.html + '</div>'); });
      // Doppelte IDs vermeiden (das Blatt kann auch offen sein)
      box.querySelectorAll('[id]').forEach(function(el) { el.removeAttribute('id'); });
      document.body.appendChild(box);
      countries.forEach(function(c) {
        document.querySelectorAll('#grid td[data-ref][data-country="' + c + '"], #mobileList td[data-ref][data-country="' + c + '"]').forEach(function(td) {
          td.classList.add('print-blank');
        });
      });
      document.body.classList.add('print-all');
      window.print();
    }).catch(function() {
      showMsg('PDF ohne Internet nur mit der Haupttabelle.', true);
      window.print();
    });
  });
  window.addEventListener('afterprint', function() {
    var box = document.getElementById('printSheets');
    if (box) box.remove();
    document.querySelectorAll('.print-blank').forEach(function(td) { td.classList.remove('print-blank'); });
    document.body.classList.remove('print-all');
  });

  document.getElementById('exportXlsxBtn').addEventListener('click', function() {
    showMsg('Excel wird erstellt...');
    window.location.href = '/api/export/xlsx';
  });


  // ───── Daten dropdown (Export / Import) ─────
  function closeDataDropdown() {
    var md = document.getElementById('moreDropdown');
    if (md) md.style.display = 'none';
  }
  document.addEventListener('click', function(e) {
    if (!e.target.closest('#moreBtn')) closeDataDropdown();
  });
  document.getElementById('moreBtn').addEventListener('click', function(e) {
    e.stopPropagation();
    var md = document.getElementById('moreDropdown');
    md.style.display = md.style.display === 'none' ? 'block' : 'none';
  });
  document.getElementById('dropdownExport').addEventListener('click', function() {
    closeDataDropdown();
    showMsg('Sicherung wird heruntergeladen...');
    window.location.href = '/api/export/data-json';
  });
  document.getElementById('dropdownImport').addEventListener('click', function() {
    closeDataDropdown();
    var inp = document.createElement('input');
    inp.type = 'file';
    inp.accept = '.txt,.json';
    inp.addEventListener('change', function() {
      if (!inp.files || !inp.files[0]) return;
      var file = inp.files[0];
      if (!confirm('Sicherung \u201e' + file.name + '\u201c laden?\n\nAlle Daten in der App werden durch diese Datei ersetzt. Das kann man nicht mit \u21b6 r\u00fcckg\u00e4ngig machen.\n\nTipp: Vorher \u201eSicherung herunterladen\u201c.')) return;
      var reader = new FileReader();
      reader.onload = function(e) {
        var content = e.target.result;
        fetch('/api/import/data', {method:'POST', headers:{'Content-Type':'application/json'}, body:content})
          .then(function(r){ return r.json(); })
          .then(function(j){
            if (j.ok) {
              showMsg('Sicherung geladen. Seite wird neu geladen...');
              setTimeout(function(){ location.reload(); }, 800);
            } else {
              showMsg('Fehler beim Laden: ' + (j.error || ''), true);
            }
          })
          .catch(function(err){ showMsg('Fehler beim Laden: ' + err, true); });
      };
      reader.readAsText(file);
    });
    inp.click();
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

  // ───── Jahr hinzufügen / entfernen (Länder-Kopf, beim Bearbeiten) ─────
  function afterYearChange(j, word) {
    if (j && j.ok) {
      showMsg('Jahr ' + j.year + ' ' + word + '. Seite wird neu geladen...');
      setTimeout(function(){ location.reload(); }, 800);
    } else if (j && j.error) {
      showMsg('Fehler: ' + j.error, true);
    }
  }
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('.yr-btn');
    if (!btn) return;
    e.stopPropagation();
    var b = btn.getAttribute('data-block'), c = btn.getAttribute('data-country');
    if (btn.classList.contains('yr-add')) {
      fetch('/api/next-year?block=' + encodeURIComponent(b) + '&country=' + encodeURIComponent(c))
        .then(function(r){ return r.json(); })
        .then(function(j){
          var y = prompt('Welches Jahr hinzuf\u00fcgen? (' + c + ')', j.nextYear || '');
          if (!y) return;
          return fetch('/api/add-year', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({block:b, country:c, year:y})})
            .then(function(r){ return r.json(); });
        })
        .then(function(j){ afterYearChange(j, 'hinzugef\u00fcgt'); })
        .catch(function(err){ showMsg('Fehler: ' + err, true); });
    } else {
      var y = prompt('Welches Jahr entfernen? (' + c + ')\nAlle M\u00fcnzen in diesem Jahr werden gel\u00f6scht. R\u00fcckg\u00e4ngig geht mit \u21b6.', btn.getAttribute('data-last') || '');
      if (!y) return;
      fetch('/api/remove-year', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({block:b, country:c, year:y})})
        .then(function(r){ return r.json(); })
        .then(function(j){ afterYearChange(j, 'entfernt'); })
        .catch(function(err){ showMsg('Fehler: ' + err, true); });
    }
  });

  // ───── Münzstätte wechseln ohne Neuladen ─────
  function switchMint(link) {
    var mint = link.getAttribute('data-mint');
    var mintsBox = link.closest('.c-mints');
    var allBtn = mintsBox.querySelector('.c-mint-all');
    var country = allBtn ? allBtn.getAttribute('data-country') : '';
    if (!country) { location.href = link.href; return; }
    // Hat die alte oder neue Münzstätte eigene Extra-Zeilen? Dann ändern sich die Zeilen -> neu laden
    var rowMints = mintsBox.getAttribute('data-row-mints') || '';
    var oldMint = getActiveMint();
    if (rowMints && (rowMints.indexOf(mint) >= 0 || rowMints.indexOf(oldMint) >= 0)) { location.href = link.href; return; }
    loadMintCells(country, mint, function() {
      mintsBox.querySelectorAll('.c-mint').forEach(function(a) { a.classList.toggle('active', a === link); });
      try { history.replaceState(null, '', '?mint=' + encodeURIComponent(mint)); } catch (e) {}
    }, function() { location.href = link.href; });
  }

  function loadMintCells(country, mint, done, fail) {
    fetch('/api/mint-cells?country=' + encodeURIComponent(country) + '&mint=' + encodeURIComponent(mint))
      .then(function(r) { return r.json(); })
      .then(function(j) {
        if (!j.ok) throw new Error(j.error || '');
        var tables = new Set();
        Object.keys(j.cells).forEach(function(ref) {
          var td = document.querySelector('td[data-ref="' + ref.replace(/"/g, '\\"') + '"]:not([data-mint])');
          if (!td) return;
          var c = j.cells[ref];
          td.textContent = c.v || '';
          // Stil genau wie beim Neuladen setzen
          td.setAttribute('style', (c.sty || '') + 'font-size:8pt;text-align:center;border:1px solid #000');
          tables.add(td.closest('table'));
          if (c.ct) td.setAttribute('data-ct', c.ct); else td.removeAttribute('data-ct');
          if (c.ct === 'x') td.setAttribute('data-xlocked', '1'); else td.removeAttribute('data-xlocked');
          if (c.img) td.setAttribute('data-link', c.img); else td.removeAttribute('data-link');
          if (c.note) td.setAttribute('data-note', c.note); else td.removeAttribute('data-note');
          td.removeAttribute('data-vp-val');
        });
        // Tabelle neu zeichnen lassen (sonst bleiben in Safari dicke Linien stehen)
        tables.forEach(function(t) {
          if (!t) return;
          t.style.display = 'none';
          void t.offsetHeight;
          t.style.display = '';
        });
        document.getElementById('activeMint').textContent = mint;
        refreshUndoPreview();
        if (done) done();
      })
      .catch(function() { if (fail) fail(); });
  }

  // ───── Münzstätten-Blatt öffnen / schließen ohne Neuladen ─────
  var sheetScrollY = 0;
  function mainParts() {
    return [document.getElementById('grid'), document.getElementById('mobileList'), document.querySelector('.flag-bar')];
  }
  function openSheet(country, push) {
    fetch('/api/mint-sheet?country=' + encodeURIComponent(country))
      .then(function(r) { return r.json(); })
      .then(function(j) {
        if (!j.ok) throw new Error(j.error || '');
        sheetScrollY = window.scrollY;
        var old = document.getElementById('sheetView');
        if (old) old.remove();
        var wrap = document.createElement('div');
        wrap.innerHTML = j.html;
        var view = wrap.firstElementChild;
        view.setAttribute('data-country', country);
        var grid = document.getElementById('grid');
        grid.parentNode.insertBefore(view, grid.nextSibling);
        view.querySelectorAll('[data-ref]').forEach(bindCell);
        mainParts().forEach(function(el) { if (el) el.style.display = 'none'; });
        document.body.classList.add('on-sheet');
        if (push) { try { history.pushState({sheet: country}, '', '?layout=mints&country=' + encodeURIComponent(country)); } catch (e) {} }
        window.scrollTo(0, 0);
      })
      .catch(function() { location.href = '/?layout=mints&country=' + encodeURIComponent(country); });
  }
  function closeSheet(push) {
    var view = document.getElementById('sheetView');
    var grid = document.getElementById('grid');
    // Direkt als Blatt geöffnet: es gibt keine Haupttabelle zum Zurückholen
    if (!grid || !grid.querySelector('td[data-ref]')) { location.href = '/'; return; }
    var country = view ? view.getAttribute('data-country') : '';
    if (view) view.remove();
    document.body.classList.remove('on-sheet');
    var ml = document.getElementById('mobileList');
    if (ml) { ml.style.display = ''; } else { grid.style.display = ''; }
    var fb = document.querySelector('.flag-bar');
    if (fb) fb.style.display = '';
    var mint = getActiveMint();
    if (push) { try { history.pushState(null, '', mint ? '?mint=' + encodeURIComponent(mint) : '/'); } catch (e) {} }
    window.scrollTo(0, sheetScrollY);
    // Änderungen aus dem Blatt in die Haupttabelle holen
    if (country && mint) loadMintCells(country, mint);
  }
  document.addEventListener('click', function(e) {
    var back = e.target.closest('.sheet-back-btn');
    if (!back) return;
    e.preventDefault();
    closeSheet(true);
  });
  window.addEventListener('popstate', function() {
    var m = /[?&]layout=mints&country=([^&]*)/.exec(location.search);
    if (m) openSheet(decodeURIComponent(m[1]), false);
    else if (document.getElementById('sheetView')) closeSheet(false);
  });

  document.addEventListener('click', function(e) {
    var a = e.target.closest('.c-mint');
    if (!a) return;
    e.preventDefault();
    e.stopPropagation();
    if (a.classList.contains('c-mint-all')) { openSheet(a.getAttribute('data-country'), true); return; }
    if (a.classList.contains('active')) return;
    switchMint(a);
  });

  // ───── Extra-Zeilen: ⓘ zeigt, was die Zeile ist; beim Bearbeiten Name + Beschreibung ändern ─────
  function yearCellHtml(country, row, label, note) {
    if (!note) return htmlEsc(label);
    return '<span class="yr-name" data-country="' + htmlEsc(country) + '" data-row="' + htmlEsc(row) +
      '" data-note="' + htmlEsc(note) + '" title="' + htmlEsc(note) + '">' + htmlEsc(label) + '</span>';
  }
  var rowEdit = null;
  function showRowModal(on) {
    document.getElementById('rowModal').style.display = on ? 'block' : 'none';
    document.getElementById('rowOverlay').style.display = on ? 'block' : 'none';
  }
  function hideNotePop() { document.getElementById('rowNotePop').style.display = 'none'; }
  document.addEventListener('click', function(e) {
    var info = e.target.closest('.yr-name');
    var cell = e.target.closest('.c-year-extra');
    if (document.body.classList.contains('edit-mode') && cell) {
      // Bearbeiten: Fenster für Name + Beschreibung
      e.stopPropagation();
      var sp = cell.querySelector('.yr-name');
      rowEdit = {country: cell.getAttribute('data-country'), row: cell.getAttribute('data-row'),
                 block: (cell.getAttribute('data-cid') || '').split('|')[0]};
      document.getElementById('rowWhere').textContent = rowEdit.country;
      document.getElementById('rowLabel').value = cell.textContent.trim();
      document.getElementById('rowNote').value = sp ? sp.getAttribute('data-note') : '';
      showRowModal(true);
      document.getElementById('rowLabel').focus();
      return;
    }
    if (info) {
      // ⓘ: Beschreibung anzeigen
      e.stopPropagation();
      var pop = document.getElementById('rowNotePop');
      var label = info.textContent.trim();
      pop.innerHTML = '<b>' + htmlEsc(info.getAttribute('data-country')) + ' \u00b7 ' + htmlEsc(label) + '</b><br>' + htmlEsc(info.getAttribute('data-note'));
      var r = info.getBoundingClientRect();
      pop.style.display = 'block';
      pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8)) + 'px';
      pop.style.top = (r.bottom + 6) + 'px';
      return;
    }
    hideNotePop();
  });
  window.addEventListener('scroll', hideNotePop, {passive: true});
  document.getElementById('rowClose').addEventListener('click', function() { showRowModal(false); });
  document.getElementById('rowCancel').addEventListener('click', function() { showRowModal(false); });
  document.getElementById('rowOverlay').addEventListener('click', function() { showRowModal(false); });
  document.getElementById('rowDelete').addEventListener('click', function() {
    if (!rowEdit) return;
    var target = rowEdit;
    var name = document.getElementById('rowLabel').value.trim() || target.row;
    if (!confirm('Zeile \u201e' + name + '\u201c bei ' + target.country + ' l\u00f6schen?\n\nAlle M\u00fcnzen in dieser Zeile werden mit gel\u00f6scht. R\u00fcckg\u00e4ngig geht mit \u21b6.')) return;
    fetch('/api/remove-year', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({block: target.block || 'A', country: target.country, year: target.row})})
      .then(function(r) { return r.json(); })
      .then(function(j) {
        if (!j.ok) { showMsg('Fehler: ' + (j.error || ''), true); return; }
        showRowModal(false);
        showMsg('Zeile gel\u00f6scht. R\u00fcckg\u00e4ngig mit \u21b6. Seite wird neu geladen...');
        setTimeout(function() { location.reload(); }, 800);
      })
      .catch(function(err) { showMsg('Fehler: ' + err, true); });
  });
  document.getElementById('rowSave').addEventListener('click', function() {
    if (!rowEdit) return;
    var label = document.getElementById('rowLabel').value.trim();
    var note = document.getElementById('rowNote').value.trim();
    if (!label) { showMsg('Der Name darf nicht leer sein.', true); return; }
    var target = rowEdit;
    fetch('/api/extra-row/rename', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({country: target.country, row: target.row, label: label, note: note})})
      .then(function(r) { return r.json(); })
      .then(function(j) {
        if (!j.ok) { showMsg('Fehler: ' + (j.error || ''), true); return; }
        showRowModal(false);
        var html = yearCellHtml(target.country, target.row, j.label, j.note);
        document.querySelectorAll('.c-year-extra').forEach(function(c) {
          if (c.getAttribute('data-country') === target.country && c.getAttribute('data-row') === target.row) c.innerHTML = html;
        });
        document.querySelectorAll('td[data-year-label]').forEach(function(td) {
          if (td.getAttribute('data-country') === target.country && td.getAttribute('data-year') === target.row) td.setAttribute('data-year-label', j.label);
        });
        showMsg('Gespeichert: \u201e' + j.label + '\u201c. R\u00fcckg\u00e4ngig mit \u21b6.');
        refreshUndoPreview();
      })
      .catch(function(err) { showMsg('Fehler: ' + err, true); });
  });

  // ───── Münze hinzufügen (ohne die Zelle zu suchen) ─────
  var QA = [];
  try { QA = JSON.parse(document.getElementById('quickData').textContent); } catch (e) {}
  var QA_DENOMS = [['1c', '1 Cent'], ['2c', '2 Cent'], ['5c', '5 Cent'], ['10c', '10 Cent'], ['20c', '20 Cent'], ['50c', '50 Cent'],
                   ['1€', '1 Euro'], ['2€', '2 Euro'], ['CC1', '2€ Gedenk 1'], ['CC2', '2€ Gedenk 2'], ['CC3', '2€ Gedenk 3']];
  var qa = {q: '', s: '', mint: '', cur: null};
  function qaStore(k, v) { try { if (v === undefined) return localStorage.getItem('muenzapp:qa:' + k); localStorage.setItem('muenzapp:qa:' + k, v); } catch (e) {} }
  function qaCountry() { return QA.filter(function(c) { return c.name === document.getElementById('qaCountry').value; })[0]; }
  function qaRef() {
    var c = qaCountry(), y = document.getElementById('qaYear').value, d = document.getElementById('qaDenom').value;
    if (!c || !y || !d) return '';
    return c.name + ':' + y + ':' + d + (c.mints.length ? ':' + qa.mint : '');
  }
  function qaFillYears() {
    var c = qaCountry(), sel = document.getElementById('qaYear'), keep = sel.value || qaStore('year');
    sel.innerHTML = c.years.filter(function(y) { return !y[2] || !c.mints.length || y[2] === qa.mint; }).map(function(y) {
      return '<option value="' + htmlEsc(y[0]) + '">' + htmlEsc(y[1]) + '</option>';
    }).join('');
    if (keep && [].some.call(sel.options, function(o) { return o.value === keep; })) sel.value = keep;
    else sel.value = sel.options.length ? sel.options[sel.options.length - 1].value : '';
    qaFillDenoms();
  }
  function qaFillDenoms() {
    var c = qaCountry(), y = document.getElementById('qaYear').value, sel = document.getElementById('qaDenom'), keep = sel.value;
    var cc = (c && c.cc[y]) || {};
    sel.innerHTML = QA_DENOMS.map(function(d) {
      return '<option value="' + d[0] + '">' + d[1] + (cc[d[0]] ? ' – ' + htmlEsc(cc[d[0]]) : '') + '</option>';
    }).join('');
    if (keep) sel.value = keep;
    qaRenderChips();
    qaLoad();
  }
  function qaMints() {
    var c = qaCountry(), row = document.getElementById('qaMintRow');
    if (!c || !c.mints.length) { row.style.display = 'none'; qa.mint = ''; return; }
    if (c.mints.indexOf(qa.mint) < 0) qa.mint = c.mints.indexOf(getActiveMint()) >= 0 ? getActiveMint() : c.mints[0];
    row.style.display = '';
    document.getElementById('qaMints').innerHTML = c.mints.map(function(m) {
      return '<span class="qa-src' + (m === qa.mint ? ' on' : '') + '" data-m="' + m + '">' + m + '</span>';
    }).join('');
  }
  // Was ist schon in der Sammlung?
  function qaLoad() {
    var ref = qaRef(), box = document.getElementById('qaHave');
    qa.cur = null;
    if (!ref) { box.textContent = ''; return; }
    box.textContent = 'Lädt…';
    fetch('/api/coin-value?ref=' + encodeURIComponent(ref)).then(function(r) { return r.json(); }).then(function(j) {
      if (ref !== qaRef()) return;
      qa.cur = j;
      var list = vpParseRaw(j.v || '');
      var html = list.length
        ? '🪙 Schon in der Sammlung: <b>' + list.length + '</b> – ' + list.map(function(e) {
            return e.text ? htmlEsc(e.text) : htmlEsc(e.q + (e.s || '')) + ' (' + (QUALITY_LABELS[e.q] || e.q) + ', ' + (SOURCE_LABELS[e.s || ''] || '') + ')';
          }).join(', ')
        : 'Noch nicht in der Sammlung.';
      if (j.ct === 'x') html += '<br><span class="qa-warn">⚠️ Als ✕ nie geprägt markiert – beim Hinzufügen wird das ✕ entfernt.</span>';
      box.innerHTML = html;
      box.classList.toggle('has', list.length > 0);
    }).catch(function() { box.textContent = ''; });
  }
  // Auswahl als Knöpfe statt Listen
  function qaRenderChips() {
    var cSel = document.getElementById('qaCountry'), ySel = document.getElementById('qaYear'), dSel = document.getElementById('qaDenom');
    var c = qaCountry();
    document.getElementById('qaCountryName').textContent = c ? c.name : '';
    document.getElementById('qaCountryChips').innerHTML = QA.map(function(x) {
      return '<button type="button" class="qa-flag' + (x.name === cSel.value ? ' on' : '') + '" data-c="' + htmlEsc(x.name) + '" title="' + htmlEsc(x.name) + '">' + (x.flag || htmlEsc(x.name.slice(0, 2))) + '</button>';
    }).join('');
    var extra = {};
    if (c) c.years.forEach(function(y) { if (!/^\d+$/.test(y[0])) extra[y[0]] = true; });
    document.getElementById('qaYearChips').innerHTML = [].map.call(ySel.options, function(o) {
      return '<button type="button" class="qa-chip' + (o.value === ySel.value ? ' on' : '') + (extra[o.value] ? ' extra' : '') + '" data-y="' + htmlEsc(o.value) + '">' + htmlEsc(o.text) + '</button>';
    }).join('');
    document.getElementById('qaDenomChips').innerHTML = [].map.call(dSel.options, function(o) {
      var parts = o.text.split(' \u2013 ');
      var short = parts[0].replace('2\u20ac Gedenk ', 'Gedenk ').replace(' Cent', 'c').replace(' Euro', '\u20ac');
      return '<button type="button" class="qa-chip' + (o.value === dSel.value ? ' on' : '') + (o.value.indexOf('CC') === 0 ? ' cc' : '') + '" data-d="' + o.value + '" title="' + htmlEsc(o.text) + '">' +
        htmlEsc(short) + (parts[1] ? '<small>' + htmlEsc(parts[1]) + '</small>' : '') + '</button>';
    }).join('');
  }

  function qaPick(groupId, attr, val) {
    document.querySelectorAll('#' + groupId + ' [' + attr + ']').forEach(function(el) { el.classList.toggle('on', el.getAttribute(attr) === val); });
  }
  function showQa(on) {
    document.getElementById('qaModal').style.display = on ? 'block' : 'none';
    document.getElementById('qaOverlay').style.display = on ? 'block' : 'none';
  }
  (function initQa() {
    var sel = document.getElementById('qaCountry');
    if (!sel) return;
    sel.innerHTML = QA.map(function(c) { return '<option value="' + htmlEsc(c.name) + '">' + c.flag + ' ' + htmlEsc(c.name) + '</option>'; }).join('');
    document.getElementById('qaBtn').addEventListener('click', function() {
      var last = qaStore('country');
      if (last && QA.some(function(c) { return c.name === last; })) sel.value = last;
      qa.q = qa.q || '✔'; qa.s = qa.s === undefined ? '' : qa.s;
      qaPick('qaQ', 'data-q', qa.q); qaPick('qaS', 'data-s', qa.s);
      document.getElementById('qaDone').textContent = '';
      qaMints(); qaFillYears();
      showQa(true);
    });
    sel.addEventListener('change', function() { qaStore('country', sel.value); document.getElementById('qaYear').value = ''; qaMints(); qaFillYears(); });
    document.getElementById('qaYear').addEventListener('change', function() { qaStore('year', this.value); qaFillDenoms(); });
    document.getElementById('qaDenom').addEventListener('change', function() { qaRenderChips(); qaLoad(); });
    // Knöpfe setzen die (unsichtbaren) Listen
    document.getElementById('qaCountryChips').addEventListener('click', function(e) {
      var b = e.target.closest('[data-c]'); if (!b) return;
      sel.value = b.getAttribute('data-c'); sel.dispatchEvent(new Event('change'));
    });
    document.getElementById('qaYearChips').addEventListener('click', function(e) {
      var b = e.target.closest('[data-y]'); if (!b) return;
      var y = document.getElementById('qaYear'); y.value = b.getAttribute('data-y'); y.dispatchEvent(new Event('change'));
    });
    document.getElementById('qaDenomChips').addEventListener('click', function(e) {
      var b = e.target.closest('[data-d]'); if (!b) return;
      var d = document.getElementById('qaDenom'); d.value = b.getAttribute('data-d'); d.dispatchEvent(new Event('change'));
    });
    document.getElementById('qaMints').addEventListener('click', function(e) {
      var m = e.target.closest('[data-m]'); if (!m) return;
      qa.mint = m.getAttribute('data-m'); qaMints(); qaFillYears();
    });
    document.getElementById('qaQ').addEventListener('click', function(e) {
      var b = e.target.closest('[data-q]'); if (!b) return; qa.q = b.getAttribute('data-q'); qaPick('qaQ', 'data-q', qa.q);
    });
    document.getElementById('qaS').addEventListener('click', function(e) {
      var b = e.target.closest('[data-s]'); if (!b) return; qa.s = b.getAttribute('data-s'); qaPick('qaS', 'data-s', qa.s);
    });
    document.getElementById('qaClose').addEventListener('click', function() { showQa(false); });
    document.getElementById('qaOverlay').addEventListener('click', function() { showQa(false); });
    document.getElementById('qaSave').addEventListener('click', function() {
      var ref = qaRef();
      if (!ref || !qa.cur) return;
      var btn = this, wasX = qa.cur.ct === 'x';
      // Neue Münze einfach anhängen – was schon in der Zelle steht, bleibt genau so
      var newVal = (wasX ? '' : (qa.cur.v || '')) + qa.q + qa.s;
      var body = {}; body[ref] = newVal;
      btn.disabled = true;
      var first = wasX ? fetch('/api/cell-types', {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify((function() { var b = {}; b[ref] = 'nodata'; return b; })())}) : Promise.resolve();
      first.then(function() {
        return fetch('/api/cells', {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      }).then(function(r) { return r.json(); }).then(function(j) {
        if (!j.ok) throw new Error(j.error || '');
        // Zelle auf der Seite gleich mitändern, falls sie sichtbar ist
        var parts = ref.split(':'), base = parts.slice(0, 3).join(':');
        var targets = [];
        if (parts.length === 4) {
          targets = [].slice.call(document.querySelectorAll('td[data-ref="' + ref + '"]'));
          if (getActiveMint() === parts[3]) targets = targets.concat([].slice.call(document.querySelectorAll('td[data-ref="' + base + '"]:not([data-mint])')));
        } else {
          targets = [].slice.call(document.querySelectorAll('td[data-ref="' + ref + '"]'));
        }
        targets.forEach(function(td) {
          td.textContent = newVal; td.setAttribute('data-vp-val', newVal);
          if (wasX) { td.removeAttribute('data-xlocked'); td.removeAttribute('data-ct'); }
        });
        var c = qaCountry(), yo = document.getElementById('qaYear'), dd = document.getElementById('qaDenom');
        document.getElementById('qaDone').innerHTML = '✅ Hinzugefügt: <b>' + htmlEsc(c.name + ' ' + yo.options[yo.selectedIndex].text + ' ' + dd.options[dd.selectedIndex].text.split(' – ')[0] + (parts.length === 4 ? ' (' + parts[3] + ')' : '')) +
          ' · ' + htmlEsc(qa.q + qa.s) + '</b>. Rückgängig mit ↶.';
        refreshBreakdown(); refreshUndoPreview(); qaLoad();
      }).catch(function(e) { showMsg('Fehler: ' + e.message, true); })
        .then(function() { btn.disabled = false; });
    });
  })();

  // ───── Sum breakdown toggle ─────
  function showSum(on) {
    document.getElementById('sumBreakdown').style.display = on ? 'block' : 'none';
    document.getElementById('sumOverlay').style.display = on ? 'block' : 'none';
  }
  document.getElementById('sumBtn').addEventListener('click', function() { showTab('tabZahlen'); showSum(true); });
  // Reiter im Info-Popup: Zahlen / Legende
  function showTab(id) {
    document.querySelectorAll('#sumBreakdown .tab-pane').forEach(function(p) { p.style.display = p.id === id ? '' : 'none'; });
    document.querySelectorAll('#sumBreakdown .info-tab').forEach(function(t) { t.classList.toggle('active', t.getAttribute('data-tab') === id); });
  }
  document.querySelectorAll('#sumBreakdown .info-tab').forEach(function(t) {
    t.addEventListener('click', function() { showTab(this.getAttribute('data-tab')); });
  });
  document.getElementById('sumClose').addEventListener('click', function() { showSum(false); });
  document.getElementById('sumOverlay').addEventListener('click', function() { showSum(false); });
  document.addEventListener('keydown', function(e) { if (e.key === 'Escape') showSum(false); });

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
      showModal('reorderModal', 'rmOverlay', true);
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

  document.getElementById('editCountries').addEventListener('click', openReorderModal);
  document.getElementById('rmClose').addEventListener('click', function() { showModal('reorderModal', 'rmOverlay', false); });
  document.getElementById('rmOverlay').addEventListener('click', function() { showModal('reorderModal', 'rmOverlay', false); });
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


  // ───── Offline ansehen ─────
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(function(){});
    // Beim ersten Besuch die Seite gleich merken (vorher läuft der Helfer noch nicht)
    if (!navigator.serviceWorker.controller) {
      navigator.serviceWorker.addEventListener('controllerchange', function() {
        var urls = [location.href];
        document.querySelectorAll('script[src], link[rel=stylesheet]').forEach(function(el) { urls.push(el.src || el.href); });
        urls.forEach(function(u) { fetch(u, {credentials: 'same-origin'}).catch(function(){}); });
      }, {once: true});
    }
    // Nach Änderungen die gemerkte Seite auffrischen, wenn man die App verlässt
    var changed = false;
    var origFetch = window.fetch;
    window.fetch = function(input, init) {
      var p = origFetch.apply(this, arguments);
      var method = (init && init.method || 'GET').toUpperCase();
      if (method !== 'GET') p.then(function(r){ if (r.ok) changed = true; }, function(){});
      return p;
    };
    document.addEventListener('visibilitychange', function() {
      if (document.visibilityState === 'hidden' && changed) {
        changed = false;
        origFetch(location.href, {credentials: 'same-origin'}).catch(function(){});
      }
    });
  }

})();

