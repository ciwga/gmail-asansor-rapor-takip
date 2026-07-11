/**
 * @type {Object|null}
 */
let socket = null;

/**
 * @type {Array<Object>}
 */
let allResults = [];

/**
 * @type {number|null}
 */
let _pollTimer = null;

/**
 * @type {number}
 */
let _currentRunId = 0;

/**
 * @type {boolean}
 */
let _isRunning = false;

/**
 * Otomatik kaydetme için debounce zamanlayıcısı
 * @type {number|null}
 */
let _autoSaveTimer = null;

document.addEventListener('DOMContentLoaded', () => {
  initThemeAndView();
  initSocket();
  loadResults();
  loadConfig();
  loadProfiles();
  checkStatus();
  checkAuthFiles();
  
  const hash = window.location.hash.substring(1);
  if (hash) {
    const targetNav = document.querySelector(`.nav-item[data-panel="${hash}"]`);
    if (targetNav) {
      switchPanel(targetNav);
    }
  }
  
  document.getElementById('menuToggle').onclick = () => {
    const sb = document.getElementById('sidebar');
    if (window.innerWidth <= 768) {
      sb.classList.toggle('open');
    } else {
      sb.classList.toggle('closed');
    }
  };

  // Otomatik Kaydetme Olay Dinleyicileri
  const configPanel = document.getElementById('panel-config');
  if (configPanel) {
    // Metin alanlarındaki her harf girişi için
    configPanel.addEventListener('input', (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName) && e.target.type !== 'file') {
        triggerAutoSave();
      }
    });
    // Onay kutuları ve seçim değişiklikleri için
    configPanel.addEventListener('change', (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName) && e.target.type !== 'file') {
        triggerAutoSave();
      }
    });
  }
});

/**
 * Ayarları arka planda güvenle otomatik kaydeder.
 * @returns {void}
 */
function triggerAutoSave() {
  if (_autoSaveTimer) {
    clearTimeout(_autoSaveTimer);
  }
  const statusEl = document.getElementById('autoSaveStatus');
  if (statusEl) {
    statusEl.textContent = '⏳ Kaydediliyor...';
    statusEl.style.color = 'var(--text-muted)';
    statusEl.style.opacity = '1';
  }
  
  _autoSaveTimer = setTimeout(() => {
    saveConfigForm();
  }, 750); // Kullanıcı işlem yaptıktan 750ms sonra tetiklenir
}

/**
 * Kullanıcı tema ve görünüm tercihlerini uygular.
 * @returns {void}
 */
function initThemeAndView() {
  const savedTheme = localStorage.getItem('appTheme');
  if (savedTheme) {
    document.body.className = savedTheme;
  } else {
    if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      document.body.className = 'theme-dark';
    } else {
      document.body.className = 'theme-light';
    }
  }
  
  const savedView = localStorage.getItem('appViewMode');
  if (savedView === 'grid') {
    document.getElementById('resultList').classList.add('grid-view');
    document.getElementById('listControls').classList.add('grid-view-active');
  }
}

/**
 * Aydınlık ve karanlık tema arasında geçiş yapar.
 * @returns {void}
 */
function toggleTheme() {
  const body = document.body;
  const isDark = body.classList.contains('theme-dark');
                 
  if (isDark) {
    body.className = 'theme-light';
    localStorage.setItem('appTheme', 'theme-light');
  } else {
    body.className = 'theme-dark';
    localStorage.setItem('appTheme', 'theme-dark');
  }
}

/**
 * Sonuçlar listesi görünüm modunu değiştirir.
 * @returns {void}
 */
function toggleViewMode() {
  const list = document.getElementById('resultList');
  const controls = document.getElementById('listControls');
  
  list.classList.toggle('grid-view');
  controls.classList.toggle('grid-view-active');
  
  if (list.classList.contains('grid-view')) {
    localStorage.setItem('appViewMode', 'grid');
  } else {
    localStorage.setItem('appViewMode', 'list');
  }
}

/**
 * Sunucu ile gerçek zamanlı bağlantıyı başlatır.
 * @returns {void}
 */
function initSocket() {
  socket = io('/logs', {
    transports: ['polling'],
    reconnection: true,
    reconnectionDelay: 3000,
    forceNew: true
  });
  
  socket.on('log', function(e) {
    appendLog(e);
    
    if (!_isRunning) {
      return;
    }
    
    const msg = e.message || '';
    if (msg.includes('e-posta içeriği')) {
      setStatus('running', 'İçerik çekiliyor...');
    } else if (msg.includes('Worker başlatılıyor')) {
      setStatus('running', 'İşleniyor...');
    }
  });

  socket.on('results_updated', function() {
    console.log('[DEBUG] Arka planda yeni veriler bulundu, arayüz güncelleniyor...');
    loadResults();
  });
  
  socket.on('watch_cycle_started', function(data) {
    console.log('[DEBUG] İzleme döngüsü başladı:', data);
    if (!_isRunning) {
      checkStatus();
    }
  });

  socket.on('auth_required', (d) => {
    showAuthModal(d.url);
  });
  
  socket.on('auth_complete', () => {
    hideAuthModal();
    setStatus('running', 'Yetkilendirildi...');
  });
}

/**
 * Motoru tetikleyerek tarama işlemini başlatır.
 * @returns {void}
 */
function startRun() {
  console.log('[DEBUG] startRun called, btn disabled:', document.getElementById('runBtn').disabled);
  document.getElementById('runBtn').disabled = true;
  _isRunning = true;
  setStatus('running', 'Başlatılıyor...');
  showProgress(5);
  
  fetch('/api/run', { method: 'POST' })
    .then(r => {
      console.log('[DEBUG] /api/run response status:', r.status);
      return r.json();
    })
    .then(d => {
      console.log('[DEBUG] /api/run response:', JSON.stringify(d));
      if (d.status === 'started') {
        _currentRunId = d.run_id || 0;
        console.log('[DEBUG] Run started, run_id:', _currentRunId);
        startPolling();
      } else if (d.status === 'already_running') {
        _currentRunId = d.run_id || 0;
        console.log('[DEBUG] Already running, run_id:', _currentRunId);
        setStatus('running', 'Zaten çalışıyor...');
        startPolling();
      } else {
        console.log('[DEBUG] Unexpected status:', d.status);
        _isRunning = false;
        document.getElementById('runBtn').disabled = false;
        hideProgress();
      }
    })
    .catch(err => {
      console.error('[DEBUG] /api/run fetch error:', err);
      _isRunning = false;
      setStatus('error', 'Bağlantı hatası');
      document.getElementById('runBtn').disabled = false;
      hideProgress();
    });
}

/**
 * @type {number}
 */
let _doneConfirmCount = 0;

/**
 * Sunucudan durum kontrol döngüsünü başlatır.
 * @returns {void}
 */
function startPolling() {
  stopPolling();
  _doneConfirmCount = 0;
  _doPoll();
}

/**
 * Sunucu durumunu sorgular ve arayüzü günceller.
 * @returns {void}
 */
