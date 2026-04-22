/**
 * livekitClient — wrappers fetch pour /api/livekit/*.
 *
 * Gated côté backend par require_vip : si l'utilisateur n'est pas VIP,
 * l'appel retourne 403 et on redirige vers /account/profile.
 */

export type VIPTokenResponse = {
  token: string;
  room: string;
  url: string;
};

export class LiveKitError extends Error {
  constructor(public status: number, public detail: string) {
    super(`[${status}] ${detail}`);
    this.name = "LiveKitError";
  }
}

export async function mintVIPToken(): Promise<VIPTokenResponse> {
  const resp = await fetch("/api/livekit/token", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
  });
  const text = await resp.text();
  const payload = text ? (() => {
    try { return JSON.parse(text); } catch { return { detail: text }; }
  })() : {};
  if (!resp.ok) {
    const detail = (payload && payload.detail) || `HTTP ${resp.status}`;
    throw new LiveKitError(resp.status, String(detail));
  }
  return payload as VIPTokenResponse;
}
