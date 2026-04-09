from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
import io
import json
import logging
import os
from threading import Event, RLock, Thread
import time
from dataclasses import dataclass
from typing import Any

import click
import requests
from PIL import Image, ImageDraw, ImageFont, ImageStat

from . import chroma, dummy  # noqa: F401
from .core import WorkflowBase, create_workflow, list_workflows

WATERMARK_PATH = "watermark.png"
DEFAULT_TOY_ANIMAL_NAME = "Toy Animal"
MAX_WATERMARK_RATIO = 0.35
WATERMARK_TEMPLATE_WIDTH = 180
WATERMARK_TEMPLATE_HEIGHT = 208
WATERMARK_TEXT_SLOTS = (
    # Derived from runner/assets/watermark.png and intentionally hardcoded.
    # Tuple layout: (upper_line_row, target_line_row, left_x, right_x)
    (80, 99, 24, 158),
    (99, 119, 24, 158),
    (119, 140, 24, 158),
)
WATERMARK_STROKE_COLOR = (216, 206, 190, 255)
DEFAULT_PROCESSING_HEARTBEAT_SECONDS = 5.0


@dataclass(slots=True)
class Job:
    case_id: int
    image_bytes: bytes
    requested_images: int
    parameters: dict[str, Any]
    generation_id: int = 1
    animal_name: str = ""
    child_name: str = ""
    animal_type: str = ""


