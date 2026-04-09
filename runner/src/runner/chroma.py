from __future__ import annotations

from collections.abc import Generator
import base64
import contextlib
from datetime import datetime
import io
import json
import logging
import multiprocessing
from pathlib import Path
import queue
import random
import re
import sys
import time
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
VLM_TEMPERATURE = 0.3
VLM_TIMEOUT_SECONDS = 120.0

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
FIRST_PASS_ALPHA_TIMEOUT_SECONDS = 120.0
FIRST_PASS_WATCHDOG_POLL_SECONDS = 0.2
FIRST_PASS_SUBPROCESS_START_METHOD = "spawn"
INCOMPLETE_CHOLESKY_WARNING_PATTERN = re.compile(
    r"(?ms)PERFORMANCE WARNING:\s*"
    r"Thresholded incomplete Cholesky decomposition failed due to insufficient positive-definiteness of matrix A with parameters:\s*"
    r"discard_threshold\s*=\s*[0-9.eE+-]+\s*"
    r"shift\s*=\s*[0-9.eE+-]+\s*"
    r"Try decreasing discard_threshold or start with a larger shift\s*"
)
INCOMPLETE_CHOLESKY_WARNING_TOKEN = (
    "thresholded incomplete cholesky decomposition failed due to insufficient "
    "positive-definiteness of matrix a"
)


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


def _strip_incomplete_cholesky_warning(message: str) -> str:
    return INCOMPLETE_CHOLESKY_WARNING_PATTERN.sub("", message)


def _emit_captured_streams(stdout_text: str, stderr_text: str) -> None:
    if stdout_text:
        print(stdout_text, end="")
    if stderr_text:
        print(stderr_text, end="", file=sys.stderr)


class _QueueTextStream(io.TextIOBase):
    def __init__(self, result_queue: Any, stream_name: str) -> None:
        self._result_queue = result_queue
        self._stream_name = stream_name

    def write(self, text: str) -> int:
        if text:
            self._result_queue.put(("stream", self._stream_name, text))
        return len(text)

    def flush(self) -> None:
        return


def _run_first_pass_remove(
    image: Image.Image,
    *,
    session: Any,
    alpha_matting: bool,
    bgcolor: tuple[int, int, int, int] | None = None,
) -> Image.Image | bytes:
    _require_chroma_dependencies()
    assert remove is not None

    return remove(
        image,
        session=session,
        alpha_matting=alpha_matting,
        alpha_matting_foreground_threshold=240,
        alpha_matting_background_threshold=10,
        alpha_matting_erode_size=10,
        only_mask=False,
        post_process_mask=False,
        bgcolor=bgcolor,
    )


def _new_first_pass_session(*, cpu_only: bool) -> Any:
    _require_chroma_dependencies()
    assert new_session is not None
    if not cpu_only:
        return new_session(model_name="u2net")

    try:
        return new_session(
            model_name="u2net",
            providers=["CPUExecutionProvider"],
        )
    except TypeError:
        # Older rembg builds may not expose a providers argument.
        return new_session(model_name="u2net")


def _serialize_image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _remove_first_pass_subprocess_worker(
    image_bytes: bytes,
    result_queue: Any,
) -> None:
    try:
        with Image.open(io.BytesIO(image_bytes)) as source_image:
            image = source_image.convert("RGB")

        # Build a fresh CPU-only session inside the subprocess to avoid
        # CUDA/ORT initialization issues in spawned workers.
        active_session = _new_first_pass_session(cpu_only=True)

        with contextlib.redirect_stdout(
            _QueueTextStream(result_queue, "stdout")
        ), contextlib.redirect_stderr(_QueueTextStream(result_queue, "stderr")):
            output = _run_first_pass_remove(
                image,
                session=active_session,
                alpha_matting=True,
                bgcolor=None,
            )

        if isinstance(output, Image.Image):
            payload = _serialize_image_to_png_bytes(output)
        else:
            payload = output
        result_queue.put(("result", payload))
    except Exception as exc:
        result_queue.put(("error", repr(exc)))


def _drain_first_pass_queue(
    result_queue: Any,
) -> tuple[str, str, bytes | None, str | None]:
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    result_payload: bytes | None = None
    failure_message: str | None = None
    while True:
        try:
            item = result_queue.get_nowait()
        except queue.Empty:
            break
        if not isinstance(item, tuple) or not item:
            continue

        if item[0] == "stream" and len(item) >= 3:
            _kind, stream_name, chunk = item
            if stream_name == "stdout":
                stdout_chunks.append(str(chunk))
            elif stream_name == "stderr":
                stderr_chunks.append(str(chunk))
            continue

        if item[0] == "result" and len(item) >= 2:
            result_payload = item[1]
            continue

        if item[0] == "error" and len(item) >= 2:
            failure_message = str(item[1])

    return (
        "".join(stdout_chunks),
        "".join(stderr_chunks),
        result_payload,
        failure_message,
    )


def _start_first_pass_context() -> multiprocessing.context.BaseContext:
    return multiprocessing.get_context(FIRST_PASS_SUBPROCESS_START_METHOD)


