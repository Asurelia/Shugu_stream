/**
 * Rail gauche flottant — port direct du mockup Stitch.
 *
 * Deux glass-panel (avec marques "+" aux coins) empilées sous le header :
 *   - Latest Subscriber  (icon box violet + nom rose néon glow)
 *   - Latest Donation    (icon box cyan  + montant cyan glow)
 *
 * Largeur fixe 288px (w-72). Les cartes sont cliquables pour prévoir un hover.
 */

type Props = {
  latestSubscriber?: { username: string };
  latestDonation?:   { amount: string; from: string };
};

export function SupportersRail({
  latestSubscriber = { username: "Nebula_Walker_99" },
  latestDonation   = { amount: "$50.00", from: "Anonymous" },
}: Props) {
  return (
    <aside className="hidden lg:flex fixed left-8 top-24 z-20 flex-col space-y-5 w-72 pointer-events-none">
      {/* Latest Subscriber */}
      <div className="glass-panel p-4 flex items-center space-x-4 pointer-events-auto">
        <div className="bg-celestial-purple/20 p-3 rounded-xl border border-celestial-purple/30 shrink-0">
          <span className="block w-7 h-7 flex items-center justify-center text-celestial-purple text-lg">✦</span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-widest text-gray-400 font-bold">
            Latest Subscriber
          </p>
          <p className="text-celestial-pink font-bold text-base md:text-lg glow-pink truncate">
            {latestSubscriber.username}
          </p>
        </div>
      </div>

      {/* Latest Donation */}
      <div className="glass-panel p-4 flex items-center space-x-4 pointer-events-auto">
        <div className="bg-cyan-500/20 p-3 rounded-xl border border-cyan-500/30 shrink-0">
          <span className="block w-7 h-7 flex items-center justify-center text-cyan-400 text-lg">◆</span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-widest text-gray-400 font-bold">
            Latest Donation
          </p>
          <p className="text-cyan-400 font-bold text-base md:text-lg glow-cyan truncate">
            {latestDonation.amount} – {latestDonation.from}
          </p>
        </div>
      </div>
    </aside>
  );
}
