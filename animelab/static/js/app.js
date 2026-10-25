'use strict';

const THEME_KEY = 'animan-theme';
let sseSource = null;
let plyrInstance = null;
let cinemaPlyrInstance = null;
let cinemaHlsInstance = null;
let currentPlayingEpNum = null;
let currentRange = 'all';
let currentPlayAbortController = null;
let currentPlayRequestId = 0;

function stopAllPlayback() {
  if (currentPlayAbortController) {
    try { currentPlayAbortController.abort(); } catch (e) {}
    currentPlayAbortController = null;
  }
  currentPlayRequestId++;
  if (cinemaPlyrInstance) {
    try { cinemaPlyrInstance.pause(); } catch (e) {}
  }
  if (cinemaHlsInstance) {
    try { cinemaHlsInstance.destroy(); } catch (e) {}
    cinemaHlsInstance = null;
  }
  const cinemaVideo = document.getElementById('cinema-player');
  if (cinemaVideo) {
    try {
      cinemaVideo.pause();
      cinemaVideo.removeAttribute('src');
      cinemaVideo.load();
    } catch (e) {}
  }
  if (plyrInstance) {
    try { plyrInstance.pause(); } catch (e) {}
  }
  const plyrVideo = document.getElementById('plyr-player');
  if (plyrVideo) {
    try {
      plyrVideo.pause();
      plyrVideo.removeAttribute('src');
      plyrVideo.load();
    } catch (e) {}
  }
}

window.addEventListener('beforeunload', stopAllPlayback);
window.addEventListener('pagehide', stopAllPlayback);

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initTelegramOfflineDetector();
  highlightActiveNav();
  bindGlobalSettingsToggle();
  loadEpisodeSizes();
  buildVersionFilters();
  checkFavoriteStatus();
  refreshDownloadBadge();
  bindPlayActionButtons();
  initShortcuts();
  initSearchAutocomplete();
  initEpisodeRangePagination();

  if (document.getElementById('download-list')) {
    initSSE();
    refreshDownloadStats();
    initDragAndDrop();
    initScheduledTicker();
  }

  if (window.location.pathname === '/settings' || document.getElementById('save-settings-btn')) {
    initDownloadSettingsPanel();
  }
});


function initTheme() {
  const urlTheme = new URLSearchParams(window.location.search).get('theme');
  const saved = (urlTheme === 'light' || urlTheme === 'dark') ? urlTheme : (localStorage.getItem(THEME_KEY) || 'dark');
  applyTheme(saved);
  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
  });
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  document.querySelectorAll('.icon-moon').forEach(el => { el.style.display = theme === 'dark' ? '' : 'none'; });
  document.querySelectorAll('.icon-sun').forEach(el => { el.style.display = theme === 'light' ? '' : 'none'; });
  localStorage.setItem(THEME_KEY, theme);
}

function getCookie(name) {
  const match = document.cookie.match(new RegExp('(^|;\\s*)(' + name + ')=([^;]*)'));
  return match ? decodeURIComponent(match[3]) : null;
}

function getCurrentLang() {
  const cookieLang = getCookie('animan_lang');
  if (cookieLang === 'fr' || cookieLang === 'en') return cookieLang;
  const docLang = document.documentElement.lang;
  if (docLang === 'fr' || docLang === 'en') return docLang;
  return 'fr';
}

function setLanguage(lang) {
  if (lang !== 'fr' && lang !== 'en') lang = 'fr';
  const maxAge = 365 * 24 * 60 * 60;
  document.cookie = `animan_lang=${lang}; path=/; max-age=${maxAge}; SameSite=Lax`;
  fetch('/api/i18n/set-language', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ language: lang })
  }).finally(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.has('lang')) {
      url.searchParams.set('lang', lang);
    }
    window.location.href = url.toString();
  });
}

function toggleLanguage() {
  const current = getCurrentLang();
  const next = current === 'fr' ? 'en' : 'fr';
  setLanguage(next);
}

window.getCurrentLang = getCurrentLang;
window.setLanguage = setLanguage;
window.toggleLanguage = toggleLanguage;

function highlightActiveNav() {
  const path = window.location.pathname;
  const entries = [
    ['/downloads', 'nav-downloads', 'mob-nav-downloads'],
    ['/library', 'nav-library', 'mob-nav-library'],
    ['/history', 'nav-history', ''],
    ['/extensions', 'nav-extensions', 'mob-nav-extensions'],
    ['/settings', 'nav-settings', 'mob-nav-settings'],
    ['/', 'nav-home', 'mob-nav-home']
  ];
  const match = entries.find(([prefix]) => prefix === '/' ? path === '/' : path.startsWith(prefix));
  if (match) {
    if (match[1]) document.getElementById(match[1])?.classList.add('active');
    if (match[2]) document.getElementById(match[2])?.classList.add('active');
  }
}

function bindGlobalSettingsToggle() {
  document.querySelectorAll('[data-toggle-download-settings], #settings-shortcut').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const panel = document.getElementById('settings-panel');
      if (panel) {
        e.preventDefault();
        panel.classList.toggle('open');
        panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } else {
        window.location.href = '/settings';
      }
    });
  });
}

// Gestion de la navigation entre les onglets de sources
window.switchSourceTab = function(sourceId) {
  document.querySelectorAll('.source-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-source-id') === sourceId);
  });
  document.querySelectorAll('.source-content-pane').forEach(pane => {
    pane.classList.remove('active');
    pane.style.display = 'none';
  });
  const targetPane = document.getElementById(`pane-source-${sourceId}`);
  if (targetPane) {
    targetPane.classList.add('active');
    targetPane.style.display = 'block';
  }
};

function initDownloadSettingsPanel() {
  const panel = document.getElementById('settings-panel');
  const toggle = document.getElementById('toggle-settings-btn');
  const save = document.getElementById('save-settings-btn');
  const uaSelect = document.getElementById('user-agent-select');
  const customUaGroup = document.getElementById('custom-ua-group');
  const customUaInput = document.getElementById('custom-ua-input');

  if (window.location.hash === '#settings-panel' || new URLSearchParams(window.location.search).has('settings')) {
    panel?.classList.add('open');
    setTimeout(() => {
      panel?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }, 100);
  }

  toggle?.addEventListener('click', () => panel?.classList.toggle('open'));
  uaSelect?.addEventListener('change', () => {
    if (customUaGroup) customUaGroup.style.display = uaSelect.value === 'Custom' ? 'grid' : 'none';
  });

  fetch('/api/download/settings')
    .then(r => r.json())
    .then(settings => {
      const maxInput = document.getElementById('max-concurrent-input');
      const speedInput = document.getElementById('global-speed-input-settings');
      const plexInput = document.getElementById('plex-org-cb');
      const serverSelect = document.getElementById('voiranime-server-select');
      if (maxInput) maxInput.value = settings.maxConcurrentDownloads ?? 3;
      if (speedInput) speedInput.value = settings.globalSpeedLimit > 0 ? Math.round(settings.globalSpeedLimit / 1024) : '';
      if (plexInput) plexInput.checked = !!settings.plexOrganization;
      if (serverSelect && settings.voiranimeDefaultServer) {
        serverSelect.value = settings.voiranimeDefaultServer;
      }
      if (settings.selectedUserAgent && uaSelect) {
        const standard = ['Random (Rotator)', 'Chrome', 'Firefox', 'Safari', 'Edge'];
        uaSelect.value = standard.includes(settings.selectedUserAgent) ? settings.selectedUserAgent : 'Custom';
        if (customUaInput && uaSelect.value === 'Custom') customUaInput.value = settings.selectedUserAgent;
        if (customUaGroup) customUaGroup.style.display = uaSelect.value === 'Custom' ? 'grid' : 'none';
      }
      
      const ffmpegBadge = document.getElementById('ffmpeg-status-badge');
      if (ffmpegBadge) {
        if (settings.ffmpegAvailable) {
          ffmpegBadge.textContent = 'Opérationnel';
          ffmpegBadge.className = 'status-badge badge-ok';
        } else {
          ffmpegBadge.textContent = 'Non trouvé (Muxing désactivé)';
          ffmpegBadge.className = 'status-badge badge-err';
        }
      }
    })
    .catch(() => {});

  // Gestion du volet Proxy
  const proxyEnableCb = document.getElementById('proxy-enable-cb');
  const proxyConfigFields = document.getElementById('proxy-config-fields');
  const proxyTypeSelect = document.getElementById('proxy-type-select');
  const proxyHostInput = document.getElementById('proxy-host-input');
  const proxyPortInput = document.getElementById('proxy-port-input');
  const proxyUserInput = document.getElementById('proxy-user-input');
  const proxyPassInput = document.getElementById('proxy-pass-input');
  const proxyTogglePassBtn = document.getElementById('proxy-toggle-pass-btn');
  const proxyEyeIcon = document.getElementById('proxy-eye-icon');
  const proxyCustomUrlInput = document.getElementById('proxy-custom-url-input');
  const proxyUrlPreview = document.getElementById('proxy-url-preview');
  const testProxyBtn = document.getElementById('test-proxy-btn');
  const proxyTestBadge = document.getElementById('proxy-test-status-badge');

  function updateProxyFieldsState() {
    const enabled = !!proxyEnableCb?.checked;
    if (proxyConfigFields) {
      proxyConfigFields.style.opacity = enabled ? '1' : '0.45';
      proxyConfigFields.style.pointerEvents = enabled ? 'auto' : 'none';
    }
  }

  function updateProxyPreview() {
    if (!proxyUrlPreview) return;
    const custom = proxyCustomUrlInput?.value.trim();
    if (custom) {
      proxyUrlPreview.textContent = custom;
      return;
    }
    const type = proxyTypeSelect?.value || 'socks5';
    const host = proxyHostInput?.value.trim();
    const port = proxyPortInput?.value.trim() || '1080';
    const user = proxyUserInput?.value.trim();
    const pass = proxyPassInput?.value;

    if (!host) {
      proxyUrlPreview.textContent = 'Non configuré';
      return;
    }

    let auth = '';
    if (user) {
      auth = `${encodeURIComponent(user)}${pass ? ':••••••' : ''}@`;
    }
    proxyUrlPreview.textContent = `${type}://${auth}${host}:${port}`;
  }

  if (proxyEnableCb) {
    proxyEnableCb.addEventListener('change', updateProxyFieldsState);
    updateProxyFieldsState();
  }

  [proxyTypeSelect, proxyHostInput, proxyPortInput, proxyUserInput, proxyPassInput, proxyCustomUrlInput].forEach(el => {
    el?.addEventListener('input', updateProxyPreview);
    el?.addEventListener('change', updateProxyPreview);
  });

  if (proxyTogglePassBtn && proxyPassInput) {
    proxyTogglePassBtn.addEventListener('click', () => {
      const isPass = proxyPassInput.type === 'password';
      proxyPassInput.type = isPass ? 'text' : 'password';
      if (proxyEyeIcon) {
        proxyEyeIcon.innerHTML = isPass
          ? '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>'
          : '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
      }
    });
  }

  // Initialisation des données proxy
  fetch('/api/proxy/settings')
    .then(r => r.json())
    .then(p => {
      if (p) {
        if (proxyEnableCb) proxyEnableCb.checked = !!p.enabled;
        if (proxyTypeSelect && p.proxy_type) proxyTypeSelect.value = p.proxy_type;
        if (proxyHostInput) proxyHostInput.value = p.host || '';
        if (proxyPortInput) proxyPortInput.value = p.port || 1080;
        if (proxyUserInput) proxyUserInput.value = p.username || '';
        if (proxyPassInput) proxyPassInput.value = p.password || '';
        if (proxyCustomUrlInput) proxyCustomUrlInput.value = p.custom_url || '';
        updateProxyFieldsState();
        updateProxyPreview();
      }
    })
    .catch(() => {});

  // Test de connexion proxy
  if (testProxyBtn) {
    testProxyBtn.addEventListener('click', async () => {
      if (proxyTestBadge) {
        proxyTestBadge.style.display = 'inline-flex';
        proxyTestBadge.className = 'status-badge';
        proxyTestBadge.innerHTML = '<span class="spinner-sm" style="display:inline-block;width:12px;height:12px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;animation:spin 0.8s linear infinite;"></span> Test en cours...';
      }
      testProxyBtn.disabled = true;

      // Construction de l'URL candidate pour le test
      let testUrl = proxyCustomUrlInput?.value.trim() || '';
      if (!testUrl && proxyHostInput?.value.trim()) {
        const type = proxyTypeSelect?.value || 'socks5';
        const host = proxyHostInput.value.trim();
        const port = proxyPortInput?.value.trim() || '1080';
        const user = proxyUserInput?.value.trim() || '';
        const pass = proxyPassInput?.value || '';
        let auth = '';
        if (user) {
          auth = `${encodeURIComponent(user)}${pass ? ':' + encodeURIComponent(pass) : ''}@`;
        }
        testUrl = `${type}://${auth}${host}:${port}`;
      }

      try {
        const res = await fetch('/api/proxy/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ proxyUrl: testUrl })
        });
        const result = await res.json();
        if (result.success) {
          if (proxyTestBadge) {
            proxyTestBadge.className = 'status-badge badge-ok';
            proxyTestBadge.textContent = `✓ Opérationnel (IP: ${result.ip || 'OK'} - ${result.latency_ms || 0} ms)`;
          }
          showToast(`Proxy opérationnel ! IP : ${result.ip || 'inconnue'} (${result.latency_ms || 0} ms)`, 'success');
        } else {
          if (proxyTestBadge) {
            proxyTestBadge.className = 'status-badge badge-err';
            proxyTestBadge.textContent = `✗ Échec : ${result.error || 'Connexion impossible'}`;
          }
          showToast(result.error || 'Échec du test proxy', 'error');
        }
      } catch (err) {
        if (proxyTestBadge) {
          proxyTestBadge.className = 'status-badge badge-err';
          proxyTestBadge.textContent = `✗ Erreur réseau : ${err.message}`;
        }
        showToast(`Erreur réseau: ${err.message}`, 'error');
      } finally {
        testProxyBtn.disabled = false;
      }
    });
  }

  // Charger les paramètres de chaque source (natives & extensions importées)
  fetch('/api/sources/settings')
    .then(r => r.json())
    .then(data => {
      if (data && data.sources) {
        const va = data.sources.find(s => s.id === 'voir-anime');
        if (va && va.settings) {
          const qStratSelect = document.getElementById('voiranime-quality-strategy-select');
          if (qStratSelect && va.settings.quality_strategy) {
            qStratSelect.value = va.settings.quality_strategy;
          }
          const srvSelect = document.getElementById('voiranime-server-select');
          if (srvSelect && va.settings.default_server && va.settings.default_server !== 'auto') {
            srvSelect.value = va.settings.default_server;
          }
        }

        const imported = data.sources.filter(s => s.type === 'imported');
        const countBadge = document.getElementById('imported-sources-count');
        if (countBadge) countBadge.textContent = imported.length;

        const importedContainer = document.getElementById('imported-extensions-list');
        if (importedContainer) {
          if (imported.length === 0) {
            importedContainer.innerHTML = `
              <div class="source-empty-settings">
                <svg class="source-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
                <div style="font-weight: 600; color: var(--text); margin-top: 10px;">Aucune extension Aniyomi installée</div>
                <p>Vous pouvez importer et activer des extensions depuis l'onglet <a href="/extensions" style="color: var(--accent); text-decoration: underline;">Extensions</a>.</p>
              </div>`;
          } else {
            importedContainer.innerHTML = `
              <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px;">
                ${imported.map(ext => `
                  <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; display: flex; align-items: center; justify-content: space-between;">
                    <div style="display: flex; align-items: center; gap: 12px; min-width: 0;">
                      ${ext.icon ? `<img src="${ext.icon}" style="width: 32px; height: 32px; border-radius: 6px; object-fit: contain; flex-shrink: 0;" onerror="this.style.display='none'"/>` : `<div style="width: 32px; height: 32px; border-radius: 6px; background: rgba(139, 92, 246, 0.15); display: flex; align-items: center; justify-content: center; color: var(--accent); font-weight: 700; font-size: 0.8rem; flex-shrink: 0;">${ext.name.slice(0, 2).toUpperCase()}</div>`}
                      <div style="min-width: 0;">
                        <div style="font-weight: 600; font-size: 0.9rem; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${ext.name}</div>
                        <div style="font-size: 0.74rem; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${ext.id}</div>
                      </div>
                    </div>
                    <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex-shrink: 0;">
                      <span class="badge" style="font-size: 0.68rem; padding: 2px 6px; border-radius: 4px; background: ${ext.isEnabled ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255, 255, 255, 0.08)'}; color: ${ext.isEnabled ? '#34d399' : 'var(--muted)'};">${ext.isEnabled ? 'Active' : 'Inactive'}</span>
                      <span style="font-size: 0.72rem; color: var(--muted);">v${ext.version || '1.0'} (${ext.lang.toUpperCase()})</span>
                    </div>
                  </div>
                `).join('')}
              </div>
              <div style="margin-top: 14px; font-size: 0.8rem; color: var(--muted); text-align: center;">
                Ces sources utilisent les paramètres généraux d'AnimeLab. Aucun réglage supplémentaire requis.
              </div>`;
          }
        }
      }
    })
    .catch(() => {});

  save?.addEventListener('click', async () => {
    const maxConcurrent = parseInt(document.getElementById('max-concurrent-input')?.value || '3', 10);
    const speedKb = parseInt(document.getElementById('global-speed-input-settings')?.value || '0', 10);
    const plexOrganization = !!document.getElementById('plex-org-cb')?.checked;
    const voiranimeDefaultServer = document.getElementById('voiranime-server-select')?.value || 'auto';
    const voiranimeQualityStrategy = document.getElementById('voiranime-quality-strategy-select')?.value || 'highest';
    let selectedUserAgent = uaSelect?.value || 'Random (Rotator)';

    if (selectedUserAgent === 'Custom') {
      selectedUserAgent = customUaInput?.value.trim() || '';
      if (!selectedUserAgent) {
        showToast('Veuillez saisir un User-Agent personnalise', 'error');
        return;
      }
    }

    const body = {
      maxConcurrentDownloads: maxConcurrent,
      globalSpeedLimit: speedKb * 1024,
      plexOrganization,
      selectedUserAgent,
      voiranimeDefaultServer,
    };

    const proxyPayload = {
      enabled: !!document.getElementById('proxy-enable-cb')?.checked,
      proxy_type: document.getElementById('proxy-type-select')?.value || 'socks5',
      host: document.getElementById('proxy-host-input')?.value.trim() || '',
      port: parseInt(document.getElementById('proxy-port-input')?.value || '1080', 10),
      username: document.getElementById('proxy-user-input')?.value.trim() || '',
      password: document.getElementById('proxy-pass-input')?.value || '',
      custom_url: document.getElementById('proxy-custom-url-input')?.value.trim() || '',
    };

    try {
      const [respGlobal, respSource, respProxy] = await Promise.all([
        fetch('/api/download/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        }),
        fetch('/api/sources/settings/voir-anime', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            quality_strategy: voiranimeQualityStrategy,
            default_server: voiranimeDefaultServer
          })
        }),
        fetch('/api/proxy/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(proxyPayload)
        })
      ]);

      const data = await respGlobal.json();
      if (data.success) {
        showToast('Paramètres enregistrés avec succès', 'success');
      } else {
        showToast(data.error || 'Erreur lors de la mise à jour', 'error');
      }
    } catch (error) {
      showToast('Erreur de connexion', 'error');
    }
  });
}

