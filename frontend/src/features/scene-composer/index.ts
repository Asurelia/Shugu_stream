/**
 * Barrel export — Scene Composer feature.
 *
 * Point d'entrée unique pour les imports depuis les pages Next.js.
 * Les modules internes (three-stage, store, panels) sont importés
 * directement depuis leurs paths quand nécessaire dans les tests.
 *
 * @module scene-composer
 */

export { SceneComposerApp, type SceneComposerAppProps } from "./SceneComposerApp";
