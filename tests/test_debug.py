import threading
import time
import unittest
from unittest.mock import Mock

from autoflow.engine import Engine, GraphError
from autoflow.registry import discover
from autoflow.server import Editor


def project(nodes, entry='target', outputs=None):
    return {'version': 1, 'schema_revision': 3, 'main': 'Main', 'graphs': {
        'Main': {'entry': entry, 'nodes': nodes, 'outputs': outputs or {}}}}


class DebugTests(unittest.TestCase):
    def start(self, document, screen=None):
        logs, errors, results = [], [], []
        engine = Engine(document, discover(), screen=screen, log=logs.append)
        def run():
            try:
                results.append(engine.run())
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        self.addCleanup(lambda: (engine.cancel.set(), worker.join(1)))
        return engine, worker, logs, errors, results

    def waiting(self, engine, previous=None):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with engine.debug_lock:
                request = engine.debug_request
                if request and request['id'] != previous:
                    return request
            time.sleep(.005)
        self.fail('No debug breakpoint appeared')

    def test_pauses_before_execution_and_requires_explicit_continue(self):
        engine, worker, logs, errors, _ = self.start(project({
            'target': {'type': 'Print', 'debug': True, 'inputs': {'value': 'hello'}}}))
        request = self.waiting(engine)
        self.assertEqual(logs, [])
        self.assertEqual(request['graph'], 'Main')
        self.assertEqual(request['inputs'][0]['value'], "'hello'")
        engine.toggle_pause()
        self.assertTrue(worker.is_alive())
        self.assertTrue(engine.resumed.is_set())
        with self.assertRaises(ValueError): engine.continue_debug('stale')
        engine.continue_debug(request['id'])
        with self.assertRaises(ValueError): engine.continue_debug(request['id'])
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(logs, ['hello'])
        self.assertEqual(errors, [])
        self.assertIsNone(engine.debug_request)

    def test_click_preview_moves_without_clicking_and_stop_cancels(self):
        screen = Mock()
        engine, worker, _, errors, _ = self.start(project({
            'target': {'type': 'Click', 'debug': True, 'inputs': {'point': {'x': 80, 'y': -20}}}}), screen)
        request = self.waiting(engine)
        screen.move.assert_called_once_with({'x': 80, 'y': -20})
        screen.click.assert_not_called()
        self.assertIn('No click sent', request['preview'])
        engine.cancel.set(); worker.join(1)
        screen.click.assert_not_called()
        self.assertIsNone(engine.debug_request)
        self.assertIn('cancelled', str(errors[0]))

    def test_continue_click_executes_once_after_preview(self):
        screen = Mock()
        engine, worker, _, errors, _ = self.start(project({
            'target': {'type': 'Click', 'debug': True, 'inputs': {'point': {'x': 1, 'y': 2}}}}), screen)
        request = self.waiting(engine)
        screen.click.assert_not_called()
        engine.continue_debug(request['id']); worker.join(1)
        screen.click.assert_called_once_with(1, 2)
        self.assertEqual(errors, [])

    def test_preview_failure_is_inspectable_and_does_not_execute(self):
        screen = Mock(); screen.move.side_effect = ValueError('No desktop')
        engine, worker, _, _, _ = self.start(project({
            'target': {'type': 'Click', 'debug': True, 'inputs': {}}}), screen)
        request = self.waiting(engine)
        self.assertIn('No desktop', request['preview'])
        screen.click.assert_not_called()
        engine.cancel.set(); worker.join(1)

    def test_offset_point_tracks_mouse_relative_to_base_without_changing_output(self):
        screen = Mock()
        screen.cursor_position.return_value = {'x': -80, 'y': 230}
        engine, worker, _, errors, results = self.start(project({
            'start': {'type': 'Start', 'inputs': {}},
            'target': {'type': 'OffsetPoint', 'debug': True, 'inputs': {
                'point': {'x': -100, 'y': 200}, 'x': 20, 'y': 30}}},
            entry='start', outputs={'point': {'ref': ['target', 'point']}}), screen)
        request = self.waiting(engine)
        screen.move.assert_called_once_with({'x': -80, 'y': 230})
        self.assertIn('Offset from base: X = +20, Y = +30', request['preview'])
        screen.cursor_position.return_value = {'x': -130, 'y': 215}
        deadline = time.monotonic() + 1
        while 'X = -30, Y = +15' not in request['preview'] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIn('Offset from base: X = -30, Y = +15', request['preview'])
        self.assertIn('Change from configured offset: X = -50, Y = -15', request['preview'])
        screen.move.assert_called_once()
        screen.click.assert_not_called()
        engine.continue_debug(request['id']); worker.join(1)
        self.assertEqual(errors, [])
        self.assertEqual(results, [{'point': {'x': -80, 'y': 230}}])
        self.assertIsNone(engine.debug_request)

    def test_offset_live_read_failure_keeps_breakpoint_stoppable(self):
        screen = Mock()
        screen.cursor_position.return_value = {'x': 0, 'y': 0}
        engine, worker, _, errors, _ = self.start(project({
            'target': {'type': 'OffsetPoint', 'debug': True, 'inputs': {}}}), screen)
        request = self.waiting(engine)
        screen.cursor_position.side_effect = RuntimeError('Cursor unavailable')
        deadline = time.monotonic() + 1
        while 'unavailable' not in request['preview'] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIn('Live preview unavailable', request['preview'])
        engine.cancel.set(); worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertIn('cancelled', str(errors[0]))

    def test_capture_offset_updates_paused_execution_and_editor_patch(self):
        screen = Mock(); screen.cursor_position.return_value = {'x': -80, 'y': 230}
        p = project({
            'start': {'type': 'Start', 'inputs': {}},
            'target': {'type': 'OffsetPoint', 'debug': True, 'inputs': {
                'point': {'x': -100, 'y': 200}, 'x': 20, 'y': 30}}},
            entry='start', outputs={'point': {'ref': ['target', 'point']}})
        engine, worker, _, errors, results = self.start(p, screen)
        request = self.waiting(engine)
        screen.cursor_position.return_value = {'x': -115, 'y': 245}
        with self.assertRaises(ValueError):engine.capture_debug_offset('stale')
        edit = engine.capture_debug_offset(request['id'])
        self.assertEqual(edit['changes'], {'x': -15, 'y': 45})
        self.assertEqual(edit['previous'], {'x': 20, 'y': 30})
        self.assertTrue(worker.is_alive())
        self.assertEqual(request['captured'], edit['changes'])
        self.assertEqual(next(i['value'] for i in request['inputs'] if i['name'] == 'x'), '-15')
        screen.cursor_position.return_value = {'x': 999, 'y': 999}
        engine.continue_debug(request['id']); worker.join(1)
        self.assertEqual(results, [{'point': {'x': -115, 'y': 245}}])
        self.assertEqual(errors, [])
        self.assertEqual(engine.project['graphs']['Main']['nodes']['target']['inputs']['x'], -15)
        self.assertEqual(p['graphs']['Main']['nodes']['target']['inputs']['x'], 20)
        self.assertEqual(len(engine.debug_edits), 1)
        screen.move.assert_called_once()
        with self.assertRaises(ValueError):engine.capture_debug_offset(request['id'])

    def test_delayed_resume_waits_two_seconds_and_rejects_duplicate_commands(self):
        engine, worker, logs, errors, _ = self.start(project({
            'target': {'type': 'Print', 'debug': True, 'inputs': {'value': 'after delay'}}}))
        request = self.waiting(engine)
        with self.assertRaises(ValueError):engine.capture_debug_offset(request['id'])
        with self.assertRaises(ValueError):engine.continue_debug(request['id'], 1)
        began = time.monotonic()
        engine.continue_debug(request['id'], 2)
        with self.assertRaises(ValueError):engine.continue_debug(request['id'])
        worker.join(.1)
        self.assertTrue(worker.is_alive()); self.assertEqual(logs, [])
        worker.join(3)
        self.assertFalse(worker.is_alive()); self.assertGreaterEqual(time.monotonic() - began, 2)
        self.assertEqual(logs, ['after delay']); self.assertEqual(errors, [])

    def test_stop_cancels_pending_delayed_resume(self):
        engine, worker, logs, errors, _ = self.start(project({
            'target': {'type': 'Print', 'debug': True, 'inputs': {'value': 'must not run'}}}))
        request = self.waiting(engine)
        engine.continue_debug(request['id'], 2)
        engine.cancel.set(); worker.join(1)
        self.assertFalse(worker.is_alive()); self.assertEqual(logs, [])
        self.assertIn('cancelled', str(errors[0]))
        self.assertIsNone(engine.debug_request)

    def test_pure_select_debug_keeps_unused_branch_deferred(self):
        engine, worker, _, errors, results = self.start(project({
            'start': {'type': 'Start', 'inputs': {}},
            'target': {'type': 'Select', 'debug': True, 'inputs': {
                'condition': True, 'when_true': 'safe', 'when_false': {'ref': ['bad', 'result']}}},
            'bad': {'type': 'DivideInt', 'inputs': {'a': 1, 'b': 0}}},
            'start', {'result': {'ref': ['target', 'result']}}))
        request = self.waiting(engine)
        self.assertTrue(next(v for v in request['inputs'] if v['name'] == 'when_false')['deferred'])
        engine.continue_debug(request['id']); worker.join(1)
        self.assertEqual(errors, [])
        self.assertEqual(results, [{'result': 'safe'}])

    def test_breakpoint_repeats_on_loop_iterations(self):
        engine, worker, logs, errors, _ = self.start(project({
            'loop': {'type': 'Repeat', 'inputs': {'count': 2}, 'next': {'body': 'target'}},
            'target': {'type': 'Print', 'debug': True, 'inputs': {'value': {'ref': ['loop', 'index']}}}}, 'loop'))
        first = self.waiting(engine)
        self.assertEqual(first['inputs'][0]['value'], '0')
        engine.continue_debug(first['id'])
        second = self.waiting(engine, first['id'])
        self.assertEqual(second['inputs'][0]['value'], '1')
        self.assertEqual(logs, ['0'])
        engine.continue_debug(second['id']); worker.join(1)
        self.assertEqual(logs, ['0', '1'])
        self.assertEqual(errors, [])

    def test_debug_off_and_invalid_metadata(self):
        for debug in (None, False):
            node = {'type': 'Print', 'inputs': {'value': 'normal'}}
            if debug is not None: node['debug'] = debug
            engine, worker, logs, errors, _ = self.start(project({'target': node}))
            worker.join(1)
            self.assertEqual(logs, ['normal']); self.assertEqual(errors, [])
            self.assertIsNone(engine.debug_request)
        with self.assertRaisesRegex(GraphError, 'debug must be a boolean'):
            Engine(project({'target': {'type': 'Start', 'inputs': {}, 'debug': 'true'}}), discover())

    def test_function_breakpoint_reports_graph_and_bounded_input(self):
        p = project({'target': {'type': 'FunctionCall', 'function': 'Child', 'inputs': {}}})
        p['graphs']['Child'] = {'entry': 'log', 'nodes': {
            'log': {'type': 'Print', 'debug': True, 'inputs': {'value': 'x' * 10000}}}}
        engine, worker, logs, errors, _ = self.start(p)
        request = self.waiting(engine)
        self.assertEqual(request['graph'], 'Child')
        self.assertLess(len(request['inputs'][0]['value']), 600)
        # The status API publishes the snapshot without its internal control flag.
        editor = object.__new__(Editor)
        editor.engine = engine; editor.running = True; editor.run_state = 'running'; editor.active_settings = {}; editor.run_id = 'test-run'
        status = editor.status()
        self.assertEqual(status['state'], 'debug')
        self.assertEqual(status['debug']['id'], request['id'])
        self.assertNotIn('continued', status['debug'])
        engine.continue_debug(request['id']); worker.join(1)
        self.assertEqual(len(logs[0]), 10000); self.assertEqual(errors, [])
