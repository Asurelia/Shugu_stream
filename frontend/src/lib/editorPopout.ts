/**
 * Scene Editor — helper pop-out multi-écran (Phase G).
 *
 * Centralise la logique de "pop out panel" pour le Scene Editor : ouverture
 * d'une fenêtre secondaire (`window.open`) qui pointe vers une vraie route
 * Next.js (`/shugu/admin/scene-editor-popout?panel=...`) et synchronisation
 * bidirectionnelle entre parent et popout via l'API navigateur native
 * `BroadcastChannel`.
 *
 * # Canal
 *
 * Un unique canal partagé `scene-editor` est utilisé. Toutes les fenêtres
 * ouvertes sur l'éditeur (parent + chaque popout) publient et écoutent sur
 * ce canal. Les messages sont typés via {@link PopoutMessage}.
 *
 * # Sécurité — défense en profondeur
 *
 * `BroadcastChannel` est strictement same-origin par spec du navigateur :
 * un autre onglet sur un domaine différent ne reçoit pas nos messages.
 * MAIS la conséquence opérationnelle est qu'un autre onglet **same-origin**
 * (ex : un autre Scene Editor ouvert dans un autre onglet, ou pire, un XSS
 * sur une autre route `localhost:3005/...`) PEUT publier sur notre canal
 * et muter notre store si on ne filtre rien d'autre.
 *
 * Le check `senderOrigin === window.location.origin` ne capture donc QUE
 * les forgeries internes au même tab (DevTools console). Pour bloquer la
 * forgerie cross-tab same-origin on ajoute un **shared secret session-
 * scoped** (`senderNonce`) :
 *
 *   1. La fenêtre parent génère un nonce (`crypto.randomUUID()`) au boot
 *      et le persiste dans `sessionStorage` (clé
 *      {@link POPOUT_NONCE_STORAGE_KEY}). `sessionStorage` est scopé à un
 *      tab + ses popups héritées (`window.open` même origin), donc un
 *      autre onglet n'y a pas accès.
 *   2. Quand le parent ouvre un popout via {@link openPanelWindow}, il
 *      passe le nonce dans la query string (`?nonce=...`). Le popout lit
 *      cette valeur et appelle {@link setPopoutNonce} au mount.
 *   3. Toute publication embarque `senderNonce` ; toute réception vérifie
 *      l'égalité avec le nonce courant. Mismatch → drop + warn.
 *
 * Note : ce N'EST PAS un signed token (HMAC complet côté backend). C'est
 * un secret partagé local, suffisant pour défendre contre un onglet frère
 * non-coopératif. Une évolution future pourrait basculer sur un JWT signé
 * côté serveur si le scope se durcit (multi-user, multi-frame).
 *
 * Tout message rejeté est loggué en `console.warn` (sans throw) pour rester
 * silencieux en production. L'ordre des checks à la réception est :
 *   1. forme valide (drop silencieux si pas valide)
 *   2. senderOrigin match (warn si mismatch)
 *   3. senderNonce match (warn si mismatch)
 *   4. panelKey scope (drop silencieux si pas le bon panel)
 *
 * # Debounce publish
 *
 * Les publish `state-sync` sont debounced 50ms par `panelKey` pour éviter
 * de spammer le canal quand le store change rapidement (drag, slider). Le
 * dernier message queued est flushé à la main via {@link flushPopout} (on
 * l'appelle au cleanup pour ne pas perdre la toute dernière mutation).
 *
 * # SSR / fallback
 *
 * `typeof BroadcastChannel === "undefined"` en SSR Next.js et sur des
 * vieux browsers (IE, Safari < 15.4). Toutes les fonctions publiques
 * doivent être no-op silencieuses dans ce cas — aucun throw, aucun log
 * bruyant (on accepte une expérience dégradée sans sync).
 */

import type { PanelKey } from "@/features/editor-shared";

const CHANNEL_NAME = "scene-editor";

/** Debounce par défaut du publish `state-sync` (ms). */
const DEFAULT_PUBLISH_DEBOUNCE_MS = 50;

