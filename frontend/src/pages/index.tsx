import { useContext, useEffect, useRef, useState } from "react";
import { Quicksand, Comfortaa } from "next/font/google";
import VrmViewer from "@/components/vrmViewer";
import { ViewerContext } from "@/features/vrmViewer/viewerContext";
import { Message, Screenplay } from "@/features/messages/messages";
import { speakFromServer } from "@/features/messages/speakFromServer";
import { Meta } from "@/components/meta";
import { Brand } from "@/components/Brand";
import { LiveHUD } from "@/components/LiveHUD";
import { VisitorLogin } from "@/components/VisitorLogin";
import { Subtitle } from "@/components/Subtitle";
import { ChatInput } from "@/components/ChatInput";
import { ChatFeed } from "@/components/ChatFeed";
import { SpeakingRing } from "@/components/SpeakingRing";
import { LoadingScreen } from "@/components/LoadingScreen";
import { Sparkles } from "@/components/Sparkles";
import { OperatorPanel, Mode } from "@/components/OperatorPanel";
import { EmoteOverlay, EmoteOverlayHandle } from "@/components/EmoteOverlay";
import { SceneManager } from "@/features/scenes/SceneManager";
import { ACTION_CLIPS } from "@/features/animations/animationPack";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import {
  ShuguClient, ShuguEvent, base64ToArrayBuffer, fetchAuthStatus,
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

type ConnStatus = "connecting" | "open" | "closed" | "error";

const MAX_CHAT_LOG = 80;

export default function Home() {
  const { viewer } = useContext(ViewerContext);

  const [operator, setOperator] = useState<{ username: string } | null>(null);
  const [authLoaded, setAuthLoaded] = useState(false);
  const [mode, setMode] = useState<Mode>("shugu");
  const [pendingHermes, setPendingHermes] = useState(false);

  const [connStatus, setConnStatus] = useState<ConnStatus>("connecting");
  const [chatLog, setChatLog] = useState<Message[]>([]);
  const [assistantMessage, setAssistantMessage] = useState("");
  const [inputValue, setInputValue] = useState("");
  const [notice, setNotice] = useState<string>("");
  const [avatarLoaded, setAvatarLoaded] = useState(false);
  const [viewerCount, setViewerCount] = useState<number>(0);
  const [speaking, setSpeaking] = useState(false);

  const clientRef = useRef<ShuguClient | null>(null);
  const modeRef = useRef<Mode>(mode);
  useEffect(() => { modeRef.current = mode; }, [mode]);

  const viewerRef = useRef(viewer);
  useEffect(() => { viewerRef.current = viewer; }, [viewer]);

  const emoteOverlayRef = useRef<EmoteOverlayHandle>(null);
  const sceneManagerRef = useRef<SceneManager | null>(null);

  const appendLog = (m: Message) => {
    setChatLog((l) => [...l.slice(-MAX_CHAT_LOG + 1), m]);
    // Trigger a brief glance toward the chat-feed zone (top-left) whenever a
    // new entry arrives — gives Shugu the impression of noticing the message.
    // NDC target: roughly the middle of the ChatFeed component on screen.
    viewerRef.current?.triggerChatGlance({ x: 0.7, y: 0.25 });
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
          if (tags.scene) sceneManagerRef.current?.requestScene(tags.scene);
          if (tags.action) {
            const clip = ACTION_CLIPS[tags.action];
            if (clip) {
              void viewerRef.current?.animationManager?.playOneShot(clip);
            } else {
              console.warn(`[tags] unknown action '${tags.action}'`);
            }
          }
          if (tags.emote) emoteOverlayRef.current?.push(tags.emote);

          if (ev.text) {
            setAssistantMessage(ev.text);
            appendLog({ role: "assistant", content: ev.text });
          }

          if (ev.audio_b64) {
            const audio = base64ToArrayBuffer(ev.audio_b64);
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
        } else if (ev.type === "performance.end") {
          setSpeaking(false);
          setTimeout(() => setAssistantMessage(""), 1800);
        } else if (ev.type === "viewer.count") {
          setViewerCount(ev.n);
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
    <div className={`${quicksand.variable} ${comfortaa.variable} font-quicksand`}>
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

      <Brand />
      <LiveHUD
        connStatus={connStatus}
        viewerCount={viewerCount}
        speaking={speaking}
      />
      {!operator && <VisitorLogin />}

      {operator && (
        <OperatorPanel
          username={operator.username}
          mode={mode}
          onModeChange={setMode}
          pendingHermesTask={pendingHermes}
        />
      )}

      <ChatFeed messages={chatLog} />

      <Subtitle text={assistantMessage} />

      {notice && (
        <div className="fixed top-[5.5rem] sm:top-24 right-4 md:right-[340px] z-20 animate-fade-up bg-shugu-live/90 text-white px-4 py-2 rounded-full text-xs sm:text-sm shadow-lg max-w-xs font-semibold">
          ✕ {notice}
        </div>
      )}

      <ChatInput
        value={inputValue}
        onChange={setInputValue}
        onSubmit={handleSubmit}
        disabled={connStatus !== "open"}
        hermesMode={!!operator && mode === "hermes"}
        voice={operator && voice.supported ? {
          supported: voice.supported,
          listening: voice.listening,
          interim: voice.interim,
          start: voice.start,
          stop: voice.stop,
        } : undefined}
      />
    </div>
  );
}
