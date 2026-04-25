# Mixamo → VRMA ETL Pipeline

**Quick start** for converting Mixamo animations to VRMA format.

## Files

- `mixamo_to_vrma_blender.py` — Main conversion script (run inside Blender)
- `convert_batch.sh` — Batch converter wrapper (orchestrates multiple files)
- `bone_mapping.py` — Mixamo → VRM skeleton mapping (WIP: extracted from main script)

## Usage

### Single animation conversion

```bash
blender --background --python mixamo_to_vrma_blender.py -- \
    --input-fbx ~/wave.fbx \
    --reference-vrm ~/avatar.vrm \
    --output-vrma ~/wave \
    --slug wave
```

### Batch conversion

```bash
./convert_batch.sh \
    ~/mixamo_exports \
    ~/vrm_reference \
    ../../frontend/public/assets/vrma
```

## Full documentation

See `../../docs/MIXAMO_VRMA_BANK.md` for complete workflow, requirements, and troubleshooting.
