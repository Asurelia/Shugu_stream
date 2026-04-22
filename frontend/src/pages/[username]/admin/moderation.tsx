import { useState } from "react";
import { Meta } from "@/components/meta";
import { AdminShell } from "@/components/admin/AdminShell";
import {
  GlassSection,
  GlassRow,
  GlassPill,
  GlassButton,
  GlassInput,
  GlassSwitch,
  GlassTabs,
} from "@/features/liquid-glass/primitives";
import { MetricTile } from "@/features/liquid-glass/dataviz";

/**
 * `/[username]/admin/moderation` — Moderation Hub.
 *
 * Trois piliers : (1) automod config avec toggles, (2) file d'attente
 * modération en temps-réel, (3) mod log pour l'audit. Colonne droite :
 * banned users + team de mods.
 */

const EVENTS: { user: string; text: string; kind: "spam" | "caps" | "link" | "word"; at: string }[] = [
  { user: "Troll99",   text: "bitcoin free money check bio",    kind: "link", at: "il y a 2s" },
  { user: "User42",    text: "AAAAAHHHHH HYPE",                  kind: "caps", at: "il y a 14s" },
  { user: "Guest7",    text: "[slur]",                            kind: "word", at: "il y a 35s" },
  { user: "Spam88",    text: "gg gg gg gg gg gg gg gg gg gg",    kind: "spam", at: "il y a 1m" },
];

