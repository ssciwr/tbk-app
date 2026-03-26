from __future__ import annotations

import io
import re
import sys
from pathlib import Path
from typing import Any

from click.testing import CliRunner
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


def test_chroma_resolve_workflow_file_uses_runner_assets_for_bare_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chroma_module = runner_module.chroma
    assets_dir = tmp_path / "runner" / "assets"
    assets_dir.mkdir(parents=True)
    expected = (assets_dir / "unit-test-background.png").resolve()
    expected.write_bytes(b"asset")

    monkeypatch.chdir(tmp_path)

    resolved = chroma_module._resolve_workflow_file(
        "unit-test-background.png",
        description="monochrome background",
    )

    assert Path(resolved) == expected


def test_chroma_resolve_workflow_file_accepts_explicit_absolute_path(
    tmp_path: Path,
) -> None:
    chroma_module = runner_module.chroma
    overridden = (tmp_path / "custom-transformer.safetensors").resolve()
    overridden.write_bytes(b"transformer")

    resolved = chroma_module._resolve_workflow_file(
        str(overridden),
        description="chroma transformer",
    )

    assert Path(resolved) == overridden


def test_chroma_resolve_workflow_file_has_clear_missing_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chroma_module = runner_module.chroma
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="runner/assets"):
        chroma_module._resolve_workflow_file(
            "missing-lora.safetensors",
            description="chroma LoRA",
        )


def test_chroma_create_debug_output_dir_creates_unique_timestamp_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chroma_module = runner_module.chroma
    monkeypatch.chdir(tmp_path)

    first_dir = chroma_module._create_debug_output_dir()
    second_dir = chroma_module._create_debug_output_dir()

    expected_root = (tmp_path / "debug-output").resolve()
    assert first_dir.parent == expected_root
    assert second_dir.parent == expected_root
    assert first_dir != second_dir
    assert first_dir.exists()
    assert second_dir.exists()


def test_chroma_debug_helpers_write_prompt_and_images(tmp_path: Path) -> None:
    chroma_module = runner_module.chroma
    debug_dir = tmp_path / "debug-output" / "run-1"
    debug_dir.mkdir(parents=True)
    source = Image.new("RGB", (8, 8), color=(12, 34, 56))

    chroma_module._write_debug_prompt(debug_dir, "generated prompt text")
    chroma_module._write_debug_image(debug_dir, "example.png", source)

    assert (debug_dir / "vlm_prompt.txt").read_text(encoding="utf-8") == (
        "generated prompt text"
    )
    with Image.open(debug_dir / "example.png") as saved:
        assert saved.size == (8, 8)


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
            "X-Child-Name": "Ada",
            "X-Animal-Name": "Bunny",
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
    assert job.requested_images == 3
    assert job.parameters == {"strength": 0.7}
    assert job.animal_name == "Bunny"
    assert job.child_name == "Ada"


def test_scaled_watermark_text_slots_follow_hardcoded_template() -> None:
    watermark = Image.new(
        "RGBA",
        (
            runner_module.WATERMARK_TEMPLATE_WIDTH,
            runner_module.WATERMARK_TEMPLATE_HEIGHT,
        ),
        (0, 0, 0, 0),
    )

    slots = runner_module._scaled_watermark_text_slots(watermark)

    assert slots == list(runner_module.WATERMARK_TEXT_SLOTS)


def test_find_blackest_corner_returns_darkest_region() -> None:
    image = Image.new("RGB", (40, 40), color=(240, 240, 240))
    for x in range(30, 40):
        for y in range(30, 40):
            image.putpixel((x, y), (0, 0, 0))

    corner = runner_module._find_blackest_corner(
        image,
        region_width=10,
        region_height=10,
    )

    assert corner == (30, 30)


def test_apply_watermark_places_template_in_blackest_corner(monkeypatch) -> None:
    source = Image.new("RGB", (60, 60), color=(255, 255, 255))
    for x in range(0, 10):
        for y in range(50, 60):
            source.putpixel((x, y), (0, 0, 0))

    watermark = Image.new("RGBA", (10, 10), color=(255, 0, 0, 255))
    captured: dict[str, str] = {}

    def fake_draw(
        _watermark: Image.Image,
        toy_animal_name: str,
        child_name: str,
        date_text: str,
    ) -> None:
        captured["toy_animal_name"] = toy_animal_name
        captured["child_name"] = child_name
        captured["date_text"] = date_text

    monkeypatch.setattr(runner_module, "_load_watermark_template", lambda: watermark)
    monkeypatch.setattr(runner_module, "_draw_watermark_text", fake_draw)

    result = runner_module._apply_watermark(source, "Fox", "Lia")

    assert captured["toy_animal_name"] == "Fox"
    assert captured["child_name"] == "Lia"
    assert re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", captured["date_text"]) is not None
    assert result.getpixel((5, 55)) == (255, 0, 0)


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