def _run_first_pass_alpha_with_watchdog(
    image: Image.Image,
    *,
    session: Any,
) -> Image.Image | bytes | None:
    del session
    process_context = _start_first_pass_context()
    result_queue = process_context.Queue()
    image_bytes = _serialize_image_to_png_bytes(image)

    process = process_context.Process(
        target=_remove_first_pass_subprocess_worker,
        args=(image_bytes, result_queue),
        daemon=True,
    )
    process.start()

    deadline = time.monotonic() + FIRST_PASS_ALPHA_TIMEOUT_SECONDS
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    warning_probe = ""
    result_payload: bytes | None = None
    failure_message: str | None = None
    saw_warning = False

    while time.monotonic() < deadline:
        wait_seconds = min(
            FIRST_PASS_WATCHDOG_POLL_SECONDS,
            max(0.0, deadline - time.monotonic()),
        )
        if wait_seconds <= 0:
            break

        try:
            item = result_queue.get(timeout=wait_seconds)
        except queue.Empty:
            if not process.is_alive():
                break
            continue

        if not isinstance(item, tuple) or not item:
            continue

        if item[0] == "stream" and len(item) >= 3:
            stream_name = str(item[1])
            chunk = str(item[2])
            if stream_name == "stdout":
                stdout_chunks.append(chunk)
            elif stream_name == "stderr":
                stderr_chunks.append(chunk)

            warning_probe = (warning_probe + chunk.lower())[-4096:]
            if INCOMPLETE_CHOLESKY_WARNING_TOKEN in warning_probe:
                saw_warning = True
                break
            continue

        if item[0] == "result" and len(item) >= 2:
            result_payload = item[1]
            break

        if item[0] == "error" and len(item) >= 2:
            failure_message = str(item[1])
            break

    timed_out = (
        result_payload is None
        and failure_message is None
        and not saw_warning
        and time.monotonic() >= deadline
    )

    if saw_warning or timed_out:
        if process.is_alive():
            process.terminate()
        process.join(timeout=2.0)

        extra_stdout, extra_stderr, _extra_result, _extra_failure = (
            _drain_first_pass_queue(result_queue)
        )
        stdout_text = "".join(stdout_chunks) + extra_stdout
        stderr_text = "".join(stderr_chunks) + extra_stderr
        _emit_captured_streams(
            _strip_incomplete_cholesky_warning(stdout_text),
            _strip_incomplete_cholesky_warning(stderr_text),
        )

        if saw_warning:
            logging.warning(
                "Detected incomplete-Cholesky warning in first-pass alpha matting; "
                "aborting that attempt and retrying with safer fallback."
            )
        else:
            logging.warning(
                "First-pass alpha matting exceeded %.1f seconds; "
                "retrying with safer fallback.",
                FIRST_PASS_ALPHA_TIMEOUT_SECONDS,
            )
        return None

    process.join(timeout=2.0)
    extra_stdout, extra_stderr, extra_result, extra_failure = _drain_first_pass_queue(
        result_queue
    )
    stdout_text = "".join(stdout_chunks) + extra_stdout
    stderr_text = "".join(stderr_chunks) + extra_stderr
    if result_payload is None and extra_result is not None:
        result_payload = extra_result
    if failure_message is None and extra_failure is not None:
        failure_message = extra_failure

    if failure_message is not None:
        _emit_captured_streams(stdout_text, stderr_text)
        logging.warning(
            "First-pass alpha matting subprocess failed (%s); retrying with safer "
            "fallback.",
            failure_message,
        )
        return None

    _emit_captured_streams(stdout_text, stderr_text)
    if result_payload is None:
        logging.warning(
            "First-pass alpha matting finished without output; retrying with safer "
            "fallback."
        )
        return None

    return result_payload


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
    output = _run_first_pass_alpha_with_watchdog(image, session=session)
    if output is None:
        output = _run_first_pass_remove(
            image,
            session=session,
            alpha_matting=False,
            bgcolor=None,
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
        assert self._first_pass_session is not None
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
        first_rembg_image = remove_background_first_pass(
            resized_input,
            session=self._first_pass_session,
        )
        _write_debug_image(
            debug_dir,
            "02_first_pass_no_background.png",
            first_rembg_image,
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
        prompt_instruction = build_vlm_prompt_instruction(
            animal_type_hint=animal_type_hint
        )

        final_prompt = generate_prompt_with_openai_compatible(
            image=first_rembg_image,
            instruction=prompt_instruction,
            base_url=normalized_vlm_server,
            api_key=self.vlm_server_key,
            model=self.vlm_model_name,
            temperature=VLM_TEMPERATURE,
            timeout=VLM_TIMEOUT_SECONDS,
        )
        logging.info("VLM prompt generation completed.")
        logging.debug("VLM generated prompt: %s", final_prompt)
        _write_debug_prompt(debug_dir, final_prompt)

        init_image = add_monochrome_background(first_rembg_image)
        _write_debug_image(debug_dir, "03_monochrome_init_image.png", init_image)
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
                f"04_chroma_generated_{index + 1:02d}.png",
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
                f"05_sdxl_rewrite_{index + 1:02d}.png",
                sdxl_result,
            )
            final_image = sdxl_result.convert("L").convert("RGB")
            _write_debug_image(
                debug_dir,
                f"06_final_output_{index + 1:02d}.png",
                final_image,
            )
            yield final_image
