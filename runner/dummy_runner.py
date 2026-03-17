from __future__ import annotations

import io
import logging
import os
import time

import requests
from PIL import Image, ImageEnhance, ImageOps


class DummyRunner:
    def __init__(self) -> None:
        self.base_url = os.getenv("BACKEND_URL", "http://backend:8000").rstrip("/")
        self.password = os.getenv("SHARED_PASSWORD", "change-me")
        self.poll_seconds = float(os.getenv("RUNNER_POLL_SECONDS", "2"))
        self.process_seconds = float(os.getenv("RUNNER_PROCESS_SECONDS", "5"))
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
        logging.info("Authenticated dummy runner.")

    def _auth_headers(self) -> dict[str, str]:
        if not self.token:
            self._refresh_token(force=True)
        assert self.token is not None
        return {"Authorization": f"Bearer {self.token}"}

    def _request_with_auth(self, method: str, path: str, **kwargs) -> requests.Response:
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

    def _next_job(self) -> tuple[int, bytes] | None:
        response = self._request_with_auth("GET", "/api/worker/jobs/next")
        if response.status_code == 204:
            return None

        response.raise_for_status()
        case_id_header = response.headers.get("X-Case-Id")
        if not case_id_header:
            raise RuntimeError("Worker job response missing X-Case-Id header.")
        return int(case_id_header), response.content

    def _manipulate_image(self, source: bytes) -> bytes:
        with Image.open(io.BytesIO(source)) as image:
            rgb_image = image.convert("RGB")

        mirrored = ImageOps.mirror(rgb_image)
        r_channel, g_channel, b_channel = mirrored.split()
        swapped = Image.merge("RGB", (g_channel, b_channel, r_channel))
        colorized = ImageEnhance.Color(swapped).enhance(1.6)
        contrasted = ImageEnhance.Contrast(colorized).enhance(1.15)

        output = io.BytesIO()
        contrasted.save(output, format="PNG")
        return output.getvalue()

    def _submit_result(self, case_id: int, image_bytes: bytes) -> dict:
        files = {
            "result": (
                f"dummy_result_{case_id}.png",
                io.BytesIO(image_bytes),
                "image/png",
            )
        }
        response = self._request_with_auth(
            "POST", f"/api/worker/jobs/{case_id}/results", files=files
        )
        response.raise_for_status()
        return response.json()

    def run(self) -> None:
        logging.info("Dummy runner started. Backend: %s", self.base_url)
        while True:
            try:
                job = self._next_job()
                if job is None:
                    time.sleep(self.poll_seconds)
                    continue

                case_id, source_image = job
                logging.info(
                    "Picked case %s. Simulating generation (%.1fs)...",
                    case_id,
                    self.process_seconds,
                )
                time.sleep(self.process_seconds)
                generated = self._manipulate_image(source_image)
                submission = self._submit_result(case_id, generated)
                logging.info(
                    "Submitted result for case %s (%s/%s, ready_for_review=%s).",
                    case_id,
                    submission.get("received_results"),
                    submission.get("expected_results"),
                    submission.get("ready_for_review"),
                )
            except KeyboardInterrupt:
                raise
            except Exception:
                logging.exception(
                    "Dummy runner loop failed. Retrying in %.1fs.", self.poll_seconds
                )
                time.sleep(self.poll_seconds)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [dummy-runner] %(message)s",
    )
    DummyRunner().run()


if __name__ == "__main__":
    main()
