from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
import io
import logging
from pathlib import Path
import random
from typing import Any

from PIL import Image

from .core import WorkflowBase

try:
    import torch
    from diffusers import (
        AutoPipelineForImage2Image,
        ChromaImg2ImgPipeline,
        ChromaTransformer2DModel,
    )
    from mistralai.client import Mistral
except ImportError as exc:
    torch = None  # type: ignore[assignment]
    AutoPipelineForImage2Image = None  # type: ignore[assignment]
    ChromaImg2ImgPipeline = None  # type: ignore[assignment]
    ChromaTransformer2DModel = None  # type: ignore[assignment]
    Mistral = None  # type: ignore[assignment]
    _CHROMA_IMPORT_ERROR: ImportError | None = exc
else:
    _CHROMA_IMPORT_ERROR = None

#
# Module level parameters of the workflow. You might want to occasionally work on these, but it
# is not worth to make them configurable via frontend or CLI.
#

# General input handling
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 1024

# VLM analysis
VLM_PROMPT_INSTRUCTION_BASE = """You are a visual analysis and prompt-engineering specialist. You are shown a single, clear, frontal image of a plush toy animal. Your goal is to:
Analyze the image carefully and describe the plush animal's external anatomical features in exhaustive detail, including:
The type of animal it represents (e.g., monkey, bear, rabbit).
The posture and orientation (e.g., sitting, standing, crouching, head facing forward or tilted).
Proportions of the limbs (length of arms vs. legs, relative size of hands and feet).
Size and positioning of ears, eyes, nose, mouth, and tail (if visible).
Any notable stylized features (e.g., exaggerated hands, large eyes, round head, oversized feet). Do not mention colors of the original image.
Based solely on this image description, construct a FLUX prompt for generating a realistic, medically plausible X-ray image of the plush animal as if it had a biological internal structure.
The FLUX prompt must meet the following criteria:
Accurately reflect the external anatomy, proportions, and posture of the plush animal.
Depict a detailed, friendly skeletal system corresponding to the animal's body shape and pose. The bones should appear realistic but adapted to the exaggerated or cartoonish proportions of the plush.
Limbs, hands, feet, ears, and tail (if present) must have anatomically plausible bone structures, adjusted to match the stylized features seen in the image.
Include only bones and soft-tissue glow; no internal organs or disturbing anatomical details.
Soft-tissue glow should create a gentle, non-creepy X-ray effect, emphasizing bone contrast while allowing for a subtle outline of the body and limbs.
Present the X-ray in a clean, clinical radiographic style with a neutral or black background, without any horror elements or unsettling features.
Your output must be only the final FLUX prompt, written in natural language, descriptive, precise, and fully self-contained.
Example output structure (you must replace placeholders with accurate descriptions from the image):
A realistic medical-style X-ray image of a [detailed animal type and description], with its [head facing direction], [pose], [detailed limb proportions], and [specific features like ear size, hand shape, tail presence]. The X-ray reveals a biologically plausible skeletal structure matching its proportions, with elongated bones in the [arms/legs], defined phalanges in [hands/feet], a simplified ribcage, vertebral column following the posture, and structural support in the [ears/tail if applicable]. The soft tissue appears as a gentle, semi-transparent glow outlining the body and limbs. The image is set on a clean, black radiographic background, realistic and educational in style, without any creepy or unsettling features."""
VLM_MODEL_NAME = "ministral-14b-latest"
VLM_FILE_PURPOSE = "ocr"
VLM_TEMPERATURE = 0.3
VLM_MAX_TOKENS = 5000

# Generation model
TRANSFORMER_PATH = "chroma-unlocked-v44-detail-calibrated.safetensors"
LORA_PATH = "Hyper-Chroma-Turbo-Alpha-16steps-lora.safetensors"
LORA_SCALE = 0.49
DTYPE = "auto"
NUM_INFERENCE_STEPS = 15
GUIDANCE_SCALE = 4.0
IMG2IMG_DENOISE_STRENGTH = 0.8
NEGATIVE_PROMPT = "illustration, anime, drawing, artwork, bad hands, blurry, low quality, out of focus, deformed, smudged, red"

