from __future__ import annotations

from collections.abc import Generator
from typing import Any, ClassVar

from PIL import Image


class WorkflowBase:
    """Base class for all runner workflows."""

    name: ClassVar[str]
    _registry: ClassVar[dict[str, type["WorkflowBase"]]] = {}

    def __init_subclass__(cls, *, name: str, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        normalized_name = name.strip().lower()
        if not normalized_name:
            raise ValueError("Workflow name must not be empty.")
        if normalized_name in WorkflowBase._registry:
            raise ValueError(f"Workflow '{normalized_name}' is already registered.")
        cls.name = normalized_name
        WorkflowBase._registry[normalized_name] = cls

    def is_available(self) -> bool:
        """Whether this workflow is available."""
        return True

    def setup(self) -> None:
        """Called once when starting the server with this workflow."""
        return None

    def configure(self, **kwargs: Any) -> None:
        """Apply runner-level configuration values before setup."""
        return None

    def parameter_schema(self) -> dict[str, Any]:
        """Return a JSONSchema dictionary describing expected parameters."""
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }

    def generate(
        self,
        img: Image.Image,
        parameters: dict[str, Any] | None = None,
        num_images: int = 1,
        debug: bool = False,
    ) -> Generator[Image.Image, None, None]:
        """Generate one or more X-Ray images for the input."""
        del debug
        for _ in range(max(num_images, 0)):
            yield img.copy()


def list_workflows() -> list[str]:
    return sorted(WorkflowBase._registry.keys())


def create_workflow(name: str) -> WorkflowBase:
    workflow_name = name.strip().lower()
    workflow_class = WorkflowBase._registry.get(workflow_name)
    if workflow_class is None:
        available = ", ".join(list_workflows())
        raise KeyError(f"Unknown workflow '{name}'. Available workflows: {available}")
    return workflow_class()
