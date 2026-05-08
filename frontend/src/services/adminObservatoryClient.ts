/**
 * adminObservatoryClient — helpers pour la page Observatory (Sprint mos-A).
 *
 * Pas de fetch JSON ici — l'endpoint Observatory expose un flux SSE
 * (`text/event-stream`) consommé via `EventSource` côté client. Ce module
 * fournit :
 *
 *   - `OBSERVATORY_EVENTS_PATH` : chemin canonique de l'endpoint, typed.
 *   - `ObservatoryEvent`        : type de l'enveloppe (côté backend
 *                                 `routes/observatory.py::_project_event`).
 *   - `parseObservatoryEvent`   : parse et valide minimalement un payload
 *                                 SSE reçu — log + drop si malformé.
 *
 * On ne wrappe pas `EventSource` dans une classe ici : le composant client
 * gère le cycle de vie (open/close) directement, ce qui est plus lisible
 * pour un MVP qu'une indirection. Si on ajoute reconnexion exponentielle
 * + backoff en itération suivante, on factorisera.
 */

/** Path canonique de l'endpoint SSE Observatory. */
export const OBSERVATORY_EVENTS_PATH = "/api/admin/observatory/events";

/**
 * Liste fixe des workers visualisés en MVP. Ces noms doivent matcher les
 * `worker` retournés par le backend (`_infer_worker` côté Python). En cas
 * de divergence, le backend garde l'autorité — la liste est un fallback
 * d'affichage tant que le mesh force-graph n'est pas câblé (itération 2).
 */
export const KNOWN_WORKERS = [
  "picker",
  "prep_worker",
  "shugu_persona_brain",
  "tts_streamer",
  "ambient_daemon",
  "storyboard",
] as const;

export type KnownWorker = (typeof KNOWN_WORKERS)[number];

/**
 * Enveloppe d'un event SSE Observatory — miroir de `_project_event` côté
 * backend. `worker` est typé `string` (et non `KnownWorker`) parce que le
 * backend peut publier d'autres workers (`world_store`, `editor_ws`, etc.)
 * que le front affichera sans crash.
 */
export type ObservatoryEvent = {
  ts: string;
  worker: string;
  type: string;
  payload: unknown;
};

/**
 * Parse un payload SSE en `ObservatoryEvent` ou `null` si malformé.
 *
 * Validation light : on vérifie juste que les 4 champs string sont
 * présents. Le `payload` peut être n'importe quoi côté JSON — on laisse
 * la couche UI le rendre comme `unknown`.
 */
export function parseObservatoryEvent(raw: string): ObservatoryEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const obj = parsed as Record<string, unknown>;
  if (typeof obj.ts !== "string") return null;
  if (typeof obj.worker !== "string") return null;
  if (typeof obj.type !== "string") return null;
  return {
    ts: obj.ts,
    worker: obj.worker,
    type: obj.type,
    payload: obj.payload,
  };
}

/**
 * Ouvre une `EventSource` sur l'endpoint Observatory.
 *
 * En same-origin, les cookies `shugu_access` sont envoyés automatiquement
 * (l'option `withCredentials: true` n'est nécessaire qu'en cross-origin —
 * ce qui n'est pas notre cas en prod, frontend et backend partagent
 * l'origine via le reverse proxy).
 *
 * Le caller doit gérer `.onmessage`, `.onerror` et appeler `.close()` au
 * cleanup (via `useEffect` return).
 */
export function openObservatoryStream(): EventSource {
  return new EventSource(OBSERVATORY_EVENTS_PATH);
}
