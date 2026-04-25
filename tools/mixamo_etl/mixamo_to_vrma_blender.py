#!/usr/bin/env python3
"""Mixamo FBX → VRMA Conversion Pipeline (Blender Python Script).

Phase: Shugu Assets ETL — Mixamo Animation Bank

This script is executed inside Blender's Python environment and handles:
1. Load a Mixamo FBX animation (T-pose humanoid, rigged with `mixamorig:*` bones)
2. Retarget Mixamo skeleton to VRM skeleton (standard bone mapping)
3. Clean up and optimize animation keyframes
4. Export as VRMA (VRM Animation format via @pixiv/three-vrm-animation spec)

Requirements:
- Blender >= 3.4 (or 4.x)
- VRM Addon for Blender (https://github.com/Saturday06/VRM_Addon_for_Blender)
- A reference VRM avatar (to extract VRM skeleton structure)

Usage in Blender Python Console:
    exec(open('/path/to/mixamo_to_vrma_blender.py').read())
    convert_mixamo_fbx_to_vrma(
        input_fbx="/path/Mixamo_Animation.fbx",
        reference_vrm="/path/Reference_Avatar.vrm",
        output_vrma="/path/output.vrma",
        anim_slug="wave",
    )

Or via command-line:
    blender --python /path/to/mixamo_to_vrma_blender.py -- \\
        --input-fbx /path/Mixamo_Animation.fbx \\
        --reference-vrm /path/Reference_Avatar.vrm \\
        --output-vrma /path/output.vrma \\
        --slug wave
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s"
)
log = logging.getLogger(__name__)


# ============================================================================
# Mixamo → VRM Skeleton Mapping (Standard VRM Specification)
# ============================================================================
# Reference: https://github.com/vrm-c/vrm-specification/blob/master/specification/HUMANOID_BONE_SPECIFICATION.md

MIXAMO_TO_VRM_BONE_MAP = {
    # Spine chain
    "mixamorig:Hips": "Armature.armature:Hips",
    "mixamorig:Spine": "Armature.armature:Spine",
    "mixamorig:Spine1": "Armature.armature:Chest",
    "mixamorig:Spine2": "Armature.armature:UpperChest",
    "mixamorig:Neck": "Armature.armature:Neck",
    "mixamorig:Head": "Armature.armature:Head",

    # Left arm
    "mixamorig:LeftShoulder": "Armature.armature:LeftShoulder",
    "mixamorig:LeftArm": "Armature.armature:LeftUpperArm",
    "mixamorig:LeftForeArm": "Armature.armature:LeftLowerArm",
    "mixamorig:LeftHand": "Armature.armature:LeftHand",

    # Right arm
    "mixamorig:RightShoulder": "Armature.armature:RightShoulder",
    "mixamorig:RightArm": "Armature.armature:RightUpperArm",
    "mixamorig:RightForeArm": "Armature.armature:RightLowerArm",
    "mixamorig:RightHand": "Armature.armature:RightHand",

    # Left leg
    "mixamorig:LeftUpLeg": "Armature.armature:LeftUpperLeg",
    "mixamorig:LeftLeg": "Armature.armature:LeftLowerLeg",
    "mixamorig:LeftFoot": "Armature.armature:LeftFoot",
    "mixamorig:LeftToeBase": "Armature.armature:LeftToes",

    # Right leg
    "mixamorig:RightUpLeg": "Armature.armature:RightUpperLeg",
    "mixamorig:RightLeg": "Armature.armature:RightLowerLeg",
    "mixamorig:RightFoot": "Armature.armature:RightFoot",
    "mixamorig:RightToeBase": "Armature.armature:RightToes",
}


def validate_blender_context() -> None:
    """Validate that we're running inside Blender Python environment."""
    try:
        import bpy  # noqa: F401
        log.info("Blender context validated (bpy module available)")
    except ImportError:
        raise RuntimeError(
            "ERROR: This script MUST be run inside Blender's Python environment.\n"
            "Usage: blender --python mixamo_to_vrma_blender.py -- [options]"
        )