function _doPoll() {
  _pollTimer = setTimeout(() => {
    fetch('/api/status?_=' + Date.now())
      .then(r => r.json())
      .then(d => {
        console.log('[POLL]', JSON.stringify({
          running: d.running, 
          run_id: d.run_id, 
          my_id: _currentRunId, 
          progress: d.progress
        }));
        
        if (_currentRunId > 0 && d.run_id !== _currentRunId) {
          _doPoll();
          return;
        }
        
        if (d.running) {
          _doneConfirmCount = 0;
          const p = d.progress;
          if (p && p.total > 0) {
            const pct = Math.min(95, 10 + Math.round((p.done / p.total) * 85));
            showProgress(pct);
            setStatus('running', p.phase || ('İşleniyor... ' + p.done + '/' + p.total + ' (%' + pct + ')'));
          } else if (p && p.phase) {
            showProgress(50);
            setStatus('running', p.phase);
          } else {
            setStatus('running', 'Çalışıyor...');
          }
          _doPoll();
        } else {
          _doneConfirmCount++;
          if (_doneConfirmCount < 2) {
            setTimeout(() => { _doPoll(); }, 500);
          } else {
            _isRunning = false;
            showProgress(100);
            setTimeout(hideProgress, 1500);
            
            if (d.last_error) {
              setStatus('error', 'Hata: ' + d.last_error);
            } else {
              setStatus('done', 'Tamamlandı');
            }
            
            document.getElementById('runBtn').disabled = false;
            loadResults();
          }
        }
      })
      .catch(() => { _doPoll(); });
  }, 1500);
}

/**
 * Durum kontrol döngüsünü durdurur.
 * @returns {void}
 */
function stopPolling() {
  if (_pollTimer) {
    clearTimeout(_pollTimer);
    _pollTimer = null;
  }
}

/**
 * Motorun genel durumunu sorgular.
 * @returns {void}
 */
function checkStatus() {
  fetch('/api/status?_=' + Date.now())
    .then(r => r.json())
    .then(d => {
      console.log('[CHECK]', JSON.stringify(d));
      if (d.running) {
        _isRunning = true;
        _currentRunId = d.run_id || 0;
        setStatus('running', 'Çalışıyor...');
        document.getElementById('runBtn').disabled = true;
        startPolling();
      }
      updateWatchUI(d.watching || d.watch_running);
    })
    .catch(() => {});
}

/**
 * @type {number}
 */
let _resetTaps = 0;

/**
 * @type {number|null}
 */
let _resetTimer = null;

/**
 * Durum sıfırlama işlemlerini yönetir.
 * @returns {void}
 */
function onStatusTap() {
  _resetTaps++;
  clearTimeout(_resetTimer);
  
  _resetTimer = setTimeout(() => {
    _resetTaps = 0;
  }, 2000);
  
  if (_resetTaps >= 5) {
    _resetTaps = 0;
    _isRunning = false;
    _currentRunId = 0;
    _doneConfirmCount = 0;
    
    stopPolling();
    hideProgress();
    document.getElementById('runBtn').disabled = false;
    setStatus('idle', 'Sıfırlandı — tekrar deneyin');
  }
}

/**
 * Yetkilendirme dosyalarının durumunu kontrol eder.
 * @returns {void}
 */
function checkAuthFiles() {
  fetch('/api/auth/status?_=' + Date.now())
    .then(r => r.json())
    .then(d => {
      const cs = document.getElementById('credStatus');
      const ts = document.getElementById('tokenStatus');
      
      if (cs) {
        cs.innerHTML = d.credentials_exists 
          ? '<span style="color:var(--green)">✓ Mevcut</span>' 
          : '<span style="color:var(--red)">✗ Yok</span>';
      }
      
      if (ts) {
        ts.innerHTML = d.token_exists 
          ? '<span style="color:var(--green)">✓ Mevcut</span>' 
          : '<span style="color:var(--red)">✗ Yok</span>';
      }
      
      const area = document.getElementById('authStatusArea');
      if (area) {
        if (!d.credentials_exists) {
          area.innerHTML = '<div style="padding:10px; background:#fce8e6; color:#a50e0e; border:1px solid #f1c4c0; border-radius:6px; font-size:12px; font-weight:500; margin-bottom:8px;">⚠️ <strong>Hata:</strong> credentials.json bulunamadı. Google Cloud Console\'dan indirip yükleyin.</div>';
        } else if (!d.token_exists) {
          area.innerHTML = '<div style="padding:10px; background:#fef7e0; color:#73510d; border:1px solid #fce8b2; border-radius:6px; font-size:12px; font-weight:500; margin-bottom:8px;">⚠️ <strong>Not:</strong> token.json yok. İşlemi başlattığınızda yetkilendirme ekranı açılacak.</div>';
        } else {
          area.innerHTML = '<div style="padding:10px; background:#e6f4ea; color:#1e4620; border:1px solid #b7e1cd; border-radius:6px; font-size:12px; font-weight:500; margin-bottom:8px;">✅ Yetkilendirme dosyaları hazır.</div>';
        }
      }
    })
    .catch(() => {});
}

/**
 * Yetkilendirme dosyası yükler.
 * @param {string} type 
 * @param {HTMLInputElement} input 
 * @returns {void}
 */
function uploadAuthFile(type, input) {
  if (!input.files.length) {
    return;
  }
  
  const fd = new FormData();
  fd.append('file', input.files[0]);
  
  fetch('/api/auth/upload/' + type, { method: 'POST', body: fd })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'uploaded') {
        alert(type + '.json yüklendi.');
        checkAuthFiles();
      } else {
        alert('Hata: ' + (d.error || ''));
      }
    })
    .catch(e => alert('Yükleme hatası'));
    
  input.value = '';
}

/**
 * İlgili yetkilendirme dosyasını indirir.
 * @param {string} type 
 * @returns {void}
 */
function downloadAuthFile(type) {
  window.open('/api/auth/download/' + type);
}

/**
 * Mevcut jeton verisini siler.
 * @returns {void}
 */
function deleteToken() {
  if (!confirm('token.json silinsin mi? Bir sonraki çalıştırmada yeniden yetkilendirme gerekecek.')) {
    return;
  }
  
  fetch('/api/auth/delete/token', { method: 'DELETE' })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'deleted') {
        alert('Token silindi.');
        checkAuthFiles();
      }
    })
    .catch(() => {});
}

/**
 * Periyodik tarama modunun durumunu değiştirir.
 * @returns {void}
 */
function toggleWatch() {
  fetch('/api/status')
    .then(r => r.json())
    .then(d => {
      if (d.watching || d.watch_running) {
        fetch('/api/watch/stop', { method: 'POST' }).then(() => {
          updateWatchUI(false);
        });
      } else {
        saveConfigForm(); // Explicit save.
        setTimeout(() => {
          fetch('/api/watch/start', { method: 'POST' })
            .then(async r => {
              const data = await r.json();
              if (!r.ok || data.status === 'error') {
                alert('HATA: ' + (data.error || data.message || 'İzleme modu başlatılamadı.'));
                updateWatchUI(false);
              } else {
                updateWatchUI(data.status === 'started' || data.status === 'already_watching');
              }
            })
            .catch(err => {
              alert('Bağlantı hatası: ' + err);
              updateWatchUI(false);
            });
        }, 500);
      }
    });
}

/**
 * Periyodik tarama arayüz durumunu günceller.
 * @param {boolean} active 
 * @returns {void}
 */
function updateWatchUI(active) {
  const btn = document.getElementById('watchBtn');
  const st = document.getElementById('watchStatus');
  
  if (active) {
    btn.textContent = '⏹ Dinlemeyi Durdur';
    btn.style.background = 'var(--red)';
    btn.style.borderColor = 'var(--red)';
    btn.style.color = '#fff';
    st.textContent = 'Aktif (Arka planda tarama yapıyor)';
  } else {
    btn.textContent = '▶ Dinlemeyi Başlat';
    btn.style.background = '';
    btn.style.borderColor = '';
    btn.style.color = '';
    st.textContent = '';
  }
}