function setSpeedLimitPreset(kb) {
  const input = document.getElementById('global-speed-input-settings');
  if (input) {
    input.value = kb > 0 ? kb : '';
    document.querySelectorAll('.speed-preset-chip').forEach(chip => {
      chip.classList.toggle('active', chip.getAttribute('data-kb') == String(kb));
    });
  }
}
window.setSpeedLimitPreset = setSpeedLimitPreset;

const episodeSizeCache = new Map();
let activeSizeFetches = 0;
const sizeFetchQueue = [];

function processSizeFetchQueue() {
  const MAX_CONCURRENT_SIZE_FETCHES = 4;
  while (activeSizeFetches < MAX_CONCURRENT_SIZE_FETCHES && sizeFetchQueue.length > 0) {
    const { span, url, server, quality } = sizeFetchQueue.shift();
    const cacheKey = `${url}::${server || ''}::${quality || ''}`;
    if (episodeSizeCache.has(cacheKey)) {
      applySizeData(span, episodeSizeCache.get(cacheKey));
      continue;
    }

    activeSizeFetches++;
    let fetchUrl = '/api/episode/size?url=' + encodeURIComponent(url);
    if (server && server !== 'auto') fetchUrl += '&server=' + encodeURIComponent(server);
    if (quality && quality !== 'auto') fetchUrl += '&quality=' + encodeURIComponent(quality);

    fetch(fetchUrl)
      .then(r => r.json())
      .then(data => {
        episodeSizeCache.set(cacheKey, data);
        applySizeData(span, data);
      })
      .catch(() => {
        span.textContent = '-';
      })
      .finally(() => {
        activeSizeFetches--;
        processSizeFetchQueue();
      });
  }
}

function applySizeData(span, data) {
  if (!span) return;
  span.textContent = data && data.success ? data.formattedSize : '-';
  const row = span.closest('.episode-item');
  if (data && data.success && data.subtitleUrl && row) {
    const sub = row.querySelector('.subtitle-cb-label');
    if (sub) sub.classList.add('is-available');
    if (!row.dataset.subtitle) row.dataset.subtitle = data.subtitleUrl;
  }
  if (row && data && data.success) {
    if (data.currentServer) {
      row.dataset.detectedServer = data.currentServer;
      if (!row.dataset.server || row.dataset.server === 'auto') {
        row.dataset.server = data.currentServer;
      }
    }
    if (data.qualitiesSizes) {
      row.dataset.qualitiesSizes = JSON.stringify(data.qualitiesSizes);
    }
    if (data.subtitles && data.subtitles.length > 0) {
      row.dataset.subtitles = JSON.stringify(data.subtitles);
      const subBtn = row.querySelector('.btn-sub-tracks');
      if (subBtn && data.subtitles.length > 1) {
        subBtn.style.display = 'inline-flex';
      }
    }

    const qSelect = row.querySelector('.episode-quality-select');
    if (qSelect && data.qualities && data.qualities.length > 0) {
      qSelect.innerHTML = '';
      const batchQ = document.getElementById('batch-quality-select')?.value;
      const targetQuality = (batchQ && batchQ !== 'auto' ? batchQ : (row.dataset.quality || data.currentQuality || ''));
      let selectedIdx = 0;
      let bestDist = Infinity;
      const targetNumM = targetQuality ? targetQuality.match(/(\d{3,4})/) : null;
      const targetNum = targetNumM ? parseInt(targetNumM[1], 10) : 0;

      data.qualities.forEach((q, idx) => {
        const opt = document.createElement('option');
        opt.value = q;
        opt.textContent = q;
        qSelect.appendChild(opt);

        if (targetQuality && (q.toLowerCase() === targetQuality.toLowerCase() || q.toLowerCase().includes(targetQuality.toLowerCase()))) {
          selectedIdx = idx;
          bestDist = 0;
        } else if (bestDist > 0 && targetNum > 0) {
          const qNumM = q.match(/(\d{3,4})/);
          if (qNumM) {
            const dist = Math.abs(parseInt(qNumM[1], 10) - targetNum);
            if (dist < bestDist) {
              bestDist = dist;
              selectedIdx = idx;
            }
          }
        }
      });
      qSelect.selectedIndex = selectedIdx;
      row.dataset.quality = qSelect.value;
      qSelect.style.display = 'inline-block';
    } else if (data.currentQuality && !row.dataset.quality) {
      row.dataset.quality = data.currentQuality;
    }
  }
}

async function onEpisodeQualityChange(selectEl) {
  const row = selectEl.closest('.episode-item');
  if (!row) return;
  const url = row.dataset.url;
  const quality = selectEl.value;
  const server = row.dataset.server || document.getElementById('batch-server-select')?.value || '';
  row.dataset.quality = quality;
  const span = row.querySelector('.episode-size');

  // Vérifier si la taille est déjà connue localement dans qualitiesSizes
  if (row.dataset.qualitiesSizes) {
    try {
      const qSizes = JSON.parse(row.dataset.qualitiesSizes);
      if (qSizes[quality]) {
        if (span) span.textContent = qSizes[quality];
        return;
      }
      for (const [k, v] of Object.entries(qSizes)) {
        if (k.toLowerCase().includes(quality.toLowerCase()) || quality.toLowerCase().includes(k.toLowerCase())) {
          if (span) span.textContent = v;
          return;
        }
      }
    } catch (e) {}
  }

  if (span) span.textContent = '...';
  try {
    const qParam = encodeURIComponent(quality);
    const sParam = server && server !== 'auto' ? `&server=${encodeURIComponent(server)}` : '';
    const resp = await fetch(`/api/episode/size?url=${encodeURIComponent(url)}&quality=${qParam}${sParam}`);
    const data = await resp.json();
    if (data.success && span) {
      span.textContent = data.formattedSize;
      if (data.qualitiesSizes) {
        row.dataset.qualitiesSizes = JSON.stringify(data.qualitiesSizes);
      }
    }
  } catch (e) {
    if (span) span.textContent = '-';
  }
}

function onBatchServerChange(server) {
  // Réinitialiser la file d'attente pour éviter les requêtes obsolètes
  sizeFetchQueue.length = 0;
  document.querySelectorAll('.episode-item').forEach(row => {
    row.dataset.server = server;
    delete row.dataset.qualitiesSizes;
    const span = row.querySelector('.episode-size');
    const url = row.dataset.url;
    if (span && url) {
      span.textContent = '...';
      sizeFetchQueue.push({
        span,
        url,
        server: server && server !== 'auto' ? server : '',
        quality: row.dataset.quality || ''
      });
    }
  });
  processSizeFetchQueue();
}

function onBatchQualityChange(quality) {
  document.querySelectorAll('.episode-item').forEach(row => {
    row.dataset.quality = quality;
    const qSelect = row.querySelector('.episode-quality-select');
    if (qSelect && quality !== 'auto') {
      let matched = false;
      for (let i = 0; i < qSelect.options.length; i++) {
        if (qSelect.options[i].value.toLowerCase().includes(quality.toLowerCase())) {
          qSelect.selectedIndex = i;
          matched = true;
          break;
        }
      }
      if (!matched) {
        const targetM = quality.match(/(\d{3,4})/);
        if (targetM) {
          const targetNum = parseInt(targetM[1], 10);
          let bestIdx = -1;
          let bestDist = Infinity;
          for (let i = 0; i < qSelect.options.length; i++) {
            const optM = qSelect.options[i].value.match(/(\d{3,4})/);
            if (optM) {
              const optNum = parseInt(optM[1], 10);
              const dist = Math.abs(optNum - targetNum);
              if (dist < bestDist) {
                bestDist = dist;
                bestIdx = i;
              }
            }
          }
          if (bestIdx >= 0) {
            qSelect.selectedIndex = bestIdx;
          }
        }
      }
      row.dataset.quality = qSelect.value;
    }
    const span = row.querySelector('.episode-size');
    const url = row.dataset.url;
    if (span && url && quality !== 'auto') {
      // Vérifier si la taille est déjà connue localement
      if (row.dataset.qualitiesSizes) {
        try {
          const qSizes = JSON.parse(row.dataset.qualitiesSizes);
          const chosen = qSelect ? qSelect.value : quality;
          if (qSizes[chosen]) {
            span.textContent = qSizes[chosen];
            return;
          }
          let found = false;
          for (const [k, v] of Object.entries(qSizes)) {
            if (k.toLowerCase().includes(quality.toLowerCase()) || quality.toLowerCase().includes(k.toLowerCase())) {
              span.textContent = v;
              found = true;
              break;
            }
          }
          if (found) return;
        } catch (e) {}
      }

      span.textContent = '...';
      const server = row.dataset.server || document.getElementById('batch-server-select')?.value || '';
      sizeFetchQueue.push({
        span,
        url,
        server: server && server !== 'auto' ? server : '',
        quality
      });
    }
  });
  processSizeFetchQueue();
}

function loadEpisodeSizes() {
  const nodes = document.querySelectorAll('.episode-size[data-url]');
  if (!nodes.length) return;

  const batchServerSel = document.getElementById('batch-server-select');
  if (batchServerSel) {
    fetch('/api/download/settings')
      .then(r => r.json())
      .then(s => {
        if (s.voiranimeDefaultServer && s.voiranimeDefaultServer !== 'auto') {
          batchServerSel.value = s.voiranimeDefaultServer;
        }
      })
      .catch(() => {});
  }

  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (!entry.isIntersecting) return;
      const span = entry.target;
      observer.unobserve(span);
      const url = span.dataset.url;
      if (!url) return;

      const server = batchServerSel?.value || '';
      const quality = document.getElementById('batch-quality-select')?.value || '';
      const cacheKey = `${url}::${server || ''}::${quality || ''}`;
      if (episodeSizeCache.has(cacheKey)) {
        applySizeData(span, episodeSizeCache.get(cacheKey));
        return;
      }

      sizeFetchQueue.push({ span, url, server, quality });
      processSizeFetchQueue();
    });
  }, { rootMargin: '40px' });

  nodes.forEach(node => observer.observe(node));
}

function buildVersionFilters() {
  const filterContainer = document.getElementById('version-filter');
  if (!filterContainer) return;

  const items = [...document.querySelectorAll('.episode-item')];
  const versions = [...new Set(items.map(item => item.dataset.version).filter(Boolean))];
  if (versions.length <= 1) return;

  filterContainer.appendChild(createFilterBtn('Tous', true, () => filterEpisodes('ALL')));
  versions.forEach(version => {
    filterContainer.appendChild(createFilterBtn(version, false, () => filterEpisodes(version)));
  });
}

function createFilterBtn(label, active, onClick) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ver-filter-btn' + (active ? ' active' : '');
  btn.textContent = label;
  btn.addEventListener('click', () => {
    document.querySelectorAll('.ver-filter-btn').forEach(item => item.classList.remove('active'));
    btn.classList.add('active');
    onClick();
  });
  return btn;
}

function filterEpisodes(version) {
  document.querySelectorAll('.episode-item').forEach(item => {
    item.style.display = version === 'ALL' || item.dataset.version === version ? '' : 'none';
  });
}

function onEpisodeCheckChange() {
  const checked = document.querySelectorAll('.episode-check:checked');
  const btn = document.getElementById('dl-selected-btn');
  const info = document.getElementById('selected-count-text');
  if (btn && !btn.classList.contains('is-loading')) btn.disabled = checked.length === 0;
  if (info) info.textContent = checked.length + ' sélectionné(s)';
}

function toggleSelectAll(checkbox) {
  document.querySelectorAll('.episode-check').forEach(cb => {
    const row = cb.closest('.episode-item');
    if (!row || row.style.display === 'none') return;
    cb.checked = checkbox.checked;
  });
  onEpisodeCheckChange();
}

async function downloadEpisode(btn) {
  const url = btn.dataset.url;
  const epNum = parseInt(btn.dataset.num, 10);
  const subtitleUrl = btn.dataset.subtitle || '';
  const row = btn.closest('.episode-item');
  const downloadSubtitles = row?.querySelector('.subtitle-check')?.checked || false;
  const animeName = typeof ANIME_NAME !== 'undefined' ? ANIME_NAME : 'Anime';
  const source = typeof SOURCE !== 'undefined' ? SOURCE : 'french-manga';
  const fileName = sanitizeFilename(animeName + ' - Episode ' + epNum + '.mp4');

  const batchServer = document.getElementById('batch-server-select')?.value;
  const selectedServer = (batchServer && batchServer !== 'auto' ? batchServer : null) || row?.dataset.server || null;
  const rowQualitySelect = row?.querySelector('.episode-quality-select');
  const selectedQuality = (rowQualitySelect && rowQualitySelect.style.display !== 'none' ? rowQualitySelect.value : '') || row?.dataset.quality || document.getElementById('batch-quality-select')?.value || null;

  if (source === 'voir-anime' && (!selectedQuality || selectedQuality === 'auto') && (!rowQualitySelect || rowQualitySelect.style.display === 'none')) {
    await handleVoirAnimeDownload(url, animeName, epNum, fileName, subtitleUrl, downloadSubtitles, null, selectedServer, selectedQuality);
    return;
  }

  btn.disabled = true;
  const origContent = btn.innerHTML;
  btn.innerHTML = '<span class="spinner-sm"></span>';
  try {
    await startDownloadRequest(animeName, epNum, url, fileName, subtitleUrl, null, 0, downloadSubtitles, selectedServer, selectedQuality, source);
  } finally {
    setTimeout(() => {
      btn.disabled = false;
      btn.innerHTML = origContent;
    }, 1200);
  }
}

async function handleVoirAnimeDownload(episodeUrl, animeName, epNum, fileName, subtitleUrl, downloadSubtitles, scheduledTime, preferredServer, preferredQuality) {
  showToast('Résolution des qualités disponibles...', 'info');
  try {
    let qUrl = '/api/voiranime/download-info?episodeUrl=' + encodeURIComponent(episodeUrl);
    if (preferredServer && preferredServer !== 'auto') {
      qUrl += '&server=' + encodeURIComponent(preferredServer);
    }
    if (preferredQuality && preferredQuality !== 'auto') {
      qUrl += '&quality=' + encodeURIComponent(preferredQuality);
    }
    const resp = await fetch(qUrl);
    const info = await resp.json();
    let qualities = {};
    try { qualities = JSON.parse(info.videoQualities || '{}'); } catch (error) {}

    if (preferredQuality && preferredQuality !== 'auto' && info.videoUrl) {
      await startDownloadRequest(animeName, epNum, info.videoUrl || episodeUrl, fileName, subtitleUrl, scheduledTime, 0, downloadSubtitles, info.serverType, info.selectedQuality || preferredQuality);
    } else if (Object.keys(qualities).length > 1) {
      showQualityModal(qualities, animeName, epNum, fileName, subtitleUrl, downloadSubtitles, scheduledTime, info.videoChunks, info.serverType);
    } else {
      await startDownloadRequest(animeName, epNum, info.videoUrl || episodeUrl, fileName, subtitleUrl, scheduledTime, 0, downloadSubtitles, info.serverType, info.selectedQuality);
    }
  } catch (error) {
    showToast('Erreur de résolution: ' + error.message, 'error');
  }
}

function showQualityModal(qualities, animeName, epNum, fileName, subtitleUrl, downloadSubtitles, scheduledTime, chunksJson, serverType) {
  const modal = document.getElementById('quality-modal');
  const list = document.getElementById('quality-list');
  if (!modal || !list) return;

  list.innerHTML = '';
  Object.entries(qualities).forEach(([label, url]) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'quality-item';
    item.innerHTML = `<span class="quality-label">${escapeHtml(label)}</span><span class="quality-download">Télécharger</span>`;
    item.addEventListener('click', async () => {
      modal.style.display = 'none';
      await startDownloadRequest(animeName, epNum, url, label + ' - ' + fileName, subtitleUrl, scheduledTime, 0, downloadSubtitles, serverType, label);
    });
    list.appendChild(item);
  });

  if (chunksJson && chunksJson !== '[]') {
    try {
      const chunks = JSON.parse(chunksJson);
      if (chunks.length > 1) {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'quality-item';
        item.innerHTML = `<span class="quality-label">Tous les morceaux (${chunks.length})</span><span class="quality-download">Concaténer</span>`;
        item.addEventListener('click', async () => {
          modal.style.display = 'none';
          await startDownloadRequest(animeName, epNum, chunks[0], fileName, subtitleUrl, scheduledTime, 0, downloadSubtitles, serverType, 'Chunks');
        });
        list.appendChild(item);
      }
    } catch (error) {}
  }

  modal.style.display = 'flex';
}

