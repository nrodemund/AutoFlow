import threading
import time
import unittest
from autoflow.engine import Engine, GraphError
from autoflow.registry import discover
from autoflow.run_control import settings


class RunControlTests(unittest.TestCase):
    def engine(self):
        return Engine({'version':1,'main':'Main','graphs':{'Main':{'entry':'status','nodes':{
            'status':{'type':'SetRunStatus','inputs':{'text':'Working'},'next':{'then':'wait'}},
            'wait':{'type':'Wait','inputs':{'milliseconds':20}}}}}},discover())

    def test_pause_blocks_execution_until_resumed(self):
        engine=self.engine();engine.toggle_pause()
        worker=threading.Thread(target=engine.run);worker.start()
        try:
            time.sleep(.1)
            self.assertTrue(engine.paused);self.assertEqual(engine.steps,0)
            engine.toggle_pause();worker.join(1)
            self.assertFalse(worker.is_alive());self.assertEqual(engine.status_text,'Working')
        finally:
            engine.cancel.set();worker.join(1)

    def test_stop_unblocks_pause(self):
        engine=self.engine();engine.toggle_pause();errors=[]
        def run():
            try:engine.run()
            except GraphError as error:errors.append(str(error))
        worker=threading.Thread(target=run);worker.start();time.sleep(.06)
        engine.cancel.set();worker.join(1)
        self.assertFalse(worker.is_alive());self.assertIn('cancelled',errors[0])

    def test_settings_validation(self):
        for bad in ({'pause_key':'F9'},{'start_delay':-1},{'overlay':'yes'},{'pause_key':'A'},{'position':'center'},
                    {'debug_capture_key':'F9'}, {'debug_resume_key':'A'}, {'debug_delay_key':'F10'}):
            with self.assertRaises(ValueError):settings({'main':'Main','graphs':{'Main':{'run_settings':bad}}})
        self.assertEqual(settings({})['stop_key'],'F9')
        self.assertEqual(settings({})['debug_capture_key'],'F6')
        self.assertEqual(settings({})['debug_resume_key'],'F10')
        self.assertEqual(settings({})['debug_delay_key'],'Shift+F10')
