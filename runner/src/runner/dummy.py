from __future__ import annotations

from collections.abc import Generator
import random
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
        self,
        img: Image.Image,
        parameters: dict[str, Any] | None = None,
        num_images: int = 1,
        debug: bool = False,
    ) -> Generator[Image.Image, None, None]:
        del debug
        base = img.convert("RGB")
        for seed in range(max(num_images, 0)):
            time.sleep(max(RUNNER_PROCESS_SECONDS, 0.0))
            rng = random.Random(seed)

            mirrored = ImageOps.mirror(base)
            r_channel, g_channel, b_channel = mirrored.split()
            swapped = Image.merge("RGB", (g_channel, b_channel, r_channel))
            colorized = ImageEnhance.Color(swapped).enhance(1.3 + rng.random() * 0.5)
            yield ImageEnhance.Contrast(colorized).enhance(1.05 + rng.random() * 0.2)