function showSubtitleChoiceModal(btn) {
  const row = btn.closest('.episode-item');
  if (!row) return;
  const modal = document.getElementById('subtitle-modal');
  const list = document.getElementById('subtitle-list');
  if (!modal || !list) return;

  list.innerHTML = '';
  let subtitles = [];
  try {
    subtitles = JSON.parse(row.dataset.subtitles || '[]');
  } catch (e) {}

  if (subtitles.length === 0 && row.dataset.subtitle) {
    subtitles = [{ label: 'Piste par défaut', url: row.dataset.subtitle, srclang: 'fr' }];
  }

  if (subtitles.length === 0) {
    list.innerHTML = '<p style="color:var(--muted);padding:14px;text-align:center;">Aucune piste alternative de sous-titres trouvée.</p>';
  } else {
    subtitles.forEach((sub, idx) => {
      const btnItem = document.createElement('button');
      btnItem.type = 'button';
      btnItem.className = 'quality-item';
      const isSelected = row.dataset.subtitle === sub.url || (idx === 0 && !row.dataset.subtitle);
      btnItem.innerHTML = `<span class="quality-label">${escapeHtml(sub.label || sub.srclang || ('Piste ' + (idx + 1)))}</span><span class="quality-download">${isSelected ? '✓ Actif' : 'Sélectionner'}</span>`;
      btnItem.onclick = () => {
        row.dataset.subtitle = sub.url;
        const cb = row.querySelector('.subtitle-check');
        if (cb) cb.checked = true;
        const chip = row.querySelector('.ep-sub-chip');
        if (chip) syncEpisodeSubtitleChip(chip, true, `✓ ${sub.label || sub.srclang || 'Sous-titres'}`);
        modal.style.display = 'none';
        showToast(`Sous-titre sélectionné : ${sub.label || sub.srclang || 'Piste'}`, 'success');
      };
      list.appendChild(btnItem);
    });
  }

  modal.style.display = 'flex';
}

function syncEpisodeSubtitleChip(btn, isChecked, customLabel) {
  if (!btn) return;
  btn.classList.toggle('active', isChecked);
  const labelEl = btn.querySelector('.ep-sub-label');
  if (labelEl) {
    labelEl.textContent = isChecked ? (customLabel || '✓ Sous-titres') : 'Sous-titres';
  }
}

function toggleEpisodeSubtitle(btn, event) {
  if (event) event.stopPropagation();
  const row = btn.closest('.episode-item');
  if (!row) return;
  const cb = row.querySelector('.subtitle-check');
  if (!cb) return;
  cb.checked = !cb.checked;
  syncEpisodeSubtitleChip(btn, cb.checked);
}

function toggleBatchSubtitles(checked) {
  document.querySelectorAll('.episode-item').forEach(row => {
    if (row.style.display === 'none') return;
    const cb = row.querySelector('.subtitle-check');
    if (cb) {
      cb.checked = checked;
      const chip = row.querySelector('.ep-sub-chip');
      if (chip) syncEpisodeSubtitleChip(chip, checked);
    }
  });
}

async function startDownloadRequest(animeName, episodeNumber, url, fileName, subtitleUrl, scheduledTime, speedLimit, downloadSubtitles, selectedServer, selectedQuality, source) {
  const currentSource = source || (typeof SOURCE !== 'undefined' ? SOURCE : 'french-manga');
  const body = { animeName, episodeNumber, url, fileName, downloadSubtitles, source: currentSource };
  if (subtitleUrl) body.subtitleUrl = subtitleUrl;
  if (scheduledTime) body.scheduledTime = scheduledTime;
  if (speedLimit) body.speedLimit = String(speedLimit);
  if (selectedServer && selectedServer !== 'auto') body.selectedServer = selectedServer;
  if (selectedQuality && selectedQuality !== 'auto') body.selectedQuality = selectedQuality;

  try {
    const resp = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await resp.json();
    if (data.success) {
      showToast((data.message || 'Téléchargement lancé !') + ' <a href="/downloads" class="toast-link">Voir la file</a>', 'success');
      refreshDownloadBadge();
      window.location.href = '/downloads';

      // Update episode row badge if on anime-detail page
      const row = document.querySelector(`.episode-item[data-num="${episodeNumber}"]`);
      if (row && !row.querySelector('.ep-queued-badge') && !row.querySelector('.ep-done-badge')) {
        const badge = document.createElement('span');
        badge.className = 'ep-queued-badge';
        badge.textContent = 'En file d\'attente';
        const titleEl = row.querySelector('.episode-title');
        if (titleEl) {
          titleEl.after(badge);
        } else {
          row.appendChild(badge);
        }
      }
    } else {
      showToast(data.error || 'Erreur de téléchargement', 'error');
    }
  } catch (err) {
    showToast('Erreur de connexion au serveur : ' + (err.message || err), 'error');
  }
}

async function downloadSelected() {
  const checked = [...document.querySelectorAll('.episode-check:checked')];
  if (!checked.length) return;

  const btn = document.getElementById('dl-selected-btn');
  const origBtnContent = btn ? btn.innerHTML : null;
  if (btn) {
    btn.classList.add('is-loading');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-sm"></span> <span>Lancement en cours...</span>';
  }

  const animeName = typeof ANIME_NAME !== 'undefined' ? ANIME_NAME : 'Anime';
  const source = typeof SOURCE !== 'undefined' ? SOURCE : 'french-manga';
  const scheduledTime = document.getElementById('schedule-input')?.value || '';
  const batchServer = document.getElementById('batch-server-select')?.value || null;
  const batchQuality = document.getElementById('batch-quality-select')?.value || null;

  const episodes = checked.map(cb => {
    const row = cb.closest('.episode-item');
    const num = parseInt(row.dataset.num, 10);
    const epServer = (batchServer && batchServer !== 'auto' ? batchServer : null) || row.dataset.server;
    const rowQ = row.querySelector('.episode-quality-select');
    const epQuality = (rowQ && rowQ.style.display !== 'none' ? rowQ.value : '') || row.dataset.quality || (batchQuality && batchQuality !== 'auto' ? batchQuality : null);
    return {
      number: String(num),
      url: row.dataset.url,
      fileName: sanitizeFilename(animeName + ' - Episode ' + num + '.mp4'),
      subtitleUrl: row.dataset.subtitle || '',
      downloadSubtitles: String(row.querySelector('.subtitle-check')?.checked || false),
      scheduledTime,
      selectedServer: epServer && epServer !== 'auto' ? epServer : null,
      selectedQuality: epQuality && epQuality !== 'auto' ? epQuality : null,
      source: row.dataset.source || source
    };
  });

  try {
    if (source === 'voir-anime' && episodes.length === 1) {
      await handleVoirAnimeDownload(
        episodes[0].url,
        animeName,
        parseInt(episodes[0].number, 10),
        episodes[0].fileName,
        episodes[0].subtitleUrl,
        episodes[0].downloadSubtitles === 'true',
        scheduledTime || null,
        episodes[0].selectedServer,
        episodes[0].selectedQuality
      );
      refreshDownloadBadge();
      return;
    }

    const resp = await fetch('/api/download/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ animeName, source, episodes })
    });
    const data = await resp.json();
    if (data.success) {
      showToast(`${episodes.length} épisode(s) ajouté(s) aux téléchargements ! <a href="/downloads" class="toast-link">Voir la file</a>`, 'success');
      window.location.href = '/downloads';

      // Mark rows with queued badge
      checked.forEach(cb => {
        const row = cb.closest('.episode-item');
        if (row && !row.querySelector('.ep-queued-badge') && !row.querySelector('.ep-done-badge')) {
          const badge = document.createElement('span');
          badge.className = 'ep-queued-badge';
          badge.textContent = 'En file d\'attente';
          const titleEl = row.querySelector('.episode-title');
          if (titleEl) {
            titleEl.after(badge);
          } else {
            row.appendChild(badge);
          }
        }
        cb.checked = false;
      });

      const selectAll = document.getElementById('select-all-cb');
      if (selectAll) selectAll.checked = false;
      refreshDownloadBadge();
    } else {
      showToast(data.error || 'Erreur lors du téléchargement par lot', 'error');
    }
  } catch (err) {
    showToast('Erreur de connexion au serveur : ' + (err.message || err), 'error');
  } finally {
    if (btn) {
      btn.classList.remove('is-loading');
      if (origBtnContent) btn.innerHTML = origBtnContent;
      btn.disabled = false;
    }
    onEpisodeCheckChange();
  }
}

async function playEpisode(btn) {
  const url = btn.dataset.url;
  const epNum = btn.dataset.num;
  const source = typeof SOURCE !== 'undefined' ? SOURCE : 'french-manga';
  const animeName = typeof ANIME_NAME !== 'undefined' ? ANIME_NAME : '';
  const animeUrl = typeof ANIME_URL !== 'undefined' ? ANIME_URL : '';
  const row = btn.closest('.episode-item');
  const version = row?.dataset.version || '';
  const batchServer = document.getElementById('batch-server-select')?.value || '';
  const server = (batchServer && batchServer !== 'auto' ? batchServer : '') || row?.dataset.server || '';
  const rowQualitySelect = row?.querySelector('.episode-quality-select');
  const quality = (rowQualitySelect && rowQualitySelect.style.display !== 'none' ? rowQualitySelect.value : '') || row?.dataset.quality || document.getElementById('batch-quality-select')?.value || '';

  // Annuler toute requête de lecture précédente
  if (currentPlayAbortController) {
    try { currentPlayAbortController.abort(); } catch (e) {}
  }
  const thisRequestId = ++currentPlayRequestId;
  currentPlayAbortController = new AbortController();

  // État visuel de chargement sur le bouton
  const origBtnContent = btn.innerHTML;
  btn.classList.add('is-loading');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-sm"></span>';

  showToast('Résolution du flux vidéo...', 'info');
  try {
    const params = new URLSearchParams({
      animeName,
      animeUrl,
      episodeUrl: url,
      episodeNumber: epNum,
      version,
      source
    });
    if (server && server !== 'auto') params.set('server', server);
    if (quality && quality !== 'auto') params.set('quality', quality);

    const resp = await fetch(`/api/media/stream/resolve?${params.toString()}`, {
      signal: currentPlayAbortController.signal
    });
    let data;
    try {
      data = await resp.json();
    } catch (parseErr) {
      data = { success: false, error: 'Source momentanément indisponible sur ce serveur' };
    }

    // Si une nouvelle requête a été émise ou si l'utilisateur a annulé
    if (thisRequestId !== currentPlayRequestId) return;

    if (!resp.ok || !data.success) {
      handlePlayStreamError(btn, server);
      return;
    }

    const videoUrl = data.streamUrl;
    const tracks = data.subtitles || [];
    const isDownloaded = Boolean(data.isDownloaded);

    // Mettre à jour visuellement la ligne et le bouton
    if (row && isDownloaded) {
      row.classList.add('ep-downloaded');
      row.dataset.downloaded = 'true';
      btn.classList.add('btn-play-local');
      btn.classList.remove('btn-play-stream');
      btn.title = 'Lecture locale (Disque dur)';
    }

    if (isDownloaded) {
      showToast('Lecture locale depuis le disque dur', 'success');
    } else {
      const srvLabel = data.serverType && data.serverType !== 'unknown' ? data.serverType : 'En ligne';
      showToast(`Streaming direct depuis ${srvLabel}...`, 'info');
    }

    const sourceMeta = {
      isDownloaded,
      sourceType: data.sourceType,
      serverType: data.serverType,
      selectedQuality: data.selectedQuality,
      qualities: data.qualities,
      filePath: data.filePath
    };

    // Si la page ou l'onglet est masqué, ne pas démarrer la lecture en arrière-plan
    if (document.hidden) {
      console.warn("Onglet en arrière-plan : la lecture automatique est suspendue.");
      return;
    }

    const cinemaModal = document.getElementById('cinema-modal');
    if (cinemaModal) {
      openCinemaModal(videoUrl, `${animeName} - Épisode ${epNum}`, tracks, epNum, sourceMeta);
    } else {
      const playerSection = document.getElementById('player-section');
      const video = document.getElementById('plyr-player');
      if (playerSection && video) {
        video.innerHTML = `<source src="${videoUrl}" type="video/mp4"/>`;
        tracks.forEach(track => {
          const trackEl = document.createElement('track');
          trackEl.kind = 'subtitles';
          trackEl.label = track.label;
          trackEl.srclang = track.srclang;
          trackEl.src = track.src;
          if (track.default) trackEl.setAttribute('default', '');
          video.appendChild(trackEl);
        });
        video.load();
        playerSection.style.display = 'block';
        playerSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

        if (window.Plyr) {
          if (!plyrInstance) {
            plyrInstance = new Plyr('#plyr-player', {
              controls: ['play', 'progress', 'current-time', 'mute', 'volume', 'captions', 'settings', 'fullscreen'],
              captions: { active: true, update: true, language: 'fr' }
            });
          } else {
            plyrInstance.source = { type: 'video', sources: [{ src: videoUrl, type: 'video/mp4' }], tracks };
          }
          plyrInstance.play().catch(() => {});
        } else {
          video.play().catch(() => {});
        }
      }
    }

    if (animeUrl) {
      fetch('/api/progress/watched', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ animeUrl, animeName, episodeNumber: String(epNum), version })
      }).catch(() => {});
      row?.classList.add('ep-watched');
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      return; // Annulation normale
    }
    handlePlayStreamError(btn, server);
  } finally {
    if (thisRequestId === currentPlayRequestId) {
      btn.classList.remove('is-loading');
      btn.disabled = false;
      btn.innerHTML = origBtnContent;
    }
  }
}

function handlePlayStreamError(btn, currentServer) {
  const serverSelect = document.getElementById('batch-server-select');
  let nextServerVal = null;
  let nextServerLabel = 'un autre miroir';

  if (serverSelect) {
    const opts = Array.from(serverSelect.options).filter(opt => opt.value && opt.value !== 'auto' && opt.value !== currentServer);
    if (opts.length > 0) {
      nextServerVal = opts[0].value;
      nextServerLabel = opts[0].text;
    }
  }

  showToast(
    'Source momentanément indisponible sur ce serveur.',
    'error',
    nextServerVal ? {
      text: `Essayer ${nextServerLabel}`,
      onClick: () => {
        if (serverSelect) {
          serverSelect.value = nextServerVal;
          if (typeof onBatchServerChange === 'function') onBatchServerChange(nextServerVal);
        }
        const row = btn.closest('.episode-item');
        if (row) row.dataset.server = nextServerVal;
        playEpisode(btn);
      }
    } : null
  );
}

function toggleEpisodeTechMenu(btn, event) {
  if (event) event.stopPropagation();
  const popover = btn.parentElement?.querySelector('.ep-tech-popover');
  if (!popover) return;
  const isVisible = popover.style.display !== 'none';
  document.querySelectorAll('.ep-tech-popover').forEach(p => p.style.display = 'none');
  popover.style.display = isVisible ? 'none' : 'block';
}

document.addEventListener('click', (e) => {
  if (!e.target.closest('.ep-tech-options-wrap')) {
    document.querySelectorAll('.ep-tech-popover').forEach(p => p.style.display = 'none');
  }
});

function openCinemaModal(videoUrl, title, tracks = [], epNum = null, sourceMeta = null) {
  const modal = document.getElementById('cinema-modal');
  const video = document.getElementById('cinema-player');
  const titleEl = document.getElementById('cinema-title');
  const infoEl = document.getElementById('cinema-ep-info');
  const badgeEl = document.getElementById('cinema-source-badge');
  if (!modal || !video) return;

  if (titleEl && title) titleEl.textContent = title;
  if (infoEl && epNum) infoEl.textContent = `Épisode ${epNum}`;
  currentPlayingEpNum = epNum;

  // Mise à jour du badge de source
  if (badgeEl) {
    if (sourceMeta && sourceMeta.isDownloaded) {
      badgeEl.className = 'cinema-badge badge-local';
      badgeEl.innerHTML = '<svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg> Disque dur (Local)';
      badgeEl.style.display = 'inline-flex';
    } else if (sourceMeta && !sourceMeta.isDownloaded) {
      badgeEl.className = 'cinema-badge badge-remote';
      const srv = (sourceMeta.serverType && sourceMeta.serverType !== 'unknown') ? sourceMeta.serverType : 'En ligne';
      const q = sourceMeta.selectedQuality && sourceMeta.selectedQuality !== 'auto' ? ` • ${sourceMeta.selectedQuality}` : '';
      badgeEl.innerHTML = `<svg viewBox="0 0 24 24" style="width:12px;height:12px;fill:currentColor;"><path d="M5 3l14 9-14 9V3z"/></svg> Streaming (${srv}${q})`;
      badgeEl.style.display = 'inline-flex';
    } else {
      badgeEl.style.display = 'none';
    }
  }

  modal.classList.add('open');

  if (cinemaHlsInstance) {
    cinemaHlsInstance.destroy();
    cinemaHlsInstance = null;
  }

  const isHls = videoUrl.includes('.m3u8');
  if (isHls && window.Hls && Hls.isSupported()) {
    video.innerHTML = '';
    cinemaHlsInstance = new Hls({
      enableWorker: true,
      lowLatencyMode: true,
    });
    cinemaHlsInstance.loadSource(videoUrl);
    cinemaHlsInstance.attachMedia(video);
    cinemaHlsInstance.on(Hls.Events.ERROR, function(event, data) {
      if (data.fatal) {
        console.warn("HLS fatal error, trying recover:", data);
        switch (data.type) {
          case Hls.ErrorTypes.NETWORK_ERROR:
            cinemaHlsInstance.startLoad();
            break;
          case Hls.ErrorTypes.MEDIA_ERROR:
            cinemaHlsInstance.recoverMediaError();
            break;
          default:
            cinemaHlsInstance.destroy();
            break;
        }
      }
    });
  } else {
    video.innerHTML = `<source src="${videoUrl}" type="${isHls ? 'application/x-mpegURL' : 'video/mp4'}"/>`;
  }

  tracks.forEach(track => {
    const trackEl = document.createElement('track');
    trackEl.kind = 'subtitles';
    trackEl.label = track.label;
    trackEl.srclang = track.srclang;
    trackEl.src = track.src;
    if (track.default) trackEl.setAttribute('default', '');
    video.appendChild(trackEl);
  });
  video.load();

  if (window.Plyr) {
    if (!cinemaPlyrInstance) {
      cinemaPlyrInstance = new Plyr('#cinema-player', {
        controls: ['play', 'progress', 'current-time', 'mute', 'volume', 'captions', 'settings', 'fullscreen'],
        captions: { active: true, update: true, language: 'fr' }
      });
    } else {
      if (!isHls) {
        cinemaPlyrInstance.source = { type: 'video', sources: [{ src: videoUrl, type: 'video/mp4' }], tracks };
      }
    }
    cinemaPlyrInstance.play().catch(() => {});
  } else {
    video.play().catch(() => {});
  }
}

