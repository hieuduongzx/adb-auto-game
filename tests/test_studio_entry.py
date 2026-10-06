"""Regression tests for Studio's packaged app routing."""
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class StudioEntryTests(unittest.TestCase):
    def check_route(self, args, expected, flow=None):
        calls = []
        modules = {
            'src.utils': types.SimpleNamespace(unblock_bundled_files=lambda: None),
            'workflow_designer': types.SimpleNamespace(run=lambda f: calls.append(('designer', f))),
            'workflow_runner': types.SimpleNamespace(run=lambda f: calls.append(('runner', f))),
            'workflow_hub': types.SimpleNamespace(run=lambda: calls.append(('hub', None))),
        }
        # Read the actual entry selected by the Studio spec.
        import ast
        tree = ast.parse((ROOT / 'packaging/apps_studio.spec').read_text(encoding='utf-8'))
        analysis = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Name) and n.func.id == 'Analysis')
        entry = analysis.args[0].elts[0].args[-1].value
        with patch.dict(sys.modules, modules), patch.object(sys, 'argv', ['Macro2k.exe', *args]):
            runpy.run_path(str(ROOT / 'packaging' / entry), run_name='__main__')
        self.assertEqual(calls, [(expected, flow)])

    def test_default_opens_designer(self):
        self.check_route([], 'designer')

    def test_runner_switch(self):
        self.check_route(['--runner', 'flow.json'], 'runner', 'flow.json')

    def test_designer_switch(self):
        self.check_route(['--designer', 'flow.json'], 'designer', 'flow.json')