class BackendClient:
    def __init__(self, *, server: str, password: str) -> None:
        self.base_url = server.rstrip("/")
        self.password = password
        self.timeout_seconds = float(os.getenv("RUNNER_HTTP_TIMEOUT_SECONDS", "30"))

        self.session = requests.Session()
        self.token: str | None = None
        self.token_expires_at = 0.0
        self._request_lock = RLock()

    def _refresh_token(self, *, force: bool = False) -> None:
        now = time.time()
        if not force and self.token and now < self.token_expires_at - 10:
            return

        response = self.session.post(
            f"{self.base_url}/api/auth/token",
            data={"password": self.password},
            timeout=self.timeout_seconds,
            allow_redirects=False,
        )
        if response.is_redirect or response.is_permanent_redirect:
            raise RuntimeError(
                "Runner authentication request to /api/auth/token was redirected "
                f"(base_url={self.base_url!r}, status={response.status_code}, "
                f"location={response.headers.get('Location', '')!r}). "
                "Use BACKEND_URL that points directly to the backend API origin."
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            allow_header = response.headers.get("Allow", "")
            body_preview = response.text.strip().replace("\n", " ")
            if len(body_preview) > 500:
                body_preview = f"{body_preview[:500]}..."
            raise RuntimeError(
                "Runner authentication failed while requesting POST /api/auth/token "
                f"(base_url={self.base_url!r}, status={response.status_code}, "
                f"allow={allow_header!r}, body={body_preview!r}). "
                "Verify BACKEND_URL points to the TBK backend and SHARED_PASSWORD matches."
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            body_preview = response.text.strip().replace("\n", " ")
            if len(body_preview) > 500:
                body_preview = f"{body_preview[:500]}..."
            raise RuntimeError(
                "Runner authentication response from /api/auth/token was not valid JSON "
                f"(base_url={self.base_url!r}, body={body_preview!r})."
            ) from exc

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise RuntimeError(
                "Runner authentication response from /api/auth/token did not contain "
                f"a valid 'access_token' (base_url={self.base_url!r}, payload={payload!r})."
            )

        self.token = access_token
        expires_in = int(payload.get("expires_in", 300))
        self.token_expires_at = now + max(expires_in, 30)
        logging.info("Authenticated runner against %s.", self.base_url)

    def _auth_headers(self) -> dict[str, str]:
        if not self.token:
            self._refresh_token(force=True)
        assert self.token is not None
        return {"Authorization": f"Bearer {self.token}"}

    def _request_with_auth(
        self, method: str, path: str, **kwargs: Any
    ) -> requests.Response:
        with self._request_lock:
            self._refresh_token()
            extra_headers = kwargs.pop("headers", None) or {}
            request_headers = self._auth_headers()
            request_headers.update(extra_headers)
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                headers=request_headers,
                timeout=self.timeout_seconds,
                **kwargs,
            )
            if response.status_code == 401:
                self._refresh_token(force=True)
                request_headers = self._auth_headers()
                request_headers.update(extra_headers)
                response = self.session.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=request_headers,
                    timeout=self.timeout_seconds,
                    **kwargs,
                )

        return response

    @staticmethod
    def _parse_parameters(response: requests.Response) -> dict[str, Any]:
        raw_parameters = response.headers.get("X-Workflow-Parameters")
        if not raw_parameters:
            return {}
        try:
            parsed = json.loads(raw_parameters)
        except json.JSONDecodeError:
            logging.warning("Ignoring invalid X-Workflow-Parameters header.")
            return {}
        if not isinstance(parsed, dict):
            logging.warning("Ignoring non-object X-Workflow-Parameters header.")
            return {}
        return parsed

    @staticmethod
    def _parse_requested_images(response: requests.Response) -> int:
        raw_requested_images = (
            response.headers.get("X-Requested-Images")
            or response.headers.get("X-Expected-Results")
            or "1"
        )
        try:
            requested_images = int(raw_requested_images)
        except ValueError:
            logging.warning(
                "Invalid requested image count '%s'; falling back to 1.",
                raw_requested_images,
            )
            return 1
        return max(requested_images, 1)

    @staticmethod
    def _parse_generation_id(response: requests.Response) -> int:
        raw_generation_id = response.headers.get("X-Generation-Id")
        if not raw_generation_id:
            raise RuntimeError("Worker job response missing X-Generation-Id header.")
        try:
            generation_id = int(raw_generation_id)
        except ValueError as exc:
            raise RuntimeError(
                "Worker job response contained an invalid X-Generation-Id header."
            ) from exc
        if generation_id < 1:
            raise RuntimeError(
                "Worker job response contained a non-positive X-Generation-Id header."
            )
        return generation_id

    def next_job(self) -> Job | None:
        response = self._request_with_auth("GET", "/api/worker/jobs/next")
        if response.status_code == 204:
            return None

        response.raise_for_status()
        case_id_header = response.headers.get("X-Case-Id")
        if not case_id_header:
            raise RuntimeError("Worker job response missing X-Case-Id header.")

        return Job(
            case_id=int(case_id_header),
            image_bytes=response.content,
            requested_images=self._parse_requested_images(response),
            parameters=self._parse_parameters(response),
            generation_id=self._parse_generation_id(response),
            animal_name=(response.headers.get("X-Animal-Name") or "").strip(),
            child_name=(response.headers.get("X-Child-Name") or "").strip(),
            animal_type=(response.headers.get("X-Animal-Type") or "").strip(),
        )

    def submit_result(
        self,
        case_id: int,
        generation_id: int,
        image_bytes: bytes,
    ) -> dict[str, Any]:
        files = {
            "result": (
                f"result_{case_id}.png",
                io.BytesIO(image_bytes),
                "image/png",
            )
        }
        response = self._request_with_auth(
            "POST",
            f"/api/worker/jobs/{case_id}/results",
            headers={"X-Generation-Id": str(generation_id)},
            files=files,
        )
        response.raise_for_status()
        return response.json()

    def report_failed_job(self, case_id: int, generation_id: int) -> dict[str, Any]:
        response = self._request_with_auth(
            "POST",
            f"/api/worker/jobs/{case_id}/failed",
            headers={"X-Generation-Id": str(generation_id)},
        )
        response.raise_for_status()
        return response.json()

    def heartbeat(self) -> None:
        response = self._request_with_auth("POST", "/api/worker/heartbeat")
        response.raise_for_status()


@contextmanager
def _processing_heartbeat(
    *,
    client: Any,
    heartbeat_seconds: float,
) -> Iterable[None]:
    heartbeat = getattr(client, "heartbeat", None)
    if not callable(heartbeat) or heartbeat_seconds <= 0:
        yield
        return

    stop_event = Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(heartbeat_seconds):
            try:
                heartbeat()
            except Exception:
                logging.exception("Failed to send runner heartbeat while processing.")

    try:
        heartbeat()
    except Exception:
        logging.exception("Failed to send initial processing heartbeat.")

    thread = Thread(
        target=heartbeat_loop, name="runner-processing-heartbeat", daemon=True
    )
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=max(heartbeat_seconds, 1.0))