function closeCinemaPlayer() {
  const modal = document.getElementById('cinema-modal');
  if (modal) modal.classList.remove('open');
  stopAllPlayback();
}

function playAdjacentEpisode(direction) {
  if (!currentPlayingEpNum) return;
  const targetNum = parseInt(currentPlayingEpNum, 10) + direction;
  const targetRow = document.querySelector(`.episode-item[data-num="${targetNum}"]`);
  if (targetRow) {
    const playBtn = targetRow.querySelector('.btn-play-ep');
    if (playBtn) playEpisode(playBtn);
  } else {
    showToast(`Aucun épisode trouvé (${direction > 0 ? 'suivant' : 'précédent'})`, 'info');
  }
}

function closePlayer() {
  document.getElementById('player-section')?.style.setProperty('display', 'none');
  if (plyrInstance) plyrInstance.pause();
  closeCinemaPlayer();
}

async function toggleFavorite(btn) {
  const url = btn.dataset.url;
  const title = btn.dataset.title;
  const imageUrl = btn.dataset.image || '';
  const source = btn.dataset.source || 'french-manga';
  const active = btn.classList.contains('active');

  try {
    if (active) {
      await fetch('/api/favorites', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });
      btn.classList.remove('active');
      btn.querySelector('span').textContent = 'Ajouter a la bibliotheque';
      showToast('Retire de la bibliotheque', 'info');
    } else {
      await fetch('/api/favorites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, title, imageUrl, source })
      });
      btn.classList.add('active');
      btn.querySelector('span').textContent = 'Dans la bibliotheque';
      showToast('Ajoute a la bibliotheque', 'success');
    }
  } catch (error) {
    showToast('Erreur favoris', 'error');
  }
}

async function checkFavoriteStatus() {
  const favBtn = document.getElementById('fav-btn');
  if (!favBtn) return;
  try {
    const resp = await fetch('/api/favorites/check?url=' + encodeURIComponent(favBtn.dataset.url));
    const data = await resp.json();
    if (data.isFavorite) {
      favBtn.classList.add('active');
      favBtn.querySelector('span').textContent = 'Dans la bibliotheque';
    }
  } catch (error) {}
}

async function toggleAutoDownload(input) {
  try {
    await fetch('/api/favorites/auto-download', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: input.dataset.url, autoDownload: input.checked })
    });
    showToast(input.checked ? 'Auto-DL active' : 'Auto-DL desactive', 'info');
  } catch (error) {
    showToast('Erreur Auto-DL', 'error');
  }
}

async function toggleAutoDownloadFromLibrary(input) {
  await toggleAutoDownload(input);
}

async function removeFavorite(btn) {
  if (!confirm('Retirer de la bibliotheque ?')) return;
  try {
    await fetch('/api/favorites', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: btn.dataset.url })
    });
    btn.closest('.anime-card')?.remove();
    showToast('Retire de la bibliotheque', 'info');
  } catch (error) {
    showToast('Erreur', 'error');
  }
}

function initSSE() {
  if (sseSource) sseSource.close();
  sseSource = new EventSource('/api/download/stream');
  sseSource.addEventListener('download-update', event => {
    try { updateTaskRow(JSON.parse(event.data)); } catch (error) {}
  });
  sseSource.onerror = () => setTimeout(initSSE, 3000);
}

function getTaskCategory(status) {
  if (['DOWNLOADING', 'RETRYING', 'PAUSED', 'MUXING'].includes(status)) return 'active';
  if (['PENDING', 'SCHEDULED'].includes(status)) return 'queue';
  if (['FAILED', 'CANCELLED', 'ERROR'].includes(status)) return 'errors';
  return 'done';
}

