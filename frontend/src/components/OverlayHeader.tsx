import Link from "next/link";

type ConnStatus = "connecting" | "open" | "closed" | "error";

type Props = {
  connStatus: ConnStatus;
  viewerCount: number;
  speaking: boolean;
  operatorUsername?: string;
};

/**
 * Header immersif — port direct du mockup Stitch.
 *
 *  ┌────────────────────────────────────────────────────────────────────┐
 *  │ CELESTIAL VEIL   TWITTER · YOUTUBE · TIKTOK   STATUS  [GO LIVE] ⎋ │
 *  └────────────────────────────────────────────────────────────────────┘
 *
 *  - Wordmark violet (`celestial-purple`) avec glow monochrome.
 *  - Nav : trois liens caps tracking-wide, actif = underline `celestial-pink` 2px.
 *  - STATUS: ACTIVE (monospace tiny vert).
 *  - Bouton GO LIVE rond gradient violet→rose.
 *  - Icônes utilitaires + avatar profil (cercle bordure purple) si opérateur.
 */
export function OverlayHeader({ connStatus, viewerCount: _vc, speaking: _sp, operatorUsername }: Props) {
  const live = connStatus === "open";
  const statusText = live ? "ACTIVE" : connStatus === "connecting" ? "WAITING" : "OFFLINE";
  const statusClass = live ? "text-green-400" : connStatus === "connecting" ? "text-amber-300" : "text-rose-400";

  const links = ["Twitter", "YouTube", "TikTok"] as const;
  const activeIdx = 0;

  return (
    <header className="fixed top-0 left-0 w-full h-16 px-6 md:px-8 flex items-center justify-between z-50 bg-black/40 backdrop-blur-md border-b border-white/10">
      {/* Gauche : wordmark + nav --------------------------------------- */}
      <div className="flex items-center space-x-8">
        <h1 className="text-2xl md:text-3xl font-black tracking-widest text-celestial-purple glow-purple veil-headline">
          CELESTIAL VEIL
        </h1>
        <nav className="hidden md:flex space-x-6 text-[11px] font-semibold uppercase tracking-[0.15em] text-gray-400">
          {links.map((l, i) => (
            <a
              key={l}
              href="#"
              className={[
                "transition-colors pb-1",
                i === activeIdx
                  ? "text-white border-b-2 border-celestial-pink"
                  : "hover:text-celestial-pink",
              ].join(" ")}
            >
              {l}
            </a>
          ))}
        </nav>
      </div>

      {/* Droite : status + CTA + icônes -------------------------------- */}
      <div className="flex items-center space-x-4 md:space-x-6">
        <div className="hidden sm:flex items-center space-x-2">
          <div className="tech-label">
            STATUS: <span className={statusClass}>{statusText}</span>
          </div>
        </div>

        <button
          className="px-5 md:px-6 py-2 bg-gradient-to-r from-[#b585ff] to-[#e879f9] text-black font-bold text-[12px] md:text-sm rounded-full transition-all transform hover:scale-105 tracking-wide"
          title={live ? "stream en ligne" : "démarrer le stream"}
        >
          GO LIVE
        </button>

        <div className="flex items-center space-x-3 md:space-x-4">
          <button
            className="w-6 h-6 opacity-70 hover:opacity-100 transition-opacity text-gray-300"
            title="alertes"
            aria-label="alertes"
          >
            ⎇
          </button>
          <button
            className="w-6 h-6 opacity-70 hover:opacity-100 transition-opacity text-gray-300"
            title="paramètres"
            aria-label="paramètres"
          >
            ⚙
          </button>
          {operatorUsername && (
            <Link
              href={`/${encodeURIComponent(operatorUsername)}/admin`}
              title={`dashboard — ${operatorUsername}`}
              className="w-8 h-8 rounded-full border-2 border-celestial-purple flex items-center justify-center text-celestial-purple text-xs font-bold hover:glow-purple transition-all"
            >
              {operatorUsername.slice(0, 1).toUpperCase()}
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
