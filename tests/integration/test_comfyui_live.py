"""Live integration tests against a real ComfyUI instance.

These boot an actual ComfyUI server (``--cpu``, no models needed) with
this pack symlinked into ``custom_nodes``, then exercise the pack
through ComfyUI's public HTTP API: node registration via /object_info
and real workflow execution via /prompt + /history — including full
loop expansion. This is the compatibility gate for new ComfyUI
versions: if ComfyUI changes the lazy-evaluation contract, the
expansion API, hidden inputs, or custom-node loading, these fail.

Skipped unless COMFYUI_DIR points at a ComfyUI checkout. Environment:
  COMFYUI_DIR     path to a ComfyUI checkout (required)
  COMFYUI_PYTHON  interpreter to launch it with
                  (default: $COMFYUI_DIR/.venv/bin/python, else python3)
  COMFYUI_PORT    port for the throwaway server (default 8189)

Provision a checkout: ./scripts/setup-comfyui.sh /tmp/ComfyUI master
Run:                  COMFYUI_DIR=/tmp/ComfyUI uv run pytest -m integration
"""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_env_dir = os.environ.get("COMFYUI_DIR")
if not _env_dir:
    pytest.skip(
        "COMFYUI_DIR not set — see tests/integration/test_comfyui_live.py",
        allow_module_level=True,
    )
COMFYUI_DIR = Path(_env_dir)

PORT = int(os.environ.get("COMFYUI_PORT", "8189"))
BASE = f"http://127.0.0.1:{PORT}"
REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_NODES = ("QualityModeSwitch", "LazySwitch", "RepeatOpen", "RepeatClose")


def comfy_python():
    override = os.environ.get("COMFYUI_PYTHON")
    if override:
        return override
    venv_python = COMFYUI_DIR / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else "python3"


def _log_tail(log_path, lines=60):
    try:
        content = Path(log_path).read_text(errors="replace").splitlines()
        return "\n".join(content[-lines:])
    except OSError:
        return "<no server log>"


def _get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as resp:
        return json.loads(resp.read())


