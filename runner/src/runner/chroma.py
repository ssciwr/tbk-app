from __future__ import annotations

from collections.abc import Generator
import base64
import io
import json
import logging
from pathlib import Path
import random
import urllib.error
import urllib.request
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
    from openai import OpenAI
    from rembg import new_session, remove
except ImportError as exc:
    torch = None  # type: ignore[assignment]
    AutoPipelineForImage2Image = None  # type: ignore[assignment]
    ChromaImg2ImgPipeline = None  # type: ignore[assignment]
    ChromaTransformer2DModel = None  # type: ignore[assignment]
    OpenAI = None  # type: ignore[assignment]
    new_session = None  # type: ignore[assignment]
    remove = None  # type: ignore[assignment]
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
MONOCHROME_BACKGROUND_PATH = "monochrome_background.png"

# VLM analysis
VLM_PROMPT_INSTRUCTION = """You are a visual analysis and prompt-engineering specialist. You are shown a single, clear, frontal image of a plush toy animal. Your goal is to:
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
VLM_TEMPERATURE = 0.3
VLM_TIMEOUT_SECONDS = 120.0

# Generation model
TRANSFORMER_PATH = "chroma-unlocked-v44-detail-calibrated.safetensors"
LORA_PATH = "Hyper-Chroma-Turbo-Alpha-16steps-lora.safetensors"
LORA_SCALE = 0.49
DTYPE = "auto"
NUM_INFERENCE_STEPS = 25
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


def _require_chroma_dependencies() -> None:
    if _CHROMA_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Chroma workflow dependencies are missing. Install them with "
            "`pip install -r runner/requirements-chroma.txt`. "
            f"Original import error: {_CHROMA_IMPORT_ERROR}"
        ) from _CHROMA_IMPORT_ERROR


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


def remove_background_first_pass(image: Image.Image, session: Any) -> Image.Image:
    _require_chroma_dependencies()
    assert remove is not None

    output = remove(
        image,
        session=session,
        alpha_matting=True,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=10,
        only_mask=False,
        post_process_mask=False,
        bgcolor=(0, 0, 0, 255),
    )
    if isinstance(output, Image.Image):
        return output.convert("RGB")
    return Image.open(io.BytesIO(output)).convert("RGB")


def remove_background_second_pass(image: Image.Image, session: Any) -> Image.Image:
    _require_chroma_dependencies()
    assert remove is not None

    output = remove(
        image,
        session=session,
        alpha_matting=False,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=10,
        only_mask=False,
        post_process_mask=False,
    )
    if isinstance(output, Image.Image):
        return output.convert("RGBA")
    return Image.open(io.BytesIO(output)).convert("RGBA")


def add_monochrome_background(image: Image.Image) -> Image.Image:
    background_path = _resolve_workflow_file(
        MONOCHROME_BACKGROUND_PATH,
        description="monochrome background",
    )
    background = Image.open(background_path).convert("RGB")
    if background.size != image.size:
        background = background.resize(image.size, Image.Resampling.NEAREST)
    return Image.alpha_composite(
        background.convert("RGBA"),
        image.convert("RGBA"),
    ).convert("RGB")


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


def image_to_data_url(image: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    mime = "image/png" if fmt.upper() == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


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


def normalize_vlm_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("Empty VLM server URL.")
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def generate_prompt_with_openai_compatible(
    image: Image.Image,
    instruction: str,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float,
    timeout: float,
) -> str:
    if not model.strip():
        raise ValueError("Missing VLM model name.")

    normalized_base_url = normalize_vlm_base_url(base_url)
    image_data_url = image_to_data_url(image, fmt="PNG")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ],
        "temperature": temperature,
    }

    if api_key.strip():
        _require_chroma_dependencies()
        assert OpenAI is not None

        client = OpenAI(
            base_url=normalized_base_url,
            api_key=api_key.strip(),
            timeout=timeout,
        )
        try:
            resp = client.chat.completions.create(
                model=payload["model"],
                messages=payload["messages"],
                temperature=payload["temperature"],
            )
        except Exception as e:
            raise RuntimeError(
                "Authenticated VLM request failed during chat.completions.create "
                f"(base_url={normalized_base_url!r}, model={model!r})."
            ) from e
    else:
        endpoint = f"{normalized_base_url}/chat/completions"
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                "Unauthenticated VLM request failed with HTTP error "
                f"{e.code} at {endpoint!r} (model={model!r}). Body: {error_body}"
            ) from e
        except Exception as e:
            raise RuntimeError(
                "Unauthenticated VLM request failed "
                f"(endpoint={endpoint!r}, model={model!r})."
            ) from e

        try:
            resp = json.loads(body)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"VLM response was not valid JSON from endpoint {endpoint!r}. Response: {body[:500]}"
            ) from e

    prompt = extract_text_from_chat_completion(resp)
    if not prompt:
        raise RuntimeError("VLM returned empty prompt text in response.")
    return prompt


class ChromaWorkflow(WorkflowBase, name="chroma"):
    def __init__(self) -> None:
        self.vlm_server = ""
        self.vlm_server_key = ""
        self.vlm_model_name = ""

        self._device: str | None = None
        self._dtype: Any = None
        self._torch: Any = None
        self._first_pass_session: Any = None
        self._second_pass_session: Any = None
        self._pipe: Any = None
        self._sdxl_pipe: Any = None

    def configure(self, **kwargs: Any) -> None:
        vlm_server = kwargs.get("vlm_server")
        if isinstance(vlm_server, str):
            self.vlm_server = vlm_server

        vlm_server_key = kwargs.get("vlm_server_key")
        if isinstance(vlm_server_key, str):
            self.vlm_server_key = vlm_server_key

        vlm_model_name = kwargs.get("vlm_model_name")
        if isinstance(vlm_model_name, str):
            self.vlm_model_name = vlm_model_name

    def setup(self) -> None:
        _require_chroma_dependencies()
        assert torch is not None
        assert new_session is not None
        if not self.vlm_server.strip():
            raise RuntimeError("Chroma workflow requires --vlm-server to be set.")
        if not self.vlm_model_name.strip():
            raise RuntimeError("Chroma workflow requires --vlm-model-name to be set.")

        device, dtype = pick_device_dtype("auto", DTYPE)
        logging.info(
            "Loading chroma workflow models (device=%s, dtype=%s).",
            device,
            dtype,
        )

        self._torch = torch
        self._device = device
        self._dtype = dtype
        self._first_pass_session = new_session(model_name="u2net")
        self._second_pass_session = new_session(model_name="isnet-general-use")
        self._pipe = load_pipeline(dtype=dtype)
        self._pipe.to(device)
        self._sdxl_pipe = load_sdxl_style_pipeline(dtype=dtype, device=device)

    def _assert_ready(self) -> None:
        if (
            self._torch is None
            or self._device is None
            or self._pipe is None
            or self._sdxl_pipe is None
            or self._first_pass_session is None
            or self._second_pass_session is None
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
    ) -> Generator[Image.Image, None, None]:
        del parameters
        self._assert_ready()
        assert self._pipe is not None
        assert self._sdxl_pipe is not None
        assert self._first_pass_session is not None
        assert self._second_pass_session is not None

        resized_input = img.convert("RGB").resize(
            (IMAGE_WIDTH, IMAGE_HEIGHT),
            Image.Resampling.NEAREST,
        )
        first_rembg_image = remove_background_first_pass(
            resized_input,
            session=self._first_pass_session,
        )
        second_rembg_image = remove_background_second_pass(
            first_rembg_image,
            session=self._second_pass_session,
        )

        normalized_vlm_server = normalize_vlm_base_url(self.vlm_server)
        key_state = (
            "provided" if self.vlm_server_key.strip() else "omitted (no auth header)"
        )
        logging.info(
            "Generating chroma prompt via VLM " "(base_url=%s, model=%s, api_key=%s).",
            normalized_vlm_server,
            self.vlm_model_name,
            key_state,
        )

        final_prompt = generate_prompt_with_openai_compatible(
            image=first_rembg_image,
            instruction=VLM_PROMPT_INSTRUCTION,
            base_url=normalized_vlm_server,
            api_key=self.vlm_server_key,
            model=self.vlm_model_name,
            temperature=VLM_TEMPERATURE,
            timeout=VLM_TIMEOUT_SECONDS,
        )
        logging.info("VLM prompt generation completed.")
        logging.debug("VLM generated prompt: %s", final_prompt)

        init_image = add_monochrome_background(second_rembg_image)
        for _ in range(max(num_images, 0)):
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

            sdxl_result = self._sdxl_pipe(
                prompt=SDXL_PROMPT,
                image=generated,
                strength=SDXL_STRENGTH,
                guidance_scale=SDXL_GUIDANCE_SCALE,
                num_inference_steps=SDXL_NUM_INFERENCE_STEPS,
                generator=generator,
            ).images[0]
            yield sdxl_result
