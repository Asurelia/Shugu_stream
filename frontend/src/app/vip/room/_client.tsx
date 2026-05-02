"use client";

/**
 * /vip/room client island — LiveKit VIP voice room with Shugu.
 *
 * Migration Pages Router → App Router (Sprint E3) :
 *   - `useRouter` import : `next/router` → `next/navigation`.
 *   - `<Meta title>` removed — the parent Server Component (page.tsx)
 *     declares `metadata` instead.
 *   - Named export `VipRoomClient` (not default) per Sprint E pattern.
 *   - LiveKitRoom cast preserved (see comment below).
 *
 * All LiveKit logic untouched : status checking, mintVIPToken, leave handler,
 * RoomStage inner component.
 */

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  GlassCard,
  GlassButton,
  GlassPill,
} from "@/features/liquid-glass/primitives";
import {
  LiveKitRoom as LiveKitRoomImpl,
  RoomAudioRenderer,
  VoiceAssistantControlBar,
  useVoiceAssistant,
  BarVisualizer,
  useLocalParticipant,
} from "@livekit/components-react";

// @livekit/components-react 2.x types its components as `(props) => ReactNode`
// rather than `JSX.Element`, which TypeScript rejects when used as a JSX tag
// under strict mode. Cast to a permissive component type so the JSX call site
// type-checks. See: https://github.com/livekit/components-js/issues — known
// upstream typing gap, removable once livekit-react ships JSX.Element-typed
// components.
const LiveKitRoom = LiveKitRoomImpl as unknown as React.ComponentType<
  Record<string, unknown>
>;
import "@livekit/components-styles";
import { mintVIPToken, LiveKitError } from "@/services/livekitClient";
import { me as fetchMe, type Me } from "@/services/accountClient";


type Status = "checking" | "connecting" | "connected" | "error" | "not_vip";


function RoomStage() {
  const { state } = useVoiceAssistant();
  const { localParticipant } = useLocalParticipant();
  const label = state === "speaking" ? "Shugu parle" :
                state === "listening" ? "Shugu t'écoute" :
                state === "thinking"  ? "Shugu réfléchit" :
                state === "connecting" ? "Connexion…" : "—";
  return (
    <div className="flex flex-col items-center justify-center gap-6 py-8">
      <GlassPill tone="primary" dot>{label}</GlassPill>
      <div className="w-[220px] h-[80px]">
        <BarVisualizer state={state} barCount={24} />
      </div>
      <p className="text-xs opacity-50">
        connecté en tant que {localParticipant?.identity ?? "…"}
      </p>
    </div>
  );
}


export function VipRoomClient() {
  const router = useRouter();
  const [status, setStatus] = useState<Status>("checking");
  const [errorDetail, setErrorDetail] = useState<string>("");
  const [me, setMe] = useState<Me | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [serverUrl, setServerUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const current = await fetchMe().catch(() => null);
      if (cancelled) return;
      if (!current) { router.replace("/account/login"); return; }
      setMe(current);
      if (!current.vip_active) { setStatus("not_vip"); return; }

      setStatus("connecting");
      try {
        const { token, url } = await mintVIPToken();
        if (cancelled) return;
        setToken(token);
        setServerUrl(url);
        setStatus("connected");
      } catch (err) {
        if (cancelled) return;
        setStatus("error");
        if (err instanceof LiveKitError) setErrorDetail(err.detail);
        else setErrorDetail("Erreur réseau inattendue");
      }
    })();
    return () => { cancelled = true; };
  }, [router]);

  const leave = () => router.push("/account/profile");

  if (status === "checking" || status === "connecting") {
    return (
      <div className="lg-page min-h-screen flex items-center justify-center p-6">
        <GlassCard padded className="max-w-md w-full text-center">
          <h1 className="text-xl font-light tracking-tight text-shugu-cream mb-2">
            {status === "checking" ? "Vérification…" : "Connexion au salon VIP…"}
          </h1>
          <p className="text-sm opacity-60">Ça prend quelques secondes.</p>
        </GlassCard>
      </div>
    );
  }

  if (status === "not_vip") {
    return (
      <div className="lg-page min-h-screen flex items-center justify-center p-6">
        <GlassCard padded className="max-w-md w-full text-center">
          <h1 className="text-xl font-light tracking-tight text-shugu-cream mb-2">
            Accès réservé aux VIPs
          </h1>
          <p className="text-sm opacity-60 mb-6">
            Tu es connecté en tant que <strong>{me?.username}</strong>,
            mais ton compte n&apos;a pas (encore) l&apos;accès VIP.
          </p>
          <GlassButton onClick={() => router.replace("/account/profile")}>
            Retour au profil
          </GlassButton>
        </GlassCard>
      </div>
    );
  }

  if (status === "error" || !token || !serverUrl) {
    return (
      <div className="lg-page min-h-screen flex items-center justify-center p-6">
        <GlassCard padded className="max-w-md w-full text-center">
          <h1 className="text-xl font-light tracking-tight text-shugu-cream mb-2">
            Impossible de rejoindre
          </h1>
          <p className="text-sm opacity-60 mb-2">
            {errorDetail || "Le tunnel LiveKit n&apos;est peut-être pas encore actif sur le serveur."}
          </p>
          <p className="text-xs opacity-50 mb-6">
            Vérifie que <code>LIVEKIT_URL</code> / <code>LIVEKIT_API_KEY</code> /
            <code>LIVEKIT_API_SECRET</code> sont dans <code>.env</code> et que
            <code>livekit-server</code> tourne.
          </p>
          <GlassButton onClick={() => router.replace("/account/profile")}>
            Retour au profil
          </GlassButton>
        </GlassCard>
      </div>
    );
  }

  return (
    <div className="lg-page min-h-screen flex items-center justify-center p-6">
      <LiveKitRoom
        token={token}
        serverUrl={serverUrl}
        connect
        audio
        video={false}
        onDisconnected={leave}
        style={{ width: "100%", maxWidth: 480 }}
      >
        <GlassCard padded className="w-full">
          <RoomAudioRenderer />
          <div className="flex items-center justify-between mb-2">
            <h1 className="text-xl font-light tracking-tight text-shugu-cream">
              Salon VIP
            </h1>
            <GlassButton variant="subtle" size="sm" onClick={leave}>
              Quitter
            </GlassButton>
          </div>
          <p className="text-xs opacity-60 mb-4">
            Conversation privée avec Shugu. Parle, écoute, coupe-la si tu veux.
          </p>
          <RoomStage />
          <div className="pt-4">
            <VoiceAssistantControlBar />
          </div>
        </GlassCard>
      </LiveKitRoom>
    </div>
  );
}
