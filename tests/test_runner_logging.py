"""Behavioral coverage for concise Runner lifecycle and activity logs."""
import ast
import threading
from pathlib import Path


ROOT = Path(__file__).parents[1]
RUNNER_PATH = ROOT / "apps" / "workflow_runner.py"


def _runner_methods(*names):
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    wanted = set(names)
    methods = [
        node
        for cls in tree.body
        if isinstance(cls, ast.ClassDef) and cls.name == "WorkflowRunnerAPI"
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    assert {method.name for method in methods} == wanted
    return methods


def test_successful_workflow_initialization_logs_one_useful_message():
    messages = []
    flow = {"name": "BrownDust2", "activities": []}

    class Engine:
        def is_running(self):
            return False

        def load(self, loaded_flow, flow_path):
            self.loaded = (loaded_flow, flow_path)

        def speedhack_info(self):
            return {}

    class WorkflowEngine:
        @staticmethod
        def load_file(path):
            return flow

    namespace = {
        "WorkflowEngine": WorkflowEngine,
        "get_capture_backend": lambda: "scrcpy",
        "log_error": lambda message: messages.append(("error", message)),
        "log_warning": lambda message: messages.append(("warning", message)),
        "log_success": lambda message: messages.append(("success", message)),
        "dict": dict,
    }
    exec(compile(ast.Module(body=_runner_methods("_load_path"), type_ignores=[]),
                 str(RUNNER_PATH), "exec"), namespace)

    class Runner:
        _load_path = namespace["_load_path"]
        _load_runner_config = lambda self, loaded_flow, path: None
        _apply_runner_config = lambda self: None
        _requirements_payload = lambda self: {}
        _controller = lambda self: "adb"
        _activities_payload = lambda self: []
        _game_path_status = lambda self: {}
        _icon_url = lambda self: ""
        _icon_key = lambda self: ""
        _push_bridge_status = lambda self, force=False: None
        _kick_device_scan = lambda self: None

        def _push(self, event, payload):
            self.events.append((event, payload))

    runner = Runner()
    runner.engine = Engine()
    runner.events = []
    runner._flow_game_path = ""
    runner._flow_emulator = {}
    runner._runner_config_path = ""

    result = runner._load_path("workflow.json")

    assert result["ok"] is True
    assert messages == [("success", "Automation initialized successfully — BrownDust2")]


def test_activity_toggle_logs_the_activity_name_and_new_state():
    messages = []
    namespace = {"log_info": lambda message: messages.append(message)}
    exec(compile(ast.Module(body=_runner_methods("toggle_activity"), type_ignores=[]),
                 str(RUNNER_PATH), "exec"), namespace)

    class Engine:
        def is_running(self):
            return False

    class Runner:
        toggle_activity = namespace["toggle_activity"]

        def _activity_runner_config(self, activity_id):
            return self.config.setdefault(activity_id, {})

        def _save_runner_config(self):
            pass

    runner = Runner()
    runner.flow = {"activities": [{"id": "farm", "name": "Daily Farm", "enabled": True}]}
    runner.engine = Engine()
    runner.config = {}
    runner._runner_config_lock = threading.RLock()

    assert runner.toggle_activity("farm", False) is True
    assert runner.toggle_activity("farm", True) is True
    assert messages == [
        "Activity disabled — Daily Farm",
        "Activity enabled — Daily Farm",
    ]
