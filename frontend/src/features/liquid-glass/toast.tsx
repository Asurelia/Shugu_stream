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
 * a11y: role="status" aria-live="polite"  (success/info/warning via type="background")
 *       role="alert"  aria-live="assertive" (error — explicit role override)
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
             * a11y:
             * - error → type="foreground" sets aria-live="assertive"; we add
             *   role="alert" explicitly because Radix defaults to role="status".
             * - all others → type="background" gives aria-live="polite" and
             *   role="status", which Radix sets by default.
             */
            type={item.variant === "error" ? "foreground" : "background"}
            role={item.variant === "error" ? "alert" : "status"}
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