def test_backend_client_report_failed_job_posts_endpoint(monkeypatch) -> None:
    client = runner_module.BackendClient(server="http://backend:8000", password="pw")
    captured: dict[str, Any] = {}

    def fake_request(method: str, path: str, **kwargs: Any) -> _FakeResponse:
        captured["method"] = method
        captured["path"] = path
        captured["kwargs"] = kwargs
        return _FakeResponse(status_code=200, json_payload={"status": "requeued"})

    monkeypatch.setattr(client, "_request_with_auth", fake_request)

    payload = client.report_failed_job(11)

    assert payload == {"status": "requeued"}
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/worker/jobs/11/failed"
    assert captured["kwargs"] == {}


def test_run_runner_submits_images_as_they_are_yielded(monkeypatch) -> None:
    source_image = _png_bytes()

    class FakeWorkflow:
        name = "dummy"

        def __init__(self) -> None:
            self.setup_called = False
            self.generate_calls: list[tuple[dict[str, Any], int, bool]] = []

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
            debug: bool = False,
        ):
            self.generate_calls.append((parameters or {}, num_images, debug))
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
    assert workflow.generate_calls == [({"alpha": 0.3}, 3, False)]
    assert len(FakeBackendClient.instances) == 1
    fake_client = FakeBackendClient.instances[0]
    assert fake_client.server == "http://backend:8000"
    assert fake_client.password == "pw"
    assert [case_id for case_id, _ in fake_client.submissions] == [7, 7, 7]
    assert all(
        image_bytes.startswith(b"\x89PNG") for _, image_bytes in fake_client.submissions
    )


def test_run_runner_skips_watermark_when_no_watermark_enabled(monkeypatch) -> None:
    source_image = _png_bytes()

    class FakeWorkflow:
        name = "dummy"

        def is_available(self) -> bool:
            return True

        def setup(self) -> None:
            return None

        def parameter_schema(self) -> dict[str, Any]:
            return {"type": "object"}

        def generate(
            self,
            img: Image.Image,
            _parameters: dict[str, Any] | None = None,
            _num_images: int = 1,
            debug: bool = False,
        ):
            del debug
            yield Image.new("RGB", img.size, color=(1, 2, 3))

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
                    case_id=5,
                    image_bytes=source_image,
                    requested_images=1,
                    parameters={},
                    animal_name="Fox",
                    child_name="Ada",
                )
            raise KeyboardInterrupt

        def submit_result(self, case_id: int, image_bytes: bytes) -> dict[str, Any]:
            self.submissions.append((case_id, image_bytes))
            return {
                "status": "accepted",
                "received_results": 1,
                "expected_results": 1,
                "ready_for_review": True,
            }

    def fail_if_called(*_args: Any, **_kwargs: Any) -> Image.Image:
        raise AssertionError(
            "_apply_watermark should not be called when no_watermark=True"
        )

    monkeypatch.setattr(runner_module, "create_workflow", lambda _name: FakeWorkflow())
    monkeypatch.setattr(runner_module, "BackendClient", FakeBackendClient)
    monkeypatch.setattr(runner_module, "_apply_watermark", fail_if_called)

    with pytest.raises(KeyboardInterrupt):
        runner_module.run_runner(
            workflow_name="dummy",
            server="http://backend:8000",
            password="pw",
            no_watermark=True,
        )

    assert len(FakeBackendClient.instances) == 1
    submissions = FakeBackendClient.instances[0].submissions
    assert [case_id for case_id, _ in submissions] == [5]
    assert submissions[0][1].startswith(b"\x89PNG")


