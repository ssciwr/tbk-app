from __future__ import annotations

from collections.abc import Iterable
import io
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import click
import requests
from PIL import Image

from . import chroma, dummy  # noqa: F401
from .core import WorkflowBase, create_workflow, list_workflows


@dataclass(slots=True)
class Job:
    case_id: int
    image_bytes: bytes
    requested_workflow: str | None
    requested_images: int
    parameters: dict[str, Any]


class BackendClient:
    def __init__(self, *, server: str, password: str) -> None:
        self.base_url = server.rstrip("/")
        self.password = password
        self.timeout_seconds = float(os.getenv("RUNNER_HTTP_TIMEOUT_SECONDS", "30"))

        self.session = requests.Session()
        self.token: str | None = None
        self.token_expires_at = 0.0

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
        self._refresh_token()
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            headers=self._auth_headers(),
            timeout=self.timeout_seconds,
            **kwargs,
        )

        if response.status_code == 401:
            self._refresh_token(force=True)
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                headers=self._auth_headers(),
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
            requested_workflow=response.headers.get("X-Workflow"),
            requested_images=self._parse_requested_images(response),
            parameters=self._parse_parameters(response),
        )

    def submit_result(self, case_id: int, image_bytes: bytes) -> dict[str, Any]:
        files = {
            "result": (
                f"result_{case_id}.png",
                io.BytesIO(image_bytes),
                "image/png",
            )
        }
        response = self._request_with_auth(
            "POST", f"/api/worker/jobs/{case_id}/results", files=files
        )
        response.raise_for_status()
        return response.json()


def _image_to_png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


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
    logging.info(
        "Runner started with workflow=%s, poll_interval=%.1fs",
        workflow.name,
        poll_seconds,
    )

    while True:
        try:
            job = client.next_job()
            if job is None:
                time.sleep(poll_seconds)
                continue

            if (
                job.requested_workflow
                and job.requested_workflow.lower() != workflow.name
            ):
                logging.info(
                    (
                        "Received case %s with backend workflow=%s; processing with %s "
                        "for %s requested image(s)."
                    ),
                    job.case_id,
                    job.requested_workflow,
                    workflow.name,
                    job.requested_images,
                )
            else:
                logging.info(
                    "Processing case %s with %s requested image(s).",
                    job.case_id,
                    job.requested_images,
                )

            with Image.open(io.BytesIO(job.image_bytes)) as source_image:
                source_image.load()
                generated_images = workflow.generate(
                    source_image.copy(),
                    _validate_parameters(workflow, job.parameters),
                    job.requested_images,
                )
            if not isinstance(generated_images, Iterable):
                raise RuntimeError(
                    (
                        f"Workflow '{workflow.name}' returned a non-iterable from "
                        "generate()."
                    )
                )

            submitted_count = 0
            for submitted_count, image in enumerate(generated_images, start=1):
                result = _image_to_png_bytes(image)
                submission = client.submit_result(job.case_id, result)
                logging.info(
                    (
                        "Submitted result %s for case %s (%s/%s, "
                        "ready_for_review=%s)."
                    ),
                    submitted_count,
                    job.case_id,
                    submission.get("received_results"),
                    submission.get("expected_results"),
                    submission.get("ready_for_review"),
                )

            if submitted_count == 0:
                raise RuntimeError(
                    (
                        f"Workflow '{workflow.name}' yielded no images for case "
                        f"{job.case_id}."
                    )
                )
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
        vlm_server=vlm_server,
        vlm_server_key=vlm_server_key,
        vlm_model_name=vlm_model_name,
    )


if __name__ == "__main__":
    cli()