function renderTaskRowInner(task, queueIndex = 1) {
  const cat = getTaskCategory(task.status);
  const animeName = task.animeName || 'Anime';
  const initial = (animeName.trim().charAt(0) || 'A').toUpperCase();
  const epNum = (task.episodeNumber !== undefined && task.episodeNumber !== null && task.episodeNumber !== '' && String(task.episodeNumber) !== 'undefined') ? task.episodeNumber : '';
  const subtitle = 'Épisode ' + epNum + (task.fileName ? ' - ' + task.fileName : '');
  const progress = Number(task.progress || 0);

  if (cat === 'errors') {
    const isEn = getCurrentLang() === 'en';
    const errTitle = escapeHtml(task.error || (isEn ? 'Download error' : 'Erreur lors du téléchargement'));
    return `
      <div class="dl-main">
        <div class="dl-cover" style="background:rgba(239,68,68,0.15);color:var(--red);font-weight:700;">${escapeHtml(initial)}</div>
        <div>
          <span class="dl-task-name">${escapeHtml(animeName)}</span>
          <span class="dl-subtitle">${escapeHtml(subtitle)}</span>
        </div>
      </div>
      <div style="display:flex; flex-direction:column; gap:4px; align-items:flex-start;">
        <span class="dl-error-badge-compact" title="${errTitle}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/></svg>
          ${task.status === 'FAILED' ? (isEn ? 'Failed' : 'Échec') : (isEn ? 'Cancelled' : 'Annulé')}
        </span>
        ${task.error ? `<span style="font-size:11px;color:var(--muted);max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(task.error)}">${escapeHtml(task.error)}</span>` : ''}
      </div>
      <span class="dl-size">${escapeHtml(task.totalSize || '0 B')}</span>
      <span class="dl-progress-text" style="color:var(--red);">${progress.toFixed(1)}%</span>
      <div class="dl-task-actions" data-id="${escapeHtml(task.id)}" data-status="${escapeHtml(task.status)}" data-animename="${escapeHtml(animeName)}" data-episodenumber="${escapeHtml(String(epNum))}">
        <button class="btn btn-sm btn-primary" type="button" onclick="redownloadTask('${escapeHtml(task.id)}')" title="${isEn ? 'Retry' : 'Réessayer'}" style="display:inline-flex;align-items:center;gap:4px;">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>
          <span>${isEn ? 'Retry' : 'Réessayer'}</span>
        </button>
        <button class="btn btn-sm btn-danger-outline" type="button" onclick="removeTask('${escapeHtml(task.id)}')" title="${isEn ? 'Remove' : 'Supprimer'}">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/></svg>
        </button>
      </div>
      <div class="dl-task-bottom-bar">
        <div class="dl-task-bottom-fill is-error" style="width:100%"></div>
      </div>`;
  }

  if (cat === 'queue') {
    let sizeContent = escapeHtml(task.totalSize || '0 B');
    if (task.status === 'SCHEDULED' && task.scheduledStartTime) {
      sizeContent = `<span class="dl-scheduled-info" data-time="${escapeHtml(task.scheduledStartTime)}">Planifié : ${formatScheduledTime(task.scheduledStartTime)}</span>`;
    }
    return `
      <span class="queue-index">${queueIndex}</span>
      <span class="drag-dots">::</span>
      <div class="dl-main">
        <div class="dl-cover">${escapeHtml(initial)}</div>
        <div>
          <span class="dl-task-name">${escapeHtml(animeName)}</span>
          <span class="dl-subtitle">${escapeHtml(subtitle)}</span>
        </div>
      </div>
      <span class="dl-size">${sizeContent}</span>
      <div class="dl-task-actions" data-id="${escapeHtml(task.id)}" data-status="${escapeHtml(task.status)}" data-animename="${escapeHtml(animeName)}" data-episodenumber="${escapeHtml(String(epNum))}">
        ${renderTaskActions(task)}
      </div>`;
  }

  if (cat === 'done') {
    const vStatus = task.verificationStatus || 'UNVERIFIED';
    const isEn = getCurrentLang() === 'en';
    let verifBadge = '';
    if (vStatus === 'VALID') {
      const dur = task.formattedDuration ? ` • ${task.formattedDuration}` : '';
      const label = isEn ? '✓ Valid' : '✓ Valide';
      const tip = isEn ? 'File intact and playable on disk' : 'Fichier intègre et lisible sur le disque';
      verifBadge = `<span class="status-badge dl-verif-badge badge-ok" style="font-size:10px; padding: 2px 6px;" title="${tip}">${label}${escapeHtml(dur)}</span>`;
    } else if (vStatus === 'MISSING') {
      const label = isEn ? '⚠ Missing' : '⚠ Manquant';
      const tip = escapeHtml(task.verificationError || (isEn ? 'File not found on disk' : 'Fichier introuvable sur le disque'));
      verifBadge = `<span class="status-badge dl-verif-badge badge-err" style="font-size:10px; padding: 2px 6px;" title="${tip}">${label}</span>`;
    } else if (vStatus === 'CORRUPTED') {
      const label = isEn ? '✗ Corrupted' : '✗ Corrompu';
      const tip = escapeHtml(task.verificationError || (isEn ? 'Corrupted video file' : 'Fichier vidéo corrompu'));
      verifBadge = `<span class="status-badge dl-verif-badge badge-err" style="font-size:10px; padding: 2px 6px;" title="${tip}">${label}</span>`;
    } else if (vStatus === 'EMPTY') {
      const label = isEn ? '✗ Empty' : '✗ Vide';
      const tip = isEn ? '0-byte file' : 'Fichier de 0 octet';
      verifBadge = `<span class="status-badge dl-verif-badge badge-err" style="font-size:10px; padding: 2px 6px;" title="${tip}">${label}</span>`;
    } else {
      const label = isEn ? 'Unverified' : 'Non vérifié';
      verifBadge = `<span class="status-badge dl-verif-badge badge-other" style="font-size:10px; padding: 2px 6px;" title="${label}">${label}</span>`;
    }

    let statusEl;
    if (task.status === 'FAILED') {
      const failedText = isEn ? 'Failed' : 'Échec';
      const retryTitle = isEn ? 'Retry immediately' : 'Réessayer immédiatement';
      const errTitle = escapeHtml(task.error || (isEn ? 'Download error' : 'Erreur lors du téléchargement'));
      statusEl = `
        <span class="dl-error-badge-compact" title="${errTitle}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/></svg>
          ${failedText}
          <button type="button" class="dl-error-retry-btn" title="${retryTitle}" onclick="event.stopPropagation(); redownloadTask('${escapeHtml(task.id)}')">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>
          </button>
        </span>`;
    } else {
      statusEl = `<span class="status-badge dl-task-status ${statusClass(task.status)}">${translateStatus(task.status)}</span>`;
    }

    return `
      <div class="dl-main">
        <div class="dl-cover">${escapeHtml(initial)}</div>
        <div>
          <span class="dl-task-name">${escapeHtml(animeName)}</span>
          <span class="dl-subtitle">${escapeHtml(subtitle)}</span>
        </div>
      </div>
      <div style="display:flex; flex-direction:column; gap:4px; align-items:flex-start;">
        ${statusEl}
        ${verifBadge}
      </div>
      <span class="dl-size">${escapeHtml(task.totalSize || '0 B')}</span>
      <span class="dl-progress-text">${progress.toFixed(1)}%</span>
      <div class="dl-task-actions" data-id="${escapeHtml(task.id)}" data-status="${escapeHtml(task.status)}" data-verification="${escapeHtml(vStatus)}" data-animename="${escapeHtml(animeName)}" data-episodenumber="${escapeHtml(String(epNum))}">
        ${renderTaskActions(task)}
      </div>`;
  }

  // cat === 'active'
  let etaText = '';
  if (task.status === 'DOWNLOADING') {
    const total = task.totalBytes || 0;
    const dl = task.downloadedBytes || 0;
    const sp = task.speedBytes || parseSpeedToBytes(task.speed);
    if (total > dl && sp > 0) {
      etaText = '• ' + formatEta(Math.round((total - dl) / sp));
    }
  }

  const limitKb = task.maxSpeedLimit > 0 ? Math.round(task.maxSpeedLimit / 1024) : 0;
  const safeId = escapeHtml(task.id);
  const limitHtml = limitKb > 0
    ? `<span class="dl-speed-limit-badge">Max: ${limitKb} KB/s <button class="speed-limit-btn" onclick="changeTaskSpeedLimit('${safeId}')">Modifier</button></span>`
    : `<button class="speed-limit-btn" onclick="changeTaskSpeedLimit('${safeId}')">Limiter</button>`;

  return `
    <div class="dl-main">
      <div class="dl-cover">${escapeHtml(initial)}</div>
      <div>
        <span class="dl-task-name">${escapeHtml(animeName)}</span>
        <span class="dl-subtitle">${escapeHtml(subtitle)}</span>
      </div>
    </div>
    <div class="dl-progress-wrap">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span class="dl-size">${escapeHtml(task.downloadedSize || '0 B')} / ${escapeHtml(task.totalSize || '0 B')}</span>
        <span class="dl-eta" id="eta-${escapeHtml(task.id)}">${etaText}</span>
      </div>
    </div>
    <span class="dl-progress-text">${progress.toFixed(1)}%</span>
    <div class="dl-speed-col">
      <span class="dl-speed">${escapeHtml(task.speed || '')}</span>
      ${task.error ? `<span class="dl-error-badge-compact" title="${escapeHtml(task.error)}"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6M9 9l6 6"/></svg> Erreur</span>` : ''}
      <div class="dl-speed-limit-container" style="margin-top: 0.25rem;">
        ${limitHtml}
      </div>
    </div>
    <div class="dl-task-actions" data-id="${escapeHtml(task.id)}" data-status="${escapeHtml(task.status)}" data-animename="${escapeHtml(animeName)}" data-episodenumber="${escapeHtml(String(epNum))}">
      ${renderTaskActions(task)}
    </div>
    <div class="dl-task-bottom-bar">
      <div class="dl-task-bottom-fill ${task.status === 'PAUSED' ? 'is-paused' : (task.error ? 'is-error' : '')}" style="width:${progress}%"></div>
    </div>`;
}

function createTaskRow(task) {
  const row = document.createElement('div');
  const cat = getTaskCategory(task.status);
  row.className = 'dl-task-row' + (cat === 'queue' ? ' queue-row' : (cat === 'done' ? ' completed-row' : (cat === 'errors' ? ' error-row' : '')));
  row.id = 'task-' + task.id;
  row.dataset.id = task.id;
  row.dataset.category = cat;
  row.dataset.status = task.status;
  row.dataset.speedBytes = task.speedBytes || 0;
  row.dataset.totalBytes = task.totalBytes || 0;
  row.dataset.downloadedBytes = task.downloadedBytes || 0;
  if (cat === 'queue') row.setAttribute('draggable', 'true');
  row.innerHTML = renderTaskRowInner(task);
  return row;
}

function updateTaskRow(task) {
  let row = document.getElementById('task-' + task.id);
  const newCat = getTaskCategory(task.status);
  const targetParentId = newCat === 'active' ? 'download-list' : (newCat === 'queue' ? 'queue-list' : (newCat === 'errors' ? 'error-list' : 'completed-list'));
  const targetParent = document.getElementById(targetParentId);
  if (!targetParent) return;

  if (!row) {
    row = createTaskRow(task);
    if (newCat === 'done' || newCat === 'errors') {
      targetParent.prepend(row);
    } else {
      targetParent.appendChild(row);
    }
    if (newCat === 'queue') reindexQueueRows();
    refreshDownloadStats();
    refreshDownloadBadge();
    return;
  }

  const oldCat = row.dataset.category || (row.classList.contains('queue-row') ? 'queue' : (row.classList.contains('error-row') ? 'errors' : (row.classList.contains('completed-row') ? 'done' : 'active')));
  if (oldCat !== newCat) {
    row.dataset.category = newCat;
    row.dataset.status = task.status;
    row.dataset.speedBytes = task.speedBytes || 0;
    row.dataset.totalBytes = task.totalBytes || 0;
    row.dataset.downloadedBytes = task.downloadedBytes || 0;
    row.className = 'dl-task-row' + (newCat === 'queue' ? ' queue-row' : (newCat === 'done' ? ' completed-row' : (newCat === 'errors' ? ' error-row' : '')));
    if (newCat === 'queue') {
      row.setAttribute('draggable', 'true');
      targetParent.appendChild(row);
    } else {
      row.removeAttribute('draggable');
      if (newCat === 'done' || newCat === 'errors') {
        targetParent.prepend(row);
      } else {
        targetParent.appendChild(row);
      }
    }
    row.innerHTML = renderTaskRowInner(task);
    reindexQueueRows();
    refreshDownloadStats();
    refreshDownloadBadge();
    return;
  }

  // In-place micro updates when category is unchanged
  row.dataset.status = task.status;
  if (newCat === 'active') {
    row.dataset.speedBytes = task.speedBytes || 0;
    row.dataset.totalBytes = task.totalBytes || 0;
    row.dataset.downloadedBytes = task.downloadedBytes || 0;

    const fill = row.querySelector('.dl-progress-fill');
    if (fill) fill.style.width = (task.progress || 0) + '%';

    const bottomFill = row.querySelector('.dl-task-bottom-fill');
    if (bottomFill) {
      bottomFill.style.width = (task.progress || 0) + '%';
      bottomFill.className = 'dl-task-bottom-fill' + (task.status === 'PAUSED' ? ' is-paused' : (task.error ? ' is-error' : ''));
    }

    const text = row.querySelector('.dl-progress-text');
    if (text) text.textContent = Number(task.progress || 0).toFixed(1) + '%';

    const size = row.querySelector('.dl-size');
    if (size) size.textContent = (task.downloadedSize || '0 B') + ' / ' + (task.totalSize || '0 B');

    let etaEl = row.querySelector('.dl-eta');
    if (task.status === 'DOWNLOADING') {
      const total = task.totalBytes || 0;
      const dl = task.downloadedBytes || 0;
      const sp = (task.speedBytes !== undefined && task.speedBytes !== null) ? Number(task.speedBytes) : parseSpeedToBytes(task.speed);
      if (etaEl) {
        if (total > dl && sp > 0) {
          etaEl.textContent = '• ' + formatEta(Math.round((total - dl) / sp));
        } else {
          etaEl.textContent = '';
        }
      }
    } else if (etaEl) {
      etaEl.textContent = '';
    }

    const speed = row.querySelector('.dl-speed');
    if (speed) speed.textContent = task.speed || '';

    const error = row.querySelector('.dl-error');
    if (error) error.textContent = task.error || '';

    const actEl = row.querySelector('.dl-task-actions');
    if (actEl && actEl.dataset.status !== task.status) {
      actEl.dataset.status = task.status;
      actEl.innerHTML = renderTaskActions(task);
    }
  } else if (newCat === 'queue') {
    const size = row.querySelector('.dl-size');
    if (size) {
      if (task.status === 'SCHEDULED' && task.scheduledStartTime) {
        size.innerHTML = `<span class="dl-scheduled-info" data-time="${task.scheduledStartTime}">Planifié : ${formatScheduledTime(task.scheduledStartTime)}</span>`;
      } else {
        size.textContent = task.totalSize || '0 B';
      }
    }
    const actEl = row.querySelector('.dl-task-actions');
    if (actEl && actEl.dataset.status !== task.status) {
      actEl.dataset.status = task.status;
      actEl.innerHTML = renderTaskActions(task);
    }
  } else if (newCat === 'done') {
    const badge = row.querySelector('.dl-task-status');
    if (badge) {
      badge.textContent = translateStatus(task.status);
      badge.className = 'status-badge dl-task-status ' + statusClass(task.status);
    }
    const actEl = row.querySelector('.dl-task-actions');
    if (actEl && actEl.dataset.status !== task.status) {
      actEl.dataset.status = task.status;
      actEl.innerHTML = renderTaskActions(task);
    }
  }

  refreshDownloadStats();
}

function renderTaskActions(task) {
  const id = task.id;
  const animeName = task.animeName || '';
  const safeAnime = animeName.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$/g, '\\$');
  const epNum = (task.episodeNumber !== undefined && task.episodeNumber !== null && task.episodeNumber !== '' && String(task.episodeNumber) !== 'undefined') ? `'${task.episodeNumber}'` : 'null';
  const isEn = getCurrentLang() === 'en';
  const upIcon = '<svg viewBox="0 0 24 24"><path d="M12 19V5"/><path d="m5 12 7-7 7 7"/></svg>';
  const downIcon = '<svg viewBox="0 0 24 24"><path d="M12 5v14"/><path d="m19 12-7 7-7-7"/></svg>';
  const pauseIcon = '<svg viewBox="0 0 24 24"><path d="M8 5v14M16 5v14"/></svg>';
  const playIcon = '<svg viewBox="0 0 24 24"><path d="M7 4v16l13-8Z"/></svg>';
  const xIcon = '<svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>';
  const trashIcon = '<svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="m19 6-1 14H6L5 6"/></svg>';
  const retryIcon = '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v6h-6"/></svg>';
  const shieldIcon = '<svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>';

  const tPause = isEn ? 'Pause' : 'Pause';
  const tCancel = isEn ? 'Cancel' : 'Annuler';
  const tResume = isEn ? 'Resume' : 'Reprendre';
  const tUp = isEn ? 'Move to top' : 'Monter';
  const tDown = isEn ? 'Move down' : 'Descendre';
  const tPrioritize = isEn ? 'Prioritize series' : 'Prioriser la série';
  const tResumeDl = isEn ? 'Resume download' : 'Reprendre le téléchargement';
  const tRetry = isEn ? 'Redownload / Retry' : 'Re-télécharger / Réessayer';
  const tVerify = isEn ? 'Verify integrity' : "Vérifier l'intégrité";
  const tRemove = isEn ? 'Remove' : 'Retirer';
  const tPlay = isEn ? 'Play' : 'Lire';
  const tRedownloadEp = isEn ? 'Redownload this episode' : 'Re-télécharger cet épisode';

  if (task.status === 'DOWNLOADING' || task.status === 'RETRYING' || task.status === 'MUXING') {
    return `<button class="btn btn-icon" title="${tPause}" onclick="apiPost('/api/download/${id}/pause')">${pauseIcon}</button>
            <button class="btn btn-icon btn-danger" title="${tCancel}" onclick="cancelTask('${id}')">${xIcon}</button>`;
  }
  if (task.status === 'PAUSED') {
    return `<button class="btn btn-icon btn-primary" title="${tResume}" onclick="apiPost('/api/download/${id}/resume')">${playIcon}</button>
            <button class="btn btn-icon btn-danger" title="${tCancel}" onclick="cancelTask('${id}')">${xIcon}</button>`;
  }
  if (task.status === 'PENDING' || task.status === 'SCHEDULED') {
    return `<button class="btn btn-icon" title="${tUp}" onclick="moveTaskToTop('${id}')">${upIcon}</button>
            <button class="btn btn-icon" title="${tDown}" disabled>${downIcon}</button>
            ${animeName ? `<button class="btn btn-icon" title="${tPrioritize}" onclick="moveSeriesToTop(\`${safeAnime}\`)"><svg viewBox="0 0 24 24"><path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/></svg></button>` : ''}
            <button class="btn btn-icon btn-danger" title="${tCancel}" onclick="cancelTask('${id}')">${xIcon}</button>`;
  }
  if (task.status === 'FAILED' || task.status === 'CANCELLED') {
    const hasProgress = (task.downloadedBytes && task.downloadedBytes > 0) || (task.progress && task.progress > 0);
    return `${hasProgress ? `<button class="btn btn-icon btn-success" title="${tResumeDl}" onclick="apiPost('/api/download/${id}/resume')">${playIcon}</button>` : ''}
            <button class="btn btn-icon btn-primary" title="${tRetry}" onclick="redownloadTask('${id}')">${retryIcon}</button>
            <button class="btn btn-icon" title="${tVerify}" onclick="verifyTask('${id}', this)">${shieldIcon}</button>
            <button class="btn btn-icon" title="${tRemove}" onclick="removeTask('${id}')">${trashIcon}</button>`;
  }
  if (task.status === 'COMPLETED') {
    const isProblem = ['MISSING', 'CORRUPTED', 'EMPTY'].includes(task.verificationStatus);
    return `<button class="btn btn-icon btn-primary" title="${tPlay}" onclick="playDownloadedTask('${id}', \`${safeAnime}\`, ${epNum})">${playIcon}</button>
            <button class="btn btn-icon" title="${tVerify}" onclick="verifyTask('${id}', this)">${shieldIcon}</button>
            ${isProblem ? `<button class="btn btn-icon btn-primary" title="${tRedownloadEp}" onclick="redownloadTask('${id}')">${retryIcon}</button>` : ''}
            <button class="btn btn-icon" title="${tRemove}" onclick="removeTask('${id}')">${trashIcon}</button>`;
  }
  return '';
}

function translateStatus(status) {
  const isEn = getCurrentLang() === 'en';
  const labelsFr = {
    PENDING: 'En attente',
    SCHEDULED: 'Planifié',
    DOWNLOADING: 'Téléchargement',
    RETRYING: 'Nouvelle tentative',
    PAUSED: 'Pause',
    COMPLETED: 'Terminé',
    FAILED: 'Échec',
    CANCELLED: 'Annulé',
    MUXING: 'Muxing sous-titres'
  };
  const labelsEn = {
    PENDING: 'Pending',
    SCHEDULED: 'Scheduled',
    DOWNLOADING: 'Downloading',
    RETRYING: 'Retrying',
    PAUSED: 'Paused',
    COMPLETED: 'Completed',
    FAILED: 'Failed',
    CANCELLED: 'Cancelled',
    MUXING: 'Muxing subtitles'
  };
  const labels = isEn ? labelsEn : labelsFr;
  return labels[status] || status;
}

function statusClass(status) {
  if (status === 'COMPLETED') return 'badge-ok';
  if (status === 'FAILED' || status === 'CANCELLED') return 'badge-err';
  if (status === 'MUXING') return 'badge-warn';
  return 'badge-other';
}

async function apiPost(url, body) {
  try {
    await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined
    });
    setTimeout(refreshDownloadStats, 250);
  } catch (e) {
    showToast('Erreur lors de l\'action', 'error');
  }
}

async function cancelTask(id) {
  try {
    const res = await fetch('/api/download/' + id, { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      showToast(data.message || 'Téléchargement annulé', 'info');
      const row = document.getElementById('task-' + id);
      if (row) {
        const completedList = document.getElementById('completed-list');
        const activeFilter = document.querySelector('.download-tabs .tab-btn.active')?.dataset?.downloadFilter || 'queue';
        if (activeFilter === 'queue') {
          row.style.transition = 'all 0.25s ease';
          row.style.opacity = '0';
          setTimeout(() => {
            if (completedList) {
              row.dataset.category = 'done';
              row.dataset.status = 'CANCELLED';
              row.className = 'dl-task-row completed-row';
              row.removeAttribute('draggable');
              row.style.opacity = '1';
              row.style.display = 'none';
              const actEl = row.querySelector('.dl-task-actions');
              if (actEl) {
                actEl.dataset.status = 'CANCELLED';
                actEl.innerHTML = renderTaskActions({ id: id, status: 'CANCELLED' });
              }
              completedList.prepend(row);
            } else {
              row.remove();
            }
            reindexQueueRows();
            refreshDownloadStats();
            refreshDownloadBadge();
          }, 250);
        } else {
          row.dataset.category = 'done';
          row.dataset.status = 'CANCELLED';
          row.className = 'dl-task-row completed-row';
          row.removeAttribute('draggable');
          const actEl = row.querySelector('.dl-task-actions');
          if (actEl) {
            actEl.dataset.status = 'CANCELLED';
            actEl.innerHTML = renderTaskActions({ id: id, status: 'CANCELLED' });
          }
          const badge = row.querySelector('.dl-task-status');
          if (badge) {
            badge.textContent = translateStatus('CANCELLED');
            badge.className = 'status-badge dl-task-status badge-err';
          }
          refreshDownloadStats();
          refreshDownloadBadge();
        }
      }
    } else {
      showToast(data.error || 'Erreur lors de l\'annulation', 'error');
    }
    setTimeout(refreshDownloadStats, 300);
  } catch (e) {
    showToast('Erreur lors de l\'annulation', 'error');
  }
}

async function removeTask(id) {
  try {
    const res = await fetch('/api/download/' + id + '/remove', { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (res.ok) {
      document.getElementById('task-' + id)?.remove();
      reindexQueueRows();
      refreshDownloadStats();
      refreshDownloadBadge();
      showToast(data.message || 'Tâche retirée', 'info');
    } else {
      showToast(data.error || 'Erreur de suppression', 'error');
    }
  } catch (e) {
    showToast('Erreur de suppression', 'error');
  }
}

async function moveTaskToTop(id) {
  try {
    const resp = await fetch('/api/download/' + id + '/move-to-top', { method: 'POST' });
    const data = await resp.json();
    showToast(data.message || 'Priorité mise à jour', data.success ? 'success' : 'error');
    if (data.success) setTimeout(() => window.location.reload(), 500);
  } catch (error) {
    showToast('Erreur réseau', 'error');
  }
}

async function moveSeriesToTop(animeName) {
  try {
    const resp = await fetch('/api/download/move-series-to-top', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ animeName })
    });
    const data = await resp.json();
    showToast(data.message || 'Série priorisée', data.success ? 'success' : 'error');
    if (data.success) setTimeout(() => window.location.reload(), 500);
  } catch (error) {
    showToast('Erreur réseau', 'error');
  }
}

function filterDownloadView(btn) {
  document.querySelectorAll('[data-download-filter]').forEach(item => item.classList.remove('active'));
  btn.classList.add('active');
  const filter = btn.dataset.downloadFilter;
  document.querySelectorAll('[data-download-group]').forEach(group => {
    group.style.display = (filter === 'all' || group.dataset.downloadGroup === filter) ? '' : 'none';
  });
  refreshDownloadStats();
}

function formatBytesSpeed(bytes) {
  if (!bytes || bytes <= 0) return '0 B/s';
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

function refreshDownloadStats() {
  const activeRows = document.querySelectorAll('#download-list .dl-task-row');
  const queueRows = document.querySelectorAll('#queue-list .dl-task-row');
  const doneRows = document.querySelectorAll('#completed-list .dl-task-row');
  const errorRows = document.querySelectorAll('#error-list .dl-task-row');

  const activeCount = activeRows.length;
  const queuedCount = queueRows.length;
  const doneCount = doneRows.length;
  const errorCount = errorRows.length;
  const totalCount = activeCount + queuedCount + doneCount + errorCount;

  // Aggregate speed across active rows
  let totalSpeedBytes = 0;
  activeRows.forEach(row => {
    if (row.dataset.status === 'DOWNLOADING') {
      const spB = Number(row.dataset.speedBytes);
      if (!isNaN(spB) && spB > 0) {
        totalSpeedBytes += spB;
      } else {
        const sp = row.querySelector('.dl-speed')?.textContent.trim();
        if (sp) totalSpeedBytes += parseSpeedToBytes(sp);
      }
    }
  });

  setText('stat-active', activeCount);
  setText('stat-queued', queuedCount);
  setText('stat-speed', formatBytesSpeed(totalSpeedBytes));
  setText('stat-errors', errorCount);
  const statCardErrors = document.getElementById('stat-card-errors');
  if (statCardErrors) statCardErrors.style.display = errorCount > 0 ? 'block' : 'none';

  setText('download-count-badge', activeCount + queuedCount);
  setText('mob-download-badge', activeCount + queuedCount);

  // Tab badges
  setText('tab-badge-queue', activeCount + queuedCount);
  setText('tab-badge-done', doneCount);
  setText('tab-badge-errors', errorCount);
  setText('tab-badge-all', totalCount);

  // Empty state placeholders
  const activeEmptyNote = document.getElementById('active-empty-note');
  const queueEmptyNote = document.getElementById('queue-empty-note');
  const doneEmptyNote = document.getElementById('done-empty-note');
  const errorEmptyNote = document.getElementById('error-empty-note');
  const globalEmpty = document.getElementById('dl-empty');
  const downloadHint = document.querySelector('.download-hint');

  if (activeEmptyNote) activeEmptyNote.style.display = activeCount === 0 ? 'block' : 'none';
  if (queueEmptyNote) queueEmptyNote.style.display = queuedCount === 0 ? 'block' : 'none';
  if (doneEmptyNote) doneEmptyNote.style.display = doneCount === 0 ? 'block' : 'none';
  if (errorEmptyNote) errorEmptyNote.style.display = errorCount === 0 ? 'block' : 'none';

  if (globalEmpty) {
    globalEmpty.style.display = totalCount === 0 ? 'flex' : 'none';
  }

  if (downloadHint) {
    const activeFilter = document.querySelector('.tab-btn.active')?.dataset.downloadFilter || 'queue';
    downloadHint.style.display = (activeFilter !== 'done' && activeFilter !== 'errors' && queuedCount > 1) ? 'flex' : 'none';
  }
}

window.cleanAllErrors = async function() {
  try {
    const errorRows = document.querySelectorAll('#error-list .dl-task-row');
    if (!errorRows.length) return;
    for (const row of errorRows) {
      const id = row.dataset.id;
      if (id) await fetch('/api/download/' + id + '/remove', { method: 'DELETE' });
    }
    showToast(getCurrentLang() === 'en' ? 'Errors cleared' : 'Erreurs nettoyées', 'success');
    setTimeout(() => window.location.reload(), 300);
  } catch(e) {
    showToast(getCurrentLang() === 'en' ? 'Failed to clear errors' : 'Erreur lors du nettoyage', 'error');
  }
};

function refreshDownloadBadge() {
  const desktopBadge = document.getElementById('download-count-badge');
  const mobBadge = document.getElementById('mob-download-badge');
  fetch('/api/download/status')
    .then(r => r.json())
    .then(tasks => {
      const activeOrPending = tasks.filter(task => ['DOWNLOADING', 'RETRYING', 'PENDING', 'SCHEDULED', 'PAUSED', 'MUXING'].includes(task.status));
      const count = activeOrPending.length;
      if (desktopBadge) setText('download-count-badge', count);
      if (mobBadge) setText('mob-download-badge', count);

      if (document.getElementById('episode-list') && typeof ANIME_NAME !== 'undefined') {
        const currentAnimeTasks = activeOrPending.filter(t => t.animeName === ANIME_NAME);
        currentAnimeTasks.forEach(task => {
          const row = document.querySelector(`.episode-item[data-num="${task.episodeNumber}"]`);
          if (row && !row.querySelector('.ep-queued-badge') && !row.querySelector('.ep-done-badge')) {
            const badge = document.createElement('span');
            badge.className = 'ep-queued-badge';
            badge.textContent = task.status === 'DOWNLOADING' ? 'En cours' : 'En file d\'attente';
            const titleEl = row.querySelector('.episode-title');
            if (titleEl) {
              titleEl.after(badge);
            } else {
              row.appendChild(badge);
            }
          }
        });
      }
    })
    .catch(() => {});
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function showToast(message, type = 'info', action = null) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast ' + type;
  
  const span = document.createElement('span');
  span.textContent = message;
  toast.appendChild(span);

  if (action && action.text) {
    const actBtn = document.createElement('button');
    actBtn.type = 'button';
    actBtn.className = 'toast-link';
    actBtn.style.background = 'none';
    actBtn.style.border = 'none';
    actBtn.style.padding = '0';
    actBtn.style.font = 'inherit';
    actBtn.textContent = action.text;
    actBtn.onclick = (e) => {
      e.stopPropagation();
      toast.remove();
      if (typeof action.onClick === 'function') action.onClick();
    };
    toast.appendChild(actBtn);
  }

  container.appendChild(toast);
  setTimeout(() => toast.remove(), action ? 7000 : 4000);
}

function sanitizeFilename(name) {
  return name.replace(/[<>:"/\\|?*]/g, '_').replace(/\s+/g, ' ').trim();
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// Drag and Drop support
function initDragAndDrop() {
  const queueList = document.getElementById('queue-list');
  if (!queueList) return;

  let dragEl = null;

  queueList.addEventListener('dragstart', (e) => {
    const row = e.target.closest('.queue-row');
    if (!row) return;
    dragEl = row;
    e.dataTransfer.effectAllowed = 'move';
    row.classList.add('dragging');
  });

  queueList.addEventListener('dragover', (e) => {
    e.preventDefault();
    const row = e.target.closest('.queue-row');
    if (!row || row === dragEl) return;
    
    const bounding = row.getBoundingClientRect();
    const offset = e.clientY - bounding.top;
    if (offset > bounding.height / 2) {
      row.after(dragEl);
    } else {
      row.before(dragEl);
    }
  });

  queueList.addEventListener('dragend', async (e) => {
    const row = e.target.closest('.queue-row');
    if (row) row.classList.remove('dragging');
    dragEl = null;

    reindexQueueRows();

    const orderedIds = [...queueList.querySelectorAll('.queue-row')].map(r => r.dataset.id);
    
    try {
      const resp = await fetch('/api/download/reorder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(orderedIds)
      });
      const data = await resp.json();
      if (data.success) {
        showToast('File d\'attente réorganisée', 'success');
      } else {
        showToast(data.error || 'Erreur lors du réordonnancement', 'error');
      }
    } catch (err) {
      showToast('Erreur de connexion', 'error');
    }
  });
}

function reindexQueueRows() {
  const queueList = document.getElementById('queue-list');
  if (!queueList) return;
  queueList.querySelectorAll('.queue-row').forEach((row, idx) => {
    const idxEl = row.querySelector('.queue-index');
    if (idxEl) idxEl.textContent = idx + 1;
  });
}

// Speed limit change
async function changeTaskSpeedLimit(id) {
  const currentLimitStr = prompt("Vitesse maximale pour cette tâche en KB/s (0 pour illimitée) :");
  if (currentLimitStr === null) return;

  const limitKb = parseInt(currentLimitStr, 10);
  if (isNaN(limitKb) || limitKb < 0) {
    showToast("Vitesse invalide", "error");
    return;
  }

  const limitBytes = limitKb * 1024;
  try {
    const resp = await fetch(`/api/download/${id}/speed-limit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: limitBytes })
    });
    const data = await resp.json();
    if (data.success) {
      showToast("Limite de vitesse mise à jour", "success");
    } else {
      showToast(data.error || "Erreur", "error");
    }
  } catch (err) {
    showToast("Erreur de connexion", "error");
  }
}

