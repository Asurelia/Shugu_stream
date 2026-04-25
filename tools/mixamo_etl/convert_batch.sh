#!/bin/bash
# Batch converter: Mixamo FBX → VRMA for Shugu animation bank
#
# Usage:
#   ./convert_batch.sh
#   OR with custom directories:
#   ./convert_batch.sh ~/mixamo_exports ~/vrm_refs output_dir

set -e

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Default directories
MIXAMO_INPUT_DIR="${1:-.}/mixamo_fbx_exports"
VRM_REFERENCE_DIR="${2:-.}/vrm_references"
OUTPUT_DIR="${3:-.}/frontend/public/assets/vrma"

# Animation list: (slug:fbx_filename)
ANIMATIONS=(
    # Idle (P0-P2)
    "idle_loop:Idle.fbx"
    "idle_breathing:Breathing_Idle.fbx"
    "idle_lookaround:Look_Around.fbx"
    "idle_stretch:Stretch.fbx"
    "idle_yawn:Yawn.fbx"

    # Greetings (P0-P2)
    "wave:Wave.fbx"
    "wave_excited:Excited_Wave.fbx"
    "bow:Bow.fbx"
    "salute:Salute.fbx"
    "peace_sign:Peace_Sign.fbx"

    # Reactions (P0-P2)
    "thumbs_up:Thumbs_Up.fbx"
    "clap:Clap.fbx"
    "cheer:Cheer.fbx"
    "fist_pump:Fist_Pump.fbx"
    "surprised_jump:Surprised.fbx"

    # Emotes (P0-P2)
    "dance:Dance.fbx"
    "dance_silly:Silly_Dance.fbx"
    "shy_giggle:Giggle.fbx"
    "shy_hide:Embarrassed.fbx"
    "thinking:Thinking.fbx"

    # Talk Gestures (P1-P2)
    "talk_explain:Talking.fbx"
    "talk_emphasize:Emphasizing.fbx"
    "nod:Nod.fbx"
    "headshake:Head_Shake.fbx"
    "shrug:Shrug.fbx"

    # Daily Life (P1-P2)
    "read_book:Reading.fbx"
    "sip_drink:Drinking.fbx"
    "doodle:Drawing.fbx"
    "type_keyboard:Typing.fbx"
    "stretch_long:Stretching.fbx"
)

# ============================================================================
# Functions
# ============================================================================

log_info() {
    echo "[INFO] $*"
}

log_error() {
    echo "[ERROR] $*" >&2
}

log_success() {
    echo "[SUCCESS] ✓ $*"
}

usage() {
    cat <<EOF
Usage: $0 [MIXAMO_DIR] [VRM_REF_DIR] [OUTPUT_DIR]

Convert Mixamo FBX animations to VRMA (VRM Animation) format.

Arguments:
  MIXAMO_DIR     Directory containing Mixamo FBX files (default: ./mixamo_fbx_exports)
  VRM_REF_DIR    Directory containing reference VRM avatar (default: ./vrm_references)
  OUTPUT_DIR     Output directory for VRMA files (default: ./frontend/public/assets/vrma)

Example:
  $0 ~/downloads/mixamo ~/vrm avatar_refs ./out
  $0  # Use defaults

Environment:
  BLENDER_CMD    Path to blender executable (default: blender)
  DRY_RUN        If set, print commands without executing

EOF
    exit 1
}

find_reference_vrm() {
    local vrm_dir="$1"
    local vrm_files

    if [[ ! -d "$vrm_dir" ]]; then
        log_error "VRM reference directory not found: $vrm_dir"
        return 1
    fi

    vrm_files=($(find "$vrm_dir" -maxdepth 1 -name "*.vrm" -type f))

    if [[ ${#vrm_files[@]} -eq 0 ]]; then
        log_error "No .vrm files found in $vrm_dir"
        return 1
    fi

    # Return first VRM found
    echo "${vrm_files[0]}"
}

# ============================================================================
# Main
# ============================================================================

main() {
    BLENDER_CMD="${BLENDER_CMD:-blender}"

    log_info "Mixamo → VRMA Batch Converter"
    log_info "======================================"
    log_info "Input directory:  $MIXAMO_INPUT_DIR"
    log_info "VRM reference:    $VRM_REFERENCE_DIR"
    log_info "Output directory: $OUTPUT_DIR"
    log_info "Blender command:  $BLENDER_CMD"
    log_info ""

    # Validate setup
    if ! command -v "$BLENDER_CMD" &>/dev/null; then
        log_error "Blender not found: $BLENDER_CMD"
        log_error "Install Blender or set BLENDER_CMD environment variable"
        exit 1
    fi

    if [[ ! -d "$MIXAMO_INPUT_DIR" ]]; then
        log_error "Mixamo input directory not found: $MIXAMO_INPUT_DIR"
        exit 1
    fi

    # Find reference VRM
    VRM_REF=$(find_reference_vrm "$VRM_REFERENCE_DIR") || exit 1
    log_info "Using reference VRM: $VRM_REF"

    # Create output directory
    mkdir -p "$OUTPUT_DIR"

    # Convert animations
    total=${#ANIMATIONS[@]}
    success=0
    failed=0
    skipped=0

    for (( i = 0; i < total; i++ )); do
        IFS=':' read -r slug fbx_file <<< "${ANIMATIONS[$i]}"
        fbx_path="$MIXAMO_INPUT_DIR/$fbx_file"

        frame_num=$((i + 1))
        echo ""
        log_info "[$frame_num/$total] Converting: $slug"

        # Skip if FBX not found
        if [[ ! -f "$fbx_path" ]]; then
            log_error "  FBX not found: $fbx_path"
            ((skipped++))
            continue
        fi

        # Skip if VRMA already exists (unless force)
        output_vrma="$OUTPUT_DIR/$slug.vrma"
        if [[ -f "$output_vrma" && -z "$FORCE_CONVERT" ]]; then
            log_info "  Skipping (already exists): $output_vrma"
            ((skipped++))
            continue
        fi

        # Run Blender conversion
        cmd="$BLENDER_CMD --background --python $SCRIPT_DIR/mixamo_to_vrma_blender.py -- \
            --input-fbx '$fbx_path' \
            --reference-vrm '$VRM_REF' \
            --output-vrma '$OUTPUT_DIR/$slug' \
            --slug '$slug'"

        if [[ -n "$DRY_RUN" ]]; then
            log_info "  [DRY RUN] $cmd"
            ((success++))
        else
            if eval "$cmd" 2>&1; then
                log_success "  $slug.vrma"
                ((success++))
            else
                log_error "  Failed to convert $slug"
                ((failed++))
            fi
        fi
    done

    # Summary
    echo ""
    echo "======================================"
    log_info "Conversion complete!"
    log_info "  Success: $success/$total"
    log_info "  Skipped: $skipped/$total"
    if [[ $failed -gt 0 ]]; then
        log_info "  Failed:  $failed/$total"
        exit 1
    fi
    log_success "All animations converted!"
}

# ============================================================================
# Entry point
# ============================================================================

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    usage
fi

main
