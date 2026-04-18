import * as THREE from "three";
import { FBXLoader } from "three/examples/jsm/loaders/FBXLoader";
import type { VRMHumanBoneName } from "@pixiv/three-vrm";
import { VRMAnimation } from "@/lib/VRMAnimation/VRMAnimation";

/**
 * Runtime Mixamo-FBX → VRM retargeter.
 *
 * Why: `fbx2vrma-converter` is a Blender plug-in. Asking the operator to run
 * Blender for every clip is friction we don't need. Instead, we load the FBX
 * directly in the browser, rename the `mixamorig:*` tracks to the VRM human
 * bone names, and wrap the result in a `VRMAnimation` so the existing
 * `createAnimationClip(vrm)` path is reused (it already handles VRM0/VRM1
 * axis flips and hip-height scaling).
 *
 * Caveat: rest-pose offset correction is NOT applied. Mixamo characters are in
 * T-pose; if the VRM was exported in A-pose, the shoulders look slightly off
 * during the first frames. Acceptable for gestural clips (wave/bow/etc.) — if
 * the result is noticeably warped, convert the FBX in Blender instead.
 */

const MIXAMO_TO_VRM: Record<string, VRMHumanBoneName> = {
  Hips: "hips",
  Spine: "spine",
  Spine1: "chest",
  Spine2: "upperChest",
  Neck: "neck",
  Head: "head",
  LeftShoulder: "leftShoulder",
  LeftArm: "leftUpperArm",
  LeftForeArm: "leftLowerArm",
  LeftHand: "leftHand",
  RightShoulder: "rightShoulder",
  RightArm: "rightUpperArm",
  RightForeArm: "rightLowerArm",
  RightHand: "rightHand",
  LeftUpLeg: "leftUpperLeg",
  LeftLeg: "leftLowerLeg",
  LeftFoot: "leftFoot",
  LeftToeBase: "leftToes",
  RightUpLeg: "rightUpperLeg",
  RightLeg: "rightLowerLeg",
  RightFoot: "rightFoot",
  RightToeBase: "rightToes",
};

// FBXLoader strips the colon from bone names, so both `mixamorig:Hips` and
// `mixamorigHips` may appear depending on the source file.
const MIXAMO_PREFIX = /^mixamorig:?/;

const loader = new FBXLoader();

function stripMixamoPrefix(name: string): string {
  return name.replace(MIXAMO_PREFIX, "");
}

function findBoneByName(root: THREE.Object3D, bareName: string): THREE.Object3D | null {
  let found: THREE.Object3D | null = null;
  root.traverse((obj) => {
    if (found) return;
    if (stripMixamoPrefix(obj.name) === bareName) found = obj;
  });
  return found;
}

export async function loadMixamoFbxAsVrmAnimation(url: string): Promise<VRMAnimation | null> {
  const fbx = await loader.loadAsync(url);
  const clip = fbx.animations?.[0];
  if (!clip) {
    console.warn(`[fbxRetarget] no animation in ${url}`);
    return null;
  }

  const vrmAnim = new VRMAnimation();
  vrmAnim.duration = clip.duration;

  // Snapshot the FBX hips rest height so VRMAnimation.createAnimationClip can
  // scale translation tracks to the VRM rig's proportions.
  const hipsNode = findBoneByName(fbx, "Hips");
  if (hipsNode) {
    vrmAnim.restHipsPosition.copy(hipsNode.position);
  }

  let matched = 0;
  for (const track of clip.tracks) {
    // Track name e.g. "mixamorigHips.quaternion" / "mixamorigHips.position".
    const dot = track.name.lastIndexOf(".");
    if (dot < 0) continue;
    const rawBone = track.name.slice(0, dot);
    const property = track.name.slice(dot + 1);
    const bareBone = stripMixamoPrefix(rawBone);
    const vrmBone = MIXAMO_TO_VRM[bareBone];
    if (!vrmBone) continue;

    if (property === "quaternion") {
      vrmAnim.humanoidTracks.rotation.set(vrmBone, track as unknown as THREE.VectorKeyframeTrack);
      matched++;
    } else if (property === "position" && vrmBone === "hips") {
      vrmAnim.humanoidTracks.translation.set(vrmBone, track as unknown as THREE.VectorKeyframeTrack);
      matched++;
    }
  }

  if (matched === 0) {
    console.warn(`[fbxRetarget] no Mixamo-named tracks in ${url} — bone prefix mismatch?`);
    return null;
  }

  return vrmAnim;
}
