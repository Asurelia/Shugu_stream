/**
 * Shugu — Liquid Glass primitives (iOS 26-style)
 *
 * Drop-in React components backed by `styles/liquid-glass.css`.
 * Deliberately minimal API: one component per DOM role, className
 * forwards, no runtime style prop gymnastics. Tailwind-friendly.
 *
 * Usage:
 *   import { GlassCard, GlassButton, GlassInput } from "@/features/liquid-glass/primitives";
 */

import React, { forwardRef, useEffect } from "react";

/* ──────────────────────────────────────────────────────────────
   LiquidLayers — specular + edge + shimmer layers
   Drop as the FIRST child of any `.lg` / `.lg-pill` / `.lg-card`
   so hover shimmer + highlights render beneath content.
   ────────────────────────────────────────────────────────────── */

export function LiquidLayers() {
  return (
    <>
      <span className="lg-specular" aria-hidden />
      <span className="lg-edge" aria-hidden />
      <span className="lg-shimmer" aria-hidden />
    </>
  );
}

/* ──────────────────────────────────────────────────────────────
   GlassSurface — raw glass container
   ────────────────────────────────────────────────────────────── */

type SurfaceVariant = "card" | "pill" | "modal" | "plain";
type SurfaceTone = "default" | "strong" | "weak";

export type GlassSurfaceProps = React.HTMLAttributes<HTMLDivElement> & {
  variant?: SurfaceVariant;
  tone?: SurfaceTone;
  layers?: boolean;
  as?: "div" | "section" | "aside" | "header" | "footer" | "nav";
};

export const GlassSurface = forwardRef<HTMLDivElement, GlassSurfaceProps>(
  ({ variant = "card", tone = "default", layers = true, as = "div", className = "", children, ...rest }, ref) => {
    const Tag = as as any;
    const variantCls =
      variant === "pill"  ? "lg-pill"
    : variant === "modal" ? "lg-modal"
    : variant === "card"  ? "lg-card"
    : "";
    const toneCls =
      tone === "strong" ? "lg-strong"
    : tone === "weak"   ? "lg-weak"
    : "";
    return (
      <Tag ref={ref} className={`lg ${variantCls} ${toneCls} ${className}`.trim()} {...rest}>
        {layers && <LiquidLayers />}
        <div className="lg-content">{children}</div>
      </Tag>
    );
  }
);
GlassSurface.displayName = "GlassSurface";

/* ──────────────────────────────────────────────────────────────
   GlassCard — padded, 22px radius, body content
   ────────────────────────────────────────────────────────────── */

export type GlassCardProps = Omit<GlassSurfaceProps, "variant"> & {
  padded?: boolean;
};

export const GlassCard = forwardRef<HTMLDivElement, GlassCardProps>(
  ({ padded = true, className = "", children, ...rest }, ref) => (
    <GlassSurface
      ref={ref}
      variant="card"
      className={`${padded ? "p-5" : ""} ${className}`.trim()}
      {...rest}
    >
      {children}
    </GlassSurface>
  )
);
GlassCard.displayName = "GlassCard";

/* ──────────────────────────────────────────────────────────────
   GlassButton — 5 variants, 3 sizes, tier shimmer for VIP/Admin
   ────────────────────────────────────────────────────────────── */

export type GlassButtonVariant = "primary" | "secondary" | "ghost" | "subtle" | "danger";
export type GlassButtonSize = "sm" | "md" | "lg";
export type GlassButtonTier = "vip" | "admin" | null;

export type GlassButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: GlassButtonVariant;
  size?: GlassButtonSize;
  tier?: GlassButtonTier;
  block?: boolean;
  leading?: React.ReactNode;
  trailing?: React.ReactNode;
  sparkles?: boolean;
};

