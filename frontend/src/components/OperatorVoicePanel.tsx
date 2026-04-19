// Operator-only mic panel — push-to-talk toggle + live state indicator.
//
// Renders under the OperatorPanel when the operator is logged in. On enable,
// asks for mic permission, opens /ws/operator/voice, and visualizes the
// duplex state (you speak / Shugu listens / Shugu speaks / you can interrupt).

import { useEffect, useRef, useState } from "react";
import { OperatorVoice, OperatorVoiceEvent, OperatorVoiceStatus, VoiceState } from "@/features/voice/operatorVoice";

type Props = {
  /** Only render when operator is authenticated. */
  enabled: boolean;
};

const STATE_LABELS: Record<VoiceState, { label: string; color: string }> = {
  idle:               { label: "en attente",         color: "bg-white/10 text-shugu-cream-dim" },
  operator_speaking:  { label: "tu parles",          color: "bg-shugu-blue/80 text-white" },
  silence_debounce:   { label: "fin de phrase…",     color: "bg-white/15 text-shugu-cream" },
  processing:         { label: "Hermes réfléchit",   color: "bg-shugu-pink/70 text-white" },
  hermes_responding:  { label: "Shugu parle",        color: "bg-shugu-pink-glow text-white shadow-[0_0_12px_rgba(255,97,127,0.6)]" },
};

export function OperatorVoicePanel({ enabled }: Props) {
  const [active, setActive] = useState(false);
  const [status, setStatus] = useState<OperatorVoiceStatus>("closed");
  const [state, setState] = useState<VoiceState>("idle");
  const [lastTranscript, setLastTranscript] = useState<string>("");
  const [error, setError] = useState<string>("");
  const voiceRef = useRef<OperatorVoice | null>(null);

  useEffect(() => {
    if (!active) {
      voiceRef.current?.stop();
      voiceRef.current = null;
      setStatus("closed");
      setState("idle");
      return;
    }
    const voice = new OperatorVoice({
      onStatus: setStatus,
      onEvent: (ev: OperatorVoiceEvent) => {
        if (ev.type === "voice.state.change") {
          setState(ev.to);
        } else if (ev.type === "voice.transcript.final") {
          setLastTranscript(ev.text);
        } else if (ev.type === "voice.barge_in") {
          // Visual pulse — UI already shows operator_speaking via state change.
        }
      },
      onMicError: (err) => {
        console.error("[voice] mic error", err);
        setError(err instanceof Error ? err.message : String(err));
        setActive(false);
      },
    });
    voiceRef.current = voice;
    void voice.start();
    return () => {
      voice.stop();
    };
  }, [active]);

  if (!enabled) return null;

  const stateLabel = STATE_LABELS[state];

  return (
    <div className="fixed bottom-28 right-4 md:right-[340px] z-20 font-quicksand pointer-events-auto">
      <div
        className="glass-pink rounded-2xl px-3 py-2.5 shadow-xl min-w-[200px]"
        style={{ maxWidth: 260 }}
      >
        <div className="flex items-center justify-between gap-2">
          <button
            onClick={() => setActive((v) => !v)}
            className={[
              "flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-bold transition-all",
              active
                ? "bg-shugu-live text-white shadow-[0_0_14px_rgba(255,59,92,0.55)]"
                : "bg-white/10 text-shugu-cream hover:bg-white/20",
            ].join(" ")}
            title={active ? "couper le micro" : "activer le micro"}
          >
            <span className="text-sm leading-none">{active ? "●" : "○"}</span>
            {active ? "micro ON" : "micro OFF"}
          </button>
          <span
            className={[
              "text-[10px] font-bold px-2.5 py-1 rounded-full transition-all",
              stateLabel.color,
            ].join(" ")}
          >
            {stateLabel.label}
          </span>
        </div>

        {active && status === "connecting" && (
          <div className="mt-1.5 text-[10px] text-shugu-cream-dim">connexion…</div>
        )}
        {active && status === "error" && (
          <div className="mt-1.5 text-[10px] text-shugu-live">erreur de connexion</div>
        )}
        {error && (
          <div className="mt-1.5 text-[10px] text-shugu-live">{error}</div>
        )}
        {lastTranscript && (
          <div
            className="mt-2 text-[10px] text-shugu-cream-dim italic leading-snug border-t border-white/5 pt-1.5"
            title={lastTranscript}
          >
            « {lastTranscript.length > 70 ? lastTranscript.slice(0, 69) + "…" : lastTranscript} »
          </div>
        )}
      </div>
    </div>
  );
}