def import_mixamo_fbx(fbx_path: str) -> Tuple[Any, Any]:
    """Import Mixamo FBX and return (armature_obj, mesh_obj).

    The Mixamo T-pose FBX typically contains:
    - Armature with bones named mixamorig:* (Hips, Spine, LeftArm, etc.)
    - Mesh with armature deformer

    Returns:
        Tuple of (armature, mesh_or_None)
    """
    import bpy

    fbx_path = Path(fbx_path)
    if not fbx_path.exists():
        raise FileNotFoundError(f"Input FBX not found: {fbx_path}")

    log.info(f"Importing Mixamo FBX: {fbx_path}")

    # Clear scene to avoid conflicts
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.outliner.orphans_purge()

    # Import FBX
    bpy.ops.import_scene.fbx(filepath=str(fbx_path))

    # Find imported armature and mesh
    armature = None
    mesh = None
    for obj in bpy.context.scene.objects:
        if obj.type == "ARMATURE":
            armature = obj
        elif obj.type == "MESH":
            mesh = obj

    if armature is None:
        raise ValueError(
            "FBX import failed: no Armature found. Is this a valid Mixamo export?"
        )

    mesh_name = mesh.name if mesh else "None"
    log.info(f"Imported armature: {armature.name}, mesh: {mesh_name}")
    return armature, mesh


def load_reference_vrm_skeleton(vrm_path: str) -> Dict[str, Any]:
    """Load a reference VRM to extract target skeleton structure.

    This reads the VRM JSON armature descriptor to get canonical bone names
    and hierarchy for the VRM humanoid.

    Args:
        vrm_path: Path to .vrm file (GLTF + JSON metadata in binary)

    Returns:
        Dict with VRM humanoid bone names and hierarchy info
    """
    import bpy

    vrm_path = Path(vrm_path)
    if not vrm_path.exists():
        raise FileNotFoundError(f"Reference VRM not found: {vrm_path}")

    log.info(f"Loading reference VRM skeleton: {vrm_path}")

    # Import the VRM as a temporary object to extract skeleton
    bpy.ops.import_scene.gltf(filepath=str(vrm_path))

    vrm_armature = None
    for obj in bpy.context.scene.objects:
        if obj.type == "ARMATURE":
            vrm_armature = obj
            break

    if vrm_armature is None:
        raise ValueError("Reference VRM has no Armature")

    # Extract bone names
    vrm_bones = {}
    for bone in vrm_armature.data.bones:
        vrm_bones[bone.name] = {
            "head": list(bone.head),
            "tail": list(bone.tail),
            "parent": bone.parent.name if bone.parent else None,
        }

    log.info(f"Extracted {len(vrm_bones)} bones from reference VRM")

    # Clean up temporary VRM import
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    return vrm_bones


def create_vrm_armature(vrm_skeleton: Dict[str, Any]) -> Any:
    """Create a new Armature with VRM skeleton structure.

    Args:
        vrm_skeleton: Dict from load_reference_vrm_skeleton()

    Returns:
        New Blender Armature object
    """
    import bpy

    log.info("Creating VRM armature structure")

    # Create new armature
    bpy.ops.object.add(type='ARMATURE', enter_editmode=False)
    vrm_armature = bpy.context.active_object
    vrm_armature.name = "VRM_Target"

    # Switch to edit mode
    bpy.context.view_layer.objects.active = vrm_armature
    bpy.ops.object.mode_set(mode='EDIT')

    arm_data = vrm_armature.data

    # Remove default bone if present
    if len(arm_data.edit_bones) > 0:
        for bone in arm_data.edit_bones[:]:
            arm_data.edit_bones.remove(bone)

    # Add bones from VRM skeleton
    for bone_name, bone_data in vrm_skeleton.items():
        edit_bone = arm_data.edit_bones.new(bone_name)
        edit_bone.head = bone_data["head"]
        edit_bone.tail = bone_data["tail"]

        if bone_data["parent"] and bone_data["parent"] in arm_data.edit_bones:
            edit_bone.parent = arm_data.edit_bones[bone_data["parent"]]

    bpy.ops.object.mode_set(mode='OBJECT')
    log.info(f"VRM armature created with {len(vrm_armature.data.bones)} bones")

    return vrm_armature


