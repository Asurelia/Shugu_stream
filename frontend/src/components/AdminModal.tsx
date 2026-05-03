import { useEffect, useState } from "react";

type Stats = {
  queue_pending: number;
  queue_ready: number;
  performances_total: number;
  performances_last_24h: number;
  active_bans: number;
};

type Ban = {
  ip_hash: string;
  ban_until: string;
  ban_reason: string | null;
  msg_count: number;
  last_seen: string;
};

type Performance = {
  performance_id: string;
  author_role: string;
  route: string;
  input_text: string;
  output_text: string | null;
  duration_ms: number | null;
  created_at: string;
};

async function j<T>(url: string): Promise<T> {
  const r = await fetch(url, { credentials: "include" });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

export function AdminModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [bans, setBans] = useState<Ban[]>([]);
  const [perfs, setPerfs] = useState<Performance[]>([]);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"overview" | "bans" | "history">("overview");

  const refresh = async () => {
    setError("");
    try {
      const [s, b, p] = await Promise.all([
        j<Stats>("/api/admin/stats"),
        j<Ban[]>("/api/admin/bans"),
        j<Performance[]>("/api/admin/performances?limit=30"),
      ]);
      setStats(s); setBans(b); setPerfs(p);
    } catch (e: any) { setError(String(e?.message || e)); }
  };

  /* eslint-disable react-hooks/set-state-in-effect -- FIXME P5: fetch+poll on open, refactor refresh to useReducer when data lib available */
  useEffect(() => {
    if (open) {
      refresh();
      const iv = setInterval(refresh, 5000);
      return () => clearInterval(iv);
    }
  }, [open]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const unban = async (ip: string) => {
    try { await fetch(`/api/admin/bans/${ip}`, { method: "DELETE", credentials: "include" }); await refresh(); } catch {}
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 bg-shugu-ink/85 flex items-center sm:items-center justify-center p-0 sm:p-4 font-quicksand">
      <div className="w-full h-full sm:h-auto sm:max-w-4xl sm:max-h-[85vh] glass-pink text-shugu-cream rounded-none sm:rounded-3xl flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 sm:px-7 py-3 sm:py-4 border-b border-shugu-pink-soft/20">
          <h2 className="text-lg sm:text-xl font-comfortaa font-bold text-shugu-pink-soft">
            ⚙ Dashboard admin
          </h2>
          <button
            onClick={onClose}
            className="text-shugu-cream-dim hover:text-shugu-cream text-2xl leading-none w-9 h-9 rounded-full hover:bg-white/10"
          >
            ×
          </button>
        </div>

        <div className="flex gap-1 px-4 pt-3 border-b border-shugu-pink-soft/10">
          {(["overview", "bans", "history"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 sm:px-4 py-2 text-xs sm:text-sm rounded-t-lg transition-colors ${
                tab === t
                  ? "bg-shugu-pink/15 text-shugu-pink-glow border-b-2 border-shugu-pink"
                  : "text-shugu-cream-dim hover:text-shugu-cream"
              }`}
            >
              {t === "overview" ? "Vue" : t === "bans" ? `Bans (${bans.length})` : `Historique (${perfs.length})`}
            </button>
          ))}
        </div>

        {error && <div className="px-6 py-2 bg-shugu-live/30 text-shugu-cream text-sm">{error}</div>}

        <div className="flex-1 overflow-y-auto p-5 sm:p-7 scroll-hidden">
          {tab === "overview" && stats && (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 sm:gap-4">
              <Stat label="Queue en attente" value={stats.queue_pending} />
              <Stat label="Queue prête" value={stats.queue_ready} />
              <Stat label="Performances total" value={stats.performances_total} />
              <Stat label="Dernières 24h" value={stats.performances_last_24h} />
              <Stat label="Bans actifs" value={stats.active_bans} />
            </div>
          )}

          {tab === "bans" && (
            <div className="space-y-2">
              {bans.length === 0 && <div className="text-shugu-cream-dim italic text-sm">Aucun ban actif ♡</div>}
              {bans.map((b) => (
                <div key={b.ip_hash} className="bg-shugu-ink/50 border border-shugu-pink-soft/10 rounded-xl px-4 py-3 flex items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="font-mono text-[11px] text-shugu-cream-dim truncate">{b.ip_hash.slice(0, 16)}…</div>
                    <div className="text-sm mt-1">
                      <span className="text-shugu-live">{b.ban_reason || "(sans motif)"}</span>
                      <span className="text-shugu-cream-dim"> — jusqu&apos;au {new Date(b.ban_until).toLocaleString("fr-FR")}</span>
                    </div>
                  </div>
                  <button
                    onClick={() => unban(b.ip_hash)}
                    className="text-xs px-3 py-1.5 bg-shugu-pink/20 hover:bg-shugu-pink/30 rounded-full text-shugu-pink-glow font-semibold"
                  >
                    débannir
                  </button>
                </div>
              ))}
            </div>
          )}

          {tab === "history" && (
            <div className="space-y-2">
              {perfs.map((p) => (
                <div key={p.performance_id} className="bg-shugu-ink/50 border border-shugu-pink-soft/10 rounded-xl px-4 py-3">
                  <div className="flex items-center gap-2 text-[11px] text-shugu-cream-dim mb-1 flex-wrap">
                    <span className={`px-2 py-0.5 rounded-full font-semibold ${
                      p.route === "shugu_filtered" ? "bg-shugu-live/30 text-shugu-live" :
                      p.author_role === "operator" ? "bg-shugu-lavender/30 text-shugu-lavender" :
                      "bg-shugu-blue/20 text-shugu-blue"
                    }`}>
                      {p.route === "shugu_filtered" ? "filtré" : p.author_role}
                    </span>
                    <span>{new Date(p.created_at).toLocaleString("fr-FR")}</span>
                    {p.duration_ms != null && <span>• {Math.round(p.duration_ms / 100) / 10}s</span>}
                  </div>
                  <div className="text-sm text-shugu-cream/90 line-clamp-3">{p.input_text}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-shugu-ink/60 rounded-2xl p-4 border border-shugu-pink-soft/10">
      <div className="text-[10px] text-shugu-cream-dim uppercase tracking-wider">{label}</div>
      <div className="text-3xl font-bold font-comfortaa mt-1 text-shugu-pink-glow">{value}</div>
    </div>
  );
}