// Scheduled count down
function formatScheduledTime(isoString) {
  try {
    const target = new Date(isoString);
    const now = new Date();
    const diffMs = target - now;
    if (diffMs <= 0) return "Démarrage imminent...";
    
    const diffSecs = Math.floor(diffMs / 1000);
    const hours = Math.floor(diffSecs / 3600);
    const mins = Math.floor((diffSecs % 3600) / 60);
    const secs = diffSecs % 60;
    
    let parts = [];
    if (hours > 0) parts.push(hours + "h");
    if (mins > 0 || hours > 0) parts.push(mins + "m");
    parts.push(secs + "s");
    
    const timeFormatted = target.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return `Démarre à ${timeFormatted} (dans ${parts.join(' ')})`;
  } catch (e) {
    return isoString;
  }
}

function initScheduledTicker() {
  setInterval(() => {
    document.querySelectorAll('.dl-scheduled-info[data-time]').forEach(el => {
      el.textContent = formatScheduledTime(el.dataset.time);
    });

    const activeRows = document.querySelectorAll('#download-list .dl-task-row');
    if (activeRows.length > 0) {
      refreshDownloadStats();
    }
  }, 1000);
}

// Delegated listener for Thymeleaf-rendered play buttons (data-action="play")
function bindPlayActionButtons() {
  document.addEventListener('click', (e) => {
    // Play button
    const playBtn = e.target.closest('[data-action="play"]');
    if (playBtn) {
      const taskId = playBtn.dataset.taskId;
      if (taskId) playDownloadedTask(taskId);
      return;
    }
    // Delete history entry button
    const delBtn = e.target.closest('[data-action="delete-history"]');
    if (delBtn) {
      const taskId = delBtn.dataset.taskId;
      if (taskId) deleteHistoryEntry(taskId, delBtn);
      return;
    }
    // Verify history entry button
    const verifBtn = e.target.closest('[data-action="verify"]');
    if (verifBtn) {
      const taskId = verifBtn.dataset.taskId;
      if (taskId) verifyTask(taskId, verifBtn);
      return;
    }
    // Redownload history entry button
    const redlBtn = e.target.closest('[data-action="redownload"]');
    if (redlBtn) {
      const taskId = redlBtn.dataset.taskId;
      if (taskId) redownloadTask(taskId);
      return;
    }
  });
}

// =========================================================================
// Nettoyage historique & bibliothèque
// =========================================================================

async function deleteHistoryEntry(taskId, triggerEl) {
  try {
    const resp = await fetch('/api/history/' + taskId, { method: 'DELETE' });
    const data = await resp.json();
    if (data.success) {
      // Retire la ligne du DOM (table row ou history-item)
      const row = triggerEl?.closest('tr') || triggerEl?.closest('.history-item');
      row?.remove();
      showToast('Entree supprimee', 'success');
    } else {
      showToast(data.error || 'Erreur', 'error');
    }
  } catch (err) {
    showToast('Erreur de connexion', 'error');
  }
}

async function clearHistory(statusFilter) {
  const msg = statusFilter
    ? 'Supprimer toutes les entrees avec ce statut ?'
    : 'Vider completement l\'historique ? Cette action est irreversible.';
  if (!confirm(msg)) return;

  let url = '/api/history';
  if (statusFilter) url += '?status=' + encodeURIComponent(statusFilter);

  try {
    const resp = await fetch(url, { method: 'DELETE' });
    const data = await resp.json();
    if (data.success) {
      showToast(data.message || 'Historique vide', 'success');
      setTimeout(() => window.location.reload(), 600);
    } else {
      showToast(data.error || 'Erreur', 'error');
    }
  } catch (err) {
    showToast('Erreur de connexion', 'error');
  }
}

async function clearHistoryByStatus(statuses) {
  await clearHistory(statuses);
}

async function clearAllFavorites() {
  if (!confirm('Retirer tous les favoris de la bibliotheque ? Cette action est irreversible.')) return;
  try {
    const resp = await fetch('/api/favorites/all', { method: 'DELETE' });
    const data = await resp.json();
    if (data.success) {
      showToast(data.message || 'Bibliotheque videe', 'success');
      const grid = document.getElementById('favorites-grid');
      if (grid) grid.innerHTML = '';
      setTimeout(() => window.location.reload(), 600);
    } else {
      showToast(data.error || 'Erreur', 'error');
    }
  } catch (err) {
    showToast('Erreur de connexion', 'error');
  }
}

// Direct play from downloads or history page
async function playDownloadedTask(taskId, animeName, episodeNumber) {
  showToast('Résolution du flux vidéo local...', 'info');
  try {
    const videoUrl = '/api/media/stream/' + taskId;
    const subsResp = await fetch('/api/media/subtitles/' + taskId);
    let tracks = [];
    try {
      const subs = await subsResp.json();
      tracks = subs.map(sub => ({ kind: 'captions', label: sub.label, srclang: sub.srclang, src: sub.src, default: sub.srclang === 'fr' }));
    } catch (e) {
      console.log("No subtitles found or error fetching subs", e);
    }

    const epDisplay = (episodeNumber && String(episodeNumber) !== 'null' && String(episodeNumber) !== 'undefined') ? ` - Épisode ${episodeNumber}` : '';
    const title = animeName ? `${animeName}${epDisplay}` : 'Lecture vidéo';
    const cinemaModal = document.getElementById('cinema-modal');
    if (cinemaModal) {
      openCinemaModal(videoUrl, title, tracks, episodeNumber, { isDownloaded: true, serverType: 'Disque dur (Local)' });
    } else {
      const playerSection = document.getElementById('player-section');
      const video = document.getElementById('plyr-player');
      if (!playerSection || !video) return;

      video.innerHTML = `<source src="${videoUrl}" type="video/mp4"/>`;
      tracks.forEach(track => {
        const trackEl = document.createElement('track');
        trackEl.kind = 'subtitles';
        trackEl.label = track.label;
        trackEl.srclang = track.srclang;
        trackEl.src = track.src;
        if (track.default) trackEl.setAttribute('default', '');
        video.appendChild(trackEl);
      });
      video.load();
      playerSection.style.display = 'block';
      playerSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

      if (window.Plyr) {
        if (!plyrInstance) {
          plyrInstance = new Plyr('#plyr-player', {
            controls: ['play', 'progress', 'current-time', 'mute', 'volume', 'captions', 'settings', 'fullscreen'],
            captions: { active: true, update: true, language: 'fr' }
          });
        } else {
          plyrInstance.source = { type: 'video', sources: [{ src: videoUrl, type: 'video/mp4' }], tracks };
        }
        plyrInstance.play();
      } else {
        video.play();
      }
    }
  } catch (error) {
    showToast('Erreur lecteur: ' + error.message, 'error');
  }
}



// =========================================================================
// Raccourcis clavier globaux
// =========================================================================

function initShortcuts() {
  document.addEventListener('keydown', (e) => {
    // Ctrl + K ou Cmd + K : Ouvre la modale globale Command Palette
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      openCommandPalette();
      return;
    }

    const isInput = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);

    if (e.key === 'Escape') {
      closeCommandPalette();
      closeCinemaPlayer();
      document.getElementById('settings-panel')?.classList.remove('open');
      document.querySelectorAll('.search-autocomplete-dropdown').forEach(d => d.classList.remove('open'));
      document.getElementById('quality-modal')?.style.setProperty('display', 'none');
      document.getElementById('subtitle-modal')?.style.setProperty('display', 'none');
      return;
    }

    if (isInput) return;

    if (e.key === '/') {
      e.preventDefault();
      openCommandPalette();
    } else if (e.key.toLowerCase() === 't' && !isInput) {
      const current = document.documentElement.getAttribute('data-theme') || 'dark';
      applyTheme(current === 'dark' ? 'light' : 'dark');
      showToast(`Thème basculé : ${current === 'dark' ? 'Clair' : 'Sombre'}`, 'info');
    }
  });
}

// =========================================================================
// Command Palette Modale Globale (Spotlight / Raycast) & Autocomplétion
// =========================================================================

const searchMemoryCache = new Map();

async function syncPaletteExtensionTabs() {
  const tabsBar = document.getElementById('palette-source-tabs');
  if (!tabsBar) return;
  try {
    const resp = await fetch('/api/extensions/list?enabled_only=true');
    if (!resp.ok) return;
    const data = await resp.json();
    const exts = data.extensions || [];
    const defaultSources = ['all', 'french-manga', 'voir-anime', 'animepahe'];

    const existingChips = new Set();
    tabsBar.querySelectorAll('.palette-tab-chip').forEach(el => {
      if (el.dataset.src) existingChips.add(el.dataset.src);
    });

    exts.forEach(ext => {
      if (!existingChips.has(ext.pkg) && !defaultSources.includes(ext.pkg)) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'palette-tab-chip palette-ext-chip';
        btn.dataset.src = ext.pkg;
        const cleanName = ext.name.replace(/^Aniyomi:\s*/i, '');
        btn.textContent = `📦 ${cleanName}`;
        btn.title = ext.name;
        btn.onclick = () => setPaletteSource(ext.pkg, btn);
        tabsBar.appendChild(btn);
        existingChips.add(ext.pkg);
      }
    });
  } catch (err) {
    // Ignore network error silently
  }
}

function openCommandPalette(initialQuery) {
  const modal = document.getElementById('command-palette-backdrop');
  const input = document.getElementById('palette-search-input');
  if (!modal || !input) return;

  modal.style.display = 'flex';
  document.body.style.overflow = 'hidden';

  // Synchronise dynamiquement les extensions actives
  syncPaletteExtensionTabs();

  if (typeof initialQuery === 'string' && initialQuery.trim().length > 0) {
    input.value = initialQuery;
  }
  input.focus();
  input.select();

  const clearBtn = document.getElementById('palette-clear-btn');
  if (clearBtn) clearBtn.style.display = input.value.trim() ? 'inline-flex' : 'none';

  if (input.value.trim().length >= 2) {
    input.dispatchEvent(new Event('input'));
  }
}

function closeCommandPalette(event) {
  if (event && event.target && event.target.closest('.palette-card')) return;
  const modal = document.getElementById('command-palette-backdrop');
  if (modal) {
    modal.style.display = 'none';
    document.body.style.overflow = '';
  }
}

function clearPaletteInput() {
  const input = document.getElementById('palette-search-input');
  const clearBtn = document.getElementById('palette-clear-btn');
  const emptyHint = document.getElementById('palette-empty-hint');
  const columns = document.getElementById('palette-columns');
  const loading = document.getElementById('palette-loading');
  const noResults = document.getElementById('palette-no-results');
  const countText = document.getElementById('palette-results-count');

  if (input) {
    input.value = '';
    input.focus();
  }
  if (clearBtn) clearBtn.style.display = 'none';
  if (emptyHint) emptyHint.style.display = 'flex';
  if (columns) columns.style.display = 'none';
  if (loading) loading.style.display = 'none';
  if (noResults) noResults.style.display = 'none';
  if (countText) countText.textContent = 'Prêt';
}

function setPaletteSource(source, chipBtn) {
  const tabs = document.querySelectorAll('.palette-tab-chip');
  tabs.forEach(t => t.classList.toggle('active', t === chipBtn));

  const topSource = document.getElementById('topbar-search-source');
  if (topSource) topSource.value = source;

  const input = document.getElementById('palette-search-input');
  if (input && input.value.trim().length >= 2) {
    input.dispatchEvent(new Event('input'));
  }
}

function handleTopbarSearchSubmit(event) {
  event.preventDefault();
  const input = document.getElementById('topbar-search-input');
  const val = input ? input.value.trim() : '';
  openCommandPalette(val);
}

