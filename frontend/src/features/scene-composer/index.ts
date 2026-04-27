/**
 * Barrel export — Scene Composer feature.
 *
 * Point d'entrée unique pour les imports depuis les sous-modules
 * (viewer, panels, store, api).
 *
 * SceneComposerApp (shell) a été supprimé en Phase 6 cleanup.
 * Les pages Next.js qui en dépendaient ont aussi été supprimées.
 *
 * @module scene-composer
 */

// Exports intentionnellement vides — les modules internes (viewer/, panels/, store/, api/)
// sont importés directement où nécessaire (notamment par scene-editor-v2).
