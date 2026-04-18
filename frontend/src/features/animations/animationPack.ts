/**
 * VRMA clip paths for one-shot actions. Files live under
 * `frontend/public/animations/` and are served statically.
 *
 * Conversion pipeline: download FBX from Mixamo → fbx2vrma-converter → drop
 * the resulting `.vrma` in the public folder with the exact filename below.
 *
 * Missing files fail gracefully: AnimationMixerManager logs a warning and
 * keeps the idle loop running.
 */

// Paths point to Mixamo FBX files — retargeted to the VRM rig at load time
// (see fbxRetarget.ts). `.vrma` files still work too — the mixer dispatches on
// extension, so you can mix both formats freely.
export const ACTION_CLIPS: Record<string, string> = {
  wave: "/animations/wave.fbx",
  nod: "/animations/nod.fbx",
  shake_head: "/animations/shake_head.fbx",
  think: "/animations/think.fbx",
  laugh: "/animations/laugh.fbx",
  shrug: "/animations/shrug.fbx",
  point: "/animations/point.fbx",
  bow: "/animations/bow.fbx",
  clap: "/animations/clap.fbx",
  peace: "/animations/peace.fbx",
  heart: "/animations/heart_pose.fbx",
  peek: "/animations/peek.fbx",
  stretch: "/animations/stretch.fbx",
  dance_light: "/animations/dance_light.fbx",
  idle_variant: "/animations/idle_variant.fbx",
};

export type ActionName = keyof typeof ACTION_CLIPS;

export function isActionName(name: string): name is ActionName {
  return name in ACTION_CLIPS;
}
