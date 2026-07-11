# Runner Asset Files

This directory is the default lookup location for bare filenames used by the Chroma workflow code.

## Expected files

1. `chroma-unlocked-v44-detail-calibrated.safetensors`
   - Chroma transformer checkpoint loaded via `from_single_file(...)`.
   - Referenced in `runner/src/runner/chroma.py`.
2. `Hyper-Chroma-Turbo-Alpha-16steps-lora.safetensors`
   - Chroma LoRA weights.
   - Referenced in `runner/src/runner/chroma.py`.
3. `your_sdxl_lora.safetensors`
   - SDXL style LoRA weights (default filename).
   - Referenced in `runner/src/runner/chroma.py`.
