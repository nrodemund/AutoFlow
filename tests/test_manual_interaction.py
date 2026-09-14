import threading
import time
import unittest
from autoflow.engine import Engine
from autoflow.registry import discover


class ManualInteractionTests(unittest.TestCase):
    def start(self):
        logs=[];errors=[]
        project={'version':1,'main':'Main','graphs':{'Main':{'entry':'ask','nodes':{
            'ask':{'type':'ManualInteraction','inputs':{'prompt':'Correct the entry'},'next':{'success':'ok','failed':'skip'}},
            'ok':{'type':'Print','inputs':{'value':'corrected'}},
            'skip':{'type':'Print','inputs':{'value':'review later'}}}}}}
        engine=Engine(project,discover(),log=logs.append)
        def run():
            try:engine.run()
            except Exception as error:errors.append(str(error))
        worker=threading.Thread(target=run,daemon=True);worker.start()
        for _ in range(100):
            if engine.manual_request:break
            time.sleep(.01)
        self.addCleanup(lambda:(engine.cancel.set(),worker.join(1)))
        self.assertIsNotNone(engine.manual_request)
        return engine,worker,logs,errors

    def test_explicit_choices_route_and_pause_cannot_acknowledge(self):
        for choice,expected in [('success','corrected'),('failed','review later')]:
            engine,worker,logs,errors=self.start()
            engine.toggle_pause();time.sleep(.07)
            self.assertTrue(worker.is_alive());self.assertEqual(logs,[])
            with self.assertRaises(ValueError):engine.answer_manual('stale',choice)
            request=engine.manual_request['id'];engine.answer_manual(request,choice)
            with self.assertRaises(ValueError):engine.answer_manual(request,choice)
            worker.join(1)
            self.assertEqual(logs,[expected]);self.assertEqual(errors,[])
            self.assertIsNone(engine.manual_request)

    def test_stop_never_takes_either_branch(self):
        engine,worker,logs,errors=self.start();engine.cancel.set();worker.join(1)
        self.assertEqual(logs,[]);self.assertIn('cancelled',errors[0]);self.assertIsNone(engine.manual_request)