# SDXL X-Ray Style Rewrite
SDXL_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
SDXL_LORA_PATH = "DD-xray-v1.safetensors"
SDXL_LORA_SCALE = 0.8
SDXL_STRENGTH = 0.4
SDXL_GUIDANCE_SCALE = 5.0
SDXL_NUM_INFERENCE_STEPS = 15
SDXL_PROMPT = "xray"
DEBUG_OUTPUT_DIR_NAME = "debug-output"


def _require_chroma_dependencies() -> None:
    if _CHROMA_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Chroma workflow dependencies are missing. Install them with "
            "`pip install -r runner/requirements-chroma.txt`. "
            f"Original import error: {_CHROMA_IMPORT_ERROR}"
        ) from _CHROMA_IMPORT_ERROR


def _normalize_animal_type_hint(raw_hint: Any) -> str:
    if not isinstance(raw_hint, str):
        return ""
    return " ".join(raw_hint.strip().split())


def build_vlm_prompt_instruction(*, animal_type_hint: str) -> str:
    cleaned_hint = _normalize_animal_type_hint(animal_type_hint)
    if cleaned_hint:
        hint_guidance = (
            f'User-provided animal type hint: "{cleaned_hint}".\n'
            "Use this as the animal type anchor when constructing the final prompt, "
            "while still matching all visible anatomy and pose details in the image."
        )
    else:
        hint_guidance = (
            "User-provided animal type hint: (none).\n"
            "Infer the animal type directly from the image."
        )
    return (
        f"{VLM_PROMPT_INSTRUCTION_BASE}\n\n" "Additional guidance:\n" f"{hint_guidance}"
    )


def _serialize_image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _candidate_asset_dirs() -> list[Path]:
    candidates = [
        (Path(__file__).resolve().parents[2] / "assets").resolve(),
        (Path.cwd() / "runner" / "assets").resolve(),
        (Path.cwd() / "assets").resolve(),
    ]
    unique: list[Path] = []
    for path in candidates:
        if path not in unique:
            unique.append(path)
    return unique


def _resolve_workflow_file(
    raw_value: str,
    *,
    description: str,
) -> str:
    normalized = raw_value.strip()
    if not normalized:
        raise ValueError(f"Missing {description} file reference.")

    if normalized.startswith(("http://", "https://")):
        return normalized

    path_value = Path(normalized).expanduser()
    has_path_hint = (
        path_value.is_absolute()
        or normalized.startswith(".")
        or "/" in normalized
        or "\\" in normalized
    )

    if has_path_hint:
        resolved = (
            path_value.resolve()
            if path_value.is_absolute()
            else (Path.cwd() / path_value).resolve()
        )
        if not resolved.exists():
            raise FileNotFoundError(f"Missing {description} file at '{resolved}'.")
        return str(resolved)

    search_paths = [
        (assets_dir / path_value).resolve() for assets_dir in _candidate_asset_dirs()
    ]
    for candidate in search_paths:
        if candidate.exists():
            return str(candidate)

    searched = ", ".join(str(path) for path in search_paths)
    raise FileNotFoundError(
        f"Missing {description} file '{normalized}'. Looked in: {searched}. "
        "Place bare filenames in ./runner/assets."
    )


def pick_device_dtype(device_arg: str, dtype_arg: str) -> tuple[str, Any]:
    _require_chroma_dependencies()
    assert torch is not None

    if device_arg == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
    else:
        device = device_arg

    if dtype_arg == "fp16":
        dtype = torch.float16
    elif dtype_arg == "bf16":
        dtype = torch.bfloat16
    elif dtype_arg == "fp32":
        dtype = torch.float32
    else:
        if device == "cuda":
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        elif device == "mps":
            dtype = torch.float16
        else:
            dtype = torch.float32
    return device, dtype


def load_pipeline(dtype: Any) -> Any:
    _require_chroma_dependencies()
    assert ChromaTransformer2DModel is not None
    assert ChromaImg2ImgPipeline is not None

    transformer_path = _resolve_workflow_file(
        TRANSFORMER_PATH,
        description="chroma transformer",
    )
    lora_reference = _resolve_workflow_file(
        LORA_PATH,
        description="chroma LoRA",
    )
    transformer = ChromaTransformer2DModel.from_single_file(
        transformer_path,
        torch_dtype=dtype,
    )
    pipe = ChromaImg2ImgPipeline.from_pretrained(
        "lodestones/Chroma",
        torch_dtype=dtype,
        transformer=transformer,
    )
    lora_path = Path(lora_reference)
    if lora_path.is_file():
        pipe.load_lora_weights(str(lora_path.parent), weight_name=lora_path.name)
    else:
        pipe.load_lora_weights(lora_reference)
    pipe.fuse_lora(lora_scale=LORA_SCALE)
    return pipe


