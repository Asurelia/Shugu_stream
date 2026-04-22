import { useState } from "react";
import { Meta } from "@/components/meta";
import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection,
  GlassRow,
  GlassPill,
  GlassButton,
  GlassInput,
  GlassTabs,
  GlassSwitch,
} from "@/features/liquid-glass/primitives";

/**
 * `/[username]/admin/schedule` — calendrier des streams.
 *
 * Vue "cette semaine" par défaut + éditeur inline pour le prochain
 * évènement. Les récurrences sont gérées via un toggle "rituel".
 */

type Event = {
  id: string;
  day: "Lun" | "Mar" | "Mer" | "Jeu" | "Ven" | "Sam" | "Dim";
  hour: string;
  title: string;
  category: string;
  ritual: boolean;
};

const INITIAL: Event[] = [
  { id: "1", day: "Lun", hour: "20:00", title: "Chill Coding",          category: "IRL",  ritual: true  },
  { id: "2", day: "Mer", hour: "21:00", title: "Baldur's Gate 3",       category: "Game", ritual: false },
  { id: "3", day: "Jeu", hour: "20:30", title: "Just Chatting — AMA",   category: "JC",   ritual: true  },
  { id: "4", day: "Sam", hour: "18:00", title: "Drawing Aura",          category: "Art",  ritual: true  },
  { id: "5", day: "Dim", hour: "21:00", title: "Marathon Souls",        category: "Game", ritual: false },
];

export default function SchedulePage() {
  const [view, setView] = useState<"week" | "month">("week");
  const [events, setEvents] = useState(INITIAL);
  const [draft, setDraft] = useState<Partial<Event>>({ day: "Lun", hour: "20:00", ritual: false });

  const addEvent = () => {
    if (!draft.title) return;
    setEvents([...events, { ...draft, id: String(Date.now()), category: draft.category ?? "Game" } as Event]);
    setDraft({ day: "Lun", hour: "20:00", ritual: false });
  };

  return (
    <>
      <Meta />
      <AdminShell
        active="schedule"
        title="Schedule"
        subtitle="Calendrier des streams et rituels récurrents."
        headerRight={
          <GlassTabs
            aria-label="Vue"
            value={view}
            onChange={(v) => setView(v as typeof view)}
            tabs={[{ value: "week", label: "Semaine" }, { value: "month", label: "Mois" }]}
          />
        }
      >
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
          <section className="flex flex-col gap-5">
            {/* Week grid */}
            <GlassSection title="Cette semaine" subtitle="Glisse une case pour bouger un évènement.">
              <div className="grid grid-cols-7 gap-2 mt-1">
                {(["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"] as const).map((d) => {
                  const dayEvents = events.filter((e) => e.day === d);
                  return (
                    <div key={d} className="flex flex-col">
                      <div className="font-mono text-[10px] text-shugu-cream-dim uppercase tracking-[0.16em] text-center py-2">
                        {d}
                      </div>
                      <div
                        className="flex-1 min-h-[160px] rounded-xl p-2 flex flex-col gap-1.5"
                        style={{ background: "rgba(255,255,255,0.02)", boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.05)" }}
                      >
                        {dayEvents.map((e) => (
                          <div
                            key={e.id}
                            className="rounded-lg px-2 py-1.5 cursor-grab"
                            style={{
                              background: e.ritual
                                ? "linear-gradient(135deg, rgba(224,142,254,0.18), rgba(253,108,156,0.14))"
                                : "rgba(18,14,30,0.6)",
                              boxShadow: e.ritual
                                ? "inset 0 0 0 1px rgba(224,142,254,0.35)"
                                : "inset 0 0 0 1px rgba(255,255,255,0.06)",
                            }}
                          >
                            <div className="font-mono text-[9px] text-shugu-cream-dim">{e.hour}</div>
                            <div className="text-[11px] text-shugu-cream font-semibold leading-tight">{e.title}</div>
                            <div className="font-mono text-[9px] text-shugu-pink-soft">{e.category}{e.ritual ? " · ♺" : ""}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </GlassSection>

            {/* Editor */}
            <GlassSection title="Nouveau stream" subtitle="Planifie rapidement un évènement.">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <GlassInput
                  label="Titre"
                  value={draft.title ?? ""}
                  onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                  placeholder="Chill Just Chatting"
                />
                <GlassInput
                  label="Catégorie"
                  value={draft.category ?? ""}
                  onChange={(e) => setDraft({ ...draft, category: e.target.value })}
                  placeholder="Game, JC, Art…"
                />
                <GlassInput
                  label="Jour"
                  value={draft.day ?? ""}
                  onChange={(e) => setDraft({ ...draft, day: e.target.value as Event["day"] })}
                />
                <GlassInput
                  label="Heure"
                  type="time"
                  value={draft.hour ?? ""}
                  onChange={(e) => setDraft({ ...draft, hour: e.target.value })}
                />
              </div>
              <div className="flex items-center justify-between mt-4">
                <label className="flex items-center gap-3 text-[12px] text-shugu-cream-dim">
                  <GlassSwitch
                    checked={!!draft.ritual}
                    onChange={(v) => setDraft({ ...draft, ritual: v })}
                    aria-label="Rituel récurrent"
                  />
                  <span>Rituel récurrent (chaque semaine)</span>
                </label>
                <GlassButton variant="primary" size="md" onClick={addEvent} disabled={!draft.title}>
                  + ajouter
                </GlassButton>
              </div>
            </GlassSection>
          </section>

          {/* Rail droit */}
          <aside className="flex flex-col gap-4">
            <GlassSection title="Prochains streams" subtitle="Les 5 à venir.">
              {events.slice(0, 5).map((e) => (
                <GlassRow
                  key={e.id}
                  label={<strong className="text-shugu-cream">{e.title}</strong>}
                  sub={`${e.day} · ${e.hour}`}
                  trailing={e.ritual ? <GlassPill tone="primary">rituel</GlassPill> : <GlassPill>one-shot</GlassPill>}
                />
              ))}
            </GlassSection>

            <GlassSection title="Intégrations" subtitle="Publie ton schedule.">
              <GlassRow
                label="Google Calendar"
                sub="synchro hebdo"
                trailing={<GlassButton variant="ghost" size="sm">Connecter</GlassButton>}
              />
              <GlassRow
                label="Discord events"
                sub="annonces auto"
                trailing={<GlassButton variant="subtle" size="sm">Déconnecter</GlassButton>}
              />
              <GlassRow
                label="Twitter thread"
                sub="post weekly recap"
                trailing={<GlassButton variant="ghost" size="sm">Connecter</GlassButton>}
              />
            </GlassSection>
          </aside>
        </div>
      </AdminShell>
    </>
  );
}
