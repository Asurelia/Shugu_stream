// Tiny nonce generator — crypto.getRandomValues when available, Math.random fallback.
const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-";

export function nanoid(size = 12): string {
  let id = "";
  if (typeof crypto !== "undefined" && (crypto as any).getRandomValues) {
    const bytes = new Uint8Array(size);
    crypto.getRandomValues(bytes);
    for (let i = 0; i < size; i++) id += ALPHABET[bytes[i] % 64];
  } else {
    for (let i = 0; i < size; i++) id += ALPHABET[Math.floor(Math.random() * 64)];
  }
  return id;
}