/**
 * Arayüzdeki genel durum rozetini günceller.
 * @param {string} s 
 * @param {string} t 
 * @returns {void}
 */
function setStatus(s, t) {
  const b = document.getElementById('statusBadge');
  b.className = 'status-badge ' + s;
  b.textContent = t;
}

/**
 * Yetkilendirme penceresini görüntüler.
 * @param {string} url 
 * @returns {void}
 */
function showAuthModal(url) {
  const modal = document.getElementById('authModal');
  const link = document.getElementById('authLink');
  
  link.href = url;
  modal.style.display = 'flex';
  setStatus('running', 'Yetkilendirme bekleniyor...');
  
  const pollAuth = setInterval(() => {
    fetch('/api/auth/status')
      .then(r => r.json())
      .then(d => {
        if (!d.auth_url) {
          clearInterval(pollAuth);
          hideAuthModal();
        }
      })
      .catch(() => {});
  }, 3000);
}

/**
 * Yetkilendirme penceresini gizler.
 * @returns {void}
 */
function hideAuthModal() {
  document.getElementById('authModal').style.display = 'none';
}

/**
 * Log nesnesini arayüze ekler.
 * @param {Object} e 
 * @returns {void}
 */
function onLogEntry(e) {
  appendLog(e);
}

/**
 * İlerleme çubuğunu günceller.
 * @param {number} pct 
 * @returns {void}
 */
function showProgress(pct) {
  const w = document.getElementById('progressBar');
  const f = document.getElementById('progressFill');
  w.classList.add('active');
  f.style.width = pct + '%';
}

/**
 * İlerleme çubuğunu gizler.
 * @returns {void}
 */
function hideProgress() {
  document.getElementById('progressBar').classList.remove('active');
  document.getElementById('progressFill').style.width = '0%';
}

/**
 * İşlenen sonuçları sunucudan alır.
 * @returns {void}
 */
function loadResults() {
  fetch('/api/results')
    .then(r => r.json())
    .then(d => {
      if (Array.isArray(d) && d.length) {
        allResults = d;
        renderResults(d);
      } else {
        allResults = [];
        renderResults([]);
      }
    })
    .catch(() => {});
}

/**
 * Listede listelenen kayıtların tümünü seçer ya da seçimi kaldırır.
 * @param {HTMLInputElement} cb 
 * @returns {void}
 */
function toggleSelectAll(cb) {
  const checkboxes = document.querySelectorAll('.row-select-cb');
  checkboxes.forEach(c => c.checked = cb.checked);
  updateSelectedCount();
}

/**
 * Kullanıcının işaretlediği kayıt sayısını günceller.
 * @returns {void}
 */
function updateSelectedCount() {
  const count = document.querySelectorAll('.row-select-cb:checked').length;
  document.getElementById('selectedCount').textContent = count + ' Seçildi';
}

/**
 * Arayüzde seçilmiş olan tüm satırların kimliklerini okur.
 * @returns {Array<string>}
 */
function getSelectedIds() {
  return Array.from(document.querySelectorAll('.row-select-cb:checked')).map(c => c.value);
}

/**
 * Kullanıcının seçtiği kayıtları YALNIZCA arayüz listesinden kaldırır.
 * @returns {void}
 */
function deleteSelectedList() {
  const ids = getSelectedIds();
  if (!ids.length) {
    alert('Lütfen listeden kaldırılacak kayıtları seçin.');
    return;
  }
  
  if (!confirm(ids.length + ' adet seçili kayıt sadece mevcut ekrandaki listeden silinsin mi? (Veritabanında kalmaya devam edecek)')) {
    return;
  }
  
  fetch('/api/results/delete-selected', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: ids })
  })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'deleted') {
        allResults = allResults.filter(r => !ids.includes(r.uuid || r.file_name));
        renderResults(allResults);
      } else {
        alert('Hata: ' + (d.error || 'İşlem gerçekleştirilemedi.'));
      }
    })
    .catch(e => alert('Bağlantı hatası: ' + e));
}

/**
 * Kullanıcının seçtiği kayıtları VERİTABANINDAN KALICI olarak siler.
 * @returns {void}
 */
function deleteSelectedDB() {
  const ids = getSelectedIds();
  if (!ids.length) {
    alert('Lütfen veritabanından silinecek kayıtları seçin.');
    return;
  }
  
  if (!confirm('DİKKAT: ' + ids.length + ' adet seçili kayıt VERİTABANINDAN (PDF dahil) kalıcı olarak silinsin mi?')) {
    return;
  }
  
  fetch('/api/database/delete-selected', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids: ids })
  })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'deleted') {
        allResults = allResults.filter(r => !ids.includes(r.uuid || r.file_name));
        renderResults(allResults);
        alert(d.deleted_count + ' kayıt sistemden tamamen silindi.');
      } else {
        alert('Hata: ' + (d.error || 'İşlem gerçekleştirilemedi.'));
      }
    })
    .catch(e => alert('Bağlantı hatası: ' + e));
}

/**
 * Veritabanında saklı olan tüm eski raporları listeye geri çağırır.
 * @returns {void}
 */
function fetchFromDB() {
  if (!confirm('Veritabanındaki kayıtlı tüm geçmiş raporlar listeye eklensin mi?')) {
    return;
  }
  
  fetch('/api/results/fetch-db', { method: 'POST' })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'fetched') {
        loadResults();
        if (d.count > 0) {
            alert('Veritabanından ' + d.count + ' yeni kayıt başarıyla listeye getirildi.');
        } else {
            alert('Eklenecek yeni geçmiş kayıt bulunamadı (Tümü zaten listede mevcut).');
        }
      } else {
        alert('Hata: ' + (d.error || 'İşlem gerçekleştirilemedi.'));
      }
    })
    .catch(e => alert('Bağlantı hatası: ' + e));
}

/**
 * Alınan sonuçları arayüze çizer.
 * @param {Array<Object>} results 
 * @returns {void}
 */
function renderResults(results) {
  const sorted = [...results].sort((a, b) => pd(a.next_inspection || '') - pd(b.next_inspection || ''));
  const list = document.getElementById('resultList');
  document.getElementById('resultCount').textContent = sorted.length.toString();
  
  if (!sorted.length) {
    list.innerHTML = '<div class="empty-state"><p>Henüz sonuç yok.</p></div>';
    document.getElementById('selectAllCheckbox').checked = false;
    updateSelectedCount();
    return;
  }
  
  list.innerHTML = sorted.map((r) => {
    const oi = allResults.indexOf(r);
    const lbl = r.label_color || '';
    const bld = r.building_name || '?';
    const prv = r.provider || '';
    const dt = r.inspection_date || '-';
    const nx = r.next_inspection || '-';
    const uid = r.uuid || '';
    const ic = labelIcon(lbl);
    const urg = urgency(nx);
    const isR = lbl.toLowerCase().includes('randevu');
    const hasP = uid && uid !== 'N/A' && !isR;
    const safeUid = uid || r.file_name || '';
    
    return `<div class="result-row" onclick="showDetail(${oi})">
      <div class="result-select" style="display:flex;align-items:center;padding-right:12px" onclick="event.stopPropagation()">
        <input type="checkbox" class="row-select-cb" value="${esc(safeUid)}" onchange="updateSelectedCount()" style="width:18px;height:18px;cursor:pointer;accent-color:var(--accent);">
      </div>
      <div class="result-label">${ic}</div>
      <div class="result-main">
        <div class="result-building">${esc(bld)}</div>
        <div class="result-provider">${esc(prv)}</div>
      </div>
      <div class="result-date" title="Kontrol Tarihi: ${esc(dt)}">
        <span class="grid-label">Kontrol Tarihi: </span>${esc(dt)}
      </div>
      <div class="result-next ${urg}" title="Sonraki Kontrol Tarihi: ${esc(nx)}">
        <span class="grid-label">Sonraki Kontrol Tarihi: </span>${esc(nx)}
      </div>
      <div class="result-actions">
        ${hasP ? `<button class="btn-row" onclick="event.stopPropagation();openPdf('${esc(uid)}')" title="PDF Aç">📄</button>` : ''}
      </div>
    </div>`;
  }).join('');
  
  document.getElementById('selectAllCheckbox').checked = false;
  updateSelectedCount();
}

