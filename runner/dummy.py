from __future__ import annotations

import time
from typing import Any

from PIL import Image, ImageEnhance, ImageOps

from .core import WorkflowBase

RUNNER_PROCESS_SECONDS = 5.0


class DummyWorkflow(WorkflowBase, name="dummy"):
    """Simple placeholder workflow for local/dev usage."""

    def is_available(self) -> bool:
        return True

    def setup(self) -> None:
        return None

    def generate(
        self, img: Image.Image, parameters: dict[str, Any] | None = None
    ) -> Image.Image:
        time.sleep(max(RUNNER_PROCESS_SECONDS, 0.0))

        mirrored = ImageOps.mirror(img.convert("RGB"))
        r_channel, g_channel, b_channel = mirrored.split()
        swapped = Image.merge("RGB", (g_channel, b_channel, r_channel))
        colorized = ImageEnhance.Color(swapped).enhance(1.6)
        return ImageEnhance.Contrast(colorized).enhance(1.15)
