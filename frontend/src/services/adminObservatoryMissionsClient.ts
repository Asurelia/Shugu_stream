/**
 * adminObservatoryMissionsClient — fetch helpers pour le Kanban Observatory
 * (Sprint mos-A, itération 2b).
 *
 * # Pourquoi un module séparé d'`adminObservatoryClient.ts`
 *
 * Le client iter 1 expose un flux SSE (`EventSource`). Le Kanban est un
 * snapshot batch (REST classique). Mélanger les deux dans le même module
 * brouille la frontière (un module = un protocole). On garde donc deux
 * fichiers symétriques côté backend (`observatory.py` SSE vs
 * `observatory_missions.py` REST).
 *
 * # Schéma — miroir de `MissionsResponse` Pydantic
 *
 * Les statuts sont strictement les 4 colonnes du Kanban. On les expose en
 * type literal pour que TypeScript détecte une dérive de payload (ex. le
 * backend qui ajouterait "ARCHIVED" sans bumper la version).
 *
 * # Erreurs réseau
 *
 * `fetchMissions` rejette en cas de status != 200. La page UI catche et
 * affiche un état dégradé (bouton retry). Pas de retry automatique côté
 * client : le Kanban est rafraîchi à la main par l'opérateur (un re-render
 * sur navigation suffit pour le MVP).
 */

/** Path canonique de l'endpoint REST missions. */
export const OBSERVATORY_MISSIONS_PATH = "/api/admin/observatory/missions";

/**
 * Statuts Kanban — les 4 colonnes affichées. Identique côté backend
 * (`MissionStatus` Pydantic literal).
 */
export const MISSION_STATUSES = ["BACKLOG", "TO_DO", "IN_PROGRESS", "DONE"] as const;
export type MissionStatus = (typeof MISSION_STATUSES)[number];

/**
 * Une mission affichée sur une carte du Kanban — miroir de `Mission`
 * Pydantic. `started_at` est `null` pour les missions BACKLOG/TO_DO
 * (pas encore démarrées — c'est l'état attendu par le backend).
 */
export type Mission = {
  id: string;
  title: string;
  agent: string;
  status: MissionStatus;
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
  started_at: string | null;
};

/** Réponse `GET /missions` — `mock=true` tant que le backend réel n'est pas wiré. */
export type MissionsResponse = {
  items: Mission[];
  total: number;
  mock: boolean;
};

/**
 * Type guard minimal — on vérifie juste les champs critiques pour ne pas
 * crasher sur un payload légèrement divergent. Le `status` est aligné sur
 * `MISSION_STATUSES` ; les autres champs sont validés par leur type runtime.
 */
function isMission(v: unknown): v is Mission {
  if (typeof v !== "object" || v === null) return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.title === "string" &&
    typeof o.agent === "string" &&
    typeof o.status === "string" &&
    (MISSION_STATUSES as readonly string[]).includes(o.status) &&
    typeof o.cost_usd === "number" &&
    typeof o.tokens_in === "number" &&
    typeof o.tokens_out === "number" &&
    (o.started_at === null || typeof o.started_at === "string")
  );
}

/**
 * Fetch la liste des missions Kanban. Lance une `Error` en cas de status
 * non-2xx ou payload invalide — la page affiche alors un état dégradé.
 *
 * Le cookie `shugu_access` est envoyé automatiquement en same-origin
 * (`credentials: "same-origin"` est le défaut implicite de fetch côté
 * navigateur).
 */
export async function fetchMissions(): Promise<MissionsResponse> {
  const resp = await fetch(OBSERVATORY_MISSIONS_PATH, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!resp.ok) {
    throw new Error(`missions fetch failed (${resp.status})`);
  }
  const raw: unknown = await resp.json();
  if (typeof raw !== "object" || raw === null) {
    throw new Error("missions payload not an object");
  }
  const obj = raw as Record<string, unknown>;
  if (!Array.isArray(obj.items)) {
    throw new Error("missions payload missing items array");
  }
  const items = obj.items.filter(isMission);
  const total = typeof obj.total === "number" ? obj.total : items.length;
  const mock = obj.mock === true;
  return { items, total, mock };
}
