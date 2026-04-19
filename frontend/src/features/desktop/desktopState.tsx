// Desktop state store — plain React reducer, no Zustand to keep deps lean.
//
// All state lives client-side: opening/editing/closing windows are purely
// events from the server that we apply to a local reducer. On backend
// restart, the desktop simply clears; Hermes re-opens what matters.
//
// The store exposes a React context + hook. Components subscribe via
// useDesktopState(); the server WS dispatches actions through a single
// `applyDesktopEvent()` helper exported for index.tsx.

import {
  Dispatch,
  ReactNode,
  createContext,
  useContext,
  useReducer,
} from "react";

export type WindowKind = "text" | "markdown" | "code" | "image" | "note";

export type DesktopWindow = {
  fileName: string;
  kind: WindowKind;
  content: string;
  language?: string;
  updatedAt: number;
  // Z-index auto-incremented on focus / open. Newest = highest.
  zIndex: number;
  // Layout hint the SceneManager-style manager uses to place windows.
  position: { x: number; y: number };
  // Last edit applied — used for char-by-char type animation on the canvas.
  // Set when file_edit applies {append}, consumed + cleared by the window.
  pendingAppend?: string;
  minimized?: boolean;
};

export type ImageDisplay = {
  url: string;
  fit: "contain" | "cover" | "fullscreen";
  caption: string;
  openedAt: number;
};

export type HermesHudState = {
  open: boolean;
  tab: string;
  view: "native" | "terminal";
};

export type DesktopState = {
  windows: Record<string, DesktopWindow>;
  order: string[];                         // fileName order, last = topmost
  image: ImageDisplay | null;              // at most one image showcase at a time
  layout: "grid" | "focus" | "minimize_all" | "tile_right";
  hermesHud: HermesHudState;
  nextZ: number;
  nextOffset: number;                      // for auto-offset on open (OpenRoom pattern)
};

const INITIAL_STATE: DesktopState = {
  windows: {},
  order: [],
  image: null,
  layout: "tile_right",
  hermesHud: { open: false, tab: "overview", view: "native" },
  nextZ: 100,
  nextOffset: 0,
};

export type DesktopAction =
  | {
      type: "window.open";
      fileName: string;
      kind: WindowKind;
      content: string;
      language?: string;
    }
  | {
      type: "window.edit";
      fileName: string;
      find?: string | null;
      replace?: string | null;
      append?: string | null;
    }
  | { type: "window.close"; fileName: string }
  | { type: "window.focus"; fileName: string }
  | { type: "window.clearAppend"; fileName: string }
  | { type: "image.show"; url: string; fit: ImageDisplay["fit"]; caption: string }
  | { type: "image.clear" }
  | { type: "layout.apply"; layout: DesktopState["layout"] }
  | { type: "hermesHud.open"; tab: string; view: "native" | "terminal" }
  | { type: "hermesHud.close" }
  | { type: "reset" };

function reducer(state: DesktopState, action: DesktopAction): DesktopState {
  switch (action.type) {
    case "window.open": {
      const existing = state.windows[action.fileName];
      const z = state.nextZ + 1;
      // Auto-offset new windows so they don't stack pixel-for-pixel (OpenRoom trick).
      const offsetStep = state.nextOffset % 5;
      const base = { x: 24 + offsetStep * 28, y: 24 + offsetStep * 24 };
      const win: DesktopWindow = {
        fileName: action.fileName,
        kind: action.kind,
        content: action.content,
        language: action.language,
        updatedAt: Date.now(),
        zIndex: z,
        position: existing?.position ?? base,
        minimized: false,
      };
      const order = state.order.filter((n) => n !== action.fileName).concat(action.fileName);
      return {
        ...state,
        windows: { ...state.windows, [action.fileName]: win },
        order,
        nextZ: z,
        nextOffset: existing ? state.nextOffset : state.nextOffset + 1,
      };
    }
    case "window.edit": {
      const win = state.windows[action.fileName];
      if (!win) return state;
      let nextContent = win.content;
      let pendingAppend = win.pendingAppend;
      if (action.append != null) {
        nextContent = `${nextContent}${action.append}`;
        pendingAppend = `${pendingAppend || ""}${action.append}`;
      }
      if (action.find != null && action.replace != null) {
        nextContent = nextContent.replace(action.find, action.replace);
        // A find/replace edit doesn't animate char-by-char — it's a snap.
      }
      return {
        ...state,
        windows: {
          ...state.windows,
          [action.fileName]: {
            ...win,
            content: nextContent,
            pendingAppend,
            updatedAt: Date.now(),
          },
        },
      };
    }
    case "window.close": {
      if (!state.windows[action.fileName]) return state;
      const { [action.fileName]: _dropped, ...rest } = state.windows;
      return {
        ...state,
        windows: rest,
        order: state.order.filter((n) => n !== action.fileName),
      };
    }
    case "window.focus": {
      const win = state.windows[action.fileName];
      if (!win) return state;
      const z = state.nextZ + 1;
      return {
        ...state,
        windows: { ...state.windows, [action.fileName]: { ...win, zIndex: z, minimized: false } },
        order: state.order.filter((n) => n !== action.fileName).concat(action.fileName),
        nextZ: z,
      };
    }
    case "window.clearAppend": {
      const win = state.windows[action.fileName];
      if (!win || !win.pendingAppend) return state;
      return {
        ...state,
        windows: {
          ...state.windows,
          [action.fileName]: { ...win, pendingAppend: undefined },
        },
      };
    }
    case "image.show":
      return {
        ...state,
        image: {
          url: action.url,
          fit: action.fit,
          caption: action.caption,
          openedAt: Date.now(),
        },
      };
    case "image.clear":
      return { ...state, image: null };
    case "layout.apply":
      if (action.layout === "minimize_all") {
        const windows = Object.fromEntries(
          Object.entries(state.windows).map(([k, w]) => [k, { ...w, minimized: true }]),
        );
        return { ...state, windows, layout: "minimize_all" };
      }
      return { ...state, layout: action.layout };
    case "hermesHud.open":
      return {
        ...state,
        hermesHud: { open: true, tab: action.tab, view: action.view },
      };
    case "hermesHud.close":
      return { ...state, hermesHud: { ...state.hermesHud, open: false } };
    case "reset":
      return INITIAL_STATE;
    default:
      return state;
  }
}

type DesktopContextValue = {
  state: DesktopState;
  dispatch: Dispatch<DesktopAction>;
};

const DesktopContext = createContext<DesktopContextValue | null>(null);

export function DesktopProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  return (
    <DesktopContext.Provider value={{ state, dispatch }}>
      {children}
    </DesktopContext.Provider>
  );
}

export function useDesktopState(): DesktopContextValue {
  const ctx = useContext(DesktopContext);
  if (!ctx) throw new Error("useDesktopState must be used under DesktopProvider");
  return ctx;
}