function initSearchAutocomplete() {
  const formatProxyImage = (url) => {
    if (!url) return '';
    if ((url.includes('voir-anime') || url.includes('voembed') || url.includes('vidmoly') || url.includes('animepahe') || url.includes('anime-sama') || url.includes('jetanime')) && !url.startsWith('/api/media/image-proxy')) {
      return `/api/media/image-proxy?url=${encodeURIComponent(url)}`;
    }
    return url;
  };

  // 1. Liaison de la modale globale Command Palette
  const bindPaletteModal = () => {
    const input = document.getElementById('palette-search-input');
    const clearBtn = document.getElementById('palette-clear-btn');
    const emptyHint = document.getElementById('palette-empty-hint');
    const loading = document.getElementById('palette-loading');
    const columns = document.getElementById('palette-columns');
    const listCol = document.getElementById('palette-list-col');
    const noResults = document.getElementById('palette-no-results');
    const countText = document.getElementById('palette-results-count');
    if (!input || !columns || !listCol) return;

    let debounceTimer = null;
    let selectedIndex = 0;
    let currentResults = [];

    // Fonctions d'étiquetage des sources (accessibles partout dans la palette)
    const getSourceLabel = (srcKey) => {
      if (!srcKey || srcKey === 'french-manga') return 'French-Manga';
      if (srcKey === 'voir-anime') return 'VoirAnime';
      if (srcKey === 'animepahe') return 'AnimePahe';
      const tabEl = Array.from(document.querySelectorAll('.palette-tab-chip')).find(el => el.dataset.src === srcKey);
      if (tabEl) return tabEl.textContent.replace('📦', '').trim();
      const parts = srcKey.split('.');
      const last = parts[parts.length - 1];
      return last.charAt(0).toUpperCase() + last.slice(1);
    };

    const getSourceTagClass = (srcKey) => {
      if (srcKey === 'voir-anime') return 'source-tag-voir-anime';
      if (srcKey === 'animepahe') return 'source-tag-animepahe';
      if (srcKey === 'french-manga') return 'source-tag-french-manga';
      return 'source-tag-imported';
    };

    const getActiveSource = () => {
      const activeTab = document.querySelector('.palette-tab-chip.active');
      return activeTab?.dataset.src || 'all';
    };

    const updatePreview = (item) => {
      if (!item) return;
      const previewBackdrop = document.getElementById('palette-preview-backdrop');
      const previewPoster = document.getElementById('palette-preview-poster');
      const previewTitle = document.getElementById('palette-preview-title');
      const previewMeta = document.getElementById('palette-preview-meta');
      const previewDesc = document.getElementById('palette-preview-desc');
      const previewCta = document.getElementById('palette-preview-cta');

      const imgUrl = formatProxyImage(item.imageUrl);
      if (previewPoster) {
        if (imgUrl) {
          previewPoster.src = imgUrl;
          previewPoster.style.display = 'block';
          if (previewBackdrop) previewBackdrop.style.backgroundImage = `url('${imgUrl}')`;
        } else {
          previewPoster.style.display = 'none';
          if (previewBackdrop) previewBackdrop.style.backgroundImage = 'none';
        }
      }

      if (previewTitle) previewTitle.textContent = item.title || '';
      if (previewDesc) previewDesc.textContent = item.synopsis || item.description || (item.episodeInfo ? `Informations : ${item.episodeInfo}` : '');

      const src = item.source || getActiveSource();
      const sourceLabel = getSourceLabel(src);
      const sourceTagClass = getSourceTagClass(src);

      if (previewMeta) {
        let metaHtml = `<span class="source-tag ${sourceTagClass}">${escapeHtml(sourceLabel)}</span>`;
        if (item.version) {
          metaHtml += `<span class="autocomplete-badge ${item.version.toUpperCase() === 'VF' ? 'autocomplete-badge-vf' : 'autocomplete-badge-vostfr'}">${escapeHtml(item.version)}</span>`;
        }
        if (item.type) {
          metaHtml += `<span style="font-size:11px;color:var(--muted);">${escapeHtml(item.type)}</span>`;
        }
        if (item.episodeInfo) {
          metaHtml += `<span style="font-size:11px;color:var(--muted);">${escapeHtml(item.episodeInfo)}</span>`;
        }
        previewMeta.innerHTML = metaHtml;
      }

      if (previewCta) {
        previewCta.href = `/anime?url=${encodeURIComponent(item.url)}&source=${encodeURIComponent(src)}`;
      }
    };

    const updateSelection = (items) => {
      items.forEach((itemEl, idx) => {
        if (idx === selectedIndex) {
          itemEl.classList.add('selected');
          itemEl.scrollIntoView({ block: 'nearest' });
          if (currentResults[idx]) {
            updatePreview(currentResults[idx]);
          }
        } else {
          itemEl.classList.remove('selected');
        }
      });
    };

    const renderPaletteModalResults = (results, source) => {
      currentResults = results || [];
      selectedIndex = 0;
      if (loading) loading.style.display = 'none';

      if (!results || results.length === 0) {
        if (emptyHint) emptyHint.style.display = 'none';
        if (columns) columns.style.display = 'none';
        if (noResults) {
          noResults.style.display = 'flex';
          const query = input.value.trim();
          noResults.innerHTML = `
            <div style="font-size:32px;margin-bottom:8px;opacity:0.6;">🔍</div>
            <div style="font-weight:600;font-size:15px;color:var(--text);">Aucun résultat trouvé pour "${escapeHtml(query)}"</div>
            <div style="font-size:12px;color:var(--muted);margin-top:4px;">
              ${source !== 'all' ? 'Essayez de sélectionner l\'onglet <strong>Toutes (Multi)</strong> pour chercher sur tous les catalogues.' : 'Vérifiez l\'orthographe ou essayez un titre alternatif.'}
            </div>
          `;
        }
        if (countText) countText.textContent = '0 résultat';
        return;
      }

      if (emptyHint) emptyHint.style.display = 'none';
      if (noResults) noResults.style.display = 'none';
      if (columns) columns.style.display = 'grid';
      if (countText) countText.textContent = `${results.length} résultat(s)`;

      let listHtml = '';
      results.forEach((item, idx) => {
        const actualSource = item.source || (item.url && item.url.includes('animepahe') ? 'animepahe' : (item.url && item.url.includes('voir-anime') ? 'voir-anime' : 'french-manga'));
        item.source = actualSource;
        const imgUrl = formatProxyImage(item.imageUrl);
        const posterHtml = imgUrl ? `
          <img class="autocomplete-poster" src="${imgUrl}" alt="" loading="lazy"
               onerror="this.style.display='none';this.nextElementSibling.style.display='flex';"/>
          <div class="autocomplete-poster-placeholder" style="display:none;">🎬</div>
        ` : `
          <div class="autocomplete-poster-placeholder">🎬</div>
        `;

        const versionBadge = item.version ? `
          <span class="autocomplete-badge ${item.version.toUpperCase() === 'VF' ? 'autocomplete-badge-vf' : 'autocomplete-badge-vostfr'}">${escapeHtml(item.version)}</span>
        ` : '';

        const sourceLabel = getSourceLabel(actualSource);
        const sourceTagClass = getSourceTagClass(actualSource);

        listHtml += `
          <a href="/anime?url=${encodeURIComponent(item.url)}&source=${encodeURIComponent(actualSource)}"
             class="autocomplete-item ${idx === 0 ? 'selected' : ''}"
             data-index="${idx}">
            ${posterHtml}
            <div class="autocomplete-info">
              <div class="autocomplete-title">${escapeHtml(item.title)}</div>
              <div class="autocomplete-sub">
                <span class="source-tag ${sourceTagClass}">${sourceLabel}</span>
                ${versionBadge}
                ${item.episodeInfo ? `<span>• ${escapeHtml(item.episodeInfo)}</span>` : ''}
              </div>
            </div>
          </a>
        `;
      });

      listCol.innerHTML = listHtml;
      updatePreview(results[0]);

      const itemEls = listCol.querySelectorAll('.autocomplete-item');
      itemEls.forEach((el, idx) => {
        el.addEventListener('mouseenter', () => {
          selectedIndex = idx;
          itemEls.forEach((it, i) => it.classList.toggle('selected', i === idx));
          if (currentResults[idx]) updatePreview(currentResults[idx]);
        });
      });
    };

    input.addEventListener('input', () => {
      clearTimeout(debounceTimer);
      const query = input.value.trim();
      if (clearBtn) clearBtn.style.display = query.length > 0 ? 'inline-flex' : 'none';

      if (query.length < 2) {
        if (emptyHint) emptyHint.style.display = 'flex';
        if (columns) columns.style.display = 'none';
        if (loading) loading.style.display = 'none';
        if (noResults) noResults.style.display = 'none';
        if (countText) countText.textContent = 'Prêt';
        return;
      }

      const source = getActiveSource();
      const cacheKey = `${query.toLowerCase()}:${source}`;

      if (searchMemoryCache.has(cacheKey)) {
        renderPaletteModalResults(searchMemoryCache.get(cacheKey), source);
        return;
      }

      if (emptyHint) emptyHint.style.display = 'none';
      if (columns) columns.style.display = 'none';
      if (noResults) noResults.style.display = 'none';
      if (loading) loading.style.display = 'flex';

      debounceTimer = setTimeout(async () => {
        try {
          const resp = await fetch(`/api/search?q=${encodeURIComponent(query)}&source=${encodeURIComponent(source)}`);
          if (!resp.ok) return;
          const results = await resp.json();
          searchMemoryCache.set(cacheKey, results || []);
          renderPaletteModalResults(results || [], source);
        } catch (e) {
          if (loading) loading.style.display = 'none';
        }
      }, 300);
    });

    input.addEventListener('keydown', (e) => {
      const items = Array.from(listCol.querySelectorAll('.autocomplete-item'));
      if (e.key === 'ArrowDown') {
        if (items.length === 0) return;
        e.preventDefault();
        selectedIndex = (selectedIndex + 1) % items.length;
        updateSelection(items);
      } else if (e.key === 'ArrowUp') {
        if (items.length === 0) return;
        e.preventDefault();
        selectedIndex = (selectedIndex - 1 + items.length) % items.length;
        updateSelection(items);
      } else if (e.key === 'Enter') {
        if (items.length > 0 && selectedIndex >= 0 && items[selectedIndex]) {
          e.preventDefault();
          items[selectedIndex].click();
        }
      } else if (e.key === 'Escape') {
        closeCommandPalette();
      }
    });
  };

  bindPaletteModal();

  // 2. Synchronisation dynamique du changement de source
  document.querySelectorAll('input[name="source"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
      const topbarSource = document.getElementById('topbar-search-source');
      if (topbarSource) topbarSource.value = e.target.value;

      const paletteChip = document.querySelector(`.palette-tab-chip[data-src="${e.target.value}"]`);
      if (paletteChip) {
        document.querySelectorAll('.palette-tab-chip').forEach(t => t.classList.remove('active'));
        paletteChip.classList.add('active');
      }
    });
  });
}

// =========================================================================
// Pagination par tranches d'épisodes et filtres de sélection par lot
// =========================================================================

function initEpisodeRangePagination() {
  const list = document.getElementById('episode-list');
  const bar = document.getElementById('episode-range-bar');
  if (!list || !bar) return;

  const items = Array.from(list.querySelectorAll('.episode-item'));
  if (items.length <= 40) {
    bar.style.display = 'none';
  } else {
    const nums = items.map(el => parseInt(el.dataset.num, 10)).filter(n => !isNaN(n));
    if (nums.length > 0) {
      const minNum = Math.min(...nums);
      const maxNum = Math.max(...nums);

      bar.innerHTML = '';
      const rangeSize = 50;

      const allChip = document.createElement('button');
      allChip.type = 'button';
      allChip.className = 'episode-range-chip active';
      allChip.textContent = `Tous (${items.length})`;
      allChip.onclick = () => filterEpisodeRange('all', allChip);
      bar.appendChild(allChip);

      for (let start = minNum; start <= maxNum; start += rangeSize) {
        const end = Math.min(start + rangeSize - 1, maxNum);
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'episode-range-chip';
        chip.textContent = `${start} - ${end}`;
        chip.onclick = () => filterEpisodeRange(`${start}-${end}`, chip);
        bar.appendChild(chip);
      }
    }
  }

  const searchInput = document.getElementById('episode-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      const q = e.target.value.trim();
      if (!q) {
        filterEpisodeRange(currentRange);
        return;
      }
      items.forEach(el => {
        const n = el.dataset.num;
        el.style.display = (n === q || (el.dataset.title || '').toLowerCase().includes(q.toLowerCase())) ? '' : 'none';
      });
    });
  }
}

function filterEpisodeRange(range, chipEl = null) {
  currentRange = range;
  if (chipEl) {
    document.querySelectorAll('.episode-range-chip').forEach(c => c.classList.remove('active'));
    chipEl.classList.add('active');
  }
  const items = document.querySelectorAll('.episode-item');
  if (range === 'all') {
    items.forEach(el => el.style.display = '');
    return;
  }
  const [start, end] = range.split('-').map(Number);
  items.forEach(el => {
    const n = parseInt(el.dataset.num, 10);
    el.style.display = (n >= start && n <= end) ? '' : 'none';
  });
}

function selectBatchFilter(mode) {
  const items = document.querySelectorAll('.episode-item');
  items.forEach(row => {
    if (row.style.display === 'none') return;
    const cb = row.querySelector('.episode-check');
    if (!cb) return;

    if (mode === 'not-downloaded') {
      cb.checked = !row.classList.contains('ep-downloaded');
    } else if (mode === 'not-watched') {
      cb.checked = !row.classList.contains('ep-watched');
    } else if (mode === 'invert') {
      cb.checked = !cb.checked;
    }
  });
  onEpisodeCheckChange();
}

// =========================================================================
// Calcul de l'ETA et vitesse de téléchargement
// =========================================================================

function formatEta(seconds) {
  if (isNaN(seconds) || seconds <= 0 || !isFinite(seconds)) return '';
  if (seconds < 60) return `~${seconds}s restantes`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins < 60) return `~${mins}m ${secs}s`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return `~${hours}h ${remMins}m`;
}

function parseSpeedToBytes(speedStr) {
  if (!speedStr || typeof speedStr !== 'string') return 0;
  const match = speedStr.match(/^([\d.]+)\s*([KMGT]?B\/s)/i);
  if (!match) return 0;
  const val = parseFloat(match[1]);
  const unit = match[2].toUpperCase();
  if (unit.startsWith('K')) return val * 1024;
  if (unit.startsWith('M')) return val * 1024 * 1024;
  if (unit.startsWith('G')) return val * 1024 * 1024 * 1024;
  return val;
}

// =========================================================================
// Fonctions de vérification d'intégrité et de re-téléchargement
// =========================================================================

async function verifyTask(taskId, triggerEl) {
  const btn = triggerEl || document.querySelector(`[data-id="${taskId}"] [onclick*="verifyTask"]`);
  const originalHtml = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-sm" style="display:inline-block;width:12px;height:12px;"></span>';
  }
  showToast('Vérification du fichier en cours...', 'info');

  try {
    const resp = await fetch(`/api/download/${taskId}/verify`, { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
      showToast(data.error || 'Erreur lors de la vérification', 'error');
      return;
    }

    if (data.valid) {
      const dur = data.formattedDuration ? ` (${data.formattedDuration})` : '';
      showToast(`Fichier intègre et lisible${dur} • ${data.formattedSize}`, 'success');
    } else {
      showToast(`Problème détecté : ${data.error || data.status}`, 'error');
    }

    // Mettre à jour l'élément dans downloads ou history
    const row = document.getElementById(`task-${taskId}`) || document.getElementById(`history-row-${taskId}`);
    if (row) {
      row.dataset.verification = data.status;
      const verifBadge = row.querySelector('.dl-verif-badge') || document.getElementById(`history-verif-badge-${taskId}`);
      if (verifBadge) {
        if (data.valid) {
          verifBadge.className = 'status-badge dl-verif-badge badge-ok';
          verifBadge.textContent = `✓ Valide${data.formattedDuration ? ' • ' + data.formattedDuration : ''}`;
          verifBadge.title = 'Fichier intègre et lisible sur le disque';
        } else if (data.status === 'MISSING') {
          verifBadge.className = 'status-badge dl-verif-badge badge-err';
          verifBadge.textContent = '⚠ Manquant';
          verifBadge.title = data.error || 'Fichier introuvable sur le disque';
        } else if (data.status === 'EMPTY') {
          verifBadge.className = 'status-badge dl-verif-badge badge-err';
          verifBadge.textContent = '✗ Vide';
          verifBadge.title = 'Fichier de 0 octet';
        } else {
          verifBadge.className = 'status-badge dl-verif-badge badge-err';
          verifBadge.textContent = '✗ Corrompu';
          verifBadge.title = data.error || 'Fichier vidéo corrompu';
        }
      }

      const actEl = row.querySelector('.dl-task-actions');
      if (actEl) {
        const taskObj = {
          id: taskId,
          status: row.dataset.status || 'COMPLETED',
          verificationStatus: data.status,
          animeName: actEl.dataset.animename || '',
          episodeNumber: actEl.dataset.episodenumber || '',
        };
        actEl.innerHTML = renderTaskActions(taskObj);
      }
    }
  } catch (e) {
    showToast('Erreur de communication : ' + e.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }
}

async function verifyAllCompletedTasks() {
  const btn = document.getElementById('btn-verify-all-downloads') || document.getElementById('btn-verify-history');
  const originalHtml = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-sm" style="display:inline-block;width:14px;height:14px;margin-right:6px;"></span>Vérification en cours...';
  }
  showToast('Vérification de l\'ensemble des fichiers en cours...', 'info');

  try {
    const resp = await fetch('/api/download/verify-all', { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok || !data.success) {
      showToast(data.error || 'Erreur lors de la vérification globale', 'error');
      return;
    }

    const issues = (data.missing || 0) + (data.corrupted || 0) + (data.empty || 0);
    if (issues === 0) {
      showToast(`Tous les fichiers (${data.valid}/${data.total}) sont intègres et valides !`, 'success');
    } else {
      showToast(`Vérification : ${data.valid} valide(s), ${data.missing} manquant(s), ${data.corrupted + data.empty} corrompu(s)`, 'error');
    }

    if (Array.isArray(data.results)) {
      data.results.forEach(res => {
        const row = document.getElementById(`task-${res.taskId}`) || document.getElementById(`history-row-${res.taskId}`);
        if (row) {
          row.dataset.verification = res.status;
          const badge = row.querySelector('.dl-verif-badge') || document.getElementById(`history-verif-badge-${res.taskId}`);
          if (badge) {
            if (res.valid) {
              badge.className = 'status-badge dl-verif-badge badge-ok';
              badge.textContent = `✓ Valide${res.formattedDuration ? ' • ' + res.formattedDuration : ''}`;
              badge.title = 'Fichier intègre et lisible sur le disque';
            } else if (res.status === 'MISSING') {
              badge.className = 'status-badge dl-verif-badge badge-err';
              badge.textContent = '⚠ Manquant';
              badge.title = res.error || 'Fichier introuvable';
            } else if (res.status === 'EMPTY') {
              badge.className = 'status-badge dl-verif-badge badge-err';
              badge.textContent = '✗ Vide';
              badge.title = 'Fichier de 0 octet';
            } else {
              badge.className = 'status-badge dl-verif-badge badge-err';
              badge.textContent = '✗ Corrompu';
              badge.title = res.error || 'Fichier corrompu';
            }
          }

          const actEl = row.querySelector('.dl-task-actions');
          if (actEl) {
            const taskObj = {
              id: res.taskId,
              status: row.dataset.status || 'COMPLETED',
              verificationStatus: res.status,
              animeName: actEl.dataset.animename || '',
              episodeNumber: actEl.dataset.episodenumber || '',
            };
            actEl.innerHTML = renderTaskActions(taskObj);
          }
        }
      });
    }
  } catch (e) {
    showToast('Erreur : ' + e.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }
}

async function redownloadTask(taskId) {
  showToast('Relance du téléchargement...', 'info');
  try {
    const resp = await fetch(`/api/download/${taskId}/redownload`, { method: 'POST' });
    const data = await resp.json();
    if (data.success) {
      showToast(data.message || 'Téléchargement relancé avec succès', 'success');
      const activeTabBtn = document.querySelector('.dl-tab[data-group="active"]');
      if (activeTabBtn) {
        activeTabBtn.click();
      } else if (window.location.pathname === '/history') {
        setTimeout(() => { window.location.href = '/downloads'; }, 800);
      }
    } else {
      showToast(data.error || 'Impossible de relancer le téléchargement', 'error');
    }
  } catch (e) {
    showToast('Erreur : ' + e.message, 'error');
  }
}

/* ==========================================================================
   Tachiyomi Page Controllers & Interactivity
   ========================================================================== */

function toggleSynopsis() {
  const box = document.getElementById('tachiyomi-synopsis');
  if (box) {
    box.classList.toggle('expanded');
  }
}

function toggleMassiveDownloadMenu(event) {
  if (event) event.stopPropagation();
  const menu = document.getElementById('tachiyomi-download-menu');
  const overflow = document.getElementById('tachiyomi-overflow-menu');
  if (overflow) {
    overflow.classList.remove('show');
    overflow.style.display = 'none';
  }
  if (menu) {
    const isShowing = menu.classList.toggle('show');
    menu.style.display = isShowing ? 'flex' : 'none';
  }
}

function toggleTachiyomiOverflowMenu(event) {
  if (event) event.stopPropagation();
  const menu = document.getElementById('tachiyomi-overflow-menu');
  const dlMenu = document.getElementById('tachiyomi-download-menu');
  if (dlMenu) {
    dlMenu.classList.remove('show');
    dlMenu.style.display = 'none';
  }
  if (menu) {
    const isShowing = menu.classList.toggle('show');
    menu.style.display = isShowing ? 'flex' : 'none';
  }
}

document.addEventListener('click', (e) => {
  const dlMenu = document.getElementById('tachiyomi-download-menu');
  if (dlMenu && !dlMenu.contains(e.target) && !e.target.closest('#tach-dl-menu-btn')) {
    dlMenu.classList.remove('show');
    dlMenu.style.display = 'none';
  }
  const overflow = document.getElementById('tachiyomi-overflow-menu');
  if (overflow && !overflow.contains(e.target) && !e.target.closest('#tach-overflow-btn')) {
    overflow.classList.remove('show');
    overflow.style.display = 'none';
  }
});

function toggleTachiyomiFilterModal(event) {
  if (event) event.stopPropagation();
  const sheet = document.getElementById('tachiyomi-filter-sheet');
  if (sheet) sheet.classList.toggle('show');
}

function closeTachiyomiFilterModal() {
  const sheet = document.getElementById('tachiyomi-filter-sheet');
  if (sheet) sheet.classList.remove('show');
}

function onFilterOverlayClick(e) {
  if (e.target.id === 'tachiyomi-filter-sheet') {
    closeTachiyomiFilterModal();
  }
}

function switchTachiyomiTab(tabName) {
  document.querySelectorAll('.tachiyomi-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  document.querySelectorAll('.tachiyomi-tab-panel').forEach(panel => {
    panel.classList.toggle('active', panel.id === `tach-tab-${tabName}`);
  });
}

async function toggleTachiyomiAutoDl(btn) {
  const animeUrl = typeof ANIME_URL !== 'undefined' ? ANIME_URL : '';
  if (!animeUrl) return;

  const isActive = btn.classList.contains('active');
  const newAutoDl = !isActive;

  try {
    const resp = await fetch('/api/library/toggle-auto-download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: animeUrl, autoDownload: newAutoDl })
    });
    const data = await resp.json();
    if (data.success) {
      btn.classList.toggle('active', newAutoDl);
      showToast(newAutoDl ? 'Surveillance Watchdog (Auto-DL) activée !' : 'Auto-DL désactivé', 'info');
    } else {
      showToast(data.error || 'Erreur lors du changement d\'Auto-DL', 'error');
    }
  } catch (err) {
    showToast('Erreur : ' + err.message, 'error');
  }
}

