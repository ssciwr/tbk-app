from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import runner.dummy as dummy_module
import runner.runner as runner_module
from runner.core import WorkflowBase, create_workflow, list_workflows


def _png_bytes(color: tuple[int, int, int] = (40, 120, 200)) -> bytes:
    image = Image.new("RGB", (16, 16), color=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _image_to_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes = b"",
        json_payload: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self._json_payload = json_payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._json_payload


@pytest.fixture(autouse=True)
def _restore_workflow_registry() -> None:
    # Ensure baseline workflow is available in every test.
    WorkflowBase._registry.setdefault("dummy", dummy_module.DummyWorkflow)
    snapshot = dict(WorkflowBase._registry)
    yield
    WorkflowBase._registry.clear()
    WorkflowBase._registry.update(snapshot)


def test_workflow_base_generate_yields_requested_number_of_copies() -> None:
    class UnitWorkflow(WorkflowBase, name="unit-base-copy"):
        pass

    workflow = UnitWorkflow()
    source = Image.new("RGB", (8, 8), color=(255, 0, 0))
    outputs = list(workflow.generate(source, parameters=None, num_images=2))

    assert len(outputs) == 2
    assert outputs[0] is not source
    outputs[0].putpixel((0, 0), (0, 255, 0))
    assert source.getpixel((0, 0)) == (255, 0, 0)


def test_create_workflow_is_case_insensitive_for_registered_workflows() -> None:
    workflow = create_workflow("DUMMY")
    assert isinstance(workflow, dummy_module.DummyWorkflow)
    assert "dummy" in list_workflows()


def test_chroma_workflow_is_registered() -> None:
    assert "chroma" in list_workflows()


def test_chroma_setup_requires_dependency_file_when_imports_fail(monkeypatch) -> None:
    chroma_module = runner_module.chroma
    monkeypatch.setattr(
        chroma_module,
        "_CHROMA_IMPORT_ERROR",
        ImportError("No module named 'torch'"),
    )
    workflow = chroma_module.ChromaWorkflow()

    with pytest.raises(RuntimeError, match="requirements-chroma.txt"):
        workflow.setup()


def test_dummy_workflow_generate_yields_seed_varied_images(monkeypatch) -> None:
    monkeypatch.setattr(dummy_module, "RUNNER_PROCESS_SECONDS", 0.0)
    workflow = dummy_module.DummyWorkflow()
    source = Image.new("RGB", (12, 12), color=(100, 40, 80))

    outputs = list(workflow.generate(source, num_images=3))

    assert len(outputs) == 3
    assert all(image.size == source.size for image in outputs)
    assert len({_image_to_bytes(image) for image in outputs}) == 3


def test_validate_parameters_only_accepts_object_schema() -> None:
    class ObjectSchemaWorkflow(WorkflowBase, name="unit-object-schema"):
        def parameter_schema(self) -> dict[str, Any]:
            return {"type": "object"}

    class ArraySchemaWorkflow(WorkflowBase, name="unit-array-schema"):
        def parameter_schema(self) -> dict[str, Any]:
            return {"type": "array"}

    object_workflow = ObjectSchemaWorkflow()
    array_workflow = ArraySchemaWorkflow()
    payload = {"foo": "bar"}

    assert runner_module._validate_parameters(object_workflow, payload) == payload
    assert runner_module._validate_parameters(array_workflow, payload) == {}


def test_backend_client_next_job_parses_headers_and_payload(monkeypatch) -> None:
    client = runner_module.BackendClient(server="http://backend:8000", password="pw")
    image_bytes = _png_bytes()

    response = _FakeResponse(
        status_code=200,
        headers={
            "X-Case-Id": "42",
            "X-Workflow": "dummy",
            "X-Requested-Images": "3",
            "X-Workflow-Parameters": '{"strength": 0.7}',
        },
        content=image_bytes,
    )
    monkeypatch.setattr(
        client, "_request_with_auth", lambda *_args, **_kwargs: response
    )

    job = client.next_job()

    assert job is not None
    assert job.case_id == 42
    assert job.image_bytes == image_bytes
    assert job.requested_workflow == "dummy"
    assert job.requested_images == 3
    assert job.parameters == {"strength": 0.7}


def test_backend_client_next_job_returns_none_on_204(monkeypatch) -> None:
    client = runner_module.BackendClient(server="http://backend:8000", password="pw")
    response = _FakeResponse(status_code=204)
    monkeypatch.setattr(
        client, "_request_with_auth", lambda *_args, **_kwargs: response
    )

    assert client.next_job() is None


def test_backend_client_submit_result_posts_file_payload(monkeypatch) -> None:
    client = runner_module.BackendClient(server="http://backend:8000", password="pw")
    captured: dict[str, Any] = {}

    def fake_request(method: str, path: str, **kwargs: Any) -> _FakeResponse:
        captured["method"] = method
        captured["path"] = path
        captured["kwargs"] = kwargs
        return _FakeResponse(status_code=200, json_payload={"status": "accepted"})

    monkeypatch.setattr(client, "_request_with_auth", fake_request)

    payload = client.submit_result(9, _png_bytes())

    assert payload == {"status": "accepted"}
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/worker/jobs/9/results"
    assert "files" in captured["kwargs"]
    filename, file_obj, content_type = captured["kwargs"]["files"]["result"]
    assert filename == "result_9.png"
    assert content_type == "image/png"
    assert file_obj.read().startswith(b"\x89PNG")


def test_run_runner_submits_images_as_they_are_yielded(monkeypatch) -> None:
    source_image = _png_bytes()

    class FakeWorkflow:
        name = "dummy"

        def __init__(self) -> None:
            self.setup_called = False
            self.generate_calls: list[tuple[dict[str, Any], int]] = []

        def is_available(self) -> bool:
            return True

        def setup(self) -> None:
            self.setup_called = True

        def parameter_schema(self) -> dict[str, Any]:
            return {"type": "object"}

        def generate(
            self,
            img: Image.Image,
            parameters: dict[str, Any] | None = None,
            num_images: int = 1,
        ):
            self.generate_calls.append((parameters or {}, num_images))
            for index in range(num_images):
                yield Image.new("RGB", img.size, color=(index, 0, 0))

    class FakeBackendClient:
        instances: list["FakeBackendClient"] = []

        def __init__(self, *, server: str, password: str) -> None:
            self.server = server
            self.password = password
            self.submissions: list[tuple[int, bytes]] = []
            self._next_calls = 0
            FakeBackendClient.instances.append(self)

        def next_job(self) -> runner_module.Job | None:
            self._next_calls += 1
            if self._next_calls == 1:
                return runner_module.Job(
                    case_id=7,
                    image_bytes=source_image,
                    requested_workflow="dummy",
                    requested_images=3,
                    parameters={"alpha": 0.3},
                )
            raise KeyboardInterrupt

        def submit_result(self, case_id: int, image_bytes: bytes) -> dict[str, Any]:
            self.submissions.append((case_id, image_bytes))
            count = len(self.submissions)
            return {
                "received_results": count,
                "expected_results": 3,
                "ready_for_review": count >= 3,
            }

    workflow = FakeWorkflow()
    monkeypatch.setattr(runner_module, "create_workflow", lambda _name: workflow)
    monkeypatch.setattr(runner_module, "BackendClient", FakeBackendClient)

    with pytest.raises(KeyboardInterrupt):
        runner_module.run_runner(
            workflow_name="dummy",
            server="http://backend:8000",
            password="pw",
        )

    assert workflow.setup_called is True
    assert workflow.generate_calls == [({"alpha": 0.3}, 3)]
    assert len(FakeBackendClient.instances) == 1
    fake_client = FakeBackendClient.instances[0]
    assert fake_client.server == "http://backend:8000"
    assert fake_client.password == "pw"
    assert [case_id for case_id, _ in fake_client.submissions] == [7, 7, 7]
    assert all(
        image_bytes.startswith(b"\x89PNG") for _, image_bytes in fake_client.submissions
    )


def test_run_runner_passes_vlm_configuration_into_workflow(monkeypatch) -> None:
    class FakeWorkflow:
        name = "dummy"

        def __init__(self) -> None:
            self.configure_calls: list[dict[str, Any]] = []
            self.setup_called = False

        def configure(self, **kwargs: Any) -> None:
            self.configure_calls.append(kwargs)

        def is_available(self) -> bool:
            return True

        def setup(self) -> None:
            self.setup_called = True

        def generate(
            self,
            _img: Image.Image,
            _parameters: dict[str, Any] | None = None,
            _num_images: int = 1,
        ):
            if False:
                yield None

    class FakeBackendClient:
        def __init__(self, *, server: str, password: str) -> None:
            self.server = server
            self.password = password

        def next_job(self) -> runner_module.Job | None:
            raise KeyboardInterrupt

    workflow = FakeWorkflow()
    monkeypatch.setattr(runner_module, "create_workflow", lambda _name: workflow)
    monkeypatch.setattr(runner_module, "BackendClient", FakeBackendClient)

    with pytest.raises(KeyboardInterrupt):
        runner_module.run_runner(
            workflow_name="dummy",
            server="http://backend:8000",
            password="pw",
            vlm_server="http://vlm.local:8001",
            vlm_server_key="test-key",
            vlm_model_name="gpt-4.1-mini",
        )

    assert workflow.setup_called is True
    assert workflow.configure_calls == [
        {
            "vlm_server": "http://vlm.local:8001",
            "vlm_server_key": "test-key",
            "vlm_model_name": "gpt-4.1-mini",
        }
    ]
