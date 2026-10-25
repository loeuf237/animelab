'use strict';
const messages = {
  en: {
    title: 'Administration', intro: 'Manage this computer’s local application.', state: 'Local server',
    open: 'Open AnimeLab', local: 'Accessible only on this computer. Closing this tab leaves the server running.',
    config: 'Startup settings', port: 'Application port', browser: 'Open in my browser instead of a native window',
    applyHint: 'Save, then restart to apply. Active downloads are paused and kept for resuming.', save: 'Save settings',
    tools: 'Maintenance', diagnose: 'Run quick diagnosis', restart: 'Restart the server', stop: 'Quit AnimeLab',
    checks: 'Checks the interface, SQLite, write access, media tools and the local server. No source websites are contacted.',
    export: 'Download diagnostic report', logs: 'Local logs: ~/.animan/desktop/desktop.log and engine.log (your user folder on Windows). Reports omit raw logs, cookies and proxy credentials.',
    recovery: 'If startup fails, reopen Administration from the extracted application folder. No administrator privileges are required.',
    ready: 'Ready', waiting: 'Starting…', offline: 'Stopped', saved: 'Settings saved. Restart to apply them.',
    confirmRestart: 'Restart AnimeLab? Active downloads will be paused and kept for resuming.',
    confirmStop: 'Quit AnimeLab? Downloads will be paused. Reopen the launcher to resume.',
    stopped: 'AnimeLab has stopped. You can close this tab.', restarting: 'Restart requested. Server status updates automatically.',
    stopping: 'Stopping AnimeLab. Downloads are being saved…',
    disconnected: 'The desktop launcher is not responding. Reopen Administration from the application folder.',
    unauthorized: 'Reopen Administration from the AnimeLab launcher to authorize this tab.',
    fallback: 'The requested port is busy. AnimeLab is using a different port; no other application was stopped.',
    native: 'The native window could not open. You can use AnimeLab in your browser.',
    pending: 'Saved startup settings will take effect after restarting.',
    failed: 'The engine is unavailable. Run diagnostics, then try restarting.',
    testing: 'Running local checks…', complete: 'All checks passed.', issues: 'Some checks failed. See the results below.',
    frontend: 'Web interface', desktop_storage: 'Desktop storage', download_storage: 'Download folder', database: 'SQLite database',
    ffmpeg: 'FFmpeg', ffprobe: 'FFprobe', backend: 'Local engine', good: 'OK', bad: 'Failed',
  },
  fr: {
    title: 'Administration', intro: 'Gérez l’application locale de cet ordinateur.', state: 'Serveur local',
    open: 'Ouvrir AnimeLab', local: 'Accessible uniquement sur cet ordinateur. Fermer cet onglet laisse le serveur actif.',
    config: 'Paramètres de démarrage', port: 'Port de l’application', browser: 'Ouvrir dans mon navigateur plutôt que dans une fenêtre native',
    applyHint: 'Enregistrez, puis redémarrez pour appliquer. Les téléchargements actifs seront suspendus et conservés pour reprise.', save: 'Enregistrer',
    tools: 'Maintenance', diagnose: 'Lancer le diagnostic rapide', restart: 'Redémarrer le serveur', stop: 'Quitter AnimeLab',
    checks: 'Vérifie l’interface, SQLite, les accès en écriture, les outils vidéo et le serveur local. Aucun site source n’est contacté.',
    export: 'Télécharger le rapport de diagnostic', logs: 'Journaux locaux : ~/.animan/desktop/desktop.log et engine.log (dans votre dossier utilisateur sous Windows). Les rapports excluent les journaux bruts, cookies et identifiants de proxy.',
    recovery: 'En cas d’échec du démarrage, rouvrez Administration depuis le dossier de l’application extraite. Aucun droit administrateur n’est nécessaire.',
    ready: 'Prêt', waiting: 'Démarrage…', offline: 'Arrêté', saved: 'Paramètres enregistrés. Redémarrez pour les appliquer.',
    confirmRestart: 'Redémarrer AnimeLab ? Les téléchargements seront suspendus et conservés pour reprise.',
    confirmStop: 'Quitter AnimeLab ? Les téléchargements seront suspendus. Rouvrez le lanceur pour reprendre.',
    stopped: 'AnimeLab est arrêté. Vous pouvez fermer cet onglet.', restarting: 'Redémarrage demandé. L’état du serveur s’actualise automatiquement.',
    stopping: 'Arrêt d’AnimeLab en cours. Les téléchargements sont en cours de sauvegarde…',
    disconnected: 'Le lanceur ne répond pas. Rouvrez Administration depuis le dossier de l’application.',
    unauthorized: 'Rouvrez Administration depuis le lanceur AnimeLab pour autoriser cet onglet.',
    fallback: 'Le port demandé est occupé. AnimeLab utilise un autre port ; aucune autre application n’a été arrêtée.',
    native: 'La fenêtre native n’a pas pu s’ouvrir. Vous pouvez utiliser AnimeLab dans le navigateur.',
    pending: 'Les paramètres enregistrés prendront effet après le redémarrage.',
    failed: 'Le moteur est indisponible. Lancez le diagnostic, puis essayez de redémarrer.',
    testing: 'Vérifications locales en cours…', complete: 'Toutes les vérifications ont réussi.', issues: 'Certaines vérifications ont échoué. Consultez les résultats.',
    frontend: 'Interface web', desktop_storage: 'Stockage de l’application', download_storage: 'Dossier des téléchargements', database: 'Base SQLite',
    ffmpeg: 'FFmpeg', ffprobe: 'FFprobe', backend: 'Moteur local', good: 'OK', bad: 'Échec',
  },
};
const $ = (id) => document.getElementById(id);
let language = (navigator.language || 'en').startsWith('fr') ? 'fr' : 'en';
let token = location.hash.slice(1);
try {
  token = token || sessionStorage.getItem('animelab-desktop') || '';
  if (token) sessionStorage.setItem('animelab-desktop', token);
} catch { /* A restricted browser can still use this tab's fragment capability. */ }
history.replaceState(null, '', location.pathname);
let initialized = false, stopped = false, report = null, status = null;
const t = (key) => messages[language][key] || key;
function notice(key) { $('notice').textContent = t(key); }
function translate() {
  document.documentElement.lang = language;
  $('language').value = language;
  document.querySelectorAll('[data-i18n]').forEach((node) => { node.textContent = t(node.dataset.i18n); });
  if (status) render(status);
  if (report) renderReport();
}
$('language').addEventListener('change', () => { language = $('language').value; translate(); });
async function api(path, data) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  let response;
  try { response = await fetch(path, {
    method: data ? 'POST' : 'GET', cache: 'no-store',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: data ? JSON.stringify(data) : undefined,
    signal: controller.signal,
  }); }
  finally { clearTimeout(timeout); }
  if (response.status === 401) throw new Error('unauthorized');
  if (!response.ok) throw new Error('disconnected');
  return response.json();
}
function render(value) {
  status = value;
  $('state').textContent = t(value.busy ? 'waiting' : value.ready ? 'ready' : value.running ? 'waiting' : 'offline');
  $('address').textContent = value.url || '—';
  $('open-app').hidden = !value.ready || value.busy;
  if (value.ready && /^http:\/\/127\.0\.0\.1:\d+\/spa\/(?:downloads|library|sources|extensions|settings)?$/.test(value.url)) $('open-app').href = value.url;
  $('warning').textContent = [value.portFallback && t('fallback'), value.pendingRestart && t('pending'), value.nativeError && t('native'), value.error && t('failed')].filter(Boolean).join(' ');
  $('restart').disabled = value.busy;
  if (!initialized) {
    $('port').value = value.configuredPort;
    $('browser').checked = value.browser;
    initialized = true;
  }
}
async function refresh() {
  if (stopped) return;
  try { render(await api('/api/status')); }
  catch (error) { notice(error.message); }
}
$('config-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    render(await api('/api/config', { port: Number($('port').value), browser: $('browser').checked }));
    notice('saved');
  } catch (error) { notice(error.message); }
});
for (const action of ['restart', 'stop']) $(''+action).addEventListener('click', async () => {
  if (!confirm(t(action === 'restart' ? 'confirmRestart' : 'confirmStop'))) return;
  try {
    await api('/api/action', { action });
    if (action === 'stop') {
      stopped = true;
      $('open-app').hidden = true;
      document.querySelectorAll('button, input').forEach((node) => { node.disabled = true; });
      notice('stopping');
      const deadline = Date.now() + 45000;
      while (Date.now() < deadline) {
        try { await api('/api/status'); }
        catch { notice('stopped'); return; }
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
      notice('disconnected');
      return;
    }
    notice('restarting');
  } catch (error) { notice(error.message); }
});
function renderReport() {
  $('results').replaceChildren();
  for (const check of report.checks) {
    const item = document.createElement('li');
    item.className = check.ok ? 'pass' : 'fail';
    item.textContent = `${check.ok ? '✓' : '!'} ${t(check.name)} — ${t(check.ok ? 'good' : 'bad')}${check.ok ? '' : ': ' + check.detail}`;
    $('results').append(item);
  }
  $('export').hidden = false;
}
$('diagnose').addEventListener('click', async () => {
  $('diagnose').disabled = true;
  notice('testing');
  try {
    report = await api('/api/diagnostics');
    renderReport();
    notice(report.ok ? 'complete' : 'issues');
  } catch (error) { notice(error.message); }
  finally { $('diagnose').disabled = false; }
});
$('export').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url; link.download = 'animelab-desktop-diagnostics.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
translate();
refresh();
setInterval(refresh, 2000);
