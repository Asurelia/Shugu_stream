import { ReactNode } from "react";

/**
 * Liquid Glass chat rail — port 1:1 de iamryanyu/gbpzgqX (iOS 26 Liquid Glass).
 *
 * Structure 3-layer + content :
 *   - `bend` (z:0)  → backdrop distortion via filter SVG #glass-blur
 *   - `face` (z:1)  → drop shadows (profondeur du verre)
 *   - `edge` (z:2)  → DOUBLE inset white 45% à +3/+3 & -3/-3 (relief spéculaire)
 *   - content (z:3) → children
 *
 * Morph : card 56×56 flottante bas-droite (rétracté) ↔ card 360×(h-32) à droite
 *   (ouvert), avec 16px de marge. Transition spring bouncy identique CodePen.
 *
 * Le filter SVG #glass-blur doit être injecté UNE SEULE FOIS dans le DOM —
 * `<LiquidGlassFilter />` s'en charge. À rendre au niveau root de la page.
 */

type Props = {
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  children: ReactNode;
};

export function LiquidGlassRail({ open, onOpen, onClose, children }: Props) {
  return (
    <div
      className="hidden md:block fixed"
      onClick={open ? undefined : onOpen}
      role={open ? undefined : "button"}
      aria-label={open ? undefined : "ouvrir le chat"}
      style={{
        right: 16,
        top: open ? 16 : "auto",
        bottom: 16,
        width: open ? 360 : 56,
        height: open ? "calc(100% - 32px)" : 56,
        borderRadius: 24,
        cursor: open ? "default" : "pointer",
        zIndex: 4,
        transition: [
          "width 0.45s cubic-bezier(0.5, 1.5, 0.5, 1)",
          "height 0.45s cubic-bezier(0.5, 1.5, 0.5, 1)",
          "top 0.45s cubic-bezier(0.5, 1.5, 0.5, 1)",
        ].join(", "),
      }}
    >
      {/* bend : config exacte du CodePen — backdrop-filter blur(3px) pull
          le backdrop dans l'élément, puis filter:url(#glass-blur) applique
          feDisplacementMap sur cette copie. Le blur est nécessaire pour que
          le filter SVG ait quelque chose à distordre (sans lui, l'élément
          est vide et le filter ne produit rien de visible). */}
      <div
        aria-hidden
        style={{
          position: "absolute", inset: 0, zIndex: 0,
          borderRadius: "inherit",
          backdropFilter: "blur(3px)",
          WebkitBackdropFilter: "blur(3px)",
          filter: "url(#glass-blur)",
        }}
      />
      {/* face : drop shadows subtiles → profondeur */}
      <div
        aria-hidden
        style={{
          position: "absolute", inset: 0, zIndex: 1,
          borderRadius: "inherit",
          boxShadow: [
            "rgba(0,0,0,0.15) 0px 4px 4px",
            "rgba(0,0,0,0.08) 0px 0px 12px",
          ].join(", "),
        }}
      />
      {/* edge : relief spéculaire 3D, double inset blanc 45% */}
      <div
        aria-hidden
        style={{
          position: "absolute", inset: 0, zIndex: 2,
          borderRadius: "inherit",
          pointerEvents: "none",
          boxShadow: [
            "rgba(255,255,255,0.45) 3px 3px 3px 0 inset",
            "rgba(255,255,255,0.45) -3px -3px 3px 0 inset",
          ].join(", "),
        }}
      />
      {/* content */}
      <div
        style={{
          position: "relative", zIndex: 3,
          width: "100%", height: "100%",
          borderRadius: "inherit",
          overflow: "hidden",
        }}
      >
        {open ? (
          <>
            <button
              onClick={(e) => { e.stopPropagation(); onClose(); }}
              className="absolute"
              style={{
                top: 14, right: 14, zIndex: 10,
                width: 28, height: 28, borderRadius: "50%",
                background: "rgba(255,255,255,0.12)",
                border: "none", cursor: "pointer",
                color: "rgba(255,255,255,0.9)",
                fontSize: "1.05rem", lineHeight: 1,
                display: "flex", alignItems: "center", justifyContent: "center",
              }}
              aria-label="fermer le chat"
            >
              ×
            </button>
            <div
              style={{
                width: "100%", height: "100%",
                display: "flex", flexDirection: "column",
                paddingTop: 16, paddingBottom: 12,
              }}
            >
              {children}
            </div>
          </>
        ) : (
          <div
            style={{
              width: "100%", height: "100%",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "rgba(255,255,255,0.95)",
            }}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="22" height="22" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" strokeWidth={1.8}
              strokeLinecap="round" strokeLinejoin="round"
              aria-hidden
            >
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Filtre SVG #glass-blur — feTurbulence + feDisplacementMap (valeurs exactes
 * du CodePen). ZÉRO changement de couleur : juste une déformation organique
 * des pixels. À monter une seule fois au niveau root.
 */
export function LiquidGlassFilter() {
  return (
    <svg
      aria-hidden
      style={{ position: "absolute", width: 0, height: 0, pointerEvents: "none" }}
    >
      <defs>
        <filter
          id="glass-blur"
          x="0%" y="0%" width="100%" height="100%"
          filterUnits="objectBoundingBox"
        >
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.003 0.007"
            numOctaves={1}
            result="turbulence"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="turbulence"
            scale={200}
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
      </defs>
    </svg>
  );
}
