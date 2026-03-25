from __future__ import annotations

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

from . import dummy  # noqa: F401
from .core import WorkflowBase, create_workflow, list_workflows


@dataclass(slots=True)
class Job:
    case_id: int
    image_bytes: bytes
    requested_workflow: str | None
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
        )
        response.raise_for_status()
        payload = response.json()
        self.token = payload["access_token"]
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


def run_runner(*, workflow_name: str, server: str, password: str) -> None:
    workflow = create_workflow(workflow_name)
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
                    "Received case %s with backend workflow=%s; processing with %s.",
                    job.case_id,
                    job.requested_workflow,
                    workflow.name,
                )
            else:
                logging.info("Processing case %s.", job.case_id)

            with Image.open(io.BytesIO(job.image_bytes)) as source_image:
                source_image.load()
                image = workflow.generate(
                    source_image.copy(),
                    _validate_parameters(workflow, job.parameters),
                )
            result = _image_to_png_bytes(image)
            submission = client.submit_result(job.case_id, result)

            logging.info(
                "Submitted result for case %s (%s/%s, ready_for_review=%s).",
                job.case_id,
                submission.get("received_results"),
                submission.get("expected_results"),
                submission.get("ready_for_review"),
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
def cli(workflow: str, server: str, password: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [runner] %(message)s",
    )
    run_runner(workflow_name=workflow, server=server, password=password)


if __name__ == "__main__":
    cli()
