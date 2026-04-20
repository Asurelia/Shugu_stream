/**
 * Augmentation locale des types CSS React pour les propriétés récentes que
 * `@types/react@18` ne connaît pas encore. Nécessaire pour les variations
 * Creator Home qui utilisent `text-wrap: balance` / `pretty`.
 */
import "react";

declare module "react" {
  interface CSSProperties {
    textWrap?: "wrap" | "nowrap" | "balance" | "pretty" | "stable";
  }
}