/**
 * Clé `sessionStorage` où le parent persiste le nonce de session. Lecture
 * partagée par les popouts ouverts depuis ce tab — `sessionStorage` est
 * hérité par les popups same-origin (cf. spec WHATWG storage area).
 */
export const POPOUT_NONCE_STORAGE_KEY = "scene-editor-popout-nonce";

/**
 * Nom du paramètre query qu'on injecte dans l'URL popout pour transmettre
 * le nonce. Le popout en lit la valeur via `router.query.nonce` (ou
 * `URLSearchParams` côté lib).
 */
export const POPOUT_NONCE_QUERY_PARAM = "nonce";

/* ─────────────────────────── TYPES ─────────────────────────── */

/** Re-export pour les consumers de cette lib qui ont déjà l'import editorPopout. */
export type { PanelKey };

/**
 * Rôle de l'émetteur du message. `'parent'` = la fenêtre principale de
 * l'éditeur, `'popout'` = une fenêtre détachée ouverte via
 * {@link openPanelWindow}. Indispensable pour ignorer ses propres messages
 * (un BroadcastChannel rebondit aussi vers l'émetteur sur d'autres contextes
 * selon les navigateurs, donc on filtre explicitement).
 */
export type PopoutRole = "parent" | "popout";

/** Discriminant des messages circulant sur le canal `scene-editor`. */
export type PopoutMessageType =
  | "state-sync"
  | "panel-action"
  | "popout-closed"
  | "popout-ready";

/**
 * Message structuré échangé entre parent et popout. `senderOrigin` est
 * ajouté automatiquement par {@link publishPopout} (on ne le demande PAS
 * au caller — c'est lui qui sert de contrôle anti-forgerie).
 */
export interface PopoutMessage {
  type: PopoutMessageType;
  payload?: unknown;
  origin: PopoutRole;
  panelKey: PanelKey;
  ts: number;
  /**
   * Origin navigateur de l'émetteur (`window.location.origin` au moment
   * du publish). Vérifiée à la réception pour rejeter des messages dont
   * l'origin mentirait sur sa provenance.
   */
  senderOrigin: string;
  /**
   * Nonce partagé scope-tab (cf. doc en tête de fichier — section Sécurité).
   * Le parent en publie le secret via sessionStorage + URL query ; les
   * popouts héritent. Tout message dont `senderNonce` ne matche pas le
   * nonce courant est rejeté avec un warn.
   */
  senderNonce: string;
}

/** Options passées à {@link openPanelWindow}. */
export interface OpenPanelOptions {
  /** Largeur de la fenêtre (défaut 800). */
  width?: number;
  /** Hauteur de la fenêtre (défaut 600). */
  height?: number;
  /**
   * Chaîne `features` passée à `window.open`. Par défaut on construit une
   * chaîne qui désactive menubar/toolbar/location/status pour un rendu
   * propre "app-like".
   */
  features?: string;
  /**
   * Chemin de la page popout. Défaut : `/shugu/admin/scene-editor-popout`.
   * Utile pour les tests qui veulent cibler une autre route ou pour un
   * déploiement multi-tenant ultérieur.
   */
  popoutPath?: string;
}

/** Subscriber signature : handler invoqué pour chaque message valide. */
export type PopoutMessageHandler = (msg: PopoutMessage) => void;

/* ─────────────────────────── FEATURE DETECTION ─────────────────────────── */

/**
 * Renvoie `true` si l'environnement supporte l'ouverture de fenêtres
 * secondaires + BroadcastChannel. False en SSR et sur les vieux browsers.
 */
function isPopoutSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.open === "function" &&
    typeof BroadcastChannel !== "undefined"
  );
}

/**
 * Renvoie l'origin courante, ou `null` si on est en SSR. Extrait dans un
 * helper pour que les tests Vitest puissent mocker `window.location` sans
 * fuite entre suites.
 */
function currentOrigin(): string | null {
  if (typeof window === "undefined" || !window.location) return null;
  return window.location.origin;
}

/* ─────────────────────────── CHANNEL SINGLETON ─────────────────────────── */

