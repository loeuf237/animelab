/* Account controls use same-origin HttpOnly sessions; no token in browser storage. */
const $ = (id) => document.getElementById(id);
const fr = {
  title: "Votre espace personnel",
  intro:
    "Votre bibliothèque, votre progression et vos sessions de sources restent liées à votre compte.",
  login: "Se connecter",
  username: "Identifiant",
  password: "Mot de passe",
  redeem: "Utiliser une invitation ou un code de récupération",
  code: "Code",
  inviteUsername: "Identifiant (invitation uniquement)",
  newPassword: "Nouveau mot de passe (12 caractères minimum)",
  continue: "Continuer",
  contact:
    "Demandez un compte ou un code de récupération à votre administrateur. Les inscriptions publiques sont désactivées.",
  open: "Ouvrir AnimeLab",
  logout: "Se déconnecter",
  changePassword: "Changer le mot de passe",
  currentPassword: "Mot de passe actuel",
  save: "Enregistrer",
  revoke:
    "Changer le mot de passe déconnecte ce compte sur tous les appareils.",
  admin: "Administration des comptes",
  create: "Créer un compte",
  initialPassword: "Mot de passe initial (12 caractères minimum)",
  downloads: "Autoriser les téléchargements",
  extensions: "Gérer les extensions",
  administrator: "Administrateur",
  invite: "Inviter une personne",
  makeInvite: "Générer une invitation (7 jours)",
  shareCode:
    "Copiez ce code et transmettez-le en privé. Il apparaît une seule fois et est utilisable une seule fois.",
  accounts: "Comptes",
  permissionsNote:
    "Modifier les permissions ou désactiver un compte révoque ses sessions et arrête son moteur. Un administrateur dispose de toutes les permissions.",
  activeCodes: "Invitations et codes de récupération actifs",
  privacy:
    "Serveur partagé · Les cookies des sources sont privés. Les fenêtres système du serveur sont indisponibles.",
  enabled: "Compte activé",
  apply: "Appliquer les permissions",
  recovery: "Code de récupération (24 h)",
  stop: "Arrêter le moteur",
  running: "Moteur actif",
  stopped: "Moteur arrêté",
  revokeCode: "Révoquer",
  invitation: "Invitation",
  recoveryCode: "Récupération",
  empty: "Aucun code actif",
  saved: "Enregistré.",
  expired: "Session expirée. Reconnectez-vous.",
};
const en = {
  enabled: "Account enabled",
  apply: "Apply permissions",
  recovery: "Recovery code (24 h)",
  stop: "Stop engine",
  running: "Engine running",
  stopped: "Engine stopped",
  revokeCode: "Revoke",
  invitation: "Invitation",
  recoveryCode: "Recovery",
  empty: "No active codes",
  saved: "Saved.",
  expired: "Session expired. Sign in again.",
};
const frenchErrors = {
  "Invalid username or password": "Identifiant ou mot de passe incorrect.",
  "Use a password of 12 to 256 characters":
    "Utilisez un mot de passe de 12 à 256 caractères.",
  "Current password is incorrect": "Le mot de passe actuel est incorrect.",
  "Username already exists": "Cet identifiant est déjà utilisé.",
  "Username: 3 to 40 letters, digits, dots, underscores or hyphens":
    "Identifiant : 3 à 40 lettres, chiffres, points, tirets ou tirets bas.",
  "Invalid or expired code": "Code invalide ou expiré.",
  "The last administrator cannot be disabled or demoted":
    "Le dernier administrateur ne peut pas être désactivé ou rétrogradé.",
  "Account not found or disabled": "Compte introuvable ou désactivé.",
  "Account not found": "Compte introuvable.",
  "Unknown permission": "Permission inconnue.",
  "Session was revoked": "La session a été révoquée. Reconnectez-vous.",
  "Too many authentication attempts; try later":
    "Trop de tentatives. Réessayez dans quinze minutes.",
  "Account limit reached (100)": "La limite de 100 comptes est atteinte.",
  "Code limit reached (100)": "La limite de 100 codes est atteinte.",
};
let lang = (navigator.language || "").startsWith("fr") ? "fr" : "en";
const originals = new Map(
  [...document.querySelectorAll("[data-i18n]")].map((node) => [
    node,
    node.textContent,
  ]),
);
let user = null;
const text = (key) => (lang === "fr" ? fr[key] : en[key]) || key;
function translate() {
  document.documentElement.lang = lang;
  for (const [node, value] of originals)
    node.textContent = lang === "fr" ? fr[node.dataset.i18n] || value : value;
  $("language").textContent = lang === "fr" ? "English" : "Français";
}
function message(value, error = false) {
  $("message").textContent =
    lang === "fr" ? frenchErrors[value] || value : value;
  $("message").className = error ? "error" : "";
}
async function api(path, method = "GET", body) {
  const response = await fetch("/api/auth/" + path, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && user) {
      user = null;
      location.replace("/auth/login");
      return;
    }
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : data.error || `HTTP ${response.status}`,
    );
  }
  return data;
}
async function cleanBrowser() {
  localStorage.clear();
  sessionStorage.clear();
  if ("caches" in window)
    await Promise.all((await caches.keys()).map((key) => caches.delete(key)));
  if ("serviceWorker" in navigator)
    await Promise.all(
      (await navigator.serviceWorker.getRegistrations()).map((item) =>
        item.unregister(),
      ),
    );
}
function form(id, handler) {
  $(id).addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    message("");
    try {
      await handler(Object.fromEntries(new FormData($(id))));
    } catch (error) {
      message(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}
function permissions(data) {
  return ["download", "extensions"].filter((name) => data[name] === "on");
}
async function entered() {
  await cleanBrowser();
  location.replace("/app/");
}
form("login", async (data) => {
  await api("login", "POST", data);
  await entered();
});
form("redeem", async (data) => {
  if (!data.username) delete data.username;
  await api("redeem", "POST", data);
  await entered();
});
form("password", async (data) => {
  await api("password", "POST", data);
  await cleanBrowser();
  location.replace("/auth/login");
});
form("create", async (data) => {
  await api("users", "POST", {
    username: data.username,
    password: data.password,
    admin: data.admin === "on",
    permissions: permissions(data),
  });
  $("create").reset();
  message(text("saved"));
  await loadUsers();
});
function showCode(value) {
  $("generated").hidden = false;
  $("generated-code").value = value;
  $("generated-code").focus();
  $("generated-code").select();
}
form("invitation", async (data) => {
  showCode(
    (await api("codes", "POST", { permissions: permissions(data) })).code,
  );
  await loadCodes();
});
$("logout").onclick = async () => {
  try {
    await api("logout", "POST", {});
    await cleanBrowser();
    location.replace("/auth/login");
  } catch (error) {
    message(error.message, true);
  }
};
$("language").onclick = () => {
  lang = lang === "fr" ? "en" : "fr";
  translate();
  if (user?.admin) refreshAdmin();
};
function checkbox(parent, key, checked) {
  const label = document.createElement("label");
  label.className = "check";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = Boolean(checked);
  label.append(input, document.createTextNode(text(key)));
  parent.append(label);
  return input;
}
function button(parent, caption, action) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = "secondary";
  node.textContent = text(caption);
  node.onclick = async () => {
    node.disabled = true;
    try {
      await action();
    } catch (error) {
      message(error.message, true);
    } finally {
      node.disabled = false;
    }
  };
  parent.append(node);
}
async function loadUsers() {
  const data = await api("users");
  $("users").replaceChildren();
  for (const account of data.users) {
    const card = document.createElement("div");
    card.className = "user";
    const title = document.createElement("strong");
    title.textContent = account.username;
    const state = document.createElement("p");
    state.textContent = text(
      data.engines.includes(account.id) ? "running" : "stopped",
    );
    card.append(title, state);
    const enabled = checkbox(card, "enabled", account.enabled);
    const admin = checkbox(card, "administrator", account.admin);
    const download = checkbox(
      card,
      "downloads",
      account.permissions.includes("download"),
    );
    const extensions = checkbox(
      card,
      "extensions",
      account.permissions.includes("extensions"),
    );
    const actions = document.createElement("div");
    actions.className = "actions";
    card.append(actions);
    button(actions, "apply", async () => {
      await api("users/" + account.id, "PATCH", {
        enabled: enabled.checked,
        admin: admin.checked,
        permissions: [
          download.checked && "download",
          extensions.checked && "extensions",
        ].filter(Boolean),
      });
      message(text("saved"));
      if (account.id === user.id) location.replace("/auth/login");
      else await loadUsers();
    });
    button(actions, "recovery", async () => {
      showCode((await api("codes", "POST", { user_id: account.id })).code);
      await loadCodes();
    });
    button(actions, "stop", async () => {
      await api("users/" + account.id + "/stop", "POST", {});
      await loadUsers();
    });
    $("users").append(card);
  }
}
async function loadCodes() {
  const data = await api("codes");
  $("codes").replaceChildren();
  if (!data.codes.length) $("codes").textContent = text("empty");
  for (const code of data.codes) {
    const row = document.createElement("div");
    row.className = "user";
    const description = document.createElement("p");
    description.textContent = `${text(code.user_id ? "recoveryCode" : "invitation")} · ${new Date(code.expires * 1000).toLocaleString(lang)}`;
    row.append(description);
    button(row, "revokeCode", async () => {
      await api("codes/" + code.id, "DELETE", {});
      await loadCodes();
    });
    $("codes").append(row);
  }
}
async function refreshAdmin() {
  try {
    await loadUsers();
    await loadCodes();
  } catch (error) {
    message(error.message, true);
  }
}
async function init() {
  translate();
  try {
    user = (await api("me")).user;
    $("identity").textContent = user.username;
    $("account-panel").hidden = false;
    $("admin-panel").hidden = !user.admin;
    if (user.admin) await refreshAdmin();
  } catch {
    $("login-panel").hidden = false;
  }
}
init();
