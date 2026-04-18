import { FormEvent, useMemo } from "react";

type Props = {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  disabled: boolean;
  hermesMode?: boolean;
  voice?: {
    supported: boolean;
    listening: boolean;
    interim: string;
    start: () => void;
    stop: () => void;
  };
};

export function ChatInput({ value, onChange, onSubmit, disabled, hermesMode, voice }: Props) {
  const placeholder = useMemo(() => {
    if (voice?.listening) return voice.interim ? `🎙️ « ${voice.interim} »` : "🎙️ écoute…";
    if (hermesMode) return "⚡ commande Hermes…";
    return "parle à Shugu ♡";
  }, [voice?.listening, voice?.interim, hermesMode]);

  const accentClass = hermesMode ? "ring-shugu-live/50" : "ring-shugu-pink/50";
  const submitClass = hermesMode
    ? "bg-shugu-live hover:bg-shugu-live/85 shadow-[0_0_20px_rgba(255,59,92,0.45)]"
    : "bg-shugu-pink hover:bg-shugu-pink-glow shadow-[0_0_20px_rgba(255,97,127,0.45)]";

  return (
    <form
      onSubmit={onSubmit}
      className="fixed bottom-0 left-0 right-0 z-20 px-3 sm:px-4 md:pr-[340px] pb-3 sm:pb-5 pt-6 sm:pt-10 bg-gradient-to-t from-shugu-ink via-shugu-ink/60 to-transparent pointer-events-none"
    >
      <div className="max-w-2xl mx-auto flex items-center gap-2 pointer-events-auto">
        {voice?.supported && (
          <button
            type="button"
            onClick={voice.listening ? voice.stop : voice.start}
            disabled={disabled}
            title={voice.listening ? "arrêter" : "parler"}
            className={`shrink-0 w-11 h-11 sm:w-12 sm:h-12 rounded-full flex items-center justify-center text-lg sm:text-xl transition-all ${
              voice.listening
                ? "bg-shugu-live text-white animate-pulse shadow-[0_0_20px_rgba(255,59,92,0.6)]"
                : "bg-shugu-ink-soft/90 text-shugu-pink-soft hover:bg-shugu-ink-soft hover:text-shugu-pink-glow"
            } disabled:opacity-40 disabled:cursor-not-allowed`}
          >
            {voice.listening ? "●" : "🎙"}
          </button>
        )}

        <div
          className={`flex-1 flex items-center bg-shugu-cream/95 rounded-full pl-5 pr-2 py-1.5 ring-2 ring-transparent focus-within:${accentClass} transition-all`}
          style={{
            boxShadow: "0 8px 28px rgba(0, 0, 0, 0.35), 0 0 0 1px rgba(255, 168, 185, 0.25) inset",
          }}
        >
          <input
            type="text"
            value={voice?.listening ? voice.interim : value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            maxLength={hermesMode ? 2000 : 500}
            disabled={disabled || !!voice?.listening}
            aria-label="message"
            className="flex-1 bg-transparent text-shugu-ink placeholder-shugu-ink/50 focus:outline-none font-quicksand text-base"
          />
          <button
            type="submit"
            disabled={!value.trim() || disabled || !!voice?.listening}
            aria-label={hermesMode ? "déléguer" : "envoyer"}
            className={`shrink-0 w-9 h-9 sm:w-10 sm:h-10 rounded-full flex items-center justify-center text-white text-lg font-bold transition-all ${submitClass} disabled:opacity-30 disabled:cursor-not-allowed disabled:shadow-none`}
          >
            {hermesMode ? "⚡" : "♡"}
          </button>
        </div>
      </div>
    </form>
  );
}