/**
 * Lazy-init d'un singleton BroadcastChannel. On le crée à la première
 * souscription/publish, et on ne le close JAMAIS automatiquement — seuls
 * les tests peuvent le reset via {@link __resetPopoutChannelForTests}.
 *
 * Rationale : un BroadcastChannel global reste léger (pas de handle OS),
 * mais le fermer puis le recréer lors d'un unsubscribe casserait la
 * réception des publishers qui partagent le même canal sur la même page.
 * On s'appuie donc sur la garbage collection implicite du browser quand
 * la page unload.
 */
let sharedChannel: BroadcastChannel | null = null;

function getChannel(): BroadcastChannel | null {
  if (!isPopoutSupported()) return null;
  if (sharedChannel === null) {
    try {
      sharedChannel = new BroadcastChannel(CHANNEL_NAME);
    } catch {
      // Certains navigateurs (test browsers très anciens) exposent le
      // constructeur mais throw à l'init. Fallback silencieux.
      sharedChannel = null;
    }
  }
  return sharedChannel;
}

/* ─────────────────────────── NONCE STATE ─────────────────────────── */

/**
 * Nonce de session courant. Lazy-init :
 *  - parent : si vide au premier `publishPopout`/`subscribePopout`, on lit
 *    `sessionStorage[POPOUT_NONCE_STORAGE_KEY]`. Si ladite clé est elle-
 *    même vide, on génère un UUID v4 et on l'écrit pour la persistance.
 *  - popout : la page popout doit appeler {@link setPopoutNonce} au mount
 *    avec la valeur passée dans `?nonce=...` AVANT de s'abonner. Sinon
 *    le lazy-init va générer un nouveau nonce qui ne matchera pas celui
 *    du parent → tous les messages seront droppés.
 *
 * Volontairement module-scoped (pas dans le channel singleton) parce que
 * la durée de vie du nonce dépasse celle d'une instance BroadcastChannel
 * — les tests peuvent reset le channel sans invalider le nonce.
 */
let currentNonce: string | null = null;

/**
 * Génère un UUID v4 cryptographiquement sûr. Wrap pour fallback si
 * `crypto.randomUUID` n'existe pas (vieux Edge, jsdom < 22).
 */
function generateNonce(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  // Fallback non-crypto (uniquement pour environnements de test où le
  // shim crypto n'existerait pas). 2^64 entropy suffit pour notre usage
  // (déjà 2^16 collision impossibles dans la fenêtre de session).
  return (
    Date.now().toString(36) +
    "-" +
    Math.random().toString(36).slice(2) +
    "-" +
    Math.random().toString(36).slice(2)
  );
}

/**
 * Setter explicite du nonce. À appeler côté popout avec la valeur reçue
 * dans `?nonce=` AVANT toute opération publish/subscribe.
 *
 * Côté parent on n'a normalement PAS besoin d'appeler ce setter : le
 * lazy-init via sessionStorage suffit. On l'expose tout de même pour
 * les tests Vitest qui veulent fixer un nonce déterministe.
 */
export function setPopoutNonce(nonce: string): void {
  if (typeof nonce !== "string" || nonce.length === 0) return;
  currentNonce = nonce;
}

/**
 * Renvoie le nonce courant, lazy-initialisé depuis `sessionStorage` si
 * possible (parent au boot) ou généré à chaud sinon. Côté popout, si on
 * arrive ici sans avoir appelé {@link setPopoutNonce}, on retombe sur
 * le mécanisme parent (lecture sessionStorage) — ce qui matche dans le
 * cas where popup hérite du sessionStorage du parent. Si tout échoue,
 * on génère localement un nonce qui NE matchera PAS celui du parent et
 * tous nos messages seront droppés (fail-closed).
 */
function getPopoutNonce(): string {
  if (currentNonce !== null) return currentNonce;
  // Tentative de récupération depuis sessionStorage.
  if (typeof window !== "undefined" && window.sessionStorage) {
    try {
      const stored = window.sessionStorage.getItem(POPOUT_NONCE_STORAGE_KEY);
      if (stored !== null && stored.length > 0) {
        currentNonce = stored;
        return stored;
      }
      // Première initialisation parent : on génère + on écrit.
      const fresh = generateNonce();
      window.sessionStorage.setItem(POPOUT_NONCE_STORAGE_KEY, fresh);
      currentNonce = fresh;
      return fresh;
    } catch {
      // sessionStorage peut throw (quotas, mode privé Safari). Fallback
      // sur un nonce module-scoped non-persisté.
    }
  }
  const fresh = generateNonce();
  currentNonce = fresh;
  return fresh;
}