def test_run_runner_reports_failed_job_when_case_stalls(monkeypatch) -> None:
    source_image = _png_bytes()

    class FakeWorkflow:
        name = "dummy"

        def is_available(self) -> bool:
            return True

        def setup(self) -> None:
            return None

        def parameter_schema(self) -> dict[str, Any]:
            return {"type": "object"}

        def generate(
            self,
            img: Image.Image,
            _parameters: dict[str, Any] | None = None,
            _num_images: int = 1,
            debug: bool = False,
        ):
            del debug
            yield Image.new("RGB", img.size, color=(1, 2, 3))
            raise RuntimeError("third image generation failed")

    class FakeBackendClient:
        instances: list["FakeBackendClient"] = []

        def __init__(self, *, server: str, password: str) -> None:
            self.server = server
            self.password = password
            self.submissions: list[int] = []
            self.reported_failures: list[int] = []
            self._next_calls = 0
            FakeBackendClient.instances.append(self)

        def next_job(self) -> runner_module.Job | None:
            self._next_calls += 1
            if self._next_calls == 1:
                return runner_module.Job(
                    case_id=7,
                    image_bytes=source_image,
                    requested_images=3,
                    parameters={},
                )
            raise KeyboardInterrupt

        def submit_result(self, case_id: int, _image_bytes: bytes) -> dict[str, Any]:
            self.submissions.append(case_id)
            return {
                "status": "accepted",
                "received_results": len(self.submissions),
                "expected_results": 3,
                "ready_for_review": False,
            }

        def report_failed_job(self, case_id: int) -> dict[str, Any]:
            self.reported_failures.append(case_id)
            return {"status": "requeued"}

    monkeypatch.setattr(runner_module, "create_workflow", lambda _name: FakeWorkflow())
    monkeypatch.setattr(runner_module, "BackendClient", FakeBackendClient)
    monkeypatch.setattr(runner_module.time, "sleep", lambda _seconds: None)

    with pytest.raises(KeyboardInterrupt):
        runner_module.run_runner(
            workflow_name="dummy",
            server="http://backend:8000",
            password="pw",
        )

    assert len(FakeBackendClient.instances) == 1
    fake_client = FakeBackendClient.instances[0]
    assert fake_client.submissions == [7]
    assert fake_client.reported_failures == [7]


def test_run_runner_passes_debug_flag_into_generate(monkeypatch) -> None:
    source_image = _png_bytes()

    class FakeWorkflow:
        name = "dummy"

        def __init__(self) -> None:
            self.debug_calls: list[bool] = []

        def is_available(self) -> bool:
            return True

        def setup(self) -> None:
            return None

        def parameter_schema(self) -> dict[str, Any]:
            return {"type": "object"}

        def generate(
            self,
            img: Image.Image,
            _parameters: dict[str, Any] | None = None,
            _num_images: int = 1,
            debug: bool = False,
        ):
            self.debug_calls.append(debug)
            yield Image.new("RGB", img.size, color=(4, 5, 6))

    class FakeBackendClient:
        def __init__(self, *, server: str, password: str) -> None:
            self.server = server
            self.password = password
            self._next_calls = 0

        def next_job(self) -> runner_module.Job | None:
            self._next_calls += 1
            if self._next_calls == 1:
                return runner_module.Job(
                    case_id=9,
                    image_bytes=source_image,
                    requested_images=1,
                    parameters={},
                )
            raise KeyboardInterrupt

        def submit_result(self, _case_id: int, _image_bytes: bytes) -> dict[str, Any]:
            return {
                "status": "accepted",
                "received_results": 1,
                "expected_results": 1,
                "ready_for_review": True,
            }

    workflow = FakeWorkflow()
    monkeypatch.setattr(runner_module, "create_workflow", lambda _name: workflow)
    monkeypatch.setattr(runner_module, "BackendClient", FakeBackendClient)

    with pytest.raises(KeyboardInterrupt):
        runner_module.run_runner(
            workflow_name="dummy",
            server="http://backend:8000",
            password="pw",
            debug=True,
        )

    assert workflow.debug_calls == [True]


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
            debug: bool = False,
        ):
            del debug
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


def test_cli_passes_no_watermark_into_run_runner(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run_runner(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(runner_module, "run_runner", fake_run_runner)
    cli_runner = CliRunner()

    result = cli_runner.invoke(
        runner_module.cli,
        [
            "--workflow",
            "dummy",
            "--server",
            "http://backend:8000",
            "--password",
            "pw",
            "--no-watermark",
        ],
    )

    assert result.exit_code == 0
    assert captured["no_watermark"] is True