def _run_workflow(graph, timeout=180):
    """Submit an API-format prompt and wait for its history entry."""
    payload = json.dumps({"prompt": graph, "client_id": uuid.uuid4().hex}).encode()
    request = urllib.request.Request(
        f"{BASE}/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            prompt_id = json.loads(resp.read())["prompt_id"]
    except urllib.error.HTTPError as err:
        pytest.fail(
            f"/prompt rejected the workflow: {err.read().decode(errors='replace')}"
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = _get(f"/history/{prompt_id}")
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(0.5)
    pytest.fail(f"workflow {prompt_id} did not finish within {timeout}s")


def _assert_success(entry):
    status = entry.get("status", {})
    assert status.get("status_str") == "success", json.dumps(status)[:2000]


@pytest.fixture(scope="session")
def comfy_server(tmp_path_factory):
    custom_nodes = COMFYUI_DIR / "custom_nodes"
    link = custom_nodes / "comfy-toolset"
    created_link = False
    if not link.exists():
        custom_nodes.mkdir(exist_ok=True)
        link.symlink_to(REPO_ROOT)
        created_link = True
    elif link.resolve() != REPO_ROOT:
        pytest.fail(
            f"{link} exists but is not this checkout ({link.resolve()}); "
            "refusing to touch it."
        )

    log_path = tmp_path_factory.mktemp("comfy") / "server.log"
    with open(log_path, "w") as log:
        proc = subprocess.Popen(
            [
                comfy_python(),
                "main.py",
                "--cpu",
                "--listen",
                "127.0.0.1",
                "--port",
                str(PORT),
            ],
            cwd=COMFYUI_DIR,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 240
            while True:
                if proc.poll() is not None:
                    pytest.fail(
                        "ComfyUI exited during startup:\n" + _log_tail(log_path)
                    )
                try:
                    with urllib.request.urlopen(f"{BASE}/system_stats", timeout=5):
                        break
                except (urllib.error.URLError, OSError):
                    if time.monotonic() > deadline:
                        proc.terminate()
                        pytest.fail(
                            "ComfyUI never became ready:\n" + _log_tail(log_path)
                        )
                    time.sleep(1)
            yield BASE
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
            if created_link:
                link.unlink()


@pytest.fixture(scope="session")
def object_info(comfy_server):
    return _get("/object_info")


class TestRegistration:
    def test_pack_nodes_registered(self, object_info):
        missing = [name for name in PACK_NODES if name not in object_info]
        assert not missing, f"pack nodes missing from /object_info: {missing}"

    def test_server_is_a_full_boot(self, object_info):
        # A husk that loaded our pack but not core nodes proves nothing.
        assert "KSampler" in object_info

    def test_lazy_flags_exposed(self, object_info):
        optional = object_info["QualityModeSwitch"]["input"]["optional"]
        for name in ("draft_model", "final_model"):
            socket_type, opts = optional[name]
            assert socket_type == "MODEL"
            assert opts.get("lazy") is True
        for name in ("a", "b"):
            socket_type, opts = object_info["LazySwitch"]["input"]["optional"][name]
            assert socket_type == "*"
            assert opts.get("lazy") is True

    def test_flow_control_contract(self, object_info):
        assert object_info["RepeatOpen"]["output"][0] == "FLOW_CONTROL"
        flow_input = object_info["RepeatClose"]["input"]["required"]["flow_control"]
        assert flow_input[0] == "FLOW_CONTROL"
        assert flow_input[1].get("rawLink") is True


class TestExecution:
    @pytest.mark.parametrize("pick_b,expected", [(False, "chose-a"), (True, "chose-b")])
    def test_lazy_switch_selects(self, comfy_server, pick_b, expected):
        entry = _run_workflow(
            {
                "switch": {
                    "class_type": "LazySwitch",
                    "inputs": {"pick_b": pick_b, "a": "chose-a", "b": "chose-b"},
                },
                "preview": {
                    "class_type": "PreviewAny",
                    "inputs": {"source": ["switch", 0]},
                },
            }
        )
        _assert_success(entry)
        assert expected in json.dumps(entry.get("outputs", {}))

    def test_lazy_switch_missing_branch_surfaces_error(self, comfy_server):
        entry = _run_workflow(
            {
                "switch": {
                    "class_type": "LazySwitch",
                    "inputs": {"pick_b": True, "a": "only-a"},
                },
                "preview": {
                    "class_type": "PreviewAny",
                    "inputs": {"source": ["switch", 0]},
                },
            }
        )
        status = entry.get("status", {})
        assert status.get("status_str") == "error"
        assert "LazySwitch" in json.dumps(status)

    def _loop_graph(self, iterations, body_nodes, close_value0):
        graph = {
            "open": {
                "class_type": "RepeatOpen",
                "inputs": {"iterations": iterations, "value0": "x"},
            },
            "close": {
                "class_type": "RepeatClose",
                "inputs": {"flow_control": ["open", 0], "value0": close_value0},
            },
            "preview": {
                "class_type": "PreviewAny",
                "inputs": {"source": ["close", 0]},
            },
        }
        graph.update(body_nodes)
        return graph

    def test_repeat_loop_passthrough(self, comfy_server):
        """Expansion machinery end-to-end with only pack nodes in the body."""
        entry = _run_workflow(
            self._loop_graph(
                3,
                {
                    "body": {
                        "class_type": "LazySwitch",
                        # RepeatOpen output slot 3 is value0
                        "inputs": {"pick_b": False, "a": ["open", 3]},
                    }
                },
                ["body", 0],
            )
        )
        _assert_success(entry)
        assert "x" in json.dumps(entry.get("outputs", {}))

    @pytest.mark.parametrize("iterations,expected", [(1, "xx"), (3, "xxxx")])
    def test_repeat_loop_body_runs_n_times(
        self, comfy_server, object_info, iterations, expected
    ):
        """Observable proof of pass count: each pass appends one 'x'."""
        if "StringConcatenate" not in object_info:
            pytest.skip("core StringConcatenate node unavailable in this ComfyUI")
        entry = _run_workflow(
            self._loop_graph(
                iterations,
                {
                    "body": {
                        "class_type": "StringConcatenate",
                        "inputs": {
                            "string_a": ["open", 3],
                            "string_b": "x",
                            "delimiter": "",
                        },
                    }
                },
                ["body", 0],
            )
        )
        _assert_success(entry)
        outputs = json.dumps(entry.get("outputs", {}))
        assert expected in outputs
        assert expected + "x" not in outputs  # not one pass too many


class TestExpansionApiCanary:
    """Direct probe of the comfy_execution surface loop_nodes.py depends
    on, run inside the ComfyUI environment. Pinpoints API drift even when
    the server-level tests fail for murkier reasons."""

    CANARY = """
from comfy_execution.graph_utils import GraphBuilder, is_link
g = GraphBuilder()
a = g.node("ClassA", "a")
a.set_input("x", 1)
a.set_override_display_id("a")
b = g.node("ClassB", "b")
b.set_input("y", a.out(0))
assert g.lookup_node("a") is a
fin = g.finalize()
assert isinstance(fin, dict) and len(fin) == 2
assert is_link(["node-id", 0])
assert not is_link(5)
assert not is_link("nope")
"""

    def test_graph_utils_surface(self):
        result = subprocess.run(
            [comfy_python(), "-c", self.CANARY],
            cwd=COMFYUI_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, (
            f"comfy_execution.graph_utils API drifted:\n{result.stderr}"
        )
