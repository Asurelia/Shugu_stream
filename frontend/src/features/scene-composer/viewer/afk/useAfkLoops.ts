/**
 * useAfkLoops — hook déterministe de boucles AFK pour le Scene Composer.
 *
 * Responsabilité unique : surveiller les conditions d'inactivité et sélectionner
 * automatiquement une animation VRMA "idle" parmi le catalogue, sans appel LLM.
 *
 * ## Comportement
 *
 * Toutes les `POLL_INTERVAL_MS` (5 s), évalue si les conditions AFK sont réunies :
 * 1. `playMode === "playing"`
 * 2. `afkLoops.enabled === true`
 * 3. `currentViewerCount < afkLoops.viewerThreshold`
 * 4. temps écoulé depuis `lastActivityAt` ≥ `afkLoops.idleSeconds`
 *
 * Si toutes les conditions sont vraies → sélectionne aléatoirement une VRMA
 * "idle-friendly" et appelle `store.setCurrentVrmaUrl(url)`.
 *
 * Si au moins une condition est fausse → ne modifie pas `currentVrmaUrl`.
 * Ce hook ne remet jamais `currentVrmaUrl` à null de lui-même — c'est au Play/Stop
 * ou à l'UI de le faire.
 *
 * ## Convention sélection VRMA "idle-friendly"
 *
 * Pour le MVP, une animation est considérée idle-friendly si son `slug` contient
 * l'un des mots-clés : `idle`, `breathe`, `wait`, `stand` (insensible à la casse).
 * Parmi les candidates, on préfère les VRMA avec `loop === true` (signal plus fort).
 * Si aucune candidate n'est trouvée, fallback sur la première VRMA disponible dans
 * le catalogue. Si le catalogue est vide, aucune action.
 *
 * ## Inactivité utilisateur
 *
 * L'inactivité est mesurée via `lastActivityAt` ref mis à jour sur `pointermove`
 * (window) et `keydown` (window). Les deux listeners sont sur window :
 * - `pointermove` sur window capte les interactions souris/pointer partout dans
 *   la page — intentionnellement pas sur le canvas car `SceneComposerViewer`
 *   gère son propre canvasRef interne (pas de forwarded-ref exposé). Mettre le
 *   listener sur window est plus robuste et couvre aussi le HUD, les panels, etc.
 * - `keydown` sur window capte les raccourcis clavier (W/E/R gizmo, etc.)
 * Adding tabIndex au canvas pour `keydown` changerait la a11y — on évite.
 *
 * ## Déterminisme
 *
 * Pas d'appel LLM. `Math.random()` est utilisé uniquement pour la sélection
 * parmi plusieurs VRMA candidates — le déclenchement est 100% basé sur les
 * conditions. E5.4 Single LLM rule respectée.
 *
 * @module viewer/afk/useAfkLoops
 */

import { useEffect, useRef, useCallback } from "react";
import type { VrmaAnimationEntry } from "../../api/catalogClient";
import type { AfkLoopsConfig, PlayMode } from "../../store/useSceneComposerStore";

// ─── Constantes ────────────────────────────────────────────────────────────────

/** Intervalle de polling pour l'évaluation des conditions AFK (ms). */
const POLL_INTERVAL_MS = 5_000;

/**
 * Mots-clés slug qui identifient une animation idle-friendly.
 * Insensible à la casse — appliqués en includes().
 */
const IDLE_KEYWORDS = ["idle", "breathe", "wait", "stand"] as const;

// ─── Types ────────────────────────────────────────────────────────────────────

