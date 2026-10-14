from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOW_JS = ROOT / "apps" / "web" / "wf" / "js" / "workflow.js"
CONDITIONS_PY = ROOT / "src" / "workflow" / "nodes" / "conditions.py"


def test_designer_exposes_device_size_condition_fields():
    source = WORKFLOW_JS.read_text(encoding="utf-8")

    assert 'if_device_size:{label:"If screen size"' in source
    assert '{k:"width",lbl:"Screen width",t:"num",d:1920}' in source
    assert '{k:"height",lbl:"Screen height",t:"num",d:1080}' in source
    assert '{k:"tolerance",lbl:"Tolerance (px)",t:"num",d:0}' in source


def test_engine_registers_device_size_as_a_condition():
    from src.workflow.catalog import NODE_TYPES

    assert NODE_TYPES["if_device_size"]["kind"] == "condition"
    assert 'if ntype == "if_device_size":' in CONDITIONS_PY.read_text(encoding="utf-8")
