/**
 * Placeholder Celestial Veil pour les sections admin pas encore câblées.
 * Pose la carte glassmorphism et l'eyebrow « En construction » — sera remplacé
 * par le contenu réel de chaque mockup (analytics / community / assets / …)
 * au fur et à mesure.
 */

type Props = {
  mockup: string;
  note?: string;
};

export function AdminPageStub({ mockup, note }: Props) {
  return (
    <div
      className="rounded-2xl p-8 min-h-[380px] flex flex-col items-center justify-center text-center gap-3"
      style={{
        background: "linear-gradient(180deg, rgba(30,30,45,0.78), rgba(26,26,40,0.94))",
        boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.04), 0 14px 40px rgba(224,142,254,0.08)",
      }}
    >
      <div className="text-veil-primary text-3xl animate-veil-pulse-glow inline-block rounded-full px-3">
        ✦
      </div>
      <div className="veil-headline text-veil-on-surface-variant text-[10px] tracking-[0.24em] uppercase">
        En construction
      </div>
      <div className="veil-headline text-veil-on-surface text-lg">
        Section sous le voile
      </div>
      <div className="veil-body text-veil-on-surface-variant text-sm max-w-md">
        Mockup de référence : <span className="text-veil-primary">{mockup}</span>.
        {note ? ` ${note}` : " Layout posé, câblage temps-réel à venir."}
      </div>
    </div>
  );
}
