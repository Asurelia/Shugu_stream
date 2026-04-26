/**
 * animations — VRMA loading + AnimationMixer pour le VRM.
 *
 * Responsabilité unique : charger une animation VRMA et la jouer via un
 * `THREE.AnimationMixer` attaché au VRM. Gère le cycle play/stop.
 *
 * NOTE ARCHITECTURE : Figma_mini (StreamStage) utilisait `poseVrm` avec des
 * rotations d'os manuelles — NON portable car dépend d'un système de pose
 * propriétaire. Ce module utilise à la place la bibliothèque Shugu existante
 * `src/lib/VRMAnimation/loadVRMAnimation.ts` (standard VRMA spec) et
 * `VRMAnimation.createAnimationClip(vrm)` pour générer le clip Three.js.
 *
 * @module three-stage/animations
 */

import * as THREE from "three";
import type { VRM } from "@pixiv/three-vrm";
import { loadVRMAnimation } from "@/lib/VRMAnimation/loadVRMAnimation";

// ─── Types ────────────────────────────────────────────────────────────────────

/** Rig d'animation actif sur un VRM. */
export interface AnimationRig {
  mixer: THREE.AnimationMixer;
  /** Stoppe l'animation en cours et libère les ressources AnimationMixer. */
  stop: () => void;
}

// ─── Implémentation ────────────────────────────────────────────────────────────

/**
 * Joue une animation VRMA sur le VRM fourni.
 *
 * Utilise `VRMAnimation.createAnimationClip(vrm)` — méthode officielle de la
 * bibliothèque Shugu (voir `src/lib/VRMAnimation/VRMAnimation.ts` ligne 28).
 * Elle traduit les tracks humanoid (rotation/translation) et les expressions
 * en KeyframeTracks Three.js compatibles.
 *
 * @param vrm     - Le VRM cible déjà monté dans la scène.
 * @param vrmaUrl - URL relative du fichier VRMA
 *                  (ex: `/assets/vrma/wave.vrma`).
 * @param loop    - Si `true`, l'animation boucle en LoopRepeat (défaut: false).
 * @returns Un `AnimationRig` avec mixer + stop(), ou `null` si l'URL est vide
 *          ou si le chargement échoue.
 */
export async function playVrmaAnimation(
  vrm: VRM,
  vrmaUrl: string,
  loop = false,
): Promise<AnimationRig | null> {
  if (!vrmaUrl) return null;

  let vrmAnimation: Awaited<ReturnType<typeof loadVRMAnimation>>;
  try {
    vrmAnimation = await loadVRMAnimation(vrmaUrl);
  } catch (err) {
    console.warn("[animations] Échec chargement VRMA:", vrmaUrl, err);
    return null;
  }

  if (!vrmAnimation) {
    console.warn("[animations] VRMAnimation null pour:", vrmaUrl);
    return null;
  }

  // `createAnimationClip` traduit les tracks VRMA en KeyframeTracks Three.js
  // adaptés au rig du VRM passé (normalisation des nœuds humanoid).
  const clip = vrmAnimation.createAnimationClip(vrm);

  const mixer = new THREE.AnimationMixer(vrm.scene);
  const action = mixer.clipAction(clip);

  action.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
  action.clampWhenFinished = !loop;
  action.play();

  function stop(): void {
    action.stop();
    mixer.stopAllAction();
    mixer.uncacheRoot(vrm.scene);
  }

  return { mixer, stop };
}

/**
 * Met à jour le mixer de l'animation (à appeler dans la boucle RAF).
 *
 * @param rig   - Le `AnimationRig` actif (peut être `null`).
 * @param delta - Temps écoulé depuis le dernier frame en secondes.
 */
export function tickAnimation(rig: AnimationRig | null, delta: number): void {
  if (rig) {
    rig.mixer.update(delta);
  }
}
