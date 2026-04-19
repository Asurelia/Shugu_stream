import { useContext, useEffect, useRef, useState } from "react";
import { Quicksand, Comfortaa, Plus_Jakarta_Sans, Inter } from "next/font/google";
import VrmViewer from "@/components/vrmViewer";
import { ViewerContext } from "@/features/vrmViewer/viewerContext";
import { Message, Screenplay } from "@/features/messages/messages";
import { speakFromServer } from "@/features/messages/speakFromServer";
import {
  StreamingAudioPlayer,
  base64ChunkToUint8,
} from "@/features/messages/audioStreamer";
import { Meta } from "@/components/meta";
import { OverlayHeader } from "@/components/OverlayHeader";
import { SupportersRail } from "@/components/SupportersRail";
import { SubGoalBar } from "@/components/SubGoalBar";
import { VisitorLogin } from "@/components/VisitorLogin";
import { ChatFeed } from "@/components/ChatFeed";
import { SpeakingRing } from "@/components/SpeakingRing";
import { LoadingScreen } from "@/components/LoadingScreen";
import { Sparkles } from "@/components/Sparkles";
import { OperatorVoicePanel } from "@/components/OperatorVoicePanel";
import { EmoteOverlay, EmoteOverlayHandle } from "@/components/EmoteOverlay";
import { Mode } from "@/components/OperatorPanel";
import { SceneManager } from "@/features/scenes/SceneManager";
import { VirtualDesktop } from "@/features/desktop/VirtualDesktop";
import { useDesktopState, WindowKind } from "@/features/desktop/desktopState";
import { ACTION_CLIPS } from "@/features/animations/animationPack";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import {
  ShuguClient, ShuguEvent, PerformanceTags, base64ToArrayBuffer, fetchAuthStatus,
} from "../services/shuguClient";

const quicksand = Quicksand({
  variable: "--font-quicksand",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "600", "700"],
});
const comfortaa = Comfortaa({
  variable: "--font-comfortaa",
  subsets: ["latin"],
  display: "swap",
  weight: ["500", "600", "700"],
});
// Celestial Veil design system — Plus Jakarta Sans for headlines, Inter for body.
const plusJakarta = Plus_Jakarta_Sans({
  variable: "--font-display",
  subsets: ["latin"],
  display: "swap",
  weight: ["500", "600", "700", "800"],
});
const interFont = Inter({
  variable: "--font-body",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "600"],
});

type ConnStatus = "connecting" | "open" | "closed" | "error";

const MAX_CHAT_LOG = 80;

