import threading
import unittest
from unittest import mock

from src.workflow import engine as E


class TestDelayAfterFind(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(E, 'ADBGameAutomation'):
            self.engine = E.WorkflowEngine()
        self.events = []
        self.engine._sleep = mock.Mock(side_effect=lambda seconds: self.events.append(('wait', seconds)))
        self.engine.auto.tap.side_effect = lambda x, y, tap_count=1: self.events.append(('tap', x, y, tap_count)) or True
        self.engine._wait_for_template = mock.Mock(side_effect=lambda *a, **kw: self.events.append(('find',)) or (10, 20))
        self.engine._wait_any = mock.Mock(side_effect=lambda *a, **kw: self.events.append(('find',)) or (10, 20))

    def test_image_waits_after_match_then_taps_with_offset_and_double_tap(self):
        self.assertTrue(self.engine._eval_condition('tap_image', {
            'template': 'one.png', 'timeout': 3, 'delayAfterFind': 1.25,
            'offsetX': 2, 'offsetY': -3, 'taps': '2',
        }))
        self.assertEqual(self.events, [('find',), ('wait', 1.25), ('tap', 12, 17, 2)])
        self.assertEqual(self.engine._last_pos, (10, 20))
        self.engine._wait_for_template.assert_called_once_with('one.png', timeout=3, threshold=.85, region=None)

    def test_any_image_modes_wait_after_match(self):
        for mode in ('sequential', 'parallel'):
            with self.subTest(mode=mode):
                self.events.clear()
                self.assertTrue(self.engine._eval_condition('tap_image_any', {
                    'templates': ['one.png', 'two.png'], 'mode': mode, 'delayAfterFind': .5,
                }))
                self.assertEqual(self.events, [('find',), ('wait', .5), ('tap', 10, 20, 1)])
                self.assertEqual(self.engine._wait_any.call_args.kwargs['parallel'], mode == 'parallel')

    def test_missing_zero_and_invalid_delay_do_not_wait(self):
        for value in (None, '', 0, -1, 'bad', [], {}, float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value):
                self.engine._sleep.reset_mock()
                self.assertTrue(self.engine._eval_condition('tap_image', {'delayAfterFind': value}))
                self.engine._sleep.assert_not_called()
        self.engine._sleep.reset_mock()
        self.assertTrue(self.engine._eval_condition('tap_image', {}))
        self.engine._sleep.assert_not_called()
        self.assertEqual(self.engine._after_find_seconds({'delayAfterFind': '0.25'}), .25)

    def test_misses_never_wait_or_tap(self):
        self.engine._wait_for_template = mock.Mock(return_value=None)
        self.engine._wait_any = mock.Mock(return_value=None)
        self.engine.auto.find_all_templates.return_value = []
        self.engine.auto.region_find_text.return_value = (False, '')
        self.engine._find_color = mock.Mock(return_value=None)
        for kind in ('tap_image', 'tap_image_any', 'tap_all_images', 'tap_text', 'tap_color'):
            with self.subTest(kind=kind):
                self.assertFalse(self.engine._eval_condition(kind, {
                    'template': 'one.png', 'text': 'OK', 'color': '#ff0000',
                    'timeout': 0, 'delayAfterFind': 2,
                }))
        self.engine._sleep.assert_not_called()
        self.engine.auto.tap.assert_not_called()

    def test_text_and_color_wait_before_tap(self):
        self.engine.auto.region_find_text.return_value = (True, 'OK')
        self.assertTrue(self.engine._eval_condition('tap_text', {
            'text': 'OK', 'x': 10, 'y': 20, 'w': 40, 'h': 20, 'delayAfterFind': .75,
        }))
        self.assertEqual(self.events, [('wait', .75), ('tap', 30, 30, 1)])
        self.events.clear()
        self.engine._find_color = mock.Mock(return_value=(50, 60))
        self.assertTrue(self.engine._eval_condition('tap_color', {'color': '#ff0000', 'delayAfterFind': .75}))
        self.assertEqual(self.events, [('wait', .75), ('tap', 50, 60, 1)])

    def test_all_images_waits_once_and_preserves_between_delay(self):
        self.engine.auto.find_all_templates.return_value = [(10, 20, .9), (30, 40, .95)]
        self.engine._tpl_wh = mock.Mock(return_value=(10, 10))
        self.assertTrue(self.engine._eval_condition('tap_all_images', {
            'template': 'one.png', 'delayAfterFind': 2, 'delayBetween': .1,
        }))
        self.assertEqual(self.events, [
            ('wait', 2), ('tap', 10, 20, 1), ('wait', .1), ('tap', 30, 40, 1), ('wait', .1),
        ])

    def test_stop_during_wait_prevents_tap(self):
        self.engine._sleep.side_effect = lambda seconds: self.engine.stop()
        self.assertFalse(self.engine._eval_condition('tap_image', {'delayAfterFind': 2}))
        self.engine.auto.tap.assert_not_called()

    def test_pause_after_wait_blocks_tap_until_resume(self):
        reached_pause = threading.Event()
        def sleep(seconds):
            self.engine._pause.clear()
            reached_pause.set()
        self.engine._sleep.side_effect = sleep
        result = []
        worker = threading.Thread(target=lambda: result.append(self.engine._eval_condition('tap_image', {'delayAfterFind': 2})))
        worker.start()
        try:
            self.assertTrue(reached_pause.wait(1))
            self.engine.auto.tap.assert_not_called()
        finally:
            self.engine._pause.set()
            worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [True])
        self.engine.auto.tap.assert_called_once()

    def test_stop_while_paused_prevents_tap(self):
        reached_pause = threading.Event()
        def sleep(seconds):
            self.engine._pause.clear()
            reached_pause.set()
        self.engine._sleep.side_effect = sleep
        worker = threading.Thread(target=lambda: self.engine._eval_condition('tap_image', {'delayAfterFind': 2}))
        worker.start()
        self.assertTrue(reached_pause.wait(1))
        self.engine.stop()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.engine.auto.tap.assert_not_called()

    def test_sequence_keeps_before_and_after_tap_waits_separate(self):
        self.engine._sequence_delay = mock.Mock(side_effect=lambda event, seconds: self.events.append(('wait', seconds)) or False)
        self.assertTrue(self.engine._a_sequence_tap_image({}, {'images': [
            {'template': 'one.png', 'delayAfterFind': .5, 'delay': .25},
            {'template': 'two.png', 'delayAfterFind': 1.5, 'delay': .75},
        ]}))
        self.assertEqual(self.events, [
            ('find',), ('wait', .5), ('tap', 10, 20, 1), ('wait', .25),
            ('find',), ('wait', 1.5), ('tap', 10, 20, 1), ('wait', .75),
        ])

    def test_sequence_stop_during_after_find_wait_cancels_successfully(self):
        def cancel(event, seconds):
            event.set()
            return True
        self.engine._sequence_delay = mock.Mock(side_effect=cancel)
        self.assertTrue(self.engine._a_sequence_tap_image({}, {'images': [
            {'template': 'one.png', 'delayAfterFind': 2, 'delay': 1},
        ]}))
        self.engine.auto.tap.assert_not_called()
        self.engine._sequence_delay.assert_called_once()

    def test_global_stop_during_sequence_after_find_wait_prevents_tap(self):
        def cancel(event, seconds):
            self.engine.stop()
            return False
        self.engine._sequence_delay = mock.Mock(side_effect=cancel)
        self.assertFalse(self.engine._a_sequence_tap_image({}, {'images': [
            {'template': 'one.png', 'delayAfterFind': 2},
        ]}))
        self.engine.auto.tap.assert_not_called()

    def test_stop_sequence_can_interrupt_a_paused_wait(self):
        waiting = threading.Event()
        original = self.engine._sequence_delay
        def wait(event, seconds):
            self.engine._pause.clear()
            waiting.set()
            return original(event, seconds)
        self.engine._sequence_delay = wait
        result = []
        worker = threading.Thread(target=lambda: result.append(self.engine._a_sequence_tap_image({}, {
            'sequenceId': 'test', 'images': [{'template': 'one.png', 'delayAfterFind': 10}],
        })))
        worker.start()
        try:
            self.assertTrue(waiting.wait(1))
            self.engine._a_stop_sequence({}, {'sequenceId': 'test'})
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result, [True])
            self.engine.auto.tap.assert_not_called()
        finally:
            self.engine.stop()
            worker.join(1)


if __name__ == '__main__':
    unittest.main()