/**
 * Sonuçları belirtilen filtreye göre düzenler.
 * @returns {void}
 */
function filterResults() {
  const f = document.getElementById('filterLabel').value;
  renderResults(f ? allResults.filter(r => (r.label_color || '').includes(f)) : allResults);
}

/**
 * Tarih dizgesini işlenebilir sayıya dönüştürür.
 * @param {string} s 
 * @returns {number}
 */
function pd(s) {
  if (!s) {
    return Infinity;
  }
  const p = s.split('.');
  if (p.length !== 3) {
    return Infinity;
  }
  const d = new Date(+p[2], +p[1] - 1, +p[0]);
  return isNaN(d) ? Infinity : d.getTime();
}

/**
 * Etiket verisine karşılık gelen emojiyi döndürür.
 * @param {string} l 
 * @returns {string}
 */
function labelIcon(l) {
  l = (l || '').toLowerCase();
  if (l.includes('kırmızı')) return '🔴';
  if (l.includes('sarı')) return '🟡';
  if (l.includes('mavi')) return '🔵';
  if (l.includes('yeşil')) return '🟢';
  if (l.includes('randevu')) return '📆';
  return '⚪';
}

/**
 * Aciliyet durumunu sınıflandırır.
 * @param {string} d 
 * @returns {string}
 */
function urgency(d) {
  try {
    const p = d.split('.');
    if (p.length !== 3) {
      return '';
    }
    const days = (new Date(+p[2], +p[1] - 1, +p[0]) - new Date()) / 864e5;
    if (days < 30) return 'urgent';
    if (days < 90) return 'soon';
    return 'ok';
  } catch {
    return '';
  }
}

/**
 * Sistemdeki rapor dosyasını tamamen siler.
 * @param {string} rid 
 * @returns {void}
 */
function deletePdf(rid) {
  if (!confirm('PDF ve kayıt silinsin mi?')) {
    return;
  }
  fetch('/api/report/delete/' + encodeURIComponent(rid), { method: 'DELETE' })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'deleted') {
        allResults = allResults.filter(r => (r.uuid || r.file_name) !== rid);
        renderResults(allResults);
      } else {
        alert('Hata: ' + (d.error || ''));
      }
    })
    .catch(() => alert('Silme başarısız'));
}

/**
 * Ekranda görüntülenen kaydı kaldırır.
 * @param {string} rid 
 * @returns {void}
 */
function deleteResult(rid) {
  if (!confirm('Kayıt kaldırılsın mı?')) {
    return;
  }
  fetch('/api/report/delete/' + encodeURIComponent(rid), { method: 'DELETE' })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'deleted') {
        allResults = allResults.filter(r => (r.uuid || r.file_name) !== rid);
        renderResults(allResults);
      }
    })
    .catch(() => {});
}

/**
 * Raporu yeni sekmede açar.
 * @param {string} rid 
 * @returns {void}
 */
function openPdf(rid) {
  window.open('/api/pdf/by-report/' + encodeURIComponent(rid), '_blank');
}

/**
 * Görüntülenen tüm sonuçları listeden kaldırır.
 * @returns {void}
 */
function deleteAllResults() {
  if (!confirm('Arayüzdeki sonuçlar listeden silinsin mi? (Bu işlem sadece görünen listeyi temizler, veritabanına dokunmaz)')) {
    return;
  }
  fetch('/api/results/clear-all', {
    method: 'POST', 
    headers: { 'Content-Type': 'application/json' }
  })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'cleared') {
        allResults = [];
        renderResults([]);
      }
    });
}

/**
 * Veritabanındaki tüm kayıtları kalıcı olarak temizler.
 * @returns {void}
 */
function clearDatabase() {
  if (!confirm('DİKKAT: Veritabanındaki tüm işlenmiş e-posta geçmişi, rapor verileri ve indirilen PDF kayıtları kalıcı olarak silinecek! (Ayarlarınız ve yetkilendirmeleriniz korunur)\n\nE-postaların tekrar ilk günkü gibi taranabilmesini sağlayacak bu işlem geri alınamaz. Onaylıyor musunuz?')) {
    return;
  }
  fetch('/api/database/clear', {
    method: 'POST', 
    headers: { 'Content-Type': 'application/json' }
  })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'cleared') {
        allResults = [];
        renderResults([]);
        alert(`Veritabanı başarıyla tamamen sıfırlandı. Toplam ${d.deleted_count} kayıt silindi.`);
      } else {
        alert('Hata: ' + (d.error || 'Bilinmeyen bir hata oluştu.'));
      }
    })
    .catch(e => alert('Bağlantı hatası: ' + e));
}

/**
 * Arayüze yeni bir e-posta kaynağı satırı ekler.
 * @param {string} label 
 * @param {string} query 
 * @param {string} proc 
 * @returns {void}
 */
function addSourceRow(label, query, proc) {
  const c = document.getElementById('sourcesContainer');
  const row = document.createElement('div');
  row.className = 'cfg-row source-row';
  row.innerHTML = `
    <input type="text" class="input-full src-label" value="${esc(label || '')}" placeholder="Bina/Etiket Adı">
    <input type="text" class="input-full src-query" value="${esc(query || '')}" placeholder="Gönderen Mail Adresi">
    <select class="input-full src-proc">
      <option value="adetsis"${proc === 'adetsis' ? ' selected' : ''}>Adetsis</option>
      <option value="mmo"${proc === 'mmo' ? ' selected' : ''}>MMO</option>
      <option value="artibel"${proc === 'artibel' ? ' selected' : ''}>Artıbel</option>
      <option value="optimaldenge"${proc === 'optimaldenge' ? ' selected' : ''}>Optimal Denge</option>
      <option value="appointment"${proc === 'appointment' ? ' selected' : ''}>Randevu</option>
    </select>
    <button class="btn-sm danger" onclick="this.parentElement.remove(); triggerAutoSave();">✕ Kaldır</button>
  `;
  c.appendChild(row);
}

/**
 * Kaynakları panele yükler.
 * @param {Array<Object>} sources 
 * @returns {void}
 */
function loadSources(sources) {
  const c = document.getElementById('sourcesContainer');
  c.innerHTML = '';
  (sources || []).forEach(s => addSourceRow(s.label_name, s.query, s.processor));
}

