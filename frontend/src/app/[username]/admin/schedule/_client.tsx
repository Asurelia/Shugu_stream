"use client";

/**
 * Schedule client island.
 *
 * Migration Pages Router → App Router (Sprint E5) :
 *   - `<Meta>` supprimé — métadonnées déclarées côté Server (`page.tsx`).
 *   - `AdminShell` migré vers `next/navigation` ; fonctionne uniquement App Router.
 *   - `export default` renommé en `export function ScheduleClient`.
 *
 * Sprint E5 DnD (audit UX 2026-05-09) :
 *   - Le sous-titre promettait "Glisse une case pour bouger un évènement" sans
 *     aucun handler DnD — promesse UI non tenue.
 *   - Implémentation jour-only via `@dnd-kit/core` (déjà installé) :
 *     PointerSensor + KeyboardSensor (a11y), DragOverlay, applyScheduleDayDrag.
 *   - Scope strict : jour-only. Cross-week et horaire sont des PRs séparées.
 */

import { useState } from "react";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  type DragEndEvent,
  type DragStartEvent,
  useSensor,
  useSensors,
} from "@dnd-kit/core";

import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection,
  GlassRow,
  GlassPill,
  GlassButton,
  GlassInput,
  GlassSelect,
  GlassTabs,
  GlassSwitch,
} from "@/features/liquid-glass/primitives";

import { WEEK_DAYS, type ScheduleEvent, type WeekDay } from "./types";
import { applyScheduleDayDrag } from "./scheduleDndLogic";
import { DroppableDayColumn } from "./DroppableDayColumn";
import { EventCardStatic } from "./DraggableEventCard";

const DAY_OPTIONS: ReadonlyArray<{ value: WeekDay; label: string }> = [
  { value: "Lun", label: "Lundi" },
  { value: "Mar", label: "Mardi" },
  { value: "Mer", label: "Mercredi" },
  { value: "Jeu", label: "Jeudi" },
  { value: "Ven", label: "Vendredi" },
  { value: "Sam", label: "Samedi" },
  { value: "Dim", label: "Dimanche" },
];

const INITIAL: ScheduleEvent[] = [
  { id: "1", day: "Lun", hour: "20:00", title: "Chill Coding",          category: "IRL",  ritual: true  },
  { id: "2", day: "Mer", hour: "21:00", title: "Baldur's Gate 3",       category: "Game", ritual: false },
  { id: "3", day: "Jeu", hour: "20:30", title: "Just Chatting — AMA",   category: "JC",   ritual: true  },
  { id: "4", day: "Sam", hour: "18:00", title: "Drawing Aura",          category: "Art",  ritual: true  },
  { id: "5", day: "Dim", hour: "21:00", title: "Marathon Souls",        category: "Game", ritual: false },
];

export function ScheduleClient() {
  const [view, setView] = useState<"week" | "month">("week");
  const [events, setEvents] = useState<ScheduleEvent[]>(INITIAL);
  const [draft, setDraft] = useState<Partial<ScheduleEvent>>({ day: "Lun", hour: "20:00", ritual: false });
  const [activeId, setActiveId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor),
  );

  const addEvent = () => {
    if (!draft.title) return;
    setEvents([
      ...events,
      { ...draft, id: String(Date.now()), category: draft.category ?? "Game" } as ScheduleEvent,
    ]);
    setDraft({ day: "Lun", hour: "20:00", ritual: false });
  };

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(String(event.active.id));
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveId(null);
    setEvents((prev) =>
      applyScheduleDayDrag(prev, String(active.id), over ? String(over.id) : null),
    );
  };

  const handleDragCancel = () => {
    setActiveId(null);
  };

  const activeEvent = activeId ? events.find((e) => e.id === activeId) : null;

  return (
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
            <DndContext
              sensors={sensors}
              onDragStart={handleDragStart}
              onDragEnd={handleDragEnd}
              onDragCancel={handleDragCancel}
            >
              <div className="grid grid-cols-7 gap-2 mt-1">
                {(WEEK_DAYS as readonly WeekDay[]).map((d) => (
                  <DroppableDayColumn
                    key={d}
                    day={d}
                    events={events.filter((e) => e.day === d)}
                  />
                ))}
              </div>

              <DragOverlay>
                {activeEvent ? (
                  <div className="opacity-90 rotate-1 scale-105 pointer-events-none">
                    <EventCardStatic event={activeEvent} />
                  </div>
                ) : null}
              </DragOverlay>
            </DndContext>
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
              <GlassSelect<WeekDay>
                label="Jour"
                options={DAY_OPTIONS}
                value={draft.day ?? "Lun"}
                onChange={(day) => setDraft({ ...draft, day })}
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
  );
}