// Téléchargement massif style Tachiyomi
function triggerTachiyomiBatch(type) {
  const menu = document.getElementById('tachiyomi-download-menu');
  if (menu) menu.classList.remove('show');

  const rows = Array.from(document.querySelectorAll('.episode-item, .tachiyomi-episode-item'));
  if (!rows.length) return;

  // Décocher tout d'abord
  document.querySelectorAll('.episode-check').forEach(cb => cb.checked = false);

  let targetRows = [];
  if (type === 'next-1') {
    const nextUnwatched = rows.find(r => !r.classList.contains('ep-watched') && r.dataset.downloaded !== 'true');
    targetRows = nextUnwatched ? [nextUnwatched] : (rows.find(r => r.dataset.downloaded !== 'true') ? [rows.find(r => r.dataset.downloaded !== 'true')] : []);
  } else if (type === 'next-5') {
    targetRows = rows.filter(r => !r.classList.contains('ep-watched') && r.dataset.downloaded !== 'true').slice(0, 5);
    if (targetRows.length === 0) targetRows = rows.filter(r => r.dataset.downloaded !== 'true').slice(0, 5);
  } else if (type === 'next-10') {
    targetRows = rows.filter(r => !r.classList.contains('ep-watched') && r.dataset.downloaded !== 'true').slice(0, 10);
    if (targetRows.length === 0) targetRows = rows.filter(r => r.dataset.downloaded !== 'true').slice(0, 10);
  } else if (type === 'next-25') {
    targetRows = rows.filter(r => !r.classList.contains('ep-watched') && r.dataset.downloaded !== 'true').slice(0, 25);
    if (targetRows.length === 0) targetRows = rows.filter(r => r.dataset.downloaded !== 'true').slice(0, 25);
  } else if (type === 'unwatched') {
    targetRows = rows.filter(r => !r.classList.contains('ep-watched') && r.dataset.downloaded !== 'true');
  } else if (type === 'not-downloaded') {
    targetRows = rows.filter(r => r.dataset.downloaded !== 'true');
  } else if (type === 'all') {
    targetRows = rows;
  }

  if (targetRows.length === 0) {
    showToast('Aucun épisode correspondant à télécharger.', 'info');
    return;
  }

  targetRows.forEach(row => {
    const cb = row.querySelector('.episode-check');
    if (cb) cb.checked = true;
  });

  showToast(`Lancement du téléchargement pour ${targetRows.length} épisode(s)...`, 'info');
  downloadSelected();
}

// Filtres et Tri Tachiyomi
let tachSortCriteria = 'number';
let tachSortAsc = false;

function applyTachiyomiFilters() {
  const filterDl = document.getElementById('tach-filter-downloaded')?.checked || false;
  const filterUnwatched = document.getElementById('tach-filter-unwatched')?.checked || false;
  const filterVf = document.getElementById('tach-filter-vf')?.checked || false;
  const filterVostfr = document.getElementById('tach-filter-vostfr')?.checked || false;

  const rows = Array.from(document.querySelectorAll('.episode-item, .tachiyomi-episode-item'));
  let visibleCount = 0;

  rows.forEach(row => {
    const isDl = row.dataset.downloaded === 'true' || row.classList.contains('ep-downloaded');
    const isWatched = row.classList.contains('ep-watched');
    const ver = (row.dataset.version || '').toUpperCase();

    let visible = true;
    if (filterDl && !isDl) visible = false;
    if (filterUnwatched && isWatched) visible = false;
    if (filterVf && !filterVostfr && !ver.includes('VF')) visible = false;
    if (filterVostfr && !filterVf && !ver.includes('VOSTFR')) visible = false;

    row.style.display = visible ? 'flex' : 'none';
    if (visible) visibleCount++;
  });

  const countEl = document.getElementById('tachiyomi-ep-count');
  if (countEl) countEl.textContent = visibleCount;

  sortTachiyomiEpisodes();
  updateTachiyomiFab();
}

function toggleTachSortDir() {
  tachSortAsc = !tachSortAsc;
  const btn = document.getElementById('tach-sort-dir-btn');
  const label = document.getElementById('tach-sort-dir-label');
  if (btn) btn.classList.toggle('asc', tachSortAsc);
  if (label) label.textContent = tachSortAsc ? 'Croissant' : 'Décroissant';
  sortTachiyomiEpisodes();
}

function selectTachSort(criteria) {
  tachSortCriteria = criteria;
  document.querySelectorAll('.tachiyomi-sort-option').forEach(opt => {
    opt.classList.toggle('active', opt.dataset.sort === criteria);
  });
  sortTachiyomiEpisodes();
}

function sortTachiyomiEpisodes() {
  const container = document.getElementById('episode-list');
  if (!container) return;

  const rows = Array.from(container.querySelectorAll('.episode-item, .tachiyomi-episode-item'));
  rows.sort((a, b) => {
    let valA = 0, valB = 0;
    if (tachSortCriteria === 'number') {
      valA = parseFloat(a.dataset.num) || 0;
      valB = parseFloat(b.dataset.num) || 0;
    } else if (tachSortCriteria === 'unwatched') {
      valA = a.classList.contains('ep-watched') ? 1 : 0;
      valB = b.classList.contains('ep-watched') ? 1 : 0;
    } else if (tachSortCriteria === 'alpha') {
      const tA = (a.dataset.title || '').toLowerCase();
      const tB = (b.dataset.title || '').toLowerCase();
      return tachSortAsc ? tA.localeCompare(tB) : tB.localeCompare(tA);
    }
    return tachSortAsc ? (valA - valB) : (valB - valA);
  });

  rows.forEach(r => container.appendChild(r));
}

// Floating Action Button
function updateTachiyomiFab() {
  const fab = document.getElementById('tachiyomi-fab');
  const fabText = document.getElementById('tachiyomi-fab-text');
  if (!fab || !fabText) return;

  const rows = Array.from(document.querySelectorAll('.episode-item, .tachiyomi-episode-item')).filter(r => r.style.display !== 'none');
  if (!rows.length) {
    fab.style.display = 'none';
    return;
  }
  fab.style.display = 'inline-flex';

  // Trouver le premier épisode non vu
  const isEn = getCurrentLang() === 'en';
  const firstUnwatched = rows.find(r => !r.classList.contains('ep-watched'));
  if (firstUnwatched) {
    const num = firstUnwatched.dataset.num;
    const startTxt = isEn ? 'Start' : 'Commencer';
    const resumeTxt = isEn ? `Resume (Ep. ${num})` : `Reprendre (Ep. ${num})`;
    fabText.textContent = (num === '1' || rows.length === 1) ? startTxt : resumeTxt;
    fab.dataset.targetNum = num;
  } else {
    fabText.textContent = isEn ? 'Rewatch (Ep. 1)' : 'Revoir (Ep. 1)';
    fab.dataset.targetNum = rows[0].dataset.num;
  }
}

function onTachiyomiFabClick() {
  const fab = document.getElementById('tachiyomi-fab');
  const targetNum = fab?.dataset.targetNum;
  if (!targetNum) return;

  const row = document.querySelector(`.episode-item[data-num="${targetNum}"], .tachiyomi-episode-item[data-num="${targetNum}"]`);
  if (row) {
    const playBtn = row.querySelector('.btn-play-ep') || row;
    playEpisode(playBtn);
  }
}

async function markAllEpisodes(watched) {
  const rows = Array.from(document.querySelectorAll('.episode-item, .tachiyomi-episode-item'));
  const animeUrl = typeof ANIME_URL !== 'undefined' ? ANIME_URL : '';
  const animeName = typeof ANIME_NAME !== 'undefined' ? ANIME_NAME : '';

  rows.forEach(row => {
    row.classList.toggle('ep-watched', watched);
  });

  updateTachiyomiFab();
  const isEn = getCurrentLang() === 'en';
  const msg = watched
    ? (isEn ? 'All episodes marked as watched' : 'Tous les épisodes ont été marqués comme vus')
    : (isEn ? 'All episodes marked as unwatched' : 'Tous les épisodes ont été marqués comme non vus');
  showToast(msg, 'info');

  const overflow = document.getElementById('tachiyomi-overflow-menu');
  if (overflow) overflow.classList.remove('show');
}

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('tachiyomi-fab')) {
    updateTachiyomiFab();
  }
});

// =============================================================================
// TELEGRAM-STYLE OFFLINE PROXY DETECTOR & PROMPT
// =============================================================================

const TELEGRAM_OFFLINE_STRINGS = {
  fr: {
    waiting: "En attente du réseau...",
    prompt: "Connexion interrompue. Se connecter via un proxy ?",
    btn_enable: "Activer le proxy",
    btn_configure: "Configurer un proxy",
    btn_settings: "Paramètres",
    reconnected: "Connecté !",
    dismiss: "Ignorer",
    enabling: "Activation...",
    enabled: "Proxy activé !"
  },
  en: {
    waiting: "Waiting for network...",
    prompt: "Connection lost. Connect via proxy?",
    btn_enable: "Enable proxy",
    btn_configure: "Configure proxy",
    btn_settings: "Settings",
    reconnected: "Connected!",
    dismiss: "Dismiss",
    enabling: "Enabling...",
    enabled: "Proxy enabled!"
  }
};

function getTgOfflineText(key) {
  const lang = (typeof getCurrentLang === 'function') ? getCurrentLang() : 'fr';
  return TELEGRAM_OFFLINE_STRINGS[lang]?.[key] || TELEGRAM_OFFLINE_STRINGS.fr[key] || '';
}

function initTelegramOfflineDetector() {
  let isOffline = !navigator.onLine;
  let banner = document.getElementById('telegram-offline-banner');

  function createBanner() {
    if (banner) return banner;
    banner = document.createElement('aside');
    banner.id = 'telegram-offline-banner';
    banner.className = 'tg-offline-banner';
    banner.setAttribute('role', 'status');
    banner.setAttribute('aria-live', 'polite');
    banner.innerHTML = `
      <div class="tg-indicator-icon" id="tg-indicator-icon">
        <svg id="tg-status-icon-offline" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="1" y1="1" x2="23" y2="23"/>
          <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"/>
          <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"/>
          <path d="M10.71 5.05A16 16 0 0 1 22.58 9"/>
          <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"/>
          <path d="M8.53 16.11a6 6 0 0 1 6.95 0"/>
          <line x1="12" y1="20" x2="12.01" y2="20"/>
        </svg>
        <svg id="tg-status-icon-online" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="display:none;">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      </div>
      <div class="tg-offline-text">
        <div class="tg-offline-title" id="tg-offline-title">${getTgOfflineText('waiting')}</div>
        <div class="tg-offline-sub" id="tg-offline-sub">${getTgOfflineText('prompt')}</div>
      </div>
      <div class="tg-offline-actions" id="tg-offline-actions"></div>
    `;
    document.body.appendChild(banner);
    return banner;
  }

  async function updateBannerActions() {
    const actionsEl = document.getElementById('tg-offline-actions');
    if (!actionsEl) return;

    let proxy = null;
    try {
      const r = await fetch('/api/proxy/settings');
      if (r.ok) proxy = await r.json();
    } catch (_) {}

    const hasHost = !!(proxy && proxy.host && String(proxy.host).trim());
    const isProxyEnabled = !!(proxy && proxy.enabled);

    if (hasHost && !isProxyEnabled) {
      actionsEl.innerHTML = `
        <button type="button" class="tg-action-btn-primary" id="tg-enable-proxy-btn">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/>
            <path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>
          </svg>
          <span>${getTgOfflineText('btn_enable')}</span>
        </button>
        <a href="/settings#proxy" class="tg-action-btn-subtle" title="${getTgOfflineText('btn_settings')}">
          ${getTgOfflineText('btn_settings')}
        </a>
        <button type="button" class="tg-action-btn-close" id="tg-dismiss-btn" aria-label="${getTgOfflineText('dismiss')}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      `;

      document.getElementById('tg-enable-proxy-btn')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const textSpan = btn.querySelector('span');
        btn.disabled = true;
        if (textSpan) textSpan.textContent = getTgOfflineText('enabling');
        try {
          const resp = await fetch('/api/proxy/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: true })
          });
          const res = await resp.json();
          if (res.success) {
            if (typeof showToast === 'function') showToast(getTgOfflineText('enabled'), 'success');
            // Tester la connectivité via le proxy
            fetch('/api/proxy/test', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({})
            }).then(r => r.json()).then(tRes => {
              if (tRes.success) {
                setOnlineState();
              }
            }).catch(() => {});
          }
        } catch (err) {
          if (typeof showToast === 'function') showToast(`Erreur: ${err.message}`, 'error');
        } finally {
          btn.disabled = false;
          if (textSpan) textSpan.textContent = getTgOfflineText('btn_enable');
        }
      });
    } else {
      actionsEl.innerHTML = `
        <a href="/settings#proxy" class="tg-action-btn-primary">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/>
            <path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>
          </svg>
          <span>${getTgOfflineText('btn_configure')}</span>
        </a>
        <button type="button" class="tg-action-btn-close" id="tg-dismiss-btn" aria-label="${getTgOfflineText('dismiss')}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      `;
    }

    document.getElementById('tg-dismiss-btn')?.addEventListener('click', () => {
      sessionStorage.setItem('animan_offline_dismissed', '1');
      banner?.classList.remove('show');
    });
  }

  function setOfflineState() {
    isOffline = true;
    if (sessionStorage.getItem('animan_offline_dismissed') === '1') return;

    createBanner();
    banner.classList.remove('connected');
    const offIcon = document.getElementById('tg-status-icon-offline');
    const onIcon = document.getElementById('tg-status-icon-online');
    if (offIcon) offIcon.style.display = '';
    if (onIcon) onIcon.style.display = 'none';

    const titleEl = document.getElementById('tg-offline-title');
    const subEl = document.getElementById('tg-offline-sub');
    if (titleEl) titleEl.textContent = getTgOfflineText('waiting');
    if (subEl) {
      subEl.textContent = getTgOfflineText('prompt');
      subEl.style.display = '';
    }

    updateBannerActions();
    banner.classList.add('show');
  }

  function setOnlineState() {
    isOffline = false;
    sessionStorage.removeItem('animan_offline_dismissed');
    if (!banner || !banner.classList.contains('show')) return;

    banner.classList.add('connected');
    const offIcon = document.getElementById('tg-status-icon-offline');
    const onIcon = document.getElementById('tg-status-icon-online');
    if (offIcon) offIcon.style.display = 'none';
    if (onIcon) onIcon.style.display = '';

    const titleEl = document.getElementById('tg-offline-title');
    const subEl = document.getElementById('tg-offline-sub');
    if (titleEl) titleEl.textContent = getTgOfflineText('reconnected');
    if (subEl) subEl.style.display = 'none';

    const actionsEl = document.getElementById('tg-offline-actions');
    if (actionsEl) actionsEl.innerHTML = '';

    setTimeout(() => {
      banner.classList.remove('show');
      setTimeout(() => {
        banner.classList.remove('connected');
      }, 400);
    }, 2200);
  }

  window.addEventListener('offline', setOfflineState);
  window.addEventListener('online', setOnlineState);

  // Hook global pour simuler / tester en direct
  window.__simulateOffline = (offline) => {
    if (offline) {
      sessionStorage.removeItem('animan_offline_dismissed');
      setOfflineState();
    } else {
      setOnlineState();
    }
  };

  if (!navigator.onLine) {
    setOfflineState();
  }
}

window.initTelegramOfflineDetector = initTelegramOfflineDetector;

