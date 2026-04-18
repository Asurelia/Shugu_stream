# Shugu animation pack — drop-in Mixamo FBX workflow

The frontend loads Mixamo `.fbx` files **directly** and retargets them to
Shugu's VRM rig at runtime (see `src/features/animations/fbxRetarget.ts`).
**No Blender, no conversion step** — just download from Mixamo and drop the
file here with the correct filename.

> The retargeter also still supports `.vrma` files. Mix both freely: if a
> given clip looks wrong in FBX, convert it via fbx2vrma-converter and replace
> `.fbx` with `.vrma` (the path in `animationPack.ts` / `scenes.ts` is just a
> string the loader reads by extension).

## How to get the files

1. Sign in to https://www.mixamo.com/ with a free Adobe account.
2. Pick **X-Bot** or **Y-Bot** as the character (they share Shugu's T-pose
   convention, so no rest-pose correction is needed).
3. Download each clip below with:
   - **Format:** FBX Binary (.fbx), 30 fps
   - **Skin:** *Without Skin* (we only want the animation tracks)
   - **Keyframe reduction:** none
   - **In Place:** check for in-place clips (wave, bow, think, …); uncheck for
     cycles that should move the hip (dance, walk, run)

4. Rename the downloaded file to match the **target filename** column.
5. Copy the files here. No server restart needed — Next serves `/public/*`
   statically; reload the page and they pop in on the next tag or `!command`.

## Required filenames

| Target filename          | Mixamo search name                 | In-place |
|--------------------------|------------------------------------|----------|
| `wave.fbx`               | Waving                             | yes      |
| `nod.fbx`                | Head Nod Yes (or Nodding)          | yes      |
| `shake_head.fbx`         | No Shake Head                      | yes      |
| `think.fbx`              | Thinking                           | yes      |
| `laugh.fbx`              | Laughing                           | yes      |
| `shrug.fbx`              | Shrugging                          | yes      |
| `point.fbx`              | Pointing (forward)                 | yes      |
| `bow.fbx`                | Standing Greeting / Bow            | yes      |
| `clap.fbx`               | Clapping                           | yes      |
| `peace.fbx`              | Victory                            | yes      |
| `heart_pose.fbx`         | Blowing Kiss                       | yes      |
| `peek.fbx`               | Peek (or Looking Around)           | yes      |
| `stretch.fbx`            | Stretching                         | yes      |
| `dance_light.fbx`        | Hip Hop Dancing (short)            | yes / no |
| `idle_variant.fbx`       | Standing Idle 2 / Breathing Idle   | yes      |

Scene idles (replace the default `idle_loop.vrma` when the scene changes):

| Target filename               | Used when scene =      | Mixamo search                     |
|-------------------------------|------------------------|-----------------------------------|
| `idle_attentive.fbx`          | `reading_chat`         | Neutral Idle (looking slightly away) |
| `idle_excited.fbx`            | `reacting`             | Happy Idle                        |
| `idle_sleepy.fbx`             | `idle_sleepy`          | Tired / Sleepy Idle               |

The default scene `just_chatting` keeps the existing `/idle_loop.vrma` that
ships in `frontend/public/`.

## Quick smoke test

Drop only `wave.fbx` first, reload, and ask Shugu "fais-moi coucou" (or type
`!wave` as a visitor). Shugu should crossfade from idle → wave → idle.

## Troubleshooting

- **Nothing happens** → open DevTools console. `[AnimationMixer] failed to
  load …` or `[fbxRetarget] no Mixamo-named tracks …` points at a naming or
  file-integrity issue. Re-download without "Skin" to halve the file size.
- **Limbs look twisted** → Mixamo T-pose vs VRM rest pose mismatch. Use
  fbx2vrma-converter offline for that specific clip and ship a `.vrma`.
- **Clip plays the wrong way** → check the file is 30 fps. Higher rates play
  too fast because the retargeter reuses the FBX time table.

## Licence

Mixamo clips are free for commercial use when downloaded through an Adobe
account. Keep a note of the account used in case of later audit.