export default function Home() {
  const { viewer } = useContext(ViewerContext);
  const { dispatch: desktopDispatch } = useDesktopState();

  const [operator, setOperator] = useState<{ username: string } | null>(null);
  const [authLoaded, setAuthLoaded] = useState(false);
  const [mode, setMode] = useState<Mode>("shugu");
  const [pendingHermes, setPendingHermes] = useState(false);

  // Override le fond body.shugu-body (dégradé rose) par un nebula radial sombre
  // pour matcher le mockup Stitch. SceneManager peut encore réécrire
  // `document.body.style.background` plus tard; cet effet ne pose que le fond
  // "au repos" et restaure la classe shugu-body en démontage.
  useEffect(() => {
    const prev = document.body.style.background;
    document.body.style.background =
      "radial-gradient(circle at center, #1a1a2e 0%, #0a0a0f 100%)";
    document.body.style.animation = "none";
    return () => {
      document.body.style.background = prev;
      document.body.style.animation = "";
    };
  }, []);

  const [connStatus, setConnStatus] = useState<ConnStatus>("connecting");
  const [chatLog, setChatLog] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [notice, setNotice] = useState<string>("");
  const [avatarLoaded, setAvatarLoaded] = useState(false);
  const [viewerCount, setViewerCount] = useState<number>(0);
  const [speaking, setSpeaking] = useState(false);
  const [debugCaptions, setDebugCaptions] = useState(false);

  const clientRef = useRef<ShuguClient | null>(null);
  const modeRef = useRef<Mode>(mode);
  useEffect(() => { modeRef.current = mode; }, [mode]);

  const viewerRef = useRef(viewer);
  useEffect(() => { viewerRef.current = viewer; }, [viewer]);

  const emoteOverlayRef = useRef<EmoteOverlayHandle>(null);
  const sceneManagerRef = useRef<SceneManager | null>(null);
  // Streaming-audio session: exactly one active player per performance.
  // Created on `performance.audio_begin`, torn down on `performance.end` or
  // `performance.truncate`.
  const streamPlayerRef = useRef<StreamingAudioPlayer | null>(null);
  const streamScreenplayRef = useRef<Screenplay | null>(null);
  // Timer IDs of pending `timed_cue` setTimeouts — must be cleared on
  // performance.truncate/performance.end otherwise late-firing cues leak
  // onto the NEXT performance's visual state (ghost scene/emote swaps).
  const cueTimersRef = useRef<number[]>([]);

  const appendLog = (m: Message) => {
    // Visitors never keep assistant messages in their local log — Shugu's voice
    // is the only carrier in public. Operator keeps them so the debug-captions
    // toggle (below) can surface them when enabled.
    if (m.role === "assistant" && !operator) return;
    setChatLog((l) => [...l.slice(-MAX_CHAT_LOG + 1), m]);
    if (m.role === "user") {
      // Glance toward the chat feed only when a real user message lands; Shugu
      // glancing at the chat while *she* speaks would feel odd.
      viewerRef.current?.triggerChatGlance({ x: 0.7, y: 0.25 });
    }
  };

  useEffect(() => {
    if (!operator) return;
    try {
      setDebugCaptions(localStorage.getItem("shugu.debug_captions") === "1");
    } catch {}
  }, [operator]);

  const handleDebugCaptionsChange = (v: boolean) => {
    setDebugCaptions(v);
    try { localStorage.setItem("shugu.debug_captions", v ? "1" : "0"); } catch {}
  };

  // Cancel every pending timed_cue setTimeout. Called on truncate/end so
  // cues scheduled for many seconds out don't fire onto the next performance.
  const clearCueTimers = () => {
    for (const id of cueTimersRef.current) window.clearTimeout(id);
    cueTimersRef.current = [];
  };

  const voice = useVoiceInput({
    lang: "fr-FR",
    onFinal: (text) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      const target: Mode = modeRef.current;
      const ok = clientRef.current?.sendChat(trimmed, target);
      if (!ok) { setNotice("déconnecté"); return; }
      appendLog({ role: "user", content: (target === "hermes" ? "🎙️⚡ " : "🎙️ ") + trimmed });
      if (target === "hermes") setPendingHermes(true);
    },
  });

  useEffect(() => {
    let cancelled = false;
    fetchAuthStatus().then((me) => { if (!cancelled) { setOperator(me); setAuthLoaded(true); } });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!authLoaded) return;
    const client = new ShuguClient({
      operator: !!operator,
      onStatus: setConnStatus,
      onEvent: async (ev: ShuguEvent) => {
        if (ev.type === "performance.start") {
          setSpeaking(true);
        } else if (ev.type === "performance.audio") {
          // Dispatch performance tags first so visuals land on the same tick
          // as the voice (or fire solo for silent performances like !actions).
          const tags = ev.tags || {};
          const applyTags = (t: PerformanceTags) => {
            if (t.scene) sceneManagerRef.current?.requestScene(t.scene);
            if (t.action) {
              const clip = ACTION_CLIPS[t.action];
              if (clip) {
                void viewerRef.current?.animationManager?.playOneShot(clip);
              } else {
                console.warn(`[tags] unknown action '${t.action}'`);
              }
            }
            if (t.emote) emoteOverlayRef.current?.push(t.emote);
          };
          applyTags(tags);

          // Storyboarded scenes ship timed cues (offset_ms + tags) that fire
          // in sync with the audio. A simple setTimeout chain is good enough
          // for ~second-level precision; we never need ms-level alignment.
          // Track IDs so clearCueTimers() can cancel them on truncate/end.
          clearCueTimers();
          if (ev.timed_cues && ev.timed_cues.length > 0) {
            for (const cue of ev.timed_cues) {
              const id = window.setTimeout(
                () => applyTags(cue.tags),
                Math.max(0, cue.offset_ms),
              );
              cueTimersRef.current.push(id);
            }
          }

          if (ev.text) {
            appendLog({ role: "assistant", content: ev.text });
          }

          // Audio source resolution: inline base64 (normal path) OR a local
          // URL under /public/ (ambient storyboards, zero-quota playback).
          let audio: ArrayBuffer | null = null;
          if (ev.audio_b64) {
            audio = base64ToArrayBuffer(ev.audio_b64);
          } else if (tags.audio_src) {
            try {
              const res = await fetch(tags.audio_src);
              if (res.ok) audio = await res.arrayBuffer();
              else console.warn(`[ambient] failed to fetch ${tags.audio_src}: ${res.status}`);
            } catch (err) {
              console.warn(`[ambient] audio_src fetch error`, err);
            }
          }
          if (audio) {
            const screenplay: Screenplay = {
              expression: (ev.screenplay?.emotion || "neutral") as Screenplay["expression"],
              talk: { style: "talk", speakerX: 0, speakerY: 0, message: ev.text || "" },
            };
            const v = viewerRef.current;
            if (v) {
              try { await speakFromServer(v, audio, screenplay); }
              catch (err) { console.error("speakFromServer failed:", err); }
            }
          }
        } else if (ev.type === "performance.audio_begin") {
          // Begin a streaming TTS performance. Fire the initial tags/cues now
          // and spin up a StreamingAudioPlayer that will receive chunks.
          const tags = ev.tags || {};
          const applyTags = (t: PerformanceTags) => {
            if (t.scene) sceneManagerRef.current?.requestScene(t.scene);
            if (t.action) {
              const clip = ACTION_CLIPS[t.action];
              if (clip) void viewerRef.current?.animationManager?.playOneShot(clip);
            }
            if (t.emote) emoteOverlayRef.current?.push(t.emote);
          };
          applyTags(tags);
          clearCueTimers();
          if (ev.timed_cues && ev.timed_cues.length > 0) {
            for (const cue of ev.timed_cues) {
              const id = window.setTimeout(
                () => applyTags(cue.tags),
                Math.max(0, cue.offset_ms),
              );
              cueTimersRef.current.push(id);
            }
          }
          if (ev.text) appendLog({ role: "assistant", content: ev.text });

          // Tear down any stale player (should never happen but be safe).
          streamPlayerRef.current?.abort("new performance");
          streamPlayerRef.current = null;

          if (!StreamingAudioPlayer.canPlayMp3Streaming()) {
            // Browser lacks MSE MP3 — we'll let the chunks queue up and hope
            // the server eventually emits `performance.audio` instead. For
            // now, just log and skip.
            console.warn("[audio] MSE MP3 not supported; streaming audio disabled");
          } else {
            const player = new StreamingAudioPlayer({
              mime: ev.mime || "audio/mpeg",
              onError: (err) => console.error("[audio] streamer error:", err),
            });
            streamPlayerRef.current = player;
            streamScreenplayRef.current = {
              expression: (ev.screenplay?.emotion || "neutral") as Screenplay["expression"],
              talk: { style: "talk", speakerX: 0, speakerY: 0, message: ev.text || "" },
            };
            // Wire the <audio> into the viewer's speak() path for lip-sync.
            // The existing LipSync reads from an AudioContext AnalyserNode,
            // so we hand it the element; the Model's speak() API accepts
            // `buffer=null` to mean "already streaming" (see model.ts).
            const sp = streamScreenplayRef.current;
            const v = viewerRef.current;
            if (v && sp) {
              v.model?.startStreamingSpeak(player.element, sp);
            }
          }
        } else if (ev.type === "performance.audio_chunk") {
          const player = streamPlayerRef.current;
          if (!player) return;
          if (ev.audio_b64) {
            const bytes = base64ChunkToUint8(ev.audio_b64);
            // `appendChunk` will now auto-start playback on the first
            // non-empty chunk (internal `started` flag), so we no longer
            // race here on seq===0 — any seq value works.
            player.appendChunk(bytes, ev.final);
          } else if (ev.final) {
            player.appendChunk(new Uint8Array(0), true);
          }
        } else if (ev.type === "performance.truncate") {
          streamPlayerRef.current?.abort(ev.reason || "truncate");
          streamPlayerRef.current = null;
          clearCueTimers();
        } else if (ev.type === "performance.end") {
          setSpeaking(false);
          streamPlayerRef.current?.abort("performance end");
          streamPlayerRef.current = null;
          clearCueTimers();
        } else if (ev.type === "viewer.count") {
          setViewerCount(ev.n);
        } else if (ev.type === "scene.change") {
          // Direct state-change from Hermes body control — bypasses picker.
          sceneManagerRef.current?.requestScene(ev.scene);
        } else if (ev.type === "look.hint") {
          viewerRef.current?.triggerChatGlance(ev.ndc);
        } else if (ev.type === "expression.set") {
          // Drive the same VRM expression path speak() uses on screenplay switch.
          const v = viewerRef.current;
          if (v?.model) {
            const emoEl = (v.model as any).emoteController;
            const proc = (v.model as any).procedural;
            try { emoEl?.playEmotion?.(ev.expression); } catch {}
            try { proc?.triggerEmotion?.(ev.expression); } catch {}
          }
        } else if (ev.type === "shot.change") {
          // No direct shot API today — we treat shot hints as scene nudges for
          // now; proper FOV/dolly control will land in phase 7 with the
          // Celestial Veil camera system.
          console.debug(`[shot] ${ev.shot}`);
        } else if (ev.type === "desktop.window_open") {
          desktopDispatch({
            type: "window.open",
            fileName: ev.file_name,
            kind: (ev.kind as WindowKind) || "text",
            content: ev.initial_content || "",
            language: ev.language || undefined,
          });
        } else if (ev.type === "desktop.file_edit") {
          desktopDispatch({
            type: "window.edit",
            fileName: ev.file_name,
            find: ev.find,
            replace: ev.replace,
            append: ev.append,
          });
        } else if (ev.type === "desktop.window_close") {
          desktopDispatch({ type: "window.close", fileName: ev.file_name });
        } else if (ev.type === "desktop.image_show") {
          desktopDispatch({
            type: "image.show",
            url: ev.url,
            fit: (ev.fit as any) || "contain",
            caption: ev.caption || "",
          });
        } else if (ev.type === "desktop.arrange") {
          desktopDispatch({ type: "layout.apply", layout: ev.layout as any });
        } else if (ev.type === "hermes_state.window_open") {
          desktopDispatch({
            type: "hermesHud.open",
            tab: ev.tab || "overview",
            view: (ev.view as any) || "native",
          });
        } else if (ev.type === "hermes_state.window_close") {
          desktopDispatch({ type: "hermesHud.close" });
        } else if (ev.type === "hermes_task.acknowledged") {
          setPendingHermes(true);
          setTimeout(() => setPendingHermes(false), (ev.eta_estimate_s + 120) * 1000);
        } else if (ev.type === "error.moderation" || ev.type === "queue.rejected") {
          setNotice(ev.reason);
          setTimeout(() => setNotice(""), 4000);
        }
      },
    });
    clientRef.current = client;
    client.connect();
    return () => client.close();
  }, [authLoaded, operator]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = inputValue.trim();
    if (!text) return;
    const target: Mode = operator ? mode : "shugu";
    const ok = clientRef.current?.sendChat(text, target);
    if (!ok) { setNotice("déconnecté, reconnexion…"); return; }
    appendLog({ role: "user", content: (target === "hermes" ? "⚡ " : "") + text });
    setInputValue("");
    if (target === "hermes") setPendingHermes(true);
  };

  return (
    <div className={`${quicksand.variable} ${comfortaa.variable} ${plusJakarta.variable} ${interFont.variable} font-quicksand`}>
      <Meta />
      <Sparkles />
      <VrmViewer
        onLoaded={() => {
          setAvatarLoaded(true);
          const v = viewerRef.current;
          if (v && !sceneManagerRef.current) {
            sceneManagerRef.current = new SceneManager({
              viewer: v,
              onBackgroundChange: (bg) => {
                document.body.style.background = bg;
              },
            });
            // No applyInitial — boot-state already matches `just_chatting` and
            // we want the CSS gradient animation to keep running until a scene
            // tag actually requests a switch.
          }
        }}
      />
      <EmoteOverlay ref={emoteOverlayRef} />
      <SpeakingRing visible={speaking} />

      {!avatarLoaded && <LoadingScreen />}

      <OverlayHeader
        connStatus={connStatus}
        viewerCount={viewerCount}
        speaking={speaking}
        operatorUsername={operator?.username}
      />

      {/* Crosshairs décoratifs aux 4 coins du viewport (signature Stitch). */}
      <div className="crosshair ch-tl" />
      <div className="crosshair ch-tr" />
      <div className="crosshair ch-bl" />
      <div className="crosshair ch-br" />

      {/* Tech labels monospace — tirés du mockup pour l'ambiance 3D-tracker. */}
      <div className="fixed top-24 left-8 tech-label z-10 pointer-events-none hidden md:block">
        X: 184.5 Y: 228.1<br />Z: 80.8
      </div>
      <div className="fixed top-24 right-8 tech-label z-10 pointer-events-none hidden md:block text-right">
        X: 104.5 Y: 220.1<br />Z: 60.8
      </div>
      <div className="fixed bottom-8 right-8 tech-label z-10 pointer-events-none hidden md:block text-right">
        STATUS: {connStatus === "open" ? "ACTIVE" : connStatus.toUpperCase()}
      </div>

      <SupportersRail />
      <SubGoalBar />

      {!operator && <VisitorLogin />}

      <OperatorVoicePanel enabled={!!operator} />

      <ChatFeed
        messages={chatLog}
        showAssistant={!!operator && debugCaptions}
        viewerCount={viewerCount}
        inputValue={inputValue}
        onInputChange={setInputValue}
        onSubmit={handleSubmit}
        inputDisabled={connStatus !== "open"}
        hermesMode={!!operator && mode === "hermes"}
        voice={operator && voice.supported ? {
          supported: voice.supported,
          listening: voice.listening,
          interim: voice.interim,
          start: voice.start,
          stop: voice.stop,
        } : undefined}
      />

      <VirtualDesktop />

      {notice && (
        <div className="fixed top-[5.5rem] sm:top-24 right-[360px] z-20 animate-fade-up bg-shugu-live/90 text-white px-4 py-2 rounded-full text-xs sm:text-sm shadow-lg max-w-xs font-semibold">
          ✕ {notice}
        </div>
      )}
    </div>
  );
}