/**
 * Arayüzdeki kaynak satırlarını toplayıp listeye dönüştürür.
 * @returns {Array<Object>}
 */
function saveSources() {
  const rows = document.querySelectorAll('#sourcesContainer .source-row');
  return Array.from(rows).map(r => {
    const l = r.querySelector('.src-label').value.trim();
    const q = r.querySelector('.src-query').value.trim();
    const p = r.querySelector('.src-proc').value;
    return q ? { label_name: l, query: q, processor: p } : null;
  }).filter(Boolean);
}

/**
 * Sonuç detay panelini açar.
 * @param {number} i 
 * @returns {void}
 */
function showDetail(i) {
  const r = allResults[i];
  if (!r) {
    return;
  }
  
  const uid = r.uuid || '';
  const isR = (r.label_color || '').toLowerCase().includes('randevu');
  
  document.getElementById('drawerTitle').textContent = r.building_name || 'Rapor';
  
  const fields = [
    ['Bina', r.building_name],
    ['Asansör', r.elevator_number],
    ['Etiket', labelIcon(r.label_color) + ' ' + (r.label_color || '')],
    ['Tarih', r.inspection_date],
    ['Sonraki', r.next_inspection],
    ['Firma', r.provider],
    ['Dosya', r.file_name],
    ['UUID', uid]
  ];
  
  document.getElementById('drawerBody').innerHTML = fields.map(([l, v]) => `
    <div class="detail-field">
      <div class="detail-label">${l}</div>
      <div class="detail-value">${esc(v || 'N/A')}</div>
    </div>
  `).join('');
  
  const ft = document.getElementById('drawerFooter');
  if (uid && uid !== 'N/A' && !isR) {
    ft.innerHTML = `
      <a class="btn-drawer primary" href="/api/pdf/by-report/${encodeURIComponent(uid)}" target="_blank">📄 Aç</a>
      <a class="btn-drawer" href="/api/pdf/by-report/${encodeURIComponent(uid)}" download>⬇ İndir</a>
      <button class="btn-drawer danger" onclick="deletePdf('${esc(uid)}');closeDrawer()">🗑 Sil</button>
    `;
  } else if (isR) {
    ft.innerHTML = `
      <span style="color:var(--text-muted);font-size:12px;flex:1;text-align:center">Randevu — PDF yok</span>
      <button class="btn-drawer danger" onclick="deleteResult('${esc(uid)}');closeDrawer()">🗑 Kaldır</button>
    `;
  } else {
    ft.innerHTML = '';
  }
  
  document.getElementById('drawer').classList.add('open');
  document.getElementById('drawerOverlay').classList.add('open');
  const sb = document.getElementById('sidebar');
  if (window.innerWidth <= 768) {
    sb.classList.remove('open');
  }
}

/**
 * Açık olan detay panelini kapatır.
 * @returns {void}
 */
function closeDrawer() {
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('drawerOverlay').classList.remove('open');
}

/**
 * Terminal ANSI renk ve format kodlarını metinden temizler.
 * @param {string} str 
 * @returns {string}
 */
function stripAnsi(str) {
  if (!str) return '';
  return str.replace(/[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nqry=><]/g, '');
}

/**
 * Arayüze log satırı ekler. Terminal ANSI kodlarını otomatik olarak ayıklar.
 * @param {Object} e 
 * @returns {void}
 */
function appendLog(e) {
  const c = document.getElementById('logContainer');
  const d = document.createElement('div');
  d.className = 'log-entry';
  
  const safeTime = stripAnsi(e.time || '');
  const safeLevel = stripAnsi(e.level || 'INFO').replace(/\s/g, '');
  const safeMsg = stripAnsi(e.message || '');
  
  d.innerHTML = `<span class="log-time">${esc(safeTime)}</span> <span class="log-level-${safeLevel}">[${safeLevel}]</span> ${esc(safeMsg)}`;
  
  c.appendChild(d);
  
  while (c.children.length > 2000) {
    c.removeChild(c.firstChild);
  }
  
  if (document.getElementById('autoScroll').checked) {
    c.scrollTop = c.scrollHeight;
  }
}

/**
 * Log ekranını temizler.
 * @returns {void}
 */
function clearLogs() {
  document.getElementById('logContainer').innerHTML = '';
}

/**
 * Güvenli klasör dizinleri için onay penceresi açar.
 * @param {string} id 
 * @returns {void}
 */
function browseFolder(id) {
  const cur = document.getElementById(id).value;
  const isSecure = id === 'cfg_path_db' || id === 'cfg_path_log';
  
  const suffix = id === 'cfg_path_output' ? '/ciktilar' :
                 id === 'cfg_path_dl' ? '/raporlar' :
                 id === 'cfg_path_db' ? '/asansor_denetcisi.db' :
                 id === 'cfg_path_log' ? 'asansor_denetcisi.log' :
                 id === 'cfg_manual_proc' ? '/manuel/islenenler' :
                 id === 'cfg_manual_path' ? '/manuel' : '';
  
  let presets, msg;
  
  if (isSecure) {
    presets = [
      { label: '1) Mevcut Proje Klasörü (Tavsiye Edilir)', path: '.' + suffix },
      { label: '2) Ev Dizini / Güvenli Alan', path: '~/' + suffix }
    ];
    msg = 'GÜVENLİK UYARISI: Bu dosya hassas veriler (Veritabanı/Log/Token) içerir.\nLütfen "İndirilenler" klasörünü KULLANMAYIN. Dışarıdan erişime kapalı güvenli bir alan seçin:\n\n';
  } else {
    presets = [
      { label: '1) Android - İndirilenler (Termux Uyumlu)', path: '~/storage/downloads' + suffix },
      { label: '2) Mevcut Proje Klasörü', path: '.' + suffix },
      { label: '3) Bilgisayar Ana Dizini (Windows/Mac/Linux)', path: '~/Downloads' + suffix }
    ];
    msg = 'Bu klasör Raporlar, Çıktılar ve Manuel okumalar içindir. Rahat erişebileceğiniz bir yer seçin:\n\n';
  }
  
  presets.forEach((p, i) => msg += `${p.label}\n -> ${p.path}\n\n`);
  msg += 'Kısa yollar (1, 2, 3) yazabilir veya dilediğiniz tam yolu girebilirsiniz.';
  
  const choice = prompt(msg, cur);
  if (choice !== null && choice.trim() !== "") {
    let finalPath = choice.trim();
    if (finalPath === '1' && presets.length > 0) finalPath = presets[0].path;
    else if (finalPath === '2' && presets.length > 1) finalPath = presets[1].path;
    else if (finalPath === '3' && presets.length > 2) finalPath = presets[2].path;
    
    const inputEl = document.getElementById(id);
    if (inputEl) {
      inputEl.value = finalPath;
      triggerAutoSave(); // Programatik değişikliği yakala
    }
  }
}

/**
 * Sunucudan yapılandırma dosyasını yükler ve UI elemanlarını doldurur.
 * @returns {void}
 */