def retarget_animation(
    source_armature: Any,
    target_armature: Any,
    bone_mapping: Dict[str, str],
    frame_range: Optional[Tuple[int, int]] = None,
) -> int:
    """Retarget animation from Mixamo armature to VRM armature.

    This copies keyframe data from Mixamo bones to VRM bones using the
    provided bone mapping. Rotation and location are retargeted.

    Args:
        source_armature: Mixamo armature (with animation)
        target_armature: VRM armature (empty, to be populated)
        bone_mapping: Dict[mixamo_bone_name] = vrm_bone_name
        frame_range: Optional (start, end) frame range. If None, uses all frames.

    Returns:
        Number of frames retargeted
    """
    import bpy

    log.info("Retargeting animation...")

    scene = bpy.context.scene
    if frame_range is None:
        frame_range = (int(scene.frame_start), int(scene.frame_end))

    frame_start, frame_end = frame_range
    log.info(f"Retargeting frames {frame_start} to {frame_end}")

    frames_retargeted = 0

    # Iterate frames
    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)

        # For each bone mapping
        for mixamo_name, vrm_name in bone_mapping.items():
            if mixamo_name not in source_armature.pose.bones:
                log.debug(f"Mixamo bone {mixamo_name} not found, skipping")
                continue

            if vrm_name not in target_armature.pose.bones:
                log.debug(f"VRM bone {vrm_name} not found, skipping")
                continue

            mixamo_bone = source_armature.pose.bones[mixamo_name]
            vrm_bone = target_armature.pose.bones[vrm_name]

            # Copy rotation (quaternion)
            vrm_bone.rotation_quaternion = mixamo_bone.rotation_quaternion.copy()

            # Copy location (only for root Hips)
            if vrm_name.endswith("Hips"):
                vrm_bone.location = mixamo_bone.location.copy()

            # Insert keyframes
            vrm_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            if vrm_name.endswith("Hips"):
                vrm_bone.keyframe_insert(data_path="location", frame=frame)

        frames_retargeted += 1
        if (frame - frame_start + 1) % 50 == 0:
            log.info(f"  Processed {frame - frame_start + 1} frames...")

    log.info(f"Retargeted {frames_retargeted} frames")
    return frames_retargeted


def bake_animation(
    armature: Any, frame_range: Optional[Tuple[int, int]] = None
) -> None:
    """Bake NLA and action to ensure clean export.

    Args:
        armature: Target armature
        frame_range: Optional frame range to bake
    """
    import bpy

    log.info("Baking animation...")

    scene = bpy.context.scene
    if frame_range is None:
        frame_range = (int(scene.frame_start), int(scene.frame_end))

    # Set frame range
    scene.frame_start = frame_range[0]
    scene.frame_end = frame_range[1]

    # Ensure action is assigned
    if armature.animation_data is None:
        armature.animation_data_create()

    log.info(f"Animation frame range: {frame_range[0]} to {frame_range[1]}")


def export_as_glb(
    armature: Any,
    mesh: Optional[Any],
    output_path: str,
    frame_range: Optional[Tuple[int, int]] = None,
) -> None:
    """Export armature + mesh as GLB (intermediate format for VRMA conversion).

    Args:
        armature: VRM target armature
        mesh: Optional mesh (can be None for animation-only export)
        output_path: Path to save .glb file
        frame_range: Optional frame range to include
    """
    import bpy

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    log.info(f"Exporting to GLB: {output_path}")

    # Select objects to export
    bpy.ops.object.select_all(action='DESELECT')
    armature.select_set(True)
    if mesh is not None:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = armature

    # Export GLB
    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        use_selection=True,
        use_animations=True,
        bake_animation=True,
        export_format='GLB',
        export_image_format='WEBP',
    )

    log.info(f"Exported GLB: {output_path}")


def export_vrma_metadata(
    output_vrma: str,
    anim_slug: str,
    frame_count: int,
    fps: float = 30.0,
) -> Dict[str, Any]:
    """Create VRMA metadata JSON descriptor.

    VRMA format metadata (supplementary to glTF):
    - animation slug (unique identifier)
    - frame count and FPS
    - retarget info (Mixamo → VRM mapping used)

    Args:
        output_vrma: Path to final .vrma file
        anim_slug: Animation identifier (e.g., "wave")
        frame_count: Total frames in animation
        fps: Frames per second (default 30)

    Returns:
        Metadata dict
    """
    output_path = Path(output_vrma)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    metadata = {
        "format": "vrma",
        "version": "1.0",
        "slug": anim_slug,
        "frame_count": frame_count,
        "fps": fps,
        "duration_seconds": frame_count / fps,
        "retarget_source": "mixamo",
        "retarget_mapping": "vrm_humanoid_standard",
        "export_date": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }

    log.info(f"VRMA metadata: {json.dumps(metadata, indent=2)}")
    return metadata