export default function ModerationPage() {
  const [view, setView] = useState<"queue" | "log">("queue");
  const [cfg, setCfg] = useState({
    caps: true, links: true, wordlist: true,
    spam: true, slowmode: false, followerOnly: false,
  });
  const toggle = (k: keyof typeof cfg) => setCfg({ ...cfg, [k]: !cfg[k] });

  return (
    <>
      <Meta />
      <AdminShell
        active="moderation"
        title="Moderation Hub"
        subtitle="Gestion viewers, règles et activité temps-réel du stream."
        headerRight={
          <div className="flex items-center gap-2">
            <GlassPill tone="primary" dot>automod actif</GlassPill>
            <GlassButton variant="danger" size="sm">Pause chat</GlassButton>
          </div>
        }
      >
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
          <section className="flex flex-col gap-5">
            {/* KPIs */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricTile label="Messages /h"  value="1 284"  color="#e08efe" />
              <MetricTile label="Modérés /h"   value="42"     color="#fd6c9c" />
              <MetricTile label="Timeouts 24h" value="18"     color="#ffcf6b" />
              <MetricTile label="Bans total"   value="124"    color="#81ecff" />
            </div>

            {/* Automod config */}
            <GlassSection title="AutoMod" subtitle="Règles appliquées automatiquement au chat.">
              <GlassRow
                label="Bloquer CAPS"
                sub="ratio > 70 % sur 5+ caractères"
                trailing={<GlassSwitch checked={cfg.caps} onChange={() => toggle("caps")} aria-label="Caps" />}
              />
              <GlassRow
                label="Filtrer les liens"
                sub="sauf pour subs"
                trailing={<GlassSwitch checked={cfg.links} onChange={() => toggle("links")} aria-label="Liens" />}
              />
              <GlassRow
                label="Liste de mots bannis"
                sub="42 mots · édite la liste"
                trailing={
                  <div className="flex gap-2">
                    <GlassButton variant="subtle" size="sm">Éditer</GlassButton>
                    <GlassSwitch checked={cfg.wordlist} onChange={() => toggle("wordlist")} aria-label="Wordlist" />
                  </div>
                }
              />
              <GlassRow
                label="Anti-spam"
                sub="throttle répétitions"
                trailing={<GlassSwitch checked={cfg.spam} onChange={() => toggle("spam")} aria-label="Spam" />}
              />
              <GlassRow
                label="Slow mode"
                sub="1 message toutes les 3s"
                trailing={<GlassSwitch checked={cfg.slowmode} onChange={() => toggle("slowmode")} aria-label="Slow" />}
              />
              <GlassRow
                label="Followers only"
                sub="réservé à ceux qui te suivent"
                trailing={<GlassSwitch checked={cfg.followerOnly} onChange={() => toggle("followerOnly")} aria-label="Followers" />}
              />
            </GlassSection>

            {/* Mod queue */}
            <GlassSection
              title={view === "queue" ? "File d'attente" : "Log de modération"}
              subtitle={view === "queue" ? "Messages retenus par l'automod." : "Historique des actions."}
              right={
                <GlassTabs
                  aria-label="Vue mod"
                  value={view}
                  onChange={(v) => setView(v as typeof view)}
                  tabs={[{ value: "queue", label: "Queue" }, { value: "log", label: "Log" }]}
                />
              }
            >
              {view === "queue" ? EVENTS.map((e, i) => (
                <GlassRow
                  key={i}
                  label={<span>
                    <strong className="text-shugu-cream">{e.user}</strong>{" "}
                    <span className="text-shugu-cream-dim italic">"{e.text}"</span>
                  </span>}
                  sub={e.at}
                  trailing={
                    <div className="flex gap-1">
                      <GlassPill tone={
                        e.kind === "word" ? "danger"
                      : e.kind === "link" ? "warn"
                      : e.kind === "caps" ? "tertiary"
                      : "secondary"
                      }>{e.kind}</GlassPill>
                      <GlassButton variant="subtle" size="sm">✓</GlassButton>
                      <GlassButton variant="danger" size="sm">🕒</GlassButton>
                    </div>
                  }
                />
              )) : LOG.map((l, i) => (
                <GlassRow
                  key={i}
                  label={<span><strong className="text-shugu-cream">{l.mod}</strong> <span className="text-shugu-cream-dim">{l.action}</span></span>}
                  sub={l.at}
                  trailing={<GlassPill tone={l.kind === "ban" ? "danger" : l.kind === "timeout" ? "warn" : "default"}>{l.kind}</GlassPill>}
                />
              ))}
            </GlassSection>
          </section>

          {/* Rail droit */}
          <aside className="flex flex-col gap-4">
            <GlassSection title="Banis récents" subtitle="7 derniers jours.">
              {[
                { u: "Troll99", why: "liens bot",    when: "hier" },
                { u: "Guest7",  why: "slur · perma", when: "il y a 2j" },
                { u: "User42",  why: "harcèlement",  when: "il y a 4j" },
              ].map((b) => (
                <GlassRow
                  key={b.u}
                  label={<strong className="text-shugu-cream">{b.u}</strong>}
                  sub={`${b.why} · ${b.when}`}
                  trailing={<GlassButton variant="subtle" size="sm">Lever</GlassButton>}
                />
              ))}
              <div className="mt-3">
                <GlassInput placeholder="Ajouter un ban…" pill />
              </div>
            </GlassSection>

            <GlassSection title="Équipe mods" subtitle="Ton cercle de confiance.">
              {[
                { u: "Nebula",   since: "janv. 2024",  actions: 412 },
                { u: "Eclipse",  since: "sept. 2024",  actions: 128 },
                { u: "Halcyon",  since: "oct. 2024",   actions:  42 },
              ].map((m) => (
                <GlassRow
                  key={m.u}
                  label={<span className="flex items-center gap-2">
                    <strong className="text-shugu-cream">{m.u}</strong>
                    <GlassPill tone="tertiary" dot>mod</GlassPill>
                  </span>}
                  sub={`depuis ${m.since} · ${m.actions} actions`}
                  trailing={<GlassButton variant="subtle" size="sm">…</GlassButton>}
                />
              ))}
              <div className="mt-3">
                <GlassButton variant="ghost" size="sm" block>+ ajouter un mod</GlassButton>
              </div>
            </GlassSection>
          </aside>
        </div>
      </AdminShell>
    </>
  );
}

const LOG = [
  { mod: "Nebula",  action: "a banni Troll99 (liens bot)",     at: "il y a 14m", kind: "ban" },
  { mod: "Automod", action: "a timeout User42 (caps)",         at: "il y a 32m", kind: "timeout" },
  { mod: "Eclipse", action: "a supprimé un message de Guest7", at: "il y a 48m", kind: "delete" },
  { mod: "Nebula",  action: "a ajouté un mot à la wordlist",   at: "il y a 1h",  kind: "config" },
];