function loadConfig() {
  fetch('/api/config')
    .then(r => {
      if (!r.ok) {
        throw new Error(`Ayarlar yüklenemedi (HTTP ${r.status})`);
      }
      return r.json();
    })
    .then(c => {
      if (c.error) {
        throw new Error(c.error);
      }
      
      const editorEl = document.getElementById('configEditor');
      if (editorEl) editorEl.value = JSON.stringify(c, null, 2);
      
      const s = c.search_settings || {};
      const p = c.paths || {};
      const w = c.web_settings || {};
      const m = c.manual_source_settings || {};
      const a = c.appointment_email_settings || {};
      const cl = c.cleanup_mode_settings || {};
      const dl = c.label_delete_settings || {};
      const tr = c.trash_mode_settings || {};
      
      // Temel Ayarlar UI
      const isSearchByLabel = !!s.search_by_label;
      const labelRadio = document.querySelector('input[name="searchMode"][value="label"]');
      const normalRadio = document.querySelector('input[name="searchMode"][value="normal"]');
      
      if (isSearchByLabel && labelRadio) {
         labelRadio.checked = true;
      } else if (!isSearchByLabel && normalRadio) {
         normalRadio.checked = true;
      }
      
      C('cfg_only_unread', isSearchByLabel ? false : !!s.search_only_unread);
      C('cfg_mark_read', s.mark_as_read_after_processing !== false);
      C('cfg_archive', s.archive_after_processing);
      
      const df = s.date_range_filter || {};
      C('cfg_date_filter_enabled', df.enabled);
      V('cfg_date_start', df.start_date || '');
      V('cfg_date_end', df.end_date || '');

      // Randevu UI
      C('cfg_appt_enabled', a.enabled !== false);
      C('cfg_appt_past', a.filter_past_dates !== false);
      C('cfg_appt_unread', !!a.search_only_unread);
      V('cfg_appt_days', a.randevu_search_days || 60);

      // Çıktı Formatları UI
      C('cfg_fmt_txt', (c.output_formats || []).includes('txt'));
      C('cfg_fmt_csv', (c.output_formats || []).includes('csv'));
      C('cfg_fmt_wa', (c.output_formats || []).includes('whatsapp'));

      // Gelişmiş Ayarlar UI
      V('cfg_mode', c.mode || 'gmail');
      V('cfg_web_host', w.host || '127.0.0.1');
      V('cfg_web_port', w.port || 5001);
      
      const wt = c.watch_settings || {}; 
      V('cfg_watch_interval', wt.interval_minutes || 30);
      
      const ls = c.label_settings || {}; 
      const cols = ls.colors || {};
      
      C('cfg_label_tree', ls.use_tree); 
      V('cfg_label_parent', ls.tree_parent || '');
      V('cfg_lbl_red', cols['Kırmızı'] || 'Kırmızı Etiketli'); 
      V('cfg_lbl_yellow', cols['Sarı'] || 'Sarı Etiketli');
      V('cfg_lbl_blue', cols['Mavi'] || 'Mavi Etiketli'); 
      V('cfg_lbl_green', cols['Yeşil'] || 'Yeşil Etiketli');
      V('cfg_lbl_appt', ls.appointment_label || 'Randevu');
      
      V('cfg_path_dl', p.download_folder || '');
      V('cfg_path_output', p.output_folder || '');
      V('cfg_path_db', p.database || '');
      V('cfg_path_log', p.log_file || '');
      
      V('cfg_workers', s.num_workers || 10);
      V('cfg_search_days', s.search_days_before_today || 0);
      V('cfg_target_labels', (s.target_labels || []).join(', '));
      V('cfg_ex_keywords', (s.exceptional_keywords || []).join(', '));
      V('cfg_ex_senders', (s.exceptional_senders || []).join(', '));
      
      const dy = s.label_specific_days_before || {};
      V('cfg_days_red', dy['Kırmızı Etiketli'] || 60);
      V('cfg_days_yellow', dy['Sarı Etiketli'] || 120);
      
      loadSources(c.sources);
      
      C('cfg_manual_enabled', m.enabled);
      V('cfg_manual_path', m.folder_path || '');
      V('cfg_manual_proc', m.processed_folder_path || '');
      
      C('cfg_force_reprocess', (c.database_settings || {}).force_reprocess_all);
      C('cfg_skip_dup', (c.database_settings || {}).skip_duplicate_downloads !== false);
      
      C('cfg_cleanup_enabled', cl.enabled);
      C('cfg_cleanup_test', cl.run_in_test_mode !== false);
      loadCleanupRules(cl.cleanup_rules);
      
      C('cfg_dellabel_enabled', dl.enabled);
      C('cfg_dellabel_test', dl.run_in_test_mode !== false);
      V('cfg_dellabel_labels', (dl.labels_to_delete_permanently || []).join(', '));
      
      C('cfg_trash_enabled', tr.enabled);
      C('cfg_trash_test', tr.run_in_test_mode !== false);
      loadTrashRules(tr.trash_rules);
    })
    .catch(err => {
      console.error('Config fetch hatası:', err);
      alert('Ayarlar sunucudan alınırken bir hata oluştu:\n' + err.message);
    });
}

/**
 * Arama modu değiştirildiğinde tetiklenen mantık kuralları.
 * @returns {void}
 */
function onSearchModeChange() {
    const radio = document.querySelector('input[name="searchMode"]:checked');
    if (!radio) return;
    
    const isLabel = radio.value === 'label';
    
    // Etiket moduna geçilirse "Sadece okunmamışlar"ı kapat, çünkü etiket zaten ayrıştırıcıdır.
    if (isLabel) {
        C('cfg_only_unread', false);
        C('cfg_appt_unread', false);
        C('cfg_fmt_wa', true);
        C('cfg_mark_read', false);
    } else {
        C('cfg_only_unread', true);
        C('cfg_appt_unread', true);
        C('cfg_fmt_wa', false);
        C('cfg_mark_read', true);
    }
}

/**
 * Yapılandırma alanındaki verileri sunucuya gönderir ve kaydeder.
 * @returns {void}
 */
