// AnimeLab PWA Registration and Installation Handler
(() => {
  'use strict';

  let deferredInstallPrompt = null;

  // 1. Register Service Worker
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker
        .register('/sw.js', { scope: '/', updateViaCache: 'none' })
        .then((reg) => {
          // Check for worker updates
          reg.addEventListener('updatefound', () => {
            const installingWorker = reg.installing;
            if (installingWorker) {
              installingWorker.addEventListener('statechange', () => {
                if (installingWorker.state === 'installed' && navigator.serviceWorker.controller) {
                  console.log('[AnimeLab PWA] Nouvelle version prête. Rafraîchissez pour l\'activer.');
                }
              });
            }
          });
        })
        .catch((err) => {
          console.warn('[AnimeLab PWA] Erreur enregistrement Service Worker:', err);
        });
    });
  }

  // 2. Detect Standalone Mode
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches ||
                       window.navigator.standalone === true;

  if (isStandalone) {
    document.documentElement.classList.add('pwa-standalone');
  }

  // 3. Handle 'beforeinstallprompt'
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;

    // Show any install trigger in the interface
    const installBtns = document.querySelectorAll('.pwa-install-trigger');
    installBtns.forEach((btn) => {
      btn.style.display = 'inline-flex';
    });

    const banner = document.getElementById('pwa-install-banner');
    if (banner && !sessionStorage.getItem('animan-pwa-banner-dismissed')) {
      banner.style.display = 'flex';
    }
  });

  // 4. Global Function to trigger installation
  window.installPwaApp = async () => {
    if (!deferredInstallPrompt) {
      if (typeof showToast === 'function') {
        showToast('AnimeLab est déjà installé ou prêt dans votre navigateur.', 'info');
      }
      return;
    }

    try {
      deferredInstallPrompt.prompt();
      const choice = await deferredInstallPrompt.userChoice;
      if (choice.outcome === 'accepted') {
        console.log('[AnimeLab PWA] Installation acceptée par l\'utilisateur');
      }
      deferredInstallPrompt = null;

      // Hide triggers
      document.querySelectorAll('.pwa-install-trigger').forEach((btn) => {
        btn.style.display = 'none';
      });
      const banner = document.getElementById('pwa-install-banner');
      if (banner) {
        banner.style.display = 'none';
      }
    } catch (err) {
      console.warn('[AnimeLab PWA] Erreur lors de l\'installation:', err);
    }
  };

  // 5. Dismiss banner
  window.dismissPwaBanner = () => {
    const banner = document.getElementById('pwa-install-banner');
    if (banner) {
      banner.style.display = 'none';
    }
    sessionStorage.setItem('animan-pwa-banner-dismissed', '1');
  };

  // 6. Installed event
  window.addEventListener('appinstalled', () => {
    deferredInstallPrompt = null;
    document.querySelectorAll('.pwa-install-trigger').forEach((btn) => {
      btn.style.display = 'none';
    });
    const banner = document.getElementById('pwa-install-banner');
    if (banner) {
      banner.style.display = 'none';
    }
    if (typeof showToast === 'function') {
      showToast('AnimeLab a été installé avec succès sur votre appareil !', 'success');
    }
  });
})();