def load_sdxl_style_pipeline(dtype: Any, device: str) -> Any:
    _require_chroma_dependencies()
    assert AutoPipelineForImage2Image is not None

    pipe = AutoPipelineForImage2Image.from_pretrained(
        SDXL_MODEL_ID,
        torch_dtype=dtype,
    )

    sdxl_lora_reference = _resolve_workflow_file(
        SDXL_LORA_PATH,
        description="SDXL LoRA",
    )
    lora_path = Path(sdxl_lora_reference)
    if lora_path.is_file():
        pipe.load_lora_weights(str(lora_path.parent), weight_name=lora_path.name)
    else:
        pipe.load_lora_weights(sdxl_lora_reference)

    pipe.fuse_lora(lora_scale=SDXL_LORA_SCALE)
    pipe.to(device)
    return pipe


def extract_text_from_chat_completion(resp: Any) -> str:
    if isinstance(resp, dict):
        choices = resp.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "")
    else:
        if not getattr(resp, "choices", None):
            return ""
        message = resp.choices[0].message
        content = getattr(message, "content", "")

    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(item.get("text", ""))
            elif hasattr(item, "text"):
                chunks.append(str(item.text))
        return "".join(chunks).strip()
    return str(content).strip()


def _create_debug_output_dir() -> Path:
    root = (Path.cwd() / DEBUG_OUTPUT_DIR_NAME).resolve()
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    debug_dir = root / timestamp
    debug_dir.mkdir(parents=False, exist_ok=False)
    return debug_dir


def _write_debug_prompt(debug_dir: Path | None, prompt: str) -> None:
    if debug_dir is None:
        return
    (debug_dir / "vlm_prompt.txt").write_text(prompt, encoding="utf-8")


def _write_debug_image(
    debug_dir: Path | None,
    filename: str,
    image: Image.Image,
) -> None:
    if debug_dir is None:
        return
    image.save(debug_dir / filename, format="PNG")


def generate_prompt_with_mistral(
    image: Image.Image,
    instruction: str,
    api_key: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    cleaned_api_key = api_key.strip()
    if not cleaned_api_key:
        raise ValueError("Missing Mistral API key.")
    if not model.strip():
        raise ValueError("Missing VLM model name.")

    _require_chroma_dependencies()
    assert Mistral is not None

    client = Mistral(api_key=cleaned_api_key)
    image_bytes = _serialize_image_to_png_bytes(image)
    uploaded_file_id: str | None = None
    stage = "uploading image"

    try:
        uploaded_file = client.files.upload(
            file={
                "file_name": "vlm_input.png",
                "content": image_bytes,
            },
            purpose=VLM_FILE_PURPOSE,
        )
        uploaded_file_id = str(uploaded_file.id)

        stage = "creating a signed file URL"
        signed_url = client.files.get_signed_url(file_id=uploaded_file_id)

        stage = "requesting chat completion"
        resp = client.chat.complete(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {"type": "image_url", "image_url": signed_url.url},
                    ],
                }
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Mistral VLM request failed while {stage} (model={model!r})."
        ) from exc
    finally:
        if uploaded_file_id is not None:
            try:
                client.files.delete(file_id=uploaded_file_id)
            except Exception:
                logging.warning(
                    "Failed to delete uploaded Mistral file %s after VLM request.",
                    uploaded_file_id,
                    exc_info=True,
                )

    prompt = extract_text_from_chat_completion(resp)
    if not prompt:
        raise RuntimeError("Mistral VLM returned empty prompt text in response.")
    return prompt