function saveConfigForm() {
  let c;
  const editorEl = document.getElementById('configEditor');
  if (!editorEl) return;

  try {
    c = JSON.parse(editorEl.value);
  } catch(e) {
    alert("Hata: Ayarlar JSON formatında hatalı, lütfen kontrol edin.");
    return;
  }
  
  c.mode = G('cfg_mode');
  
  // Çıktı Formatlarını Topla ve Kaydet
  const fm = [];
  if (B('cfg_fmt_txt')) fm.push('txt');
  if (B('cfg_fmt_csv')) fm.push('csv');
  if (B('cfg_fmt_wa')) fm.push('whatsapp');
  c.output_formats = fm;
  
  if (!c.web_settings) c.web_settings = {};
  c.web_settings.host = G('cfg_web_host');
  c.web_settings.port = parseInt(G('cfg_web_port')) || 5001;
  
  if (!c.watch_settings) c.watch_settings = {};
  c.watch_settings.interval_minutes = parseInt(G('cfg_watch_interval')) || 30;
  
  if (!c.label_settings) c.label_settings = {};
  c.label_settings.use_tree = B('cfg_label_tree');
  c.label_settings.tree_parent = G('cfg_label_parent');
  c.label_settings.colors = {
    'Kırmızı': G('cfg_lbl_red') || 'Kırmızı Etiketli',
    'Sarı': G('cfg_lbl_yellow') || 'Sarı Etiketli',
    'Mavi': G('cfg_lbl_blue') || 'Mavi Etiketli',
    'Yeşil': G('cfg_lbl_green') || 'Yeşil Etiketli'
  };
  c.label_settings.appointment_label = G('cfg_lbl_appt') || 'Randevu';
  
  c.color_labels = Object.values(c.label_settings.colors).concat([c.label_settings.appointment_label]);
  
  if (!c.paths) c.paths = {};
  c.paths.download_folder = G('cfg_path_dl');
  c.paths.output_folder = G('cfg_path_output');
  c.paths.database = G('cfg_path_db');
  c.paths.log_file = G('cfg_path_log');
  
  if (!c.search_settings) c.search_settings = {};
  
  const radio = document.querySelector('input[name="searchMode"]:checked');
  c.search_settings.search_by_label = radio ? (radio.value === 'label') : false;
  
  c.search_settings.search_only_unread = B('cfg_only_unread');
  c.search_settings.mark_as_read_after_processing = B('cfg_mark_read');
  c.search_settings.archive_after_processing = B('cfg_archive');
  c.search_settings.num_workers = parseInt(G('cfg_workers')) || 10;
  c.search_settings.search_days_before_today = parseInt(G('cfg_search_days')) || 0;
  
  c.search_settings.date_range_filter = {
    enabled: B('cfg_date_filter_enabled'),
    start_date: G('cfg_date_start'),
    end_date: G('cfg_date_end')
  };

  c.search_settings.target_labels = csv('cfg_target_labels');
  c.search_settings.exceptional_keywords = csv('cfg_ex_keywords');
  c.search_settings.exceptional_senders = csv('cfg_ex_senders');
  c.search_settings.label_specific_days_before = {
    'Kırmızı Etiketli': parseInt(G('cfg_days_red')) || 60,
    'Sarı Etiketli': parseInt(G('cfg_days_yellow')) || 120
  };
  
  c.sources = saveSources();
  
  if (!c.appointment_email_settings) c.appointment_email_settings = {};
  c.appointment_email_settings.enabled = B('cfg_appt_enabled');
  c.appointment_email_settings.filter_past_dates = B('cfg_appt_past');
  c.appointment_email_settings.randevu_search_days = parseInt(G('cfg_appt_days')) || 60;
  c.appointment_email_settings.search_only_unread = B('cfg_appt_unread');
  
  if (!c.manual_source_settings) c.manual_source_settings = {};
  c.manual_source_settings.enabled = B('cfg_manual_enabled');
  c.manual_source_settings.folder_path = G('cfg_manual_path');
  c.manual_source_settings.processed_folder_path = G('cfg_manual_proc');
  
  if (!c.database_settings) c.database_settings = {};
  c.database_settings.force_reprocess_all = B('cfg_force_reprocess');
  c.database_settings.skip_duplicate_downloads = B('cfg_skip_dup');
  
  if (!c.cleanup_mode_settings) c.cleanup_mode_settings = {};
  c.cleanup_mode_settings.enabled = B('cfg_cleanup_enabled');
  c.cleanup_mode_settings.run_in_test_mode = B('cfg_cleanup_test');
  c.cleanup_mode_settings.cleanup_rules = saveCleanupRules();
  
  if (!c.label_delete_settings) c.label_delete_settings = {};
  c.label_delete_settings.enabled = B('cfg_dellabel_enabled');
  c.label_delete_settings.run_in_test_mode = B('cfg_dellabel_test');
  c.label_delete_settings.labels_to_delete_permanently = csv('cfg_dellabel_labels');
  
  if (!c.trash_mode_settings) c.trash_mode_settings = {};
  c.trash_mode_settings.enabled = B('cfg_trash_enabled');
  c.trash_mode_settings.run_in_test_mode = B('cfg_trash_test');
  c.trash_mode_settings.trash_rules = saveTrashRules();
  
  editorEl.value = JSON.stringify(c, null, 2);
  
  const statusEl = document.getElementById('autoSaveStatus');
  
  fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(c)
  })
    .then(r => r.json())
    .then(d => {
      if (d.status === 'saved') {
        if (statusEl) {
            statusEl.textContent = '✓ Otomatik kaydedildi';
            statusEl.style.color = 'var(--green)';
            statusEl.style.opacity = '1';
            
            setTimeout(() => {
                if (statusEl.textContent === '✓ Otomatik kaydedildi') {
                    statusEl.style.opacity = '0';
                }
            }, 2500);
        }
      } else {
        if (statusEl) {
            statusEl.textContent = '⚠️ Kaydetme hatası';
            statusEl.style.color = 'var(--red)';
        }
        alert('Hata: ' + (d.error || 'Bilinmeyen bir hata oluştu.'));
      }
    })
    .catch(err => {
      console.error('Config kaydetme hatası:', err);
      if (statusEl) {
          statusEl.textContent = '⚠️ Bağlantı hatası';
          statusEl.style.color = 'var(--red)';
      }
    });
}

/**
 * Yeni bir temizlik kuralı alanı ekler.
 * @param {string} labels 
 * @param {string} senders 
 * @param {string} keywords 
 * @param {string|number} days 
 * @returns {void}
 */
function addCleanupRule(labels, senders, keywords, days) {
  const c = document.getElementById('cleanupRulesContainer');
  const row = document.createElement('div');
  row.className = 'rule-row';
  row.innerHTML = `
    <div class="cfg-row">
      <label>Kaldırılacak Etiketler</label>
      <input type="text" class="input-full cr-labels" value="${esc(labels || '')}" placeholder="Kırmızı Etiketli, Sarı Etiketli">
      <small class="field-hint">Bu etiketler eşleşen e-postalardan kaldırılır</small>
    </div>
    <div class="cfg-row">
      <label>Göndericiler</label>
      <input type="text" class="input-full cr-senders" value="${esc(senders || '')}" placeholder="info@mmo.org.tr, rapor@asansorkontrol.net">
      <small class="field-hint">Sadece bu adreslerden gelen e-postalara uygulanır (boş = hepsi)</small>
    </div>
    <div class="cfg-row">
      <label>Konu İçerik</label>
      <input type="text" class="input-full cr-keywords" value="${esc(keywords || '')}" placeholder="Onaylanmış Rapor, Randevu">
      <small class="field-hint">E-posta konusunda bu kelimelerden biri geçmeli (boş = hepsi)</small>
    </div>
    <div class="cfg-row">
      <label>Gün (eski)</label>
      <input type="number" class="input-sm cr-days" value="${days || ''}" placeholder="30" style="width:80px">
      <small class="field-hint">Bu günden eski e-postalara uygulanır (boş = tümü)</small>
      <button class="btn-sm" onclick="this.closest('.rule-row').remove(); triggerAutoSave();" style="color:var(--red);margin-left:auto">✕ Kaldır</button>
    </div>
  `;
  c.appendChild(row);
}

/**
 * Yeni bir çöp kutusu kuralı alanı ekler.
 * @param {string} labels 
 * @param {string} senders 
 * @param {string} keywords 
 * @param {string|number} days 
 * @returns {void}
 */
