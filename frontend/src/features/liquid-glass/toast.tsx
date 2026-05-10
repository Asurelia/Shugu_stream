"use client";

/**
 * Shugu — Liquid Glass Toast (Radix UI Toast backend)
 *
 * Public API:
 *   <GlassToastProvider>      → app/providers.tsx (one global mount)
 *   const { toast } = useToast();
 *   toast.success("Saved");
 *   toast.error("Failed", { description: "Network error" });
 *   toast.info("...");
 *   toast.warning("...");
 *
 * a11y: Radix manages ARIA semantics via a hidden ToastAnnounce element.
 *       type="background" → aria-live="polite"  (success/info/warning)
 *       type="foreground" → aria-live="assertive" (error)
 *       No explicit role= is set on Toast.Root (<li>) — Radix handles it.
 */
import * as Toast from "@radix-ui/react-toast";
import React, { createContext, useCallback, useContext, useRef, useState } from "react";

type ToastVariant = "success" | "error" | "info" | "warning";

type ToastItem = {
  id: number;
  variant: ToastVariant;
  title: React.ReactNode;
  description?: React.ReactNode;
  duration?: number;
};

type ToastOptions = { description?: React.ReactNode; duration?: number };

type ToastAPI = {
  success: (title: React.ReactNode, opts?: ToastOptions) => void;
  error:   (title: React.ReactNode, opts?: ToastOptions) => void;
  info:    (title: React.ReactNode, opts?: ToastOptions) => void;
  warning: (title: React.ReactNode, opts?: ToastOptions) => void;
};

const ToastContext = createContext<ToastAPI | null>(null);

export function useToast(): ToastAPI {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <GlassToastProvider>");
  return ctx;
}

export function GlassToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  // Counter-based IDs are collision-safe even with vi.useFakeTimers().
  const counter = useRef(0);

  const push = useCallback(
    (variant: ToastVariant, title: React.ReactNode, opts?: ToastOptions) => {
      const id = ++counter.current;
      setItems((prev) => [...prev, { id, variant, title, ...opts }]);
    },
    []
  );

  const api: ToastAPI = {
    success: (t, o) => push("success", t, o),
    error:   (t, o) => push("error",   t, o),
    info:    (t, o) => push("info",    t, o),
    warning: (t, o) => push("warning", t, o),
  };

  return (
    <ToastContext.Provider value={api}>
      <Toast.Provider duration={5000} swipeDirection="right">
        {children}
        {items.map((item) => (
          <Toast.Root
            key={item.id}
            className={`lg-toast lg-toast-${item.variant}`}
            duration={item.duration}
            onOpenChange={(open) =>
              !open && setItems((p) => p.filter((i) => i.id !== item.id))
            }
            /**
             * a11y: Radix manages ARIA via a hidden ToastAnnounce element
             * (role="status" + aria-live) — NOT via role on the visible <li>.
             * - type="foreground" → aria-live="assertive" (errors)
             * - type="background" → aria-live="polite"    (others)
             *
             * Do NOT pass role= explicitly: Toast.Root renders as <li> inside
             * the <ol> Viewport, and role="status"|"alert" are not allowed on
             * <li> per ARIA spec (axe-core: aria-allowed-role + list).
             */
            type={item.variant === "error" ? "foreground" : "background"}
          >
            <Toast.Title className="lg-toast-title">{item.title}</Toast.Title>
            {item.description && (
              <Toast.Description className="lg-toast-desc">
                {item.description}
              </Toast.Description>
            )}
            <Toast.Close className="lg-toast-close" aria-label="Fermer">
              ✕
            </Toast.Close>
          </Toast.Root>
        ))}
        <Toast.Viewport className="lg-toast-viewport" />
      </Toast.Provider>
    </ToastContext.Provider>
  );
}
