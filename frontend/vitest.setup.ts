/**
 * Vitest global setup — jest-dom matchers + browser API stubs.
 *
 * Les tests Zustand n'ont pas besoin de matchers React Testing Library, mais
 * on charge jest-dom ici pour que les futurs tests de composants (panels,
 * primitives) puissent utiliser `toBeInTheDocument()` etc. sans setup par
 * fichier.
 */

import "@testing-library/jest-dom/vitest";

// jsdom ne ship pas ResizeObserver nativement (ajouté en 2020 mais absent de
// jsdom 20). On stub un noop pour tous les tests qui montent des composants
// avec ResizeObserver (SceneComposerViewer, etc.).
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  // @ts-expect-error — stub jsdom only
  globalThis.ResizeObserver = ResizeObserverStub;
}

// jsdom ne ship pas BroadcastChannel nativement : on stub un noop pour que
// les modules qui l'appellent à l'import (pop-out logic en Phase G) ne
// crashent pas. Tests qui veulent vraiment tester ce comportement doivent
// fournir leur propre mock par describe.
if (typeof globalThis.BroadcastChannel === "undefined") {
  class BroadcastChannelStub {
    name: string;
    onmessage: ((ev: MessageEvent) => void) | null = null;
    constructor(name: string) {
      this.name = name;
    }
    postMessage(): void {}
    close(): void {}
    addEventListener(): void {}
    removeEventListener(): void {}
    dispatchEvent(): boolean {
      return true;
    }
  }
  // @ts-expect-error — stub en dev only
  globalThis.BroadcastChannel = BroadcastChannelStub;
}