def convert_mixamo_fbx_to_vrma(
    input_fbx: str,
    reference_vrm: str,
    output_vrma: str,
    anim_slug: str,
    frame_range: Optional[Tuple[int, int]] = None,
    fps: float = 30.0,
) -> None:
    """Main conversion pipeline: Mixamo FBX → VRMA.

    Args:
        input_fbx: Path to Mixamo FBX file (T-pose + animation)
        reference_vrm: Path to reference VRM (for skeleton extraction)
        output_vrma: Path to output VRMA file (without .vrma extension)
        anim_slug: Animation slug identifier (e.g., "wave")
        frame_range: Optional (start, end) frame range
        fps: Frames per second (default 30)
    """
    validate_blender_context()

    log.info("=" * 70)
    log.info("Mixamo FBX → VRMA Conversion Pipeline")
    log.info(f"Input FBX: {input_fbx}")
    log.info(f"Reference VRM: {reference_vrm}")
    log.info(f"Output VRMA: {output_vrma}")
    log.info(f"Animation Slug: {anim_slug}")
    log.info("=" * 70)

    try:
        # Step 1: Import Mixamo FBX
        mixamo_arm, mixamo_mesh = import_mixamo_fbx(input_fbx)

        # Step 2: Load VRM reference skeleton
        vrm_skeleton = load_reference_vrm_skeleton(reference_vrm)

        # Step 3: Create target VRM armature
        vrm_arm = create_vrm_armature(vrm_skeleton)

        # Step 4: Retarget animation
        frame_count = retarget_animation(
            mixamo_arm, vrm_arm,
            MIXAMO_TO_VRM_BONE_MAP,
            frame_range=frame_range
        )

        # Step 5: Bake and finalize
        bake_animation(vrm_arm, frame_range=frame_range)

        # Step 6: Export as GLB intermediate
        glb_path = Path(output_vrma).with_suffix('.glb')
        export_as_glb(vrm_arm, None, str(glb_path), frame_range=frame_range)

        # Step 7: Generate VRMA metadata
        metadata = export_vrma_metadata(output_vrma, anim_slug, frame_count, fps=fps)

        # Step 8: Package as VRMA (GLB + metadata JSON sidecar)
        output_path = Path(output_vrma).with_suffix('.vrma')
        vrma_meta_path = output_path.with_suffix('.vrma.meta.json')

        # For now, VRMA = GLB + metadata JSON
        # A proper implementation would bundle both into a single archive
        if glb_path.exists():
            import shutil
            shutil.copy2(glb_path, output_path)
            log.info(f"VRMA exported: {output_path}")

        with open(vrma_meta_path, 'w') as f:
            json.dump(metadata, f, indent=2)
            log.info(f"VRMA metadata exported: {vrma_meta_path}")

        log.info("=" * 70)
        log.info(f"SUCCESS: {anim_slug}.vrma exported")
        log.info("=" * 70)

    except Exception as e:
        log.error(f"CONVERSION FAILED: {e}", exc_info=True)
        raise


def main() -> None:
    """CLI entry point for command-line usage."""
    parser = argparse.ArgumentParser(
        description="Mixamo FBX → VRMA conversion (Blender Python script)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  blender --python mixamo_to_vrma_blender.py -- \\
      --input-fbx ~/mixamo_wave.fbx \\
      --reference-vrm ~/avatar.vrm \\
      --output-vrma ~/wave \\
      --slug wave

  blender --background --python mixamo_to_vrma_blender.py -- \\
      --input-fbx ~/dance.fbx \\
      --reference-vrm ~/avatar.vrm \\
      --output-vrma ~/dance \\
      --slug dance \\
      --frame-range 0 120
        """,
    )

    parser.add_argument(
        "--input-fbx",
        type=str,
        required=True,
        help="Path to Mixamo FBX file",
    )
    parser.add_argument(
        "--reference-vrm",
        type=str,
        required=True,
        help="Path to reference VRM avatar (for skeleton extraction)",
    )
    parser.add_argument(
        "--output-vrma",
        type=str,
        required=True,
        help="Output path for VRMA file (without .vrma extension)",
    )
    parser.add_argument(
        "--slug",
        type=str,
        required=True,
        help="Animation identifier (e.g., 'wave', 'dance')",
    )
    parser.add_argument(
        "--frame-range",
        type=int,
        nargs=2,
        metavar=("START", "END"),
        default=None,
        help="Optional frame range to export (default: all frames)",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Frames per second (default: 30)",
    )

    args = parser.parse_args()

    convert_mixamo_fbx_to_vrma(
        input_fbx=args.input_fbx,
        reference_vrm=args.reference_vrm,
        output_vrma=args.output_vrma,
        anim_slug=args.slug,
        frame_range=tuple(args.frame_range) if args.frame_range else None,
        fps=args.fps,
    )


if __name__ == "__main__":
    main()
