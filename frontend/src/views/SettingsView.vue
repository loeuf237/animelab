<template>
  <div class="settings-dashboard-pro settings-page-layout fade-in">
    <!-- Header principal -->
    <header class="settings-header-pro">
      <div>
        <h1 class="page-title" style="margin: 0">{{ tx('Paramètres') }}</h1>
        <p class="page-sub" style="margin: 4px 0 0">
          {{ tx("Configurez l'interface, les répertoires, les débits et le proxy réseau.") }}
        </p>
      </div>

      <button type="button" class="btn btn-primary" :disabled="isSaving" @click="saveAll">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          style="
            stroke: currentColor;
            fill: none;
            stroke-width: 2;
            vertical-align: middle;
            margin-right: 6px;
          "
        >
          <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
          <polyline points="17 21 17 13 7 13 7 21" />
          <polyline points="7 3 7 8 15 8" />
        </svg>
        <span>{{ tx(isSaving ? 'Enregistrement...' : 'Enregistrer les paramètres') }}</span>
      </button>
    </header>

    <!-- Sous-onglets horizontaux de paramètres -->
    <label class="settings-section-select">
      <span>{{ tx('Section') }}</span>
      <select v-model="currentTab" class="input-premium">
        <option value="general">{{ tx('Général') }}</option>
        <option value="downloads">{{ tx('Téléchargements') }}</option>
        <option value="sources">Sources</option>
        <option value="storage">{{ tx('Système & Stockage') }}</option>
        <option value="proxy">{{ tx('Proxy & Réseau') }}</option>
      </select>
    </label>
    <nav class="settings-nav-tabs" :aria-label="tx('Section')">
      <button
        type="button"
        class="settings-nav-tab"
        :class="{ active: currentTab === 'general' }"
        @click="currentTab = 'general'"
      >
        <svg
          width="17"
          height="17"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path
            d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"
          />
        </svg>
        <span>{{ tx('Général') }}</span>
      </button>

      <button
        type="button"
        class="settings-nav-tab"
        :class="{ active: currentTab === 'downloads' }"
        @click="currentTab = 'downloads'"
      >
        <svg
          width="17"
          height="17"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <path d="M12 3v11" />
          <path d="m7 10 5 5 5-5" />
          <path d="M5 20h14" />
        </svg>
        <span>{{ tx('Téléchargements') }}</span>
      </button>

      <button
        type="button"
        class="settings-nav-tab"
        :class="{ active: currentTab === 'sources' }"
        @click="currentTab = 'sources'"
      >
        <svg
          width="17"
          height="17"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <polygon points="23 7 16 12 23 17 23 7" />
          <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
        </svg>
        <span>Sources</span>
      </button>

      <button
        type="button"
        class="settings-nav-tab"
        :class="{ active: currentTab === 'storage' }"
        @click="currentTab = 'storage'"
      >
        <svg
          width="17"
          height="17"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
          <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
          <line x1="6" y1="6" x2="6.01" y2="6" />
          <line x1="6" y1="18" x2="6.01" y2="18" />
        </svg>
        <span>{{ tx('Système & Stockage') }}</span>
      </button>

      <button
        type="button"
        class="settings-nav-tab"
        :class="{ active: currentTab === 'proxy' }"
        @click="currentTab = 'proxy'"
      >
        <svg
          width="17"
          height="17"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <rect x="16" y="16" width="6" height="6" rx="1" />
          <rect x="2" y="16" width="6" height="6" rx="1" />
          <rect x="9" y="2" width="6" height="6" rx="1" />
          <path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3" />
          <path d="M12 12V8" />
        </svg>
        <span>{{ tx('Proxy & Réseau') }}</span>
      </button>
    </nav>

    <!-- Onglet 1 : Général & Réseau HTTP -->
    <div
      v-show="currentTab === 'general'"
      class="settings-tab-pane"
      :class="{ active: currentTab === 'general' }"
    >
      <section class="settings-card-pro">
        <div class="settings-card-header-pro">
          <div class="settings-card-icon-pro">
            <svg width="20" height="20" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" />
              <line x1="2" y1="12" x2="22" y2="12" />
              <path
                d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"
              />
            </svg>
          </div>
          <div>
            <h2 class="settings-card-title-pro">{{ tx('Général') }}</h2>
            <p class="settings-card-sub-pro">
              {{ tx("Langue de l'interface, identité HTTP et organisation des médias.") }}
            </p>
          </div>
        </div>

        <!-- Langue -->
        <div class="setting-row-pro">
          <div class="setting-meta-pro">
            <label class="setting-title-pro" style="display: block; cursor: pointer">{{
              tx("Langue de l'interface")
            }}</label>
            <div class="setting-desc-pro">
              {{ tx("Choisissez la langue d'affichage globale d'AnimeLab.") }}
            </div>
          </div>
          <div class="setting-ctrl-pro">
            <select
              :value="i18nStore.currentLang"
              class="input-premium setting-select-pro"
              @change="onLanguageChange(($event.target as HTMLSelectElement).value)"
            >
              <option value="fr">{{ tx('Français (French)') }}</option>
              <option value="en">{{ tx('English (Anglais)') }}</option>
            </select>
          </div>
        </div>

        <!-- Thème d'affichage -->
        <div class="setting-row-pro">
          <div class="setting-meta-pro">
            <label class="setting-title-pro" style="display: block; cursor: pointer">{{
              tx("Thème d'affichage")
            }}</label>
            <div class="setting-desc-pro">
              {{ tx("Palette de couleurs pour l'interface utilisateur.") }}
            </div>
          </div>
          <div class="setting-ctrl-pro">
            <select
              v-model="theme"
              class="input-premium setting-select-pro"
              @change="onThemeChange"
            >
              <option value="dark">{{ tx('Sombre (Deep Slate / AMOLED)') }}</option>
              <option value="light">{{ tx('Clair (Mihon Material Light)') }}</option>
            </select>
          </div>
        </div>

        <div class="setting-row-pro">
          <div class="setting-meta-pro">
            <label class="setting-title-pro">{{ tx('Profil réseau des sources') }}</label>
            <div class="setting-desc-pro">
              {{
                tx(
                  'Profil Chrome stable ; l’identité HTTP correspond à l’empreinte TLS et reste la même pendant les sessions.',
                )
              }}
            </div>
          </div>
        </div>

        <!-- Organisation Plex / Jellyfin -->
        <div class="setting-row-pro">
          <div class="setting-meta-pro">
            <label class="setting-title-pro" style="display: block; cursor: pointer">{{
              tx('Organisation Plex / Jellyfin')
            }}</label>
            <div class="setting-desc-pro">
              {{ tx('Crée une arborescence standard') }}
              <code>{{ tx("Nom de l'Anime/Season 01/S01EXX.mp4") }}</code
              >.
            </div>
          </div>
          <div class="setting-ctrl-pro">
            <label class="toggle-switch">
              <input v-model="plexOrganization" type="checkbox" />
              <span class="toggle-slider"></span>
            </label>
          </div>
        </div>
      </section>
    </div>

    <!-- Onglet 2 : Téléchargements & Bande Passante -->
    <div
      v-show="currentTab === 'downloads'"
      class="settings-tab-pane"
      :class="{ active: currentTab === 'downloads' }"
    >
      <section class="settings-card-pro">
        <div class="settings-card-header-pro">
          <div class="settings-card-icon-pro">
            <svg width="20" height="20" viewBox="0 0 24 24">
              <path d="M12 3v11" />
              <path d="m7 10 5 5 5-5" />
              <path d="M5 20h14" />
            </svg>
          </div>
          <div>
            <h2 class="settings-card-title-pro">{{ tx('Téléchargements & Bande Passante') }}</h2>
            <p class="settings-card-sub-pro">
              {{ tx("Gérez le débit, le parallélisme et la file d'attente.") }}
            </p>
          </div>
        </div>

        <!-- Téléchargements simultanés -->
        <div class="setting-row-pro">
          <div class="setting-meta-pro">
            <label class="setting-title-pro" style="display: block; cursor: pointer">{{
              tx('Téléchargements simultanés max')
            }}</label>
            <div class="setting-desc-pro">
              {{ tx('Nombre de tâches de téléchargement exécutées en parallèle (1 à 20).') }}
            </div>
          </div>
          <div class="setting-ctrl-pro">
            <input
              v-model.number="maxConcurrentDownloads"
              type="number"
              class="input-premium setting-input-sm"
              min="1"
              max="20"
            />
          </div>
        </div>

        <!-- Limite de vitesse globale -->
        <div class="setting-row-pro">
          <div class="setting-meta-pro">
            <label class="setting-title-pro" style="display: block; cursor: pointer">{{
              tx('Limite de vitesse globale')
            }}</label>
            <div class="setting-desc-pro">
              {{ tx('Plafond total partagé par tous les téléchargements (0 = illimité).') }}
            </div>
          </div>
          <div class="setting-ctrl-pro">
            <div class="speed-ctrl-group">
              <div class="speed-input-box">
                <input
                  v-model.number="globalSpeedKb"
                  type="number"
                  class="input-premium setting-input-md"
                  placeholder="0"
                  min="0"
                />
                <span class="speed-unit-tag">{{ tx('Ko/s') }}</span>
              </div>
              <div class="speed-preset-chips">
                <button type="button" class="speed-preset-chip" @click="globalSpeedKb = 0">
                  0
                </button>
                <button type="button" class="speed-preset-chip" @click="globalSpeedKb = 1024">
                  {{ tx('1 Mo/s') }}
                </button>
                <button type="button" class="speed-preset-chip" @click="globalSpeedKb = 3072">
                  {{ tx('3 Mo/s') }}
                </button>
                <button type="button" class="speed-preset-chip" @click="globalSpeedKb = 5120">
                  {{ tx('5 Mo/s') }}
                </button>
                <button type="button" class="speed-preset-chip" @click="globalSpeedKb = 10240">
                  {{ tx('10 Mo/s') }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- Onglet 3 : Paramètres par Source -->
    <div
      v-show="currentTab === 'sources'"
      class="settings-tab-pane"
      :class="{ active: currentTab === 'sources' }"
    >
      <section class="settings-card-pro">
        <div class="settings-card-header-pro">
          <div class="settings-card-icon-pro">
            <svg width="20" height="20" viewBox="0 0 24 24">
              <polygon points="23 7 16 12 23 17 23 7" />
              <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
            </svg>
          </div>
          <div>
            <h2 class="settings-card-title-pro">{{ tx('Paramètres par Source') }}</h2>
            <p class="settings-card-sub-pro">
              {{
                tx(
                  'Configuration individualisée pour chaque source (VoirAnime, AnimePahe, French-Manga).',
                )
              }}
            </p>
          </div>
        </div>

        <!-- Sous-onglets sources -->
        <div class="source-tabs-container">
          <button
            type="button"
            class="source-tab-btn"
            :class="{ active: activeSourceTab === 'voir-anime' }"
            @click="activeSourceTab = 'voir-anime'"
          >
            <span>VoirAnime</span>
            <span class="source-tab-badge">FR</span>
          </button>

          <button
            type="button"
            class="source-tab-btn"
            :class="{ active: activeSourceTab === 'animepahe' }"
            @click="activeSourceTab = 'animepahe'"
          >
            <span>AnimePahe</span>
            <span class="source-tab-badge">VOST</span>
          </button>

          <button
            type="button"
            class="source-tab-btn"
            :class="{ active: activeSourceTab === 'french-manga' }"
            @click="activeSourceTab = 'french-manga'"
          >
            <span>French-Manga</span>
            <span class="source-tab-badge">FR</span>
          </button>
        </div>

        <!-- VoirAnime -->
        <div v-show="activeSourceTab === 'voir-anime'" style="padding: 10px 0">
          <div class="setting-row-pro">
            <div class="setting-meta-pro">
              <label class="setting-title-pro" style="display: block; cursor: pointer">{{
                tx('Hébergeur tenté en priorité')
              }}</label>
              <div class="setting-desc-pro">
                {{
                  tx('Serveur vidéo sélectionné par défaut lors de la lecture ou téléchargement.')
                }}
              </div>
            </div>
            <div class="setting-ctrl-pro">
              <select v-model="voiranimeDefaultServer" class="input-premium setting-select-pro">
                <option value="auto">{{ tx('Auto (Défaut / Default)') }}</option>
                <option value="myTV">myTV (HLS)</option>
                <option value="stape">Streamtape (Direct MP4)</option>
                <option value="voe">VOE</option>
                <option value="fhd1">FHD1</option>
                <option value="moon">MOON</option>
              </select>
            </div>
          </div>
        </div>

        <!-- AnimePahe -->
        <div
          v-show="activeSourceTab === 'animepahe'"
          style="padding: 28px 24px; text-align: center; color: var(--muted)"
        >
          <div style="font-weight: 600; color: var(--text); margin-bottom: 6px">
            AnimePahe (Kwik Stream)
          </div>
          <p>
            {{ tx('Flux vidéo ultra-rapides et compacts. Aucun paramètre spécifique requis.') }}
          </p>
        </div>

        <!-- French-Manga -->
        <div
          v-show="activeSourceTab === 'french-manga'"
          style="padding: 28px 24px; text-align: center; color: var(--muted)"
        >
          <div style="font-weight: 600; color: var(--text); margin-bottom: 6px">
            French-Manga (Vidzy)
          </div>
          <p>{{ tx('Flux directs Vidzy avec sous-titres FR synchronisés.') }}</p>
        </div>
      </section>
    </div>

    <!-- Onglet 4 : Stockage & Système -->
    <div
      v-show="currentTab === 'storage'"
      class="settings-tab-pane"
      :class="{ active: currentTab === 'storage' }"
    >
      <AndroidStorageSettings />
      <DiagnosticsExport />
      <section class="settings-card-pro">
        <div class="settings-card-header-pro">
          <div class="settings-card-icon-pro">
            <svg width="20" height="20" viewBox="0 0 24 24">
              <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
              <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
              <line x1="6" y1="6" x2="6.01" y2="6" />
              <line x1="6" y1="18" x2="6.01" y2="18" />
            </svg>
          </div>
          <div>
            <h2 class="settings-card-title-pro">{{ tx('Système & Stockage') }}</h2>
            <p class="settings-card-sub-pro">
              {{ tx('Outils système et gestion du stockage local.') }}
            </p>
          </div>
        </div>

        <!-- FFmpeg status -->
        <div class="setting-row-pro">
          <div class="setting-meta-pro">
            <div class="setting-title-pro">{{ tx('FFmpeg & Outils de transcodage') }}</div>
            <div class="setting-desc-pro">
              {{ tx('Muxing HLS, assemblage audio/vidéo et encapsulation MP4.') }}
            </div>
          </div>
          <div class="setting-ctrl-pro">
            <span
              class="status-badge"
              :class="ffmpegAvailable ? 'badge-ok' : 'badge-err'"
              style="padding: 5px 12px; font-size: 0.82rem; border-radius: 6px"
            >
              {{ tx(ffmpegAvailable ? 'Opérationnel' : 'Non trouvé (Muxing désactivé)') }}
            </span>
          </div>
        </div>

        <!-- Répertoire de téléchargement -->
        <div class="setting-row-pro">
          <div class="setting-meta-pro">
            <div class="setting-title-pro">{{ tx('Répertoire de téléchargement') }}</div>
            <div class="setting-desc-pro">
              {{ tx('Chemin absolu de destination sur le serveur.') }}
            </div>
          </div>
          <div class="setting-ctrl-pro" style="flex: 1; max-width: 380px">
            <input
              type="text"
              class="input-premium"
              readonly
              :value="storageInfo?.downloadDir || 'Chargement...'"
              style="
                width: 100%;
                opacity: 0.85;
                font-family: monospace;
                font-size: 0.82rem;
                cursor: default;
              "
            />
          </div>
        </div>

        <!-- Espace disque -->
        <div
          class="setting-row-pro"
          style="flex-direction: column; align-items: stretch; gap: 12px"
        >
          <div class="setting-meta-pro">
            <div class="setting-title-pro">{{ tx('Espace disque') }}</div>
            <div class="setting-desc-pro">
              {{ tx('Capacité totale et espace disque disponible.') }}
            </div>
          </div>
          <div class="storage-card-box">
            <div class="storage-bar-labels">
              <span class="storage-stat-highlight">
                {{ tx(storageUsedGb) }} GB / {{ tx(storageTotalGb) }} GB ({{
                  tx(storageInfo?.usedPercent || 0)
                }}%)
              </span>
              <span class="storage-stat-muted">
                {{ tx(storageFreeGb) }} {{ tx('GB libres') }}
              </span>
            </div>
            <div class="storage-bar-track">
              <div
                class="storage-bar-fill"
                :style="{ width: `${Math.min(100, Math.max(0, storageInfo?.usedPercent || 0))}%` }"
              ></div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- Onglet 5 : Réseau & Proxy -->
    <div
      v-show="currentTab === 'proxy'"
      class="settings-tab-pane"
      :class="{ active: currentTab === 'proxy' }"
    >
      <BrowserVerificationSettings :active="currentTab === 'proxy'" />
      <ProxyPoolSettings :active="currentTab === 'proxy'" />
      <section class="settings-card-pro">
        <div class="settings-card-header-pro">
          <div class="settings-card-icon-pro">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <rect x="16" y="16" width="6" height="6" rx="1" />
              <rect x="2" y="16" width="6" height="6" rx="1" />
              <rect x="9" y="2" width="6" height="6" rx="1" />
              <path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3" />
              <path d="M12 12V8" />
            </svg>
          </div>
          <div>
            <h2 class="settings-card-title-pro">{{ tx('Manuel · Votre serveur proxy') }}</h2>
            <p class="settings-card-sub-pro">
              {{
                tx(
                  'Acheminez vos requêtes via un proxy HTTP/SOCKS pour contourner les blocages FAI.',
                )
              }}
            </p>
          </div>
        </div>

        <!-- Switch principal -->
        <div class="setting-row-pro">
          <div class="setting-meta-pro">
            <label class="setting-title-pro" style="display: block; cursor: pointer">{{
              tx('Activer le serveur proxy')
            }}</label>
            <div class="setting-desc-pro">
              {{
                tx('Active le routage du scraping et des résolutions vidéo par le proxy configuré.')
              }}
            </div>
          </div>
          <div class="setting-ctrl-pro">
            <label class="toggle-switch">
              <input v-model="proxySettings.enabled" type="checkbox" />
              <span class="toggle-slider"></span>
            </label>
          </div>
        </div>

        <!-- Champs configurables -->
        <div style="display: flex; flex-direction: column">
          <!-- Protocole / Type -->
          <div class="setting-row-pro">
            <div class="setting-meta-pro">
              <label class="setting-title-pro" style="display: block; cursor: pointer">{{
                tx('Protocole / Type de proxy')
              }}</label>
              <div class="setting-desc-pro">{{ tx('Type de serveur proxy utilisé.') }}</div>
            </div>
            <div class="setting-ctrl-pro">
              <select v-model="proxySettings.proxy_type" class="input-premium setting-select-pro">
                <option value="socks5">{{ tx('SOCKS5 (Recommandé / Rapide)') }}</option>
                <option value="socks5h">{{ tx('SOCKS5h (DNS Distant / Anti-DNS Leak)') }}</option>
                <option value="http">HTTP</option>
                <option value="https">HTTPS</option>
                <option value="socks4">SOCKS4</option>
              </select>
            </div>
          </div>

          <!-- Hôte et Port -->
          <div class="setting-row-pro">
            <div class="setting-meta-pro">
              <label class="setting-title-pro" style="display: block; cursor: pointer">{{
                tx('Hôte & Port')
              }}</label>
              <div class="setting-desc-pro">
                {{ tx("Adresse IP ou nom de domaine du proxy et son port d'écoute.") }}
              </div>
            </div>
            <div
              class="setting-ctrl-pro"
              style="display: flex; gap: 10px; flex: 1; max-width: 440px"
            >
              <input
                v-model="proxySettings.host"
                type="text"
                class="input-premium"
                style="flex: 2; min-width: 0"
                :placeholder="tx('127.0.0.1 ou proxy.example.com')"
              />
              <input
                v-model.number="proxySettings.port"
                type="number"
                class="input-premium"
                style="flex: 1; min-width: 80px; max-width: 110px"
                placeholder="1080"
                min="1"
                max="65535"
              />
            </div>
          </div>

          <!-- Authentification -->
          <div class="setting-row-pro">
            <div class="setting-meta-pro">
              <div class="setting-title-pro">{{ tx('Authentification (Optionnel)') }}</div>
              <div class="setting-desc-pro">
                {{ tx("Identifiants d'accès si le proxy exige une authentification.") }}
              </div>
            </div>
            <div
              class="setting-ctrl-pro"
              style="display: flex; gap: 10px; flex: 1; max-width: 440px"
            >
              <input
                v-model="proxySettings.username"
                type="text"
                class="input-premium"
                style="flex: 1; min-width: 0"
                :placeholder="tx('Nom d\'utilisateur')"
                autocomplete="off"
              />
              <div
                style="
                  position: relative;
                  flex: 1;
                  min-width: 0;
                  display: flex;
                  align-items: center;
                "
              >
                <input
                  v-model="proxySettings.password"
                  :type="showProxyPassword ? 'text' : 'password'"
                  class="input-premium"
                  style="width: 100%; padding-right: 36px"
                  :placeholder="tx('Mot de passe')"
                  autocomplete="new-password"
                />
                <button
                  type="button"
                  style="
                    position: absolute;
                    right: 8px;
                    background: none;
                    border: none;
                    color: var(--muted);
                    cursor: pointer;
                    padding: 4px;
                  "
                  @click="showProxyPassword = !showProxyPassword"
                >
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                  >
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          <!-- URL Brute Override -->
          <div class="setting-row-pro">
            <div class="setting-meta-pro">
              <label class="setting-title-pro" style="display: block; cursor: pointer">{{
                tx('URL Brute Personnalisée (Override)')
              }}</label>
              <div class="setting-desc-pro">
                {{ tx("Remplace l'assemblage automatique hôte/port si renseignée.") }}
              </div>
            </div>
            <div class="setting-ctrl-pro" style="flex: 1; max-width: 440px">
              <input
                v-model="proxySettings.custom_url"
                type="text"
                class="input-premium"
                style="width: 100%; font-family: monospace; font-size: 0.84rem"
                placeholder="socks5://user:pass@127.0.0.1:1080"
              />
            </div>
          </div>

          <!-- Live Resolved Proxy Preview Box -->
          <div
            class="setting-row-pro"
            style="
              background: rgba(124, 58, 237, 0.05);
              border: 1px dashed var(--line);
              border-radius: 8px;
              padding: 12px 16px;
              margin: 8px 24px;
            "
          >
            <div
              style="
                font-size: 0.82rem;
                color: var(--muted);
                display: flex;
                align-items: center;
                gap: 8px;
              "
            >
              <svg
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="16" x2="12" y2="12" />
                <line x1="12" y1="8" x2="12.01" y2="8" />
              </svg>
              <span>{{ tx('URL effective :') }}</span>
              <code style="color: var(--accent); font-weight: 600; word-break: break-all">
                {{ tx(effectiveProxyUrl) }}
              </code>
            </div>
          </div>

          <!-- Tester la connexion -->
          <div class="setting-row-pro" style="border-bottom: none">
            <div class="setting-meta-pro">
              <div class="setting-title-pro">{{ tx('Tester la connexion') }}</div>
              <div class="setting-desc-pro">
                {{ tx('Envoie une requête HTTP de test via le proxy.') }}
              </div>
            </div>
            <div
              class="setting-ctrl-pro"
              style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap"
            >
              <button
                type="button"
                class="btn btn-outline"
                :disabled="isTestingProxy"
                style="display: inline-flex; align-items: center; gap: 8px"
                @click="testProxyConnection"
              >
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                >
                  <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                </svg>
                <span>{{ tx(isTestingProxy ? 'Test en cours...' : 'Tester le proxy') }}</span>
              </button>
              <span
                v-if="proxyTestResult"
                class="status-badge"
                :class="proxyTestResult.success ? 'badge-ok' : 'badge-err'"
                style="padding: 6px 12px; border-radius: 6px; font-size: 0.82rem"
              >
                {{ tx(proxyTestResult.message) }}
              </span>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- Toast Notification -->
  </div>
</template>

<script setup lang="ts">
import DiagnosticsExport from '@/components/DiagnosticsExport.vue'
import { tx, readPreference, writePreference } from '@/utils/locale'
import { useNotifications } from '@/stores/notifications'
import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/client'
import { useI18nStore } from '@/stores/i18n'
import ProxyPoolSettings from '@/components/ProxyPoolSettings.vue'
import BrowserVerificationSettings from '@/components/BrowserVerificationSettings.vue'
import AndroidStorageSettings from '@/components/AndroidStorageSettings.vue'
import { useRoute } from 'vue-router'

const i18nStore = useI18nStore()

const currentTab = ref<'general' | 'downloads' | 'sources' | 'storage' | 'proxy'>('general')
if (useRoute().query.tab === 'proxy') currentTab.value = 'proxy'
if (useRoute().query.tab === 'storage') currentTab.value = 'storage'
const activeSourceTab = ref<'voir-anime' | 'animepahe' | 'french-manga'>('voir-anime')

const theme = ref('dark')
const uaSelection = ref('Random (Rotator)')
const customUa = ref('')
const plexOrganization = ref(false)

const maxConcurrentDownloads = ref(3)
const globalSpeedKb = ref(0)
const voiranimeDefaultServer = ref('auto')
const ffmpegAvailable = ref(true)

const storageInfo = ref<any>(null)

const proxySettings = ref({
  enabled: false,
  proxy_type: 'socks5',
  host: '',
  port: 1080,
  username: '',
  password: '',
  custom_url: '',
})

const showProxyPassword = ref(false)
const isTestingProxy = ref(false)
const proxyTestResult = ref<{ success: boolean; message: string } | null>(null)
const isSaving = ref(false)

const notifications = useNotifications()
function showToast(message: string, tone: 'success' | 'error' | 'info' = 'info') {
  notifications.notify(message, tone)
}

const storageUsedGb = computed(() => {
  if (!storageInfo.value || !storageInfo.value.usedBytes) return '0.0'
  return (storageInfo.value.usedBytes / 1024 ** 3).toFixed(1)
})

const storageTotalGb = computed(() => {
  if (!storageInfo.value || !storageInfo.value.totalBytes) return '0.0'
  return (storageInfo.value.totalBytes / 1024 ** 3).toFixed(1)
})

const storageFreeGb = computed(() => {
  if (!storageInfo.value || !storageInfo.value.freeBytes) return '0.0'
  return (storageInfo.value.freeBytes / 1024 ** 3).toFixed(1)
})

const effectiveProxyUrl = computed(() => {
  if (!proxySettings.value.enabled) return 'Proxy désactivé'
  if (proxySettings.value.custom_url) return proxySettings.value.custom_url
  if (!proxySettings.value.host) return 'Non configuré'

  const type = proxySettings.value.proxy_type || 'socks5'
  const auth = proxySettings.value.username
    ? `${proxySettings.value.username}:${proxySettings.value.password}@`
    : ''
  const port = proxySettings.value.port || 1080
  return `${type}://${auth}${proxySettings.value.host}:${port}`
})

function onThemeChange() {
  writePreference('theme', theme.value)
  document.documentElement.setAttribute('data-theme', theme.value)
}

async function onLanguageChange(lang: string) {
  await i18nStore.changeLanguage(lang as 'fr' | 'en')
  showToast('Langue mise à jour.')
}

async function loadSettings() {
  try {
    const dl = await api.getDownloadSettings()
    if (dl) {
      maxConcurrentDownloads.value = dl.maxConcurrentDownloads || 3
      globalSpeedKb.value = dl.globalSpeedLimit ? Math.round(dl.globalSpeedLimit / 1024) : 0
      plexOrganization.value = Boolean(dl.plexOrganization)
      voiranimeDefaultServer.value = dl.voiranimeDefaultServer || 'auto'
      ffmpegAvailable.value = dl.ffmpegAvailable !== false

      const ua = dl.selectedUserAgent || 'Random (Rotator)'
      const standard = ['Random (Rotator)', 'Chrome', 'Firefox', 'Safari', 'Edge']
      if (standard.includes(ua)) {
        uaSelection.value = ua
      } else {
        uaSelection.value = 'Custom'
        customUa.value = ua
      }
    }
  } catch (e) {
    console.debug('Failed to load dl settings:', e)
  }

  try {
    const px = await api.getProxySettings()
    if (px) {
      proxySettings.value = {
        enabled: Boolean(px.enabled),
        proxy_type: px.proxy_type || px.proxyType || 'socks5',
        host: px.host || '',
        port: px.port || 1080,
        username: px.username || '',
        password: px.password || '',
        custom_url: px.custom_url || px.customUrl || '',
      }
    }
  } catch (e) {
    console.debug('Failed to load proxy settings:', e)
  }

  try {
    const st = await api.getStorageInfo()
    if (st) {
      storageInfo.value = st
    }
  } catch (e) {
    console.debug('Failed to load storage info:', e)
  }
}

async function testProxyConnection() {
  isTestingProxy.value = true
  proxyTestResult.value = null

  try {
    const res = await api.testProxy(undefined, proxySettings.value)
    if (res.success) {
      proxyTestResult.value = {
        success: true,
        message: `Connexion réussie (${res.latencyMs || 0}ms - IP: ${res.ip || 'OK'})`,
      }
    } else {
      proxyTestResult.value = {
        success: false,
        message: `Échec : ${res.error || 'Connexion impossible'}`,
      }
    }
  } catch (e: any) {
    proxyTestResult.value = {
      success: false,
      message: `Erreur : ${e.message || 'Serveur injoignable'}`,
    }
  } finally {
    isTestingProxy.value = false
  }
}

async function saveAll() {
  isSaving.value = true
  try {
    const finalUa = uaSelection.value === 'Custom' ? customUa.value.trim() : uaSelection.value
    const globalBytes = globalSpeedKb.value > 0 ? globalSpeedKb.value * 1024 : 0

    await api.saveDownloadSettings({
      maxConcurrentDownloads: maxConcurrentDownloads.value,
      globalSpeedLimit: globalBytes,
      plexOrganization: plexOrganization.value,
      selectedUserAgent: finalUa,
      voiranimeDefaultServer: voiranimeDefaultServer.value,
    })

    await api.saveProxySettings(proxySettings.value)

    showToast('Tous les paramètres ont été enregistrés avec succès !', 'success')
  } catch (e: any) {
    showToast(e.message || 'Erreur lors de la sauvegarde.', 'error')
  } finally {
    isSaving.value = false
  }
}

onMounted(() => {
  theme.value = (readPreference('theme') as string) || 'dark'
  loadSettings()
})
</script>

<style scoped>
.settings-dashboard-pro {
  padding: 24px 20px;
}
.settings-header-pro {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}
.settings-section-select {
  display: none;
}
@media (max-width: 768px) {
  .settings-dashboard-pro {
    padding: 0;
    gap: 16px;
  }
  .settings-header-pro {
    gap: 12px;
  }
  .settings-header-pro .page-sub {
    font-size: 13px;
    line-height: 1.5;
  }
  .settings-header-pro > button {
    width: 100%;
  }
  .settings-nav-tabs {
    display: none;
  }
  .settings-section-select {
    display: grid;
    gap: 6px;
    font-size: 12px;
    color: var(--muted);
  }
  .settings-section-select select {
    width: 100%;
    min-width: 0;
    min-height: 44px;
  }
  .source-tabs-container {
    flex-wrap: wrap;
    padding: 12px;
    gap: 6px;
  }
  .source-tab-btn {
    flex: 1 1 auto;
    justify-content: center;
    min-height: 44px;
    padding: 6px 10px;
  }
  .source-tab-btn svg {
    flex-shrink: 0;
  }
  .toast-notification {
    bottom: calc(80px + env(safe-area-inset-bottom, 0px));
    left: 12px;
    right: 12px;
  }
}
.settings-tab-pane.active {
  display: block !important;
}

.toast-notification {
  position: fixed;
  bottom: 24px;
  right: 24px;
  padding: 12px 20px;
  border-radius: var(--radius-sm);
  background: rgba(15, 23, 42, 0.95);
  border: 1px solid var(--border-highlight);
  color: #fff;
  font-size: 0.9rem;
  font-weight: 600;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  z-index: 500;
  animation: slideUp 0.25s ease;
}

.toast-success {
  border-left: 4px solid #10b981;
}

.toast-error {
  border-left: 4px solid #ef4444;
}

.toast-info {
  border-left: 4px solid #6366f1;
}

@keyframes slideUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.badge-ok {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.badge-err {
  background: rgba(239, 68, 68, 0.2);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.3);
}
</style>