def _image_to_png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@lru_cache(maxsize=1)
def _load_watermark_template() -> Image.Image:
    watermark_reference = chroma._resolve_workflow_file(
        WATERMARK_PATH,
        description="watermark",
    )
    with Image.open(watermark_reference) as watermark_image:
        return watermark_image.convert("RGBA")


def _text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _load_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    if bold:
        font_names = ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf")
    else:
        font_names = ("DejaVuSans.ttf", "Arial.ttf")
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size=size)
        except OSError:
            continue
    if bold:
        return _load_font(size, bold=False)
    return ImageFont.load_default()


def _fit_text_for_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    *,
    bold: bool = False,
) -> tuple[str, ImageFont.ImageFont]:
    cleaned_text = " ".join(text.strip().split()) or "-"
    if max_width <= 0 or max_height <= 0:
        return cleaned_text, ImageFont.load_default()

    for size in range(max(max_height + 2, 9), 7, -1):
        font = _load_font(size, bold=bold)
        width, height = _text_size(draw, cleaned_text, font)
        if width <= max_width and height <= max_height:
            return cleaned_text, font

    fallback_font = _load_font(9, bold=bold)
    clipped = cleaned_text
    while (
        len(clipped) > 1
        and _text_size(draw, f"{clipped}...", fallback_font)[0] > max_width
    ):
        clipped = clipped[:-1]
    if (
        clipped != cleaned_text
        and _text_size(draw, f"{clipped}...", fallback_font)[0] <= max_width
    ):
        clipped = f"{clipped}..."
    return clipped, fallback_font


def _scaled_watermark_text_slots(
    watermark: Image.Image,
) -> list[tuple[int, int, int, int]]:
    scale_x = watermark.width / WATERMARK_TEMPLATE_WIDTH
    scale_y = watermark.height / WATERMARK_TEMPLATE_HEIGHT
    scaled: list[tuple[int, int, int, int]] = []
    for upper_row, target_row, left, right in WATERMARK_TEXT_SLOTS:
        scaled_upper_row = max(
            0, min(watermark.height - 1, int(round(upper_row * scale_y)))
        )
        scaled_target_row = max(
            scaled_upper_row + 1,
            min(watermark.height - 1, int(round(target_row * scale_y))),
        )
        scaled_left = max(0, min(watermark.width - 1, int(round(left * scale_x))))
        scaled_right = max(
            scaled_left + 1,
            min(watermark.width - 1, int(round(right * scale_x))),
        )
        scaled.append((scaled_upper_row, scaled_target_row, scaled_left, scaled_right))
    return scaled


def _child_line_text(child_name: str) -> str:
    normalized = " ".join(child_name.strip().split())
    if not normalized:
        return "von Kind"
    return f"von {normalized}"


