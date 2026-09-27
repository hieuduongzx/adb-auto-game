import json
from pathlib import Path

from apps.workflow_designer import WorkflowDesignerAPI


def test_open_migrates_delay_on_disk_immediately(tmp_path):
    path = tmp_path / 'flow.json'
    flow = {'name': 'Example', 'nodeDefaults': {'delayBefore': 2, 'delayAfter': 8},
            'activities': [{'graph': {'nodes': [
                {'id': 'a', 'type': 'tap_image', 'params': {'delayAfterFind': 0.5}, 'delayBefore': 3, 'delayAfter': 4},
                {'id': 'b', 'type': 'tap', 'params': {}, 'delayAfter': 6},
                {'id': 'legacy', 'type': 'tap', 'params': {'delay': 2}}]}}],
            'functions': [{'graph': {'nodes': [{'id': 'c', 'type': 'tap', 'params': {}, 'delayBefore': 1}]}}]}
    path.write_text(json.dumps(flow), encoding='utf-8')
    api = WorkflowDesignerAPI.__new__(WorkflowDesignerAPI)
    api._pending_load = str(path)
    api._remember_dir = lambda _: None
    api._remember_last_workflow = lambda _: None
    result = api.get_last_workflow()
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert json.loads(result['text']) == saved
    assert saved['nodeDefaults'] == {'delay': 2}
    a, b, legacy = saved['activities'][0]['graph']['nodes']
    assert a == {'id': 'a', 'type': 'tap_image', 'params': {'delayAfterFind': 0.5}, 'delay': 3}
    assert b == {'id': 'b', 'type': 'tap', 'params': {}}
    assert legacy == {'id': 'legacy', 'type': 'tap', 'params': {}, 'delay': 2}
    assert saved['functions'][0]['graph']['nodes'][0]['delay'] == 1