export const GlassButton = forwardRef<HTMLButtonElement, GlassButtonProps>(
  (
    {
      variant = "ghost",
      size = "md",
      tier = null,
      block,
      leading,
      trailing,
      sparkles,
      className = "",
      children,
      ...rest
    },
    ref
  ) => {
    const tierCls = tier === "vip" ? "lgb-tier-vip" : tier === "admin" ? "lgb-tier-admin" : "";
    const cls = [
      "lgb",
      `lgb-${variant}`,
      `lgb-${size}`,
      block && "lgb-block",
      tierCls,
      className,
    ]
      .filter(Boolean)
      .join(" ");
    const wantSparkles = sparkles ?? tier !== null;

    return (
      <button ref={ref} className={cls} {...rest}>
        {leading}
        {children}
        {trailing}
        {wantSparkles && (
          <span className="lg-sparkles" aria-hidden>
            <span className="lg-sparkle s1">✦</span>
            <span className="lg-sparkle s2">✧</span>
            <span className="lg-sparkle s3">✦</span>
          </span>
        )}
      </button>
    );
  }
);
GlassButton.displayName = "GlassButton";

/* ──────────────────────────────────────────────────────────────
   GlassInput — labelled input, pill / rounded variants
   ────────────────────────────────────────────────────────────── */

export type GlassInputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  label?: string;
  hint?: string;
  error?: string;
  pill?: boolean;
  wrapClassName?: string;
};

export const GlassInput = forwardRef<HTMLInputElement, GlassInputProps>(
  ({ label, hint, error, pill, className = "", wrapClassName = "", id, ...rest }, ref) => {
    const inputId = id || (label ? `lgi-${label.replace(/\s+/g, "-").toLowerCase()}` : undefined);
    return (
      <div className={`lgi-group ${wrapClassName}`.trim()}>
        {label && <label htmlFor={inputId} className="lgi-label">{label}</label>}
        <input
          ref={ref}
          id={inputId}
          className={`lgi lg-focus-ring ${pill ? "lgi-pill" : ""} ${error ? "lgi-error" : ""} ${className}`.trim()}
          aria-invalid={!!error}
          {...rest}
        />
        {(error || hint) && (
          <span className={`lgi-hint ${error ? "error" : ""}`}>{error || hint}</span>
        )}
      </div>
    );
  }
);
GlassInput.displayName = "GlassInput";

/* ──────────────────────────────────────────────────────────────
   GlassPill — compact info chip
   ────────────────────────────────────────────────────────────── */

export type GlassPillProps = React.HTMLAttributes<HTMLSpanElement> & {
  tone?: "default" | "primary" | "secondary" | "tertiary" | "warn" | "danger";
  dot?: boolean;
};

export function GlassPill({ tone = "default", dot, className = "", children, ...rest }: GlassPillProps) {
  const toneStyle: React.CSSProperties = {
    primary:   { color: "#e08efe", borderColor: "rgba(224,142,254,0.3)" },
    secondary: { color: "#fd6c9c", borderColor: "rgba(253,108,156,0.3)" },
    tertiary:  { color: "#81ecff", borderColor: "rgba(129,236,255,0.3)" },
    warn:      { color: "#ffcf6b", borderColor: "rgba(255,207,107,0.35)" },
    danger:    { color: "#ff8aa2", borderColor: "rgba(255,106,138,0.3)" },
    default:   {},
  }[tone];
  return (
    <span
      className={`lgb lgb-sm ${className}`.trim()}
      style={{ cursor: "default", ...toneStyle }}
      {...rest}
    >
      {dot && (
        <span
          aria-hidden
          style={{
            width: 6, height: 6, borderRadius: "50%",
            background: "currentColor", boxShadow: "0 0 8px currentColor",
          }}
        />
      )}
      {children}
    </span>
  );
}

/* ──────────────────────────────────────────────────────────────
   GlassTabs — iOS Settings segmented control
   ────────────────────────────────────────────────────────────── */

export type GlassTab = { value: string; label: React.ReactNode };
export type GlassTabsProps = {
  tabs: GlassTab[];
  value: string;
  onChange: (v: string) => void;
  className?: string;
  "aria-label"?: string;
};