/**
 * Test hook : reset le nonce courant. À utiliser dans `beforeEach` des
 * tests Vitest pour garantir que chaque test repart sur un nonce frais.
 */
export function __resetPopoutNonceForTests(): void {
  currentNonce = null;
  if (typeof window !== "undefined" && window.sessionStorage) {
    try {
      window.sessionStorage.removeItem(POPOUT_NONCE_STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }
}

/**
 * Test hook : reset le singleton + efface les timers en attente. À utiliser
 * uniquement dans `beforeEach` des tests Vitest. Exporté avec un préfixe
 * `__` pour signaler qu'il ne fait pas partie de l'API publique.
 */
export function __resetPopoutChannelForTests(): void {
  if (sharedChannel !== null) {
    try {
      sharedChannel.close();
    } catch {
      /* ignore */
    }
    sharedChannel = null;
  }
  // Flush timers debounce en cours
  pendingDebounces.forEach((timer) => clearTimeout(timer));
  pendingDebounces.clear();
  pendingMessages.clear();
}

/* ─────────────────────────── DEBOUNCE STATE ─────────────────────────── */

/**
 * Debounce par `panelKey` + `type`. On a besoin de debouncer séparément
 * les messages `state-sync` d'un panel donné, sans ralentir les
 * `panel-action` ou les `popout-ready` qui sont ponctuels.
 *
 * La clé est `${type}:${panelKey}` — un `state-sync` du panel `scene` et
 * un `state-sync` du panel `inspector` n'interfèrent pas entre eux.
 */
const pendingDebounces = new Map<string, ReturnType<typeof setTimeout>>();
const pendingMessages = new Map<string, PopoutMessage>();

function debounceKeyOf(msg: Pick<PopoutMessage, "type" | "panelKey">): string {
  return `${msg.type}:${msg.panelKey}`;
}

/**
 * Flushe immédiatement tous les messages debouncés en attente. À appeler
 * avant un cleanup (unmount, window close) pour ne pas perdre la dernière
 * mutation.
 *
 * Expose aussi la possibilité de flush une seule clé via l'argument
 * optionnel — pratique pour les tests fins.
 */
export function flushPopout(key?: string): void {
  const channel = getChannel();
  if (!channel) {
    // Rien à flush si le canal n'existe pas — on clear quand même les
    // structures internes pour éviter une fuite mémoire sur reload.
    pendingDebounces.forEach((t) => clearTimeout(t));
    pendingDebounces.clear();
    pendingMessages.clear();
    return;
  }
  const flushOne = (k: string) => {
    const timer = pendingDebounces.get(k);
    if (timer !== undefined) {
      clearTimeout(timer);
      pendingDebounces.delete(k);
    }
    const msg = pendingMessages.get(k);
    if (msg !== undefined) {
      pendingMessages.delete(k);
      try {
        channel.postMessage(msg);
      } catch {
        /* canal peut être closed si on flush après __reset */
      }
    }
  };
  if (key !== undefined) {
    flushOne(key);
    return;
  }
  // Snapshot des clés pour éviter la mutation pendant l'itération.
  const keys = Array.from(pendingDebounces.keys());
  for (const k of keys) flushOne(k);
}

/* ─────────────────────────── PUBLIC API ─────────────────────────── */

/**
 * Ouvre une fenêtre secondaire pour afficher un seul panel du Scene
 * Editor. La fenêtre pointe vers la route Next.js
 * `/shugu/admin/scene-editor-popout?panel=<panelKey>` et monte un React
 * app minimal qui dialogue avec le parent via BroadcastChannel.
 *
 * - Retourne la `Window` native si l'open a réussi.
 * - Retourne `null` si :
 *    * on est en SSR (pas de `window.open`),
 *    * BroadcastChannel est indisponible (navigateur trop vieux),
 *    * le browser a bloqué la popup (politique anti-popup).
 *
 * Le caller est responsable d'observer `win.closed` pour détecter la
 * fermeture (fallback au message `popout-closed`).
 */
export function openPanelWindow(
  panelKey: PanelKey,
  options: OpenPanelOptions = {},
): Window | null {
  if (!isPopoutSupported()) {
    // Fallback silencieux : SSR ou navigateur trop vieux.
    return null;
  }
  const {
    width = 800,
    height = 600,
    features,
    popoutPath = "/shugu/admin/scene-editor-popout",
  } = options;

  const defaultFeatures =
    `width=${width},height=${height},` +
    "menubar=no,toolbar=no,location=no,status=no,resizable=yes,scrollbars=yes";
  const featuresStr = features ?? defaultFeatures;

  // Même origine garantie car on construit une URL relative : le browser
  // n'élargit jamais au-delà de `window.location.origin`.
  // On embarque le nonce dans la query string : la popup en a besoin pour
  // que ses publish soient acceptés par les subscribers parent. Le nonce
  // ne fuite pas en logs serveur — la route est statique côté Next, pas
  // d'API call qui passerait par un access-log.
  const nonce = getPopoutNonce();
  const url =
    `${popoutPath}?panel=${encodeURIComponent(panelKey)}` +
    `&${POPOUT_NONCE_QUERY_PARAM}=${encodeURIComponent(nonce)}`;
  // Nom stable par panel : rouvrir la même "pop out Inspector" bascule
  // le focus sur la fenêtre existante au lieu d'en créer une seconde.
  const windowName = `shugu-scene-editor-popout-${panelKey}`;

  let win: Window | null = null;
  try {
    win = window.open(url, windowName, featuresStr);
  } catch {
    // Certains navigateurs throw si on est dans un contexte de sandbox
    // interdit.
    win = null;
  }
  return win;
}

/**
 * Publie un message sur le canal partagé. Les champs `ts`, `senderOrigin`
 * et `senderNonce` sont remplis automatiquement (le caller ne les fournit
 * PAS — c'est la lib qui contrôle leur valeur, sinon on perdrait la
 * propriété anti-forgerie).
 *
 * Debouncé par (`type`, `panelKey`) avec `DEFAULT_PUBLISH_DEBOUNCE_MS` pour
 * les `state-sync` — les autres types sont envoyés immédiatement (ce sont
 * des signaux ponctuels : `popout-ready`, `popout-closed`, `panel-action`).
 */
export function publishPopout(
  msg: Omit<PopoutMessage, "ts" | "senderOrigin" | "senderNonce">,
): void {
  const channel = getChannel();
  if (!channel) return;
  const origin = currentOrigin();
  if (origin === null) return;

  const fullMessage: PopoutMessage = {
    ...msg,
    ts: Date.now(),
    senderOrigin: origin,
    senderNonce: getPopoutNonce(),
  };

  // Pas de debounce pour les signaux ponctuels — on perdrait l'événement
  // (ex: popout-ready) si un `state-sync` debounced le succède immédiatement.
  if (fullMessage.type !== "state-sync") {
    try {
      channel.postMessage(fullMessage);
    } catch {
      /* canal fermé en course */
    }
    return;
  }

  const key = debounceKeyOf(fullMessage);
  pendingMessages.set(key, fullMessage);
  const existing = pendingDebounces.get(key);
  if (existing !== undefined) clearTimeout(existing);
  const timer = setTimeout(() => {
    pendingDebounces.delete(key);
    const queued = pendingMessages.get(key);
    pendingMessages.delete(key);
    if (queued === undefined) return;
    const ch = getChannel();
    if (!ch) return;
    try {
      ch.postMessage(queued);
    } catch {
      /* canal fermé */
    }
  }, DEFAULT_PUBLISH_DEBOUNCE_MS);
  pendingDebounces.set(key, timer);
}

/**
 * Valide la structure d'un message reçu. On exige :
 *   - un objet non-nul,
 *   - `type` ∈ {state-sync, panel-action, popout-closed, popout-ready},
 *   - `origin` ∈ {parent, popout},
 *   - `panelKey` string,
 *   - `ts` number,
 *   - `senderOrigin` string,
 *   - `senderNonce` string non-vide.
 *
 * Retourne `true` si OK, `false` sinon. N'affiche pas de warning ici — le
 * caller (subscribePopout handler) logge seulement les rejets dus à la
 * sécurité (origin/nonce mismatch), pas les messages malformés (trop
 * bruyant si un autre onglet ancien spam le canal).
 */
function isValidMessage(msg: unknown): msg is PopoutMessage {
  if (!msg || typeof msg !== "object") return false;
  const m = msg as Record<string, unknown>;
  if (
    m.type !== "state-sync" &&
    m.type !== "panel-action" &&
    m.type !== "popout-closed" &&
    m.type !== "popout-ready"
  ) {
    return false;
  }
  if (m.origin !== "parent" && m.origin !== "popout") return false;
  if (typeof m.panelKey !== "string") return false;
  if (typeof m.ts !== "number") return false;
  if (typeof m.senderOrigin !== "string") return false;
  if (typeof m.senderNonce !== "string" || m.senderNonce.length === 0) {
    return false;
  }
  return true;
}

/**
 * Souscrit aux messages destinés à un `panelKey` donné. Le handler est
 * invoqué uniquement pour les messages dont :
 *   - la forme est valide ({@link isValidMessage}),
 *   - `senderOrigin === window.location.origin` (sécurité tab-scope),
 *   - `senderNonce === <nonce de session courant>` (sécurité cross-tab),
 *   - `panelKey === <paramètre>` (scope au panel).
 *
 * Retourne une fonction de désinscription. La désinscription enlève
 * seulement ce listener — elle ne ferme PAS le canal partagé (d'autres
 * abonnés peuvent encore l'utiliser).
 */
export function subscribePopout(
  panelKey: PanelKey,
  onMessage: PopoutMessageHandler,
): () => void {
  const channel = getChannel();
  if (!channel) {
    // Fallback silencieux : on retourne une dispose no-op pour que le
    // caller puisse l'invoquer sans garde.
    return () => {};
  }
  const origin = currentOrigin();

  const listener = (event: MessageEvent) => {
    const data = event.data;
    if (!isValidMessage(data)) {
      // Message malformé : drop silencieux. Peut arriver si une vieille
      // version du frontend est encore ouverte dans un autre onglet.
      return;
    }
    // Sécurité couche 1 : rejet explicite si senderOrigin ne matche pas
    // l'origin courante. Capture les forgeries DevTools intra-tab. À
    // checker AVANT le nonce pour préserver le warn "mismatched origin"
    // attendu par le scenario 4 Playwright.
    if (origin !== null && data.senderOrigin !== origin) {
      console.warn(
        "[editorPopout] dropped message with mismatched origin",
        { received: data.senderOrigin, expected: origin },
      );
      return;
    }
    // Sécurité couche 2 : rejet si senderNonce ne matche pas le nonce
    // courant. Capture les forgeries cross-tab same-origin (un autre
    // onglet `localhost:3005` n'a pas accès à notre sessionStorage).
    const expectedNonce = getPopoutNonce();
    if (data.senderNonce !== expectedNonce) {
      console.warn(
        "[editorPopout] dropped message with mismatched nonce",
        { received: data.senderNonce, expected: expectedNonce },
      );
      return;
    }
    if (data.panelKey !== panelKey) return;
    onMessage(data);
  };

  channel.addEventListener("message", listener);
  return () => {
    channel.removeEventListener("message", listener);
  };
}

/* ─────────────────────────── CONSTANTS EXPORTS ─────────────────────────── */

/** Exposé pour les tests — évite de hardcoder la valeur dans les specs. */
export const POPOUT_PUBLISH_DEBOUNCE_MS = DEFAULT_PUBLISH_DEBOUNCE_MS;
/** Exposé pour debug / tests. */
export const POPOUT_CHANNEL_NAME = CHANNEL_NAME;
