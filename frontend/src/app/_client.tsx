"use client";

/**
 * Root viewer hub — App Router migration (Sprint E6).
 *
 * Pages Router → App Router changes applied:
 *   - `useRouter` import: `next/router` → `next/navigation` (push/replace API
 *     identical; `.query` was not used on this page).
 *   - `<Meta>` component removed — metadata is declared in `page.tsx` (Server).
 *   - next/font/google imports and local font const declarations removed; the
 *     five CSS variables (--font-quicksand, --font-comfortaa, --font-display,
 *     --font-body, --font-mono) are already applied on <html> by app/layout.tsx.
 *   - Font variable classNames stripped from the root wrapper div (vars on <html>
 *     are inherited — no className needed here).
 */
import { useContext, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { useRouter } from "next/navigation";

import { ChatFeed } from "@/components/ChatFeed";
import { EmoteOverlay, EmoteOverlayHandle } from "@/components/EmoteOverlay";
import { LiveKitProvider } from "@/features/livekit/LiveKitProvider";
import { ViewerEventsProvider } from "@/features/viewer/ViewerEventsProvider";
import { LiquidGlassFilter } from "@/components/LiquidGlassRail";
import { LoadingScreen } from "@/components/LoadingScreen";
import { SpeakingRing } from "@/components/SpeakingRing";
import { VisitorLogin } from "@/components/VisitorLogin";
import { ViewerStage, type ChatMsg } from "@/components/ViewerStage";
import VrmViewer from "@/components/vrmViewer";
import { ACTION_CLIPS, getActionClips, invalidateActionClipsCache } from "@/features/animations/animationPack";
import {
  StreamingAudioPlayer,
  base64ChunkToUint8,
} from "@/features/messages/audioStreamer";
import { Message, Screenplay } from "@/features/messages/messages";
import { speakFromServer } from "@/features/messages/speakFromServer";
import { invalidate as invalidateRegistry } from "@/features/registry/registryClient";
import { SceneManager } from "@/features/scenes/SceneManager";
import { refreshScenes } from "@/features/scenes/scenes";
import { ViewerContext } from "@/features/vrmViewer/viewerContext";
import { refreshEmotes } from "@/components/EmoteOverlay";
import { useHmsUptime } from "@/hooks/useHmsUptime";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import {
  ShuguClient,
  ShuguEvent,
  PerformanceTags,
  base64ToArrayBuffer,
  fetchAuthStatus,
  logout,
} from "../services/shuguClient";

type ConnStatus = "connecting" | "open" | "closed" | "error";

const MAX_CHAT_LOG = 80;

export function HomeClient() {
  const { viewer } = useContext(ViewerContext);

  const [operator, setOperator] = useState<{ username: string } | null>(null);
  const [authLoaded, setAuthLoaded] = useState(false);

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

  // Uptime démarré à l'ouverture du WS. reactionSeed incrémenté à chaque
  // performance.audio pour déclencher les emoji flottants dans ViewerStage.
  const [streamStartMs, setStreamStartMs] = useState<number | null>(null);
  const [reactionSeed, setReactionSeed] = useState(0);
  const uptime = useHmsUptime(streamStartMs);
  const router = useRouter();
  useEffect(() => {
    if (connStatus === "open") {
      // P6: functional update — sets startMs once on first "open", never re-triggers.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setStreamStartMs((prev) => prev ?? Date.now());
    }
  }, [connStatus]);

  const clientRef = useRef<ShuguClient | null>(null);

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
  // Ref-mirror so the ShuguClient useEffect closure always calls the latest
  // appendLog without needing to list it as a dep (which would reconnect the
  // WebSocket on every render since appendLog is recreated each render).
  const appendLogRef = useRef(appendLog);
  useEffect(() => { appendLogRef.current = appendLog; });

  useEffect(() => {
    if (!operator) return;
    try {
      // P2: SSR-safe localStorage init in effect gated on operator — cannot use useState lazy init here.
      // eslint-disable-next-line react-hooks/set-state-in-effect
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
      const ok = clientRef.current?.sendChat(trimmed);
      if (!ok) { setNotice("déconnecté"); return; }
      appendLog({ role: "user", content: "🎙️ " + trimmed });
    },
  });

  useEffect(() => {
    let cancelled = false;
    fetchAuthStatus().then((me) => { if (!cancelled) { setOperator(me); setAuthLoaded(true); } });
    // Prime les caches registry au boot : gestures (via animationPack),
    // scenes (map SCENES), emotes (map EMOJI). Toutes ont un fallback
    // statique → safe même si le fetch échoue.
    getActionClips().catch(() => { /* fallback pris automatiquement */ });
    refreshScenes().catch(() => { /* idem */ });
    refreshEmotes().catch(() => { /* idem */ });
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
            appendLogRef.current({ role: "assistant", content: ev.text });
            setReactionSeed((s) => s + 1);
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
          if (ev.text) {
            appendLogRef.current({ role: "assistant", content: ev.text });
            setReactionSeed((s) => s + 1);
          }

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
          // Direct state-change from LLM body control — bypasses picker.
          sceneManagerRef.current?.requestScene(ev.scene);
        } else if (ev.type === "scene.preview") {
          // Scene editor admin broadcast — applique la config directement
          // au Viewer, en **bypassant** le cooldown SceneManager. Temporaire :
          // au F5 le visiteur retombe sur la scene DB.
          const cfg = ev.config;
          const v = viewerRef.current;
          console.log("[scene.preview] received", ev.slug, cfg);
          if (v) {
            v.setShot({
              cameraBase: new THREE.Vector3(cfg.camera.x, cfg.camera.y, cfg.camera.z),
              lookAt: new THREE.Vector3(cfg.look_at.x, cfg.look_at.y, cfg.look_at.z),
              fov: cfg.fov,
            });
            v.setAvatarTransform(
              new THREE.Vector3(
                cfg.avatar_position.x, cfg.avatar_position.y, cfg.avatar_position.z,
              ),
              cfg.avatar_rotation_y,
            );
          }
          if (cfg.background) document.body.style.background = cfg.background;
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
        } else if (ev.type === "registry.invalidated") {
          // Le backend a modifié le registry : on flush TOUS les caches
          // locaux + on re-fetch les kinds consommés par la page visiteur
          // (gestures, scenes, emotes). Les autres kinds (shot, expression,
          // mood) sont lus à la demande donc pas besoin de refresh immédiat.
          invalidateRegistry();
          invalidateActionClipsCache();
          void getActionClips();
          void refreshScenes();
          void refreshEmotes();
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

  // Mapping chatLog → ChatMsg[] pour ViewerStage. Les messages assistant
  // sont marqués `stream: true` uniquement quand ils sont le DERNIER message
  // (simule l'arrivée live). Les historiques ne streament pas.
  const stageMessages: ChatMsg[] = chatLog.map((m, i) => {
    const isLast = i === chatLog.length - 1;
    if (m.role === "system") {
      return { kind: "system", text: m.content };
    }
    if (m.role === "assistant") {
      return {
        kind: "assistant",
        who: "Shugu",
        text: m.content,
        stream: isLast,
      };
    }
    // role === "user"
    return {
      kind: "visitor",
      who: operator?.username ?? "you",
      text: m.content,
      rank: operator ? "admin" : "guest",
      glyph: operator ? "♚" : "",
    };
  });

  const handleStageSend = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const ok = clientRef.current?.sendChat(trimmed);
    if (!ok) { setNotice("déconnecté, reconnexion…"); return; }
    appendLog({ role: "user", content: trimmed });
    setInputValue("");
  };

  // Sprint D PR D-8 wiring : LiveKitProvider (audio TTS streaming) +
  // ViewerEventsProvider (events scéniques scene.apply / voice.interrupt) sont
  // montés ICI à côté de `<VrmViewer />`. Ils partagent le hook
  // `useViewerToken` mutualisé qui fetch + refresh proactif T-60s.
  //
  // Gate `operator` (passé via `enabled`) : `POST /api/voice/token` exige un
  // cookie `shugu_user_access` valide (route 401 sans). Sans ce gate, un
  // visiteur anonyme verrait un toast d'erreur permanent. Pour Sprint D MVP,
  // voice est réservé aux user authentifiés. Sprint E ouvrira aux visiteurs
  // (token anonymous-but-rate-limited).
  //
  // On wrap INCONDITIONNELLEMENT par les deux Providers (vs swap on/off de
  // l'arbre racine) pour éviter qu'un login mid-session unmount + remount le
  // sous-arbre `<VrmViewer />` (28 MB de re-parsing). `enabled` est plumbed
  // jusqu'au hook `useViewerToken` qui no-op tant qu'il est false.
  const voiceWiringActive = !!operator;

  const innerStage = (
    <div className="font-quicksand">
      <LiquidGlassFilter />

      <EmoteOverlay ref={emoteOverlayRef} />
      <SpeakingRing visible={speaking} />

      {!avatarLoaded && <LoadingScreen />}

      {/* ViewerStage — port 1:1 de preview/proto/app.jsx. Le VRM remplace la
          scène nebula/avatar via la prop `stageSlot`. */}
      <ViewerStage
        stageSlot={
          <VrmViewer
            onLoaded={() => {
              setAvatarLoaded(true);
              const v = viewerRef.current;
              if (v && !sceneManagerRef.current) {
                const mgr = new SceneManager({
                  viewer: v,
                  onBackgroundChange: (bg) => {
                    document.body.style.background = bg;
                  },
                });
                sceneManagerRef.current = mgr;
                void refreshScenes().then(() => mgr.applyInitial());
              }
            }}
          />
        }
        messages={stageMessages}
        session={operator ? { name: operator.username, tier: "admin" } : null}
        viewerCount={viewerCount}
        uptimeLabel={`LIVE · ${uptime}`}
        connStatus={connStatus}
        inputValue={inputValue}
        onInputChange={setInputValue}
        onSend={handleStageSend}
        inputDisabled={connStatus !== "open"}
        reactionSeed={reactionSeed}
        onLogin={() => { void router.push("/login"); }}
        onSignup={() => { void router.push("/login"); }}
        onAccount={() => {
          if (operator) void router.push(`/${encodeURIComponent(operator.username)}/account`);
        }}
        onLogout={async () => {
          await logout();
          setOperator(null);
        }}
        onAdmin={() => {
          if (operator) void router.push(`/${encodeURIComponent(operator.username)}/admin`);
        }}
        voice={operator && voice.supported ? {
          supported: voice.supported,
          listening: voice.listening,
          interim: voice.interim,
          start: voice.start,
          stop: voice.stop,
        } : undefined}
      />

      {/* VisitorLogin — retirée du viewer (absente du proto). Le login est
          maintenant accessible via le menu déployable du brand pill (HudTop →
          "Log in" / "Sign up"). Décommenter pour réactiver. */}
      {/* {!operator && <VisitorLogin />} */}

      {notice && (
        <div className="fixed top-[5.5rem] sm:top-24 right-[380px] z-20 animate-fade-up bg-shugu-live/90 text-white px-4 py-2 rounded-full text-xs sm:text-sm shadow-lg max-w-xs font-semibold">
          ✕ {notice}
        </div>
      )}
    </div>
  );

  // D-8 wiring : wrap inconditionnel par les deux Providers, qui no-op
  // (skip fetch token + skip WebSocket) tant que `enabled` est false.
  // Préserve l'identité du sous-arbre `<VrmViewer />` à travers un login.
  return (
    <LiveKitProvider enabled={voiceWiringActive}>
      <ViewerEventsProvider enabled={voiceWiringActive}>
        {innerStage}
      </ViewerEventsProvider>
    </LiveKitProvider>
  );
}
