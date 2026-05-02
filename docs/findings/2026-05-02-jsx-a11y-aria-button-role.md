---
date: 2026-05-02
status: open
severity: low
discovered_during: PR #76 (Sprint A migration Next 13→16)
related_files:
  - frontend/src/features/scene-composer/panels/ScenesListPanel.tsx
---

## Résumé

Un élément utilise `role="button"` avec `aria-selected` — combinaison invalide selon ARIA spec. Le bon pattern serait `role="tab"` (ou `role="option"` selon contexte) puisque `aria-selected` est destiné aux items qui peuvent être sélectionnés (tabs, listbox options, gridcell).

```
./src/features/scene-composer/panels/ScenesListPanel.tsx
198:15  Warning: The attribute aria-selected is not supported by the role button.
```

## Symptôme observé

Warning ESLint `jsx-a11y/role-supports-aria-props`. Non bloquant.

## Impact

- **Accessibility** : screen readers peuvent annoncer incorrectement
  l'élément. Un user de NVDA/VoiceOver voit "button" mais le `aria-selected`
  est ignoré ou rapporté comme "selected" sans contexte clair.
- **Conformance WCAG** : viol mineur de WCAG 4.1.2 (Name, Role, Value).

## Cause racine probable

Pattern UI où un bouton dans une liste de scènes affiche l'état "scène
active" via un highlight visuel + `aria-selected={isActive}`. Le dev a
choisi `role="button"` parce que c'est cliquable, sans réaliser que
`aria-selected` impliquait un contexte de sélection (listbox/tablist).

## Action recommandée

**Phase 2 (App Router migration) ou audit a11y dédié** :

Deux options selon le pattern UX intention :

### Option A : C'est une liste sélectionnable (le plus probable)
Remplacer le wrapper par `role="listbox"` avec items `role="option"` :
```tsx
<div role="listbox" aria-label="Liste des scènes">
  {scenes.map(scene => (
    <div
      key={scene.id}
      role="option"
      aria-selected={scene.id === activeId}
      tabIndex={scene.id === activeId ? 0 : -1}
      onClick={() => activate(scene.id)}
      onKeyDown={...}  // arrow keys navigation
    >
      {scene.name}
    </div>
  ))}
</div>
```

### Option B : C'est juste un bouton qui happen to indiquer un état
Retirer `aria-selected` et utiliser `aria-pressed` :
```tsx
<button
  aria-pressed={isActive}
  onClick={() => activate(scene.id)}
>
  {scene.name}
</button>
```

## Pourquoi pas en Sprint A

A11y demande de l'analyse UX (clavier, screen readers). Out of scope du
sprint CI. Documenté pour suivi.