class ChromaWorkflow(WorkflowBase, name="chroma"):
    def __init__(self) -> None:
        self.mistral_api_key = ""

        self._device: str | None = None
        self._dtype: Any = None
        self._torch: Any = None
        self._pipe: Any = None
        self._sdxl_pipe: Any = None

    def configure(self, **kwargs: Any) -> None:
        mistral_api_key = kwargs.get("mistral_api_key")
        if isinstance(mistral_api_key, str):
            self.mistral_api_key = mistral_api_key

    def setup(self) -> None:
        _require_chroma_dependencies()
        assert torch is not None
        if not self.mistral_api_key.strip():
            raise RuntimeError("Chroma workflow requires --mistral-api-key to be set.")

        device, dtype = pick_device_dtype("auto", DTYPE)
        logging.info(
            "Loading chroma workflow models (device=%s, dtype=%s).",
            device,
            dtype,
        )

        self._torch = torch
        self._device = device
        self._dtype = dtype
        self._pipe = load_pipeline(dtype=dtype)
        self._pipe.to(device)
        self._sdxl_pipe = load_sdxl_style_pipeline(dtype=dtype, device=device)

    def _assert_ready(self) -> None:
        if (
            self._torch is None
            or self._device is None
            or self._pipe is None
            or self._sdxl_pipe is None
        ):
            raise RuntimeError(
                "Chroma workflow is not initialized. setup() must be called first."
            )

    def _new_generator(self) -> Any:
        self._assert_ready()
        assert self._torch is not None
        assert self._device is not None
        generator_device = "cuda" if self._device == "cuda" else "cpu"
        seed = random.randint(1, 2**64 - 1)
        return self._torch.Generator(device=generator_device).manual_seed(seed)

    def generate(
        self,
        img: Image.Image,
        parameters: dict[str, Any] | None = None,
        num_images: int = 1,
        debug: bool = False,
    ) -> Generator[Image.Image, None, None]:
        self._assert_ready()
        assert self._pipe is not None
        assert self._sdxl_pipe is not None
        workflow_parameters = parameters or {}
        animal_type_hint = _normalize_animal_type_hint(
            workflow_parameters.get("animal_type")
        )

        debug_dir: Path | None = None
        if debug:
            debug_dir = _create_debug_output_dir()
            print(f"Debug output directory: {debug_dir}", flush=True)

        resized_input = img.convert("RGB").resize(
            (IMAGE_WIDTH, IMAGE_HEIGHT),
            Image.Resampling.NEAREST,
        )
        _write_debug_image(debug_dir, "01_resized_input.png", resized_input)

        key_state = "provided" if self.mistral_api_key.strip() else "omitted"
        logging.info(
            "Generating chroma prompt via Mistral VLM (model=%s, api_key=%s).",
            VLM_MODEL_NAME,
            key_state,
        )
        prompt_instruction = build_vlm_prompt_instruction(
            animal_type_hint=animal_type_hint
        )

        final_prompt = generate_prompt_with_mistral(
            image=resized_input,
            instruction=prompt_instruction,
            api_key=self.mistral_api_key,
            model=VLM_MODEL_NAME,
            temperature=VLM_TEMPERATURE,
            max_tokens=VLM_MAX_TOKENS,
        )
        logging.info("VLM prompt generation completed.")
        logging.debug("VLM generated prompt: %s", final_prompt)
        _write_debug_prompt(debug_dir, final_prompt)

        init_image = resized_input
        for index in range(max(num_images, 0)):
            generator = self._new_generator()
            generated = self._pipe(
                prompt=final_prompt,
                negative_prompt=NEGATIVE_PROMPT,
                image=init_image,
                width=IMAGE_WIDTH,
                height=IMAGE_HEIGHT,
                num_inference_steps=NUM_INFERENCE_STEPS,
                guidance_scale=GUIDANCE_SCALE,
                strength=IMG2IMG_DENOISE_STRENGTH,
                generator=generator,
            ).images[0]
            _write_debug_image(
                debug_dir,
                f"02_chroma_generated_{index + 1:02d}.png",
                generated,
            )

            sdxl_result = self._sdxl_pipe(
                prompt=SDXL_PROMPT,
                image=generated,
                strength=SDXL_STRENGTH,
                guidance_scale=SDXL_GUIDANCE_SCALE,
                num_inference_steps=SDXL_NUM_INFERENCE_STEPS,
                generator=generator,
            ).images[0]
            _write_debug_image(
                debug_dir,
                f"03_sdxl_rewrite_{index + 1:02d}.png",
                sdxl_result,
            )
            final_image = sdxl_result.convert("L").convert("RGB")
            _write_debug_image(
                debug_dir,
                f"04_final_output_{index + 1:02d}.png",
                final_image,
            )
            yield final_image