export function GlassTabs({ tabs, value, onChange, className = "", ...a11y }: GlassTabsProps) {
  return (
    <div role="tablist" aria-label={a11y["aria-label"]} className={`lg-tabs ${className}`.trim()}>
      {tabs.map((t) => (
        <button
          key={t.value}
          role="tab"
          aria-selected={value === t.value}
          className="lg-tab"
          onClick={() => onChange(t.value)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────
   GlassModal — scrim + animated morph card
   ────────────────────────────────────────────────────────────── */

export type GlassModalProps = {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: number | string;
  closeOnScrim?: boolean;
};

export function GlassModal({
  open, onClose, title, children, footer, width = 480, closeOnScrim = true,
}: GlassModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div
      className="lg-scrim"
      onClick={(e) => closeOnScrim && e.target === e.currentTarget && onClose()}
      role="dialog"
      aria-modal="true"
    >
      <div className="lg-modal-wrap" style={{ width, maxWidth: "100%" }}>
        <GlassSurface variant="modal" tone="strong">
          {title && (
            <div
              style={{
                padding: "18px 22px 0",
                display: "flex", alignItems: "center", justifyContent: "space-between",
              }}
            >
              <h2
                style={{
                  margin: 0, fontSize: 16, fontWeight: 700,
                  color: "var(--on-surface)", letterSpacing: "0.02em",
                }}
              >
                {title}
              </h2>
              <button
                aria-label="Fermer"
                onClick={onClose}
                className="lgb lgb-subtle lgb-sm"
                style={{ padding: "4px 8px", minWidth: 0 }}
              >
                ✕
              </button>
            </div>
          )}
          <div style={{ padding: "18px 22px" }}>{children}</div>
          {footer && (
            <div
              style={{
                padding: "14px 22px 20px",
                display: "flex", gap: 8, justifyContent: "flex-end",
                borderTop: "1px solid rgba(255,255,255,0.06)",
              }}
            >
              {footer}
            </div>
          )}
        </GlassSurface>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────
   GlassSwitch — toggle
   ────────────────────────────────────────────────────────────── */

export type GlassSwitchProps = {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  "aria-label"?: string;
  id?: string;
};

export function GlassSwitch({ checked, onChange, disabled, id, ...a11y }: GlassSwitchProps) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={a11y["aria-label"]}
      disabled={disabled}
      className="lg-switch lg-focus-ring"
      onClick={() => !disabled && onChange(!checked)}
    />
  );
}

/* ──────────────────────────────────────────────────────────────
   Section scaffolding used by Account + Admin pages
   ────────────────────────────────────────────────────────────── */

export type GlassSectionProps = React.HTMLAttributes<HTMLElement> & {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  right?: React.ReactNode;
  danger?: boolean;
};

export function GlassSection({
  title, subtitle, right, danger, className = "", children, ...rest
}: GlassSectionProps) {
  return (
    <section className={`lg-section ${danger ? "danger" : ""} ${className}`.trim()} {...rest}>
      {(title || right) && (
        <header className="lg-section-head">
          <div>
            {title && <div className="lg-section-title">{title}</div>}
            {subtitle && <div className="lg-section-sub">{subtitle}</div>}
          </div>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export type GlassRowProps = React.HTMLAttributes<HTMLDivElement> & {
  label: React.ReactNode;
  sub?: React.ReactNode;
  value?: React.ReactNode;
  trailing?: React.ReactNode;
};

export function GlassRow({ label, sub, value, trailing, className = "", ...rest }: GlassRowProps) {
  return (
    <div className={`lg-row ${className}`.trim()} {...rest}>
      <div className="lg-row-label">
        {label}
        {sub && <div className="lg-row-sub">{sub}</div>}
      </div>
      {value && <div className="lg-row-value">{value}</div>}
      {trailing}
    </div>
  );
}
