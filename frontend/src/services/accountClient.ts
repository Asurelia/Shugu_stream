/**
 * accountClient — wrappers fetch pour les endpoints /account/*.
 *
 * Tous les endpoints utilisent les cookies httpOnly (credentials: "include").
 * Les erreurs HTTP 4xx/5xx renvoient une AccountError avec le `detail` du backend.
 */

export type Me = {
  user_id: string;
  username: string;
  email: string;
  role: "member" | "vip";
  email_verified: boolean;
  vip_active: boolean;
  vip_until: string | null;
};

export type RegisterResponse = {
  user_id: string;
  username: string;
  email: string;
  email_sent: boolean;
};

export class AccountError extends Error {
  constructor(public status: number, public detail: string) {
    super(`[${status}] ${detail}`);
    this.name = "AccountError";
  }
}

async function request<T>(
  path: string,
  opts: RequestInit = {},
): Promise<T> {
  const resp = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
    ...opts,
  });
  const text = await resp.text();
  const payload = text ? (() => {
    try { return JSON.parse(text); } catch { return { detail: text }; }
  })() : {};
  if (!resp.ok) {
    const detail = (payload && payload.detail) || `HTTP ${resp.status}`;
    throw new AccountError(resp.status, String(detail));
  }
  return payload as T;
}

export async function register(
  body: { username: string; email: string; password: string },
): Promise<RegisterResponse> {
  return request("/account/register", { method: "POST", body: JSON.stringify(body) });
}

export async function login(
  body: { username_or_email: string; password: string },
): Promise<Me> {
  return request("/account/login", { method: "POST", body: JSON.stringify(body) });
}

export async function logout(): Promise<{ ok: boolean }> {
  return request("/account/logout", { method: "POST" });
}

export async function refresh(): Promise<Me> {
  return request("/account/refresh", { method: "POST" });
}

export async function me(): Promise<Me | null> {
  try {
    return await request<Me>("/account/me");
  } catch (err) {
    if (err instanceof AccountError && err.status === 401) return null;
    throw err;
  }
}

export async function verifyEmail(token: string): Promise<{ ok: boolean; detail?: string }> {
  return request("/account/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
}

export async function resendVerify(email: string): Promise<{ ok: boolean; detail?: string }> {
  return request("/account/resend-verify", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}
