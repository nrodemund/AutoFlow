import io
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from autoflow import datasets as ds, bundles
from autoflow.engine import Engine, load_project
from autoflow.registry import discover
from autoflow.server import Editor

ROOT = Path(__file__).resolve().parents[1]
class DatasetTests(unittest.TestCase):
    def test_csv_preserves_text(self):
        table,_=ds.read('code,name\n001,"Ada, É"\n002,Bob\n'.encode(),'.csv')
        self.assertEqual(table['rows'][0],{'code':'001','name':'Ada, É'})
        self.assertEqual(ds.read(ds.write(table,'.csv'),'.csv')[0],table)
    def test_excel_types_and_formula_text(self):
        table={'columns':['text','number','flag','empty'],'rows':[{'text':'=1+1','number':2.5,'flag':True,'empty':None}]}
        self.assertEqual(ds.read(ds.write(table,'.xlsx'),'.xlsx')[0],table)
    def test_validation_and_indices(self):
        for table in [{'columns':['x','x'],'rows':[]},{'columns':['x'],'rows':[{'x':[]}]}]:
            with self.assertRaises(ValueError): ds.validate(table)
        for i in [-1,True,1]:
            with self.assertRaises(ValueError): ds.row_at({'rows':[{}]},i)
    def test_sort(self):
        table={'columns':['x'],'rows':[{'x':10},{'x':2},{'x':None}]}
        ds.sort(table,'x');self.assertEqual([r['x'] for r in table['rows']],[None,2,10])
    def test_graph_mutates_shared_dataset(self):
        p=load_project(ROOT/'examples/dataset-demo.json');messages=[]
        engine=Engine(p,discover(),log=messages.append);engine.run()
        self.assertEqual(messages,['Ada','Linus'])
        self.assertEqual([r['status'] for r in engine.project['datasets']['Data']['rows']],['processed']*2)
        self.assertEqual(p['datasets']['Data']['rows'][0]['status'],'pending')
    def test_node_mutations_and_fresh_reads(self):
        from types import SimpleNamespace
        registry=discover();engine=SimpleNamespace(project={'datasets':{'Data':{'columns':['x'],'rows':[{'x':1}]}}})
        context=SimpleNamespace(engine=engine)
        def call(name,**inputs):
            node=registry[name];return node.execute(context,'test',node.defaults|{'dataset':ds.get_dataset(engine.project,'Data')}|inputs)[0]
        call('SetField',column='x',value=7);self.assertEqual(call('GetField',column='x')['value'],7)
        call('AppendRow',row={'x':8});self.assertEqual(call('RowCount')['count'],2)
        self.assertEqual(call('FindRows',column='x',query='8')['indices'],[1])
        call('DeleteRow',index=0);self.assertEqual(call('GetRow')['row'],{'x':8})
    def test_bundle_contains_dataset_and_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'assets').mkdir();(root/'assets/t.png').write_bytes(b'asset')
            p=load_project(ROOT/'examples/dataset-demo.json');ds.validate_all(p['datasets']);p['texture']='assets/t.png'
            raw=bundles.export(p,root)
            with ZipFile(io.BytesIO(raw)) as z:self.assertEqual(len([n for n in z.namelist() if n.startswith('assets/')]),1)
            restored=bundles.unpack(raw,root,lambda p:ds.validate_all(p['datasets']))
            self.assertEqual(restored['datasets'],p['datasets']);self.assertEqual((root/restored['texture']).read_bytes(),b'asset')
    def test_bundle_rejects_traversal(self):
        stream=io.BytesIO()
        with ZipFile(stream,'w') as z:z.writestr('../evil','x');z.writestr('project.json','{}')
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):bundles.unpack(stream.getvalue(),d,lambda p:None)
    def test_run_result(self):
        import time
        from autoflow.engine import SimulationScreen
        with tempfile.TemporaryDirectory() as d:
            editor=Editor(d,screen_factory=lambda _:SimulationScreen())
            project=load_project(ROOT/'examples/dataset-demo.json')
            project['graphs'][project['main']]['run_settings']={'start_delay':0}
            run_id=editor.run(project,{})
            for _ in range(100):
                if not editor.running:break
                time.sleep(.01)
            self.assertEqual(editor.results[run_id]['Data']['rows'][0]['status'],'processed')