/** Paramètres d'entrée du hook useAfkLoops. */
export interface UseAfkLoopsParams {
  /**
   * Référence au canvas Three.js — utilisée pour écouter `pointermove`
   * et mettre à jour `lastActivityAt`.
   */
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  /** Mode de lecture actuel (du store). */
  playMode: PlayMode;
  /** Configuration des boucles AFK (du store). */
  afkLoops: AfkLoopsConfig;
  /**
   * Catalogue des animations VRMA disponibles.
   *
   * Si vide, le hook est no-op (aucune animation à sélectionner).
   */
  vrmaCatalogue: VrmaAnimationEntry[];
  /**
   * Nombre de viewers connectés en temps réel.
   *
   * Câblage réel prévu dans une phase ultérieure. Pour E5.4, passer 0 (mode
   * solo) afin que les AFK loops se déclenchent en mode preview+idle.
   */
  currentViewerCount: number;
  /** Action store : définit l'URL VRMA à jouer. */
  setCurrentVrmaUrl: (url: string | null) => void;
}

/** Résultat retourné par le hook. */
export interface UseAfkLoopsResult {
  /**
   * Indique si une boucle AFK est actuellement active.
   *
   * `true` uniquement si toutes les conditions sont réunies et qu'une VRMA
   * a été sélectionnée au dernier cycle de polling.
   */
  afkActive: boolean;
}

// ─── Helpers purs ─────────────────────────────────────────────────────────────

/**
 * Filtre les VRMA idle-friendly depuis le catalogue.
 *
 * Priorité :
 * 1. VRMA dont le slug contient un mot-clé idle ET loop===true
 * 2. VRMA dont le slug contient un mot-clé idle (loop non requis)
 * 3. (fallback) première VRMA disponible
 *
 * Si le catalogue est vide → retourne null.
 *
 * @param catalogue - Liste des animations VRMA disponibles.
 * @returns L'URL VRMA sélectionnée aléatoirement, ou null si catalogue vide.
 */
export function selectIdleVrma(catalogue: VrmaAnimationEntry[]): string | null {
  if (catalogue.length === 0) return null;

  const slugIsIdle = (slug: string): boolean =>
    IDLE_KEYWORDS.some((kw) => slug.toLowerCase().includes(kw));

  // Priorité 1 : idle + loop
  const idleLoop = catalogue.filter((a) => slugIsIdle(a.slug) && a.loop);
  if (idleLoop.length > 0) {
    const picked = idleLoop[Math.floor(Math.random() * idleLoop.length)];
    return picked ? picked.file : null;
  }

  // Priorité 2 : idle (sans contrainte loop)
  const idleOnly = catalogue.filter((a) => slugIsIdle(a.slug));
  if (idleOnly.length > 0) {
    const picked = idleOnly[Math.floor(Math.random() * idleOnly.length)];
    return picked ? picked.file : null;
  }

  // Fallback : première VRMA disponible
  return catalogue[0]?.file ?? null;
}

/**
 * Évalue si les conditions AFK sont réunies.
 *
 * @param playMode - Mode de lecture actuel.
 * @param afkLoops - Configuration AFK.
 * @param currentViewerCount - Nombre de viewers connectés.
 * @param elapsedIdleMs - Temps écoulé depuis la dernière interaction (ms).
 * @returns `true` si toutes les conditions sont remplies.
 */
