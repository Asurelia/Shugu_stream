// Web Speech API wrapper — Chrome/Edge/Safari. Firefox has no native STT.
// Produces interim + final transcripts in French by default.
import { useCallback, useRef, useState } from "react";

type Opts = {
  lang?: string;
  onFinal?: (text: string) => void;
};

export function useVoiceInput({ lang = "fr-FR", onFinal }: Opts = {}) {
  const [supported] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return !!(
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    );
  });
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const recRef = useRef<any>(null);

  const start = useCallback(() => {
    if (typeof window === "undefined") return;
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return;
    const rec = new SR();
    rec.lang = lang;
    rec.interimResults = true;
    rec.continuous = false;

    let finalText = "";

    rec.onresult = (ev: any) => {
      let curInterim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results[i];
        const t: string = res[0].transcript;
        if (res.isFinal) finalText += t;
        else curInterim += t;
      }
      setInterim(curInterim);
    };

    rec.onend = () => {
      setListening(false);
      setInterim("");
      const out = finalText.trim();
      if (out) onFinal?.(out);
    };

    rec.onerror = (ev: any) => {
      console.error("speech recognition error:", ev.error);
      setListening(false);
      setInterim("");
    };

    recRef.current = rec;
    setListening(true);
    setInterim("");
    rec.start();
  }, [lang, onFinal]);

  const stop = useCallback(() => {
    try { recRef.current?.stop(); } catch {}
  }, []);

  return { supported, listening, interim, start, stop };
}
