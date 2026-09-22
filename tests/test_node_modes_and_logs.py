import unittest
import threading
import time
from unittest import mock

from src.workflow import engine as E


class TestNodeModesAndLogs(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(E, 'ADBGameAutomation'):
            self.engine = E.WorkflowEngine()
        self.engine._ensure_ready = mock.Mock(return_value=True)
        self.engine._sleep = mock.Mock()

    def user_messages(self, logged):
        return [c.args[0] for c in logged.call_args_list
                if c.kwargs.get('kind') == E.LOG_KIND_USER]

    def test_wait_random_mode_and_legacy_use_same_range(self):
        with mock.patch.object(E.random, 'uniform', return_value=1.25) as pick:
            self.engine._a_wait({}, {'mode': 'random', 'min': 2, 'max': .5})
            pick.assert_called_once_with(.5, 2)
            self.engine._sleep.assert_called_once_with(1.25)
        self.engine._sleep.reset_mock()
        self.engine._a_wait({}, {'seconds': 0})
        self.engine._sleep.assert_called_once_with(0)

    def test_swipe_direction_mode_uses_device_center(self):
        self.engine.auto.adb.get_screen_size.return_value = (1920, 1080)
        self.engine._a_swipe({}, {'mode': 'direction', 'direction': 'left',
                                  'distance': 200, 'duration': 450})
        self.engine.auto.swipe.assert_called_once_with(960, 540, 760, 540, 450)

    def test_swipe_old_coordinates_unchanged(self):
        self.engine._a_swipe({}, {'x1': 1, 'y1': 2, 'x2': 3, 'y2': 4, 'duration': 5})
        self.engine.auto.swipe.assert_called_once_with(1, 2, 3, 4, 5)

    def test_if_device_size_matches_with_tolerance(self):
        self.engine.auto.adb.get_screen_size.return_value = (1918, 1082)

        self.assertTrue(self.engine._eval_condition(
            'if_device_size', {'width': 1920, 'height': 1080, 'tolerance': 2}
        ))

    def test_if_device_size_rejects_unknown_size_even_when_negated(self):
        self.engine.auto.adb.get_screen_size.return_value = (0, 0)

        self.assertFalse(self.engine._eval_condition(
            'if_device_size', {'width': 1920, 'height': 1080, 'negate': True}
        ))

    def test_if_device_size_supports_negating_a_known_mismatch(self):
        self.engine.auto.adb.get_screen_size.return_value = (1600, 900)

        self.assertTrue(self.engine._eval_condition(
            'if_device_size', {'width': 1920, 'height': 1080, 'negate': True}
        ))

    def test_sequence_tap_runs_points_in_order_with_each_delay_after_tap(self):
        points = [
            {'x': 10, 'y': 20, 'delay': 0.5},
            {'x': 30, 'y': 40, 'delay': 1},
        ]
        with mock.patch.object(self.engine, '_sequence_delay', wraps=self.engine._sequence_delay) as delay:
            self.engine._a_sequence_tap({}, {'points': points})

        self.assertEqual(self.engine.auto.tap.call_args_list, [
            mock.call(10, 20, tap_count=1),
            mock.call(30, 40, tap_count=1),
        ])
        self.assertEqual(delay.call_args_list, [
            mock.call(mock.ANY, 0.5),
            mock.call(mock.ANY, 1),
        ])

    def test_sequence_tap_image_finds_taps_and_delays_each_item_in_order(self):
        self.engine._wait_for_template = mock.Mock(side_effect=[(11, 12), (31, 32)])
        images = [
            {'template': 'one.png', 'threshold': .8, 'timeout': 2,
             'offsetX': 1, 'offsetY': 2, 'delay': .5},
            {'template': 'two.png', 'threshold': .9, 'timeout': 3,
             'offsetX': -1, 'offsetY': 0, 'delay': 1},
        ]
        with mock.patch.object(self.engine, '_sequence_delay', wraps=self.engine._sequence_delay) as delay:
            self.assertTrue(self.engine._a_sequence_tap_image({}, {'images': images}))

        self.assertEqual(self.engine._wait_for_template.call_args_list, [
            mock.call('one.png', timeout=2, threshold=.8, region=None),
            mock.call('two.png', timeout=3, threshold=.9, region=None),
        ])
        self.assertEqual(self.engine.auto.tap.call_args_list, [
            mock.call(12, 14, tap_count=1),
            mock.call(30, 32, tap_count=1),
        ])
        self.assertEqual(delay.call_args_list, [
            mock.call(mock.ANY, .5), mock.call(mock.ANY, 1)
        ])

    def test_stop_sequence_stops_matching_sequence_before_next_tap(self):
        started = threading.Event()
        release = threading.Event()
        taps = []

        def tap(x, y, tap_count=1):
            taps.append((x, y))
            started.set()
            release.wait(1)
            return True

        self.engine.auto.tap.side_effect = tap
        points = [{'x': 10, 'y': 20, 'delay': 0}, {'x': 30, 'y': 40, 'delay': 0}]
        result = {}

        worker = threading.Thread(
            target=lambda: result.setdefault(
                'ok', self.engine._a_sequence_tap({}, {'sequenceId': 'main', 'points': points})
            )
        )
        worker.start()
        self.assertTrue(started.wait(1))
        self.assertTrue(self.engine._a_stop_sequence({}, {'sequenceId': 'main'}))
        release.set()
        worker.join(1)

        self.assertTrue(result['ok'])
        self.assertEqual(taps, [(10, 20)])

    def test_tap_text_taps_the_center_of_the_matching_ocr_region_with_offset(self):
        self.engine.auto.region_find_text.return_value = (True, 'PLAY NOW')

        result = self.engine._eval_condition('tap_text', {
            'text': 'PLAY', 'x': 100, 'y': 200, 'w': 300, 'h': 80,
            'timeout': 0, 'offsetX': 5, 'offsetY': -10,
        })

        self.assertTrue(result)
        self.engine.auto.region_find_text.assert_called_once_with(
            'PLAY', region=(100, 200, 300, 80), whitelist=None,
        )
        self.engine.auto.tap.assert_called_once_with(255, 230, tap_count=1)
        self.assertEqual(self.engine._last_pos, (250, 240))

    def test_tap_text_does_not_tap_when_ocr_region_does_not_match(self):
        self.engine.auto.region_find_text.return_value = (False, 'PAUSE')

        result = self.engine._eval_condition('tap_text', {
            'text': 'PLAY', 'x': 10, 'y': 20, 'w': 100, 'h': 40, 'timeout': 0,
        })

        self.assertFalse(result)
        self.engine.auto.tap.assert_not_called()

    def test_if_variable_supports_value_type_checks(self):
        cases = [
            (12, 'is_integer', True),
            ('12', 'is_integer', True),
            ('12.5', 'is_integer', False),
            (12.5, 'is_number', True),
            ('hello', 'is_text', True),
            ('', 'is_empty', True),
            (None, 'is_empty', True),
            ('hello', 'is_not_number', True),
        ]
        for current, op, expected in cases:
            with self.subTest(current=current, op=op):
                self.assertEqual(self.engine._compare(current, op, ''), expected)

    def test_branch_logs_emit_only_taken_port_and_resolve_live_vars(self):
        node = {'id': 'n', 'type': 'if_image', 'log': 'enter',
                'outputLogs': {'true': 'found {score}', 'false': 'missing'},
                'outputLog': 'old fallback'}
        self.engine._vars = {'score': 7}
        for result, expected in [(True, 'found 7'), (False, 'missing')]:
            with self.subTest(result=result), mock.patch.object(E, 'log_info') as logged:
                self.engine._eval_condition = mock.Mock(return_value=result)
                out = self.engine.run_single_node(node)
                self.assertEqual(out['port'], 'true' if result else 'false')
                self.assertEqual(self.user_messages(logged), ['enter', expected])

    def test_explicit_empty_branch_does_not_fall_back_to_old_log(self):
        with mock.patch.object(E, 'log_info') as logged:
            self.engine._node_done({'outputLog': 'old', 'outputLogs': {'true': ''}},
                                   'n', 'ok', 'true')
            self.assertEqual(self.user_messages(logged), [])

    def test_old_output_log_still_works_in_runner_without_migration(self):
        with mock.patch.object(E, 'log_info') as logged:
            self.engine._node_done({'outputLog': 'old'}, 'n', 'ok', 'false')
            self.assertEqual(self.user_messages(logged), ['old'])

    def test_terminal_completion_log_and_action_error_log(self):
        with mock.patch.object(E, 'log_info') as logged:
            self.engine._node_done({'type': 'end', 'outputLogs': {'$done': 'finished'}},
                                   'e', 'ok', None)
            self.engine._node_done({'type': 'tap', 'outputLogs': {'out': 'sent', '$error': 'failed'}},
                                   't', 'fail', 'out')
            self.assertEqual(self.user_messages(logged), ['finished', 'failed'])

    def test_condition_exception_uses_false_log_in_single_node_test(self):
        self.engine._eval_condition = mock.Mock(side_effect=RuntimeError('fixture'))
        with mock.patch.object(E, 'log_info') as logged, mock.patch.object(E, 'log_error'):
            result = self.engine.run_single_node({'id': 'n', 'type': 'if_image',
                                                 'outputLogs': {'false': 'no match'}})
            self.assertEqual(result['port'], 'false')
            self.assertEqual(self.user_messages(logged), ['no match'])

    def test_start_and_condition_logs_in_real_graph_walk(self):
        graph = {'nodes': [
            {'id': 's', 'type': 'start', 'log': 'start in', 'outputLogs': {'out': 'start out'}},
            {'id': 'c', 'type': 'if_image', 'outputLogs': {'true': 'yes', 'false': 'no'}},
            {'id': 'e', 'type': 'end', 'outputLogs': {'$done': 'end'}},
        ], 'edges': [{'from': 's', 'fromPort': 'out', 'to': 'c'},
                     {'from': 'c', 'fromPort': 'false', 'to': 'e'}]}
        self.engine._eval_condition = mock.Mock(return_value=False)
        with mock.patch.object(E, 'log_info') as logged:
            self.engine._run_graph(graph)
            self.assertEqual(self.user_messages(logged), ['start in', 'start out', 'no', 'end'])

    def test_parallel_logs_only_wired_branches(self):
        graph = {'nodes': [{'id': 's', 'type': 'start'},
                           {'id': 'p', 'type': 'parallel', 'params': {'count': 3},
                            'outputLogs': {'1': 'arm one', '2': 'unused', '3': 'arm three'}},
                           {'id': 'a', 'type': 'end'}, {'id': 'b', 'type': 'end'}],
                 'edges': [{'from': 's', 'to': 'p'}, {'from': 'p', 'fromPort': '1', 'to': 'a'},
                           {'from': 'p', 'fromPort': '3', 'to': 'b'}]}
        with mock.patch.object(E, 'log_info') as logged:
            self.engine._run_graph(graph)
            self.assertCountEqual(self.user_messages(logged), ['arm one', 'arm three'])


if __name__ == '__main__':
    unittest.main()
