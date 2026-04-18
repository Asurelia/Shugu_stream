// Feed a server-provided audio buffer + screenplay into the existing VRM `speak()` API.
// This bypasses the original createSpeakCharacter() which fetches from ElevenLabs client-side.
import { Viewer } from "../vrmViewer/viewer";
import { Screenplay } from "./messages";

export async function speakFromServer(
  viewer: Viewer,
  audio: ArrayBuffer,
  screenplay: Screenplay,
  onStart?: () => void,
  onComplete?: () => void,
) {
  onStart?.();
  try {
    await viewer.model?.speak(audio, screenplay);
  } finally {
    onComplete?.();
  }
}