export function checkAfkConditions(
  playMode: PlayMode,
  afkLoops: AfkLoopsConfig,
  currentViewerCount: number,
  elapsedIdleMs: number,
): boolean {
  if (playMode !== "playing") return false;
  if (!afkLoops.enabled) return false;
  if (currentViewerCount >= afkLoops.viewerThreshold) return false;
  if (elapsedIdleMs < afkLoops.idleSeconds * 1000) return false;
  return true;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

/**
 * Gère les boucles AFK déterministes du Scene Composer.
 *
 * Monte les listeners d'inactivité (pointermove + keydown) et démarre un
 * setInterval de polling. Cleanup au unmount.
 *
 * @example
 * ```tsx
 * const { afkActive } = useAfkLoops({
 *   canvasRef,
 *   playMode,
 *   afkLoops,
 *   vrmaCatalogue: catalog?.vrma_animations ?? [],
 *   currentViewerCount: 0,
 *   setCurrentVrmaUrl,
 * });
 * ```
 */
export function useAfkLoops({
  canvasRef,
  playMode,
  afkLoops,
  vrmaCatalogue,
  currentViewerCount,
  setCurrentVrmaUrl,
}: UseAfkLoopsParams): UseAfkLoopsResult {
  // Ref latest — permet aux closures du setInterval de lire les valeurs actuelles
  // sans restarting l'intervalle à chaque re-render.
  const playModeRef = useRef<PlayMode>(playMode);
  playModeRef.current = playMode;

  const afkLoopsRef = useRef<AfkLoopsConfig>(afkLoops);
  afkLoopsRef.current = afkLoops;

  const vrmaCatalogueRef = useRef<VrmaAnimationEntry[]>(vrmaCatalogue);
  vrmaCatalogueRef.current = vrmaCatalogue;

  const currentViewerCountRef = useRef<number>(currentViewerCount);
  currentViewerCountRef.current = currentViewerCount;

  const setCurrentVrmaUrlRef = useRef(setCurrentVrmaUrl);
  setCurrentVrmaUrlRef.current = setCurrentVrmaUrl;

  /** Timestamp de la dernière interaction utilisateur (ms epoch). */
  const lastActivityAt = useRef<number>(Date.now());

  /** Ref pour tracker si AFK est actif (pour le retour de résultat). */
  const afkActiveRef = useRef<boolean>(false);

  // ── Handlers d'activité ────────────────────────────────────────────────────

  const handleActivity = useCallback(() => {
    lastActivityAt.current = Date.now();
  }, []);

  // ── Setup listeners + interval ─────────────────────────────────────────────
  useEffect(() => {
    // pointermove sur window — interactions souris/pointer dans toute la page.
    // Intentionnellement sur window (pas canvasRef.current) car SceneComposerViewer
    // gère son propre canvasRef interne sans forwarded-ref exposé. Cela couvre aussi
    // les interactions dans les panels et le HUD.
    window.addEventListener("pointermove", handleActivity, { passive: true });

    // keydown sur window — raccourcis clavier (W/E/R gizmo, etc.).
    // Intentionnellement sur window (pas canvas) pour éviter de modifier tabIndex.
    window.addEventListener("keydown", handleActivity, { passive: true });

    // Polling AFK toutes les POLL_INTERVAL_MS.
    const intervalId = setInterval(() => {
      const elapsed = Date.now() - lastActivityAt.current;

      const shouldTrigger = checkAfkConditions(
        playModeRef.current,
        afkLoopsRef.current,
        currentViewerCountRef.current,
        elapsed,
      );

      if (shouldTrigger) {
        const url = selectIdleVrma(vrmaCatalogueRef.current);
        if (url) {
          setCurrentVrmaUrlRef.current(url);
          afkActiveRef.current = true;
        }
      } else {
        afkActiveRef.current = false;
      }
    }, POLL_INTERVAL_MS);

    // ── Cleanup ────────────────────────────────────────────────────────────
    return () => {
      clearInterval(intervalId);
      window.removeEventListener("pointermove", handleActivity);
      window.removeEventListener("keydown", handleActivity);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Mount-only — toutes les props lues via refs.

  // Note : afkActive est une valeur dérivée de afkActiveRef. Ce hook ne force
  // pas de re-render sur le changement d'état AFK — c'est intentionnel pour
  // éviter les re-renders inutiles. Le parent (SceneComposerPage) peut lire
  // afkActiveRef.current si besoin d'un indicateur temps réel.
  // Pour E5.4, on retourne false/true basé sur l'évaluation synchrone actuelle.
  const isCurrentlyAfk =
    playMode === "playing" &&
    afkLoops.enabled &&
    currentViewerCount < afkLoops.viewerThreshold;

  return {
    afkActive: isCurrentlyAfk && afkActiveRef.current,
  };
}