def _draw_watermark_text(
    watermark: Image.Image,
    toy_animal_name: str,
    child_name: str,
    date_text: str,
) -> None:
    draw = ImageDraw.Draw(watermark)
    slots = _scaled_watermark_text_slots(watermark)
    labels = [
        " ".join(toy_animal_name.strip().split()) or DEFAULT_TOY_ANIMAL_NAME,
        _child_line_text(child_name),
        date_text,
    ]
    upper_gap = max(1, int(round(1.0 * watermark.height / WATERMARK_TEMPLATE_HEIGHT)))
    lower_gap = max(3, int(round(3.0 * watermark.height / WATERMARK_TEMPLATE_HEIGHT)))

    for label, slot in zip(labels, slots):
        upper_row, target_row, left, right = slot
        x_center = (left + right) // 2
        max_width = max(10, (right - left + 1) - 6)
        max_height = max(9, target_row - upper_row - upper_gap - lower_gap)
        text_value, font = _fit_text_for_width(
            draw,
            label,
            max_width=max_width,
            max_height=max_height,
            bold=True,
        )
        text_width, text_height = _text_size(draw, text_value, font)

        text_bottom_y = target_row - lower_gap
        min_top_y = upper_row + upper_gap
        text_top_y = max(min_top_y, text_bottom_y - text_height)
        text_x = max(0, min(watermark.width - text_width, x_center - (text_width // 2)))

        draw.text(
            (text_x, text_top_y),
            text_value,
            fill=WATERMARK_STROKE_COLOR,
            font=font,
        )


def _scale_watermark_to_image(
    image: Image.Image, watermark: Image.Image
) -> Image.Image:
    max_width = max(1, int(image.width * MAX_WATERMARK_RATIO))
    max_height = max(1, int(image.height * MAX_WATERMARK_RATIO))
    scale = min(max_width / watermark.width, max_height / watermark.height, 1.0)
    if scale >= 1.0:
        return watermark
    scaled_size = (
        max(1, int(round(watermark.width * scale))),
        max(1, int(round(watermark.height * scale))),
    )
    return watermark.resize(scaled_size, Image.Resampling.LANCZOS)


def _find_blackest_corner(
    image: Image.Image,
    region_width: int,
    region_height: int,
) -> tuple[int, int]:
    grayscale = image.convert("L")
    width, height = grayscale.size
    region_width = max(1, min(region_width, width))
    region_height = max(1, min(region_height, height))
    corners = [
        (0, 0),
        (width - region_width, 0),
        (0, height - region_height),
        (width - region_width, height - region_height),
    ]

    darkest_corner = corners[0]
    darkest_mean = float("inf")
    for x, y in corners:
        region = grayscale.crop((x, y, x + region_width, y + region_height))
        mean_value = ImageStat.Stat(region).mean[0]
        if mean_value < darkest_mean:
            darkest_mean = mean_value
            darkest_corner = (x, y)
    return darkest_corner


def _apply_watermark(
    image: Image.Image,
    toy_animal_name: str,
    child_name: str,
) -> Image.Image:
    watermark = _load_watermark_template().copy()
    watermark = _scale_watermark_to_image(image, watermark)
    _draw_watermark_text(
        watermark,
        toy_animal_name=toy_animal_name,
        child_name=child_name,
        date_text=datetime.now().strftime("%d.%m.%y"),
    )

    composited = image.convert("RGBA")
    position = _find_blackest_corner(
        composited,
        region_width=watermark.width,
        region_height=watermark.height,
    )
    composited.alpha_composite(watermark, dest=position)
    return composited.convert("RGB")


def _should_apply_watermark(job: Job, *, no_watermark: bool) -> bool:
    if no_watermark:
        return False
    return bool(job.animal_name.strip()) and bool(job.child_name.strip())


def _validate_parameters(
    workflow: WorkflowBase, parameters: dict[str, Any]
) -> dict[str, Any]:
    schema = workflow.parameter_schema()
    if not isinstance(schema, dict):
        return {}
    if schema.get("type") == "object" and isinstance(parameters, dict):
        return parameters
    return {}


def run_runner(
    *,
    workflow_name: str,
    server: str,
    password: str,
    debug: bool = False,
    no_watermark: bool = False,
    vlm_server: str | None = None,
    vlm_server_key: str | None = None,
    vlm_model_name: str | None = None,
) -> None:
    workflow = create_workflow(workflow_name)
    configure = getattr(workflow, "configure", None)
    if callable(configure):
        configure(
            vlm_server=vlm_server,
            vlm_server_key=vlm_server_key,
            vlm_model_name=vlm_model_name,
        )

    if not workflow.is_available():
        raise click.ClickException(
            f"Workflow '{workflow.name}' is not available in this environment."
        )
    workflow.setup()

    client = BackendClient(server=server, password=password)
    poll_seconds = float(os.getenv("RUNNER_POLL_SECONDS", "2"))
    heartbeat_seconds = float(
        os.getenv(
            "RUNNER_PROCESSING_HEARTBEAT_SECONDS",
            str(DEFAULT_PROCESSING_HEARTBEAT_SECONDS),
        )
    )
    logging.info(
        (
            "Runner started with workflow=%s, poll_interval=%.1fs, "
            "processing_heartbeat_interval=%.1fs"
        ),
        workflow.name,
        poll_seconds,
        heartbeat_seconds,
    )

    while True:
        try:
            job = client.next_job()
            if job is None:
                time.sleep(poll_seconds)
                continue

            logging.info(
                "Processing case %s with %s requested image(s).",
                job.case_id,
                job.requested_images,
            )

            with _processing_heartbeat(
                client=client,
                heartbeat_seconds=heartbeat_seconds,
            ):
                with Image.open(io.BytesIO(job.image_bytes)) as source_image:
                    source_image.load()
                    workflow_parameters = dict(
                        _validate_parameters(workflow, job.parameters)
                    )
                    if job.animal_type:
                        workflow_parameters["animal_type"] = job.animal_type
                    generated_images = workflow.generate(
                        source_image.copy(),
                        workflow_parameters,
                        job.requested_images,
                        debug=debug,
                    )
                if not isinstance(generated_images, Iterable):
                    raise RuntimeError(
                        (
                            f"Workflow '{workflow.name}' returned a non-iterable from "
                            "generate()."
                        )
                    )

                submitted_count = 0
                try:
                    for submitted_count, image in enumerate(generated_images, start=1):
                        output_image = (
                            image
                            if not _should_apply_watermark(
                                job, no_watermark=no_watermark
                            )
                            else _apply_watermark(
                                image,
                                job.animal_name,
                                job.child_name,
                            )
                        )
                        result = _image_to_png_bytes(output_image)
                        submission = client.submit_result(
                            job.case_id,
                            job.generation_id,
                            result,
                        )
                        submission_status = str(submission.get("status", "accepted"))
                        logging.info(
                            (
                                "Submitted result %s for case %s (%s/%s, "
                                "ready_for_review=%s, status=%s)."
                            ),
                            submitted_count,
                            job.case_id,
                            submission.get("received_results"),
                            submission.get("expected_results"),
                            submission.get("ready_for_review"),
                            submission_status,
                        )
                        if submission_status != "accepted":
                            logging.info(
                                (
                                    "Stopping work on case %s generation %s after "
                                    "backend returned status=%s."
                                ),
                                job.case_id,
                                job.generation_id,
                                submission_status,
                            )
                            break

                    if submitted_count == 0:
                        raise RuntimeError(
                            (
                                f"Workflow '{workflow.name}' yielded no images for case "
                                f"{job.case_id}."
                            )
                        )
                except Exception:
                    logging.exception(
                        "Case %s failed after submitting %s/%s result image(s).",
                        job.case_id,
                        submitted_count,
                        job.requested_images,
                    )
                    if submitted_count < job.requested_images:
                        try:
                            failure_report = client.report_failed_job(
                                job.case_id,
                                job.generation_id,
                            )
                            logging.info(
                                "Reported failed job for case %s: %s.",
                                job.case_id,
                                failure_report.get("status"),
                            )
                        except Exception:
                            logging.exception(
                                "Failed to report job failure for case %s.",
                                job.case_id,
                            )
                    time.sleep(poll_seconds)
        except KeyboardInterrupt:
            raise
        except Exception:
            logging.exception(
                "Runner loop failed. Retrying in %.1fs.",
                poll_seconds,
            )
            time.sleep(poll_seconds)


@click.command()
@click.option(
    "--workflow",
    required=True,
    type=click.Choice(list_workflows(), case_sensitive=False),
    help="Workflow implementation to run.",
)
@click.option(
    "--server",
    envvar="BACKEND_URL",
    required=True,
    help="Backend base URL (for example http://backend:8000).",
)
@click.option(
    "--password",
    envvar="SHARED_PASSWORD",
    required=True,
    help="Shared worker password used to obtain backend auth tokens.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable workflow debug mode (writes intermediate artifacts when supported).",
)
@click.option(
    "--no-watermark",
    is_flag=True,
    default=False,
    help="Skip watermark generation and overlay.",
)
@click.option(
    "--vlm-server",
    help="VLM base URL.",
)
@click.option(
    "--vlm-server-key",
    help="VLM API key.",
)
@click.option(
    "--vlm-model-name",
    help="VLM model name.",
)
def cli(
    workflow: str,
    server: str,
    password: str,
    debug: bool,
    no_watermark: bool,
    vlm_server: str | None,
    vlm_server_key: str | None,
    vlm_model_name: str | None,
) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [runner] %(message)s",
    )
    run_runner(
        workflow_name=workflow,
        server=server,
        password=password,
        debug=debug,
        no_watermark=no_watermark,
        vlm_server=vlm_server,
        vlm_server_key=vlm_server_key,
        vlm_model_name=vlm_model_name,
    )


if __name__ == "__main__":
    cli()
