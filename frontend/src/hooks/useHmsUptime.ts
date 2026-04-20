import { useEffect, useState } from "react";

/**
 * Uptime HH:MM:SS compté à partir de `startMs`. Pas persistant — au F5 le
 * compteur reset (représente la session viewer, pas l'uptime serveur qui
 * nécessiterait un endpoint). `null` → "00:00:00".
 */
export function useHmsUptime(startMs: number | null): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (startMs === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [startMs]);
  if (startMs === null) return "00:00:00";
  const s = Math.max(0, Math.floor((now - startMs) / 1000));
  const h = String(Math.floor(s / 3600)).padStart(2, "0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const sec = String(s % 60).padStart(2, "0");
  return `${h}:${m}:${sec}`;
}
