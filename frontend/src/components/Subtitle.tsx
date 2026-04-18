type Props = {
  text: string;
};

export function Subtitle({ text }: Props) {
  if (!text) return null;
  return (
    <div className="fixed bottom-28 left-0 right-0 md:right-[340px] flex justify-center px-4 sm:px-6 z-20 pointer-events-none">
      <div
        className="max-w-2xl px-5 sm:px-7 py-3 sm:py-4 bubble-kawaii font-quicksand font-semibold text-shugu-ink text-base sm:text-xl leading-snug text-center animate-bubble-pop"
        style={{
          background: "linear-gradient(135deg, #FFC9D6 0%, #FFF8F1 50%, #DCC7FF 100%)",
          boxShadow: "0 8px 28px rgba(255, 97, 127, 0.45), 0 0 0 2px rgba(255, 168, 185, 0.3) inset",
        }}
      >
        {text}
      </div>
    </div>
  );
}