function addTrashRule(labels, senders, keywords, days) {
  const c = document.getElementById('trashRulesContainer');
  const row = document.createElement('div');
  row.className = 'rule-row';
  row.innerHTML = `
    <div class="cfg-row">
      <label>Gerekli Etiketler</label>
      <input type="text" class="input-full tr-labels" value="${esc(labels || '')}" placeholder="İşlem Başarısız">
      <small class="field-hint">Bu etiketlere sahip e-postalar çöpe taşınır</small>
    </div>
    <div class="cfg-row">
      <label>Göndericiler</label>
      <input type="text" class="input-full tr-senders" value="${esc(senders || '')}" placeholder="info@mmo.org.tr">
      <small class="field-hint">Sadece bu adreslerden gelen e-postalara uygulanır (boş = hepsi)</small>
    </div>
    <div class="cfg-row">
      <label>Konu İçerik</label>
      <input type="text" class="input-full tr-keywords" value="${esc(keywords || '')}" placeholder="Onaylanmış Rapor">
      <small class="field-hint">E-posta konusunda bu kelimelerden biri geçmeli (boş = hepsi)</small>
    </div>
    <div class="cfg-row">
      <label>Gün (eski)</label>
      <input type="number" class="input-sm tr-days" value="${days || ''}" placeholder="90" style="width:80px">
      <small class="field-hint">Bu günden eski e-postalara uygulanır (boş = tümü)</small>
      <button class="btn-sm" onclick="this.closest('.rule-row').remove(); triggerAutoSave();" style="color:var(--red);margin-left:auto">✕ Kaldır</button>
    </div>
  `;
  c.appendChild(row);
}

/**
 * Kayıtlı temizlik kurallarını panellere yerleştirir.
 * @param {Array<Object>} rules 
 * @returns {void}
 */
function loadCleanupRules(rules) {
  const container = document.getElementById('cleanupRulesContainer');
  if (!container) return;
  container.innerHTML = '';
  (rules || []).forEach(r => {
    const f = r.filters || {};
    addCleanupRule(
      (r.labels_to_remove || []).join(', '),
      (f.from_senders || []).join(', '),
      (f.subject_keywords || []).join(', '),
      f.days_older_than || ''
    );
  });
}

/**
 * Kayıtlı çöp kutusu kurallarını panellere yerleştirir.
 * @param {Array<Object>} rules 
 * @returns {void}
 */
function loadTrashRules(rules) {
  const container = document.getElementById('trashRulesContainer');
  if (!container) return;
  container.innerHTML = '';
  (rules || []).forEach(r => {
    const f = r.filters || {};
    addTrashRule(
      (f.required_labels || []).join(', '),
      (f.from_senders || []).join(', '),
      (f.subject_keywords || []).join(', '),
      f.days_older_than || ''
    );
  });
}

/**
 * Arayüzdeki temizlik kurallarını listeye dönüştürür.
 * @returns {Array<Object>}
 */
function saveCleanupRules() {
  return Array.from(document.querySelectorAll('#cleanupRulesContainer .rule-row')).map(r => ({
    labels_to_remove: csv_val(r, '.cr-labels'),
    filters: {
      from_senders: csv_val(r, '.cr-senders'),
      subject_keywords: csv_val(r, '.cr-keywords'),
      days_older_than: parseInt(r.querySelector('.cr-days').value) || 0
    }
  }));
}

/**
 * Arayüzdeki çöp kutusu kurallarını listeye dönüştürür.
 * @returns {Array<Object>}
 */
function saveTrashRules() {
  return Array.from(document.querySelectorAll('#trashRulesContainer .rule-row')).map(r => ({
    filters: {
      required_labels: csv_val(r, '.tr-labels'),
      from_senders: csv_val(r, '.tr-senders'),
      subject_keywords: csv_val(r, '.tr-keywords'),
      days_older_than: parseInt(r.querySelector('.tr-days').value) || 0
    }
  }));
}

/**
 * Elemanların değerlerini ayrıştırır ve temizler.
 * @param {HTMLElement} row 
 * @param {string} sel 
 * @returns {Array<string>}
 */
function csv_val(row, sel) {
  const el = row.querySelector(sel);
  if (!el) return [];
  return (el.value || '').split(',').map(s => s.trim()).filter(Boolean);
}

/**
 * Bakım görevini (temizlik vb.) tetikler.
 * @param {string} action 
 * @param {string} label 
 * @returns {void}
 */
function runMaintenance(action, label) {
  if (!confirm(label + ' işlemi başlatılsın mı?\nÖnce ayarları kaydettiğinizden emin olun.')) {
    return;
  }
  
  saveConfigForm();
  
  setTimeout(() => {
    fetch('/api/maintenance/' + action, { method: 'POST' })
      .then(r => r.json())
      .then(d => {
        if (d.status === 'started') {
          alert(label + ' başlatıldı. Sonuçlar Log panelinde görünecek.');
        } else {
          alert('Hata: ' + JSON.stringify(d));
        }
      })
      .catch(e => alert('Bağlantı hatası: ' + e));
  }, 500);
}

/**
 * İşlemci profillerini yükler.
 * @returns {void}
 */
function loadProfiles() {
  fetch('/api/scraping-profiles')
    .then(r => r.json())
    .then(d => V('profileEditor', JSON.stringify(d, null, 2)))
    .catch(() => {});
}

/**
 * İşlemci profillerini kaydeder.
 * @returns {void}
 */
function saveProfiles() {
  try {
    const editorVal = G('profileEditor');
    if (!editorVal) return;
    const d = JSON.parse(editorVal);
    
    fetch('/api/scraping-profiles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(d)
    })
      .then(r => r.json())
      .then(data => alert(data.status === 'saved' ? 'Kaydedildi!' : 'Hata'));
  } catch (e) {
    alert('JSON hatası: ' + e.message);
  }
}

/**
 * Menü sekmeleri arasında geçiş yapar.
 * @param {HTMLElement} el 
 * @returns {void}
 */
function switchPanel(el) {
  const panelName = el.dataset.panel;
  
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  el.classList.add('active');
  
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  const targetPanel = document.getElementById('panel-' + panelName);
  if (targetPanel) {
      targetPanel.classList.add('active');
  }
  
  const sb = document.getElementById('sidebar');
  if (window.innerWidth <= 768) {
    sb.classList.remove('open');
  }
  
  history.replaceState(null, null, '#' + panelName);
  
  if (panelName === 'logs') {
    fetch('/api/logs')
      .then(r => r.json())
      .then(l => {
        const container = document.getElementById('logContainer');
        if (container) {
            container.innerHTML = '';
            l.forEach(appendLog);
        }
      })
      .catch(() => {});
  }
}

/**
 * HTML özel karakterlerini filtreler.
 * @param {string} s 
 * @returns {string}
 */
function esc(s) {
  if (!s) {
    return '';
  }
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

/**
 * Null korumalı: Verilen id'li elemanın değerini döndürür.
 * @param {string} id 
 * @returns {string}
 */
function G(id) {
  const el = document.getElementById(id);
  return el ? el.value : '';
}

/**
 * Null korumalı: Verilen id'li elemanın değerini atar.
 * @param {string} id 
 * @param {string} v 
 * @returns {void}
 */
function V(id, v) {
  const el = document.getElementById(id);
  if (el) {
    el.value = v;
  }
}

/**
 * Null korumalı: Verilen id'li checkbox durumunu döndürür.
 * @param {string} id 
 * @returns {boolean}
 */
function B(id) {
  const el = document.getElementById(id);
  return el ? el.checked : false;
}

/**
 * Null korumalı: Verilen id'li checkbox durumunu atar.
 * @param {string} id 
 * @param {boolean} v 
 * @returns {void}
 */
function C(id, v) {
  const el = document.getElementById(id);
  if (el) {
    el.checked = !!v;
  }
}

/**
 * CSV ayrılmış değerleri listeye dönüştürür.
 * @param {string} id 
 * @returns {Array<string>}
 */
function csv(id) {
  const val = G(id);
  return val ? val.split(',').map(s => s.trim()).filter(Boolean) : [];
}