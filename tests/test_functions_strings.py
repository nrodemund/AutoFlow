import unittest
from autoflow.engine import Engine, GraphError
from autoflow.registry import discover


def document():
    return {'version':1,'schema_revision':3,'main':'Main','graphs':{
        'Main': {'entry':'call','parameters':{},'outputs':{'greeting':{'ref':['call','greeting']},'length':{'ref':['call','length']}},'nodes':{
            'call':{'type':'FunctionCall','function':'Greet','inputs':{'name':'Ada'}}}},
        'Greet': {'entry':'return','parameters':{'name':'string'},'return_types':{'greeting':'string','length':'integer'},'outputs':{},'nodes':{
            'name':{'type':'FunctionParameter','parameter':'name','inputs':{}},
            'append':{'type':'StringAppend','inputs':{'a':'Hello ','b':{'ref':['name','value']}}},
            'length':{'type':'StringLength','inputs':{'text':{'ref':['name','value']}}},
            'return':{'type':'FunctionReturn','inputs':{'greeting':{'ref':['append','result']},'length':{'ref':['length','length']}}}}}}}


class FunctionTests(unittest.TestCase):
    def test_typed_parameters_and_multiple_returns(self):
        self.assertEqual(Engine(document(),discover()).run(),{'greeting':'Hello Ada','length':3})

    def test_type_and_signature_errors(self):
        p=document();p['graphs']['Main']['nodes']['call']['inputs']['name']=123
        with self.assertRaisesRegex(GraphError,'string'): Engine(p,discover()).run()
        p=document();del p['graphs']['Main']['nodes']['call']['inputs']['name']
        with self.assertRaisesRegex(GraphError,'missing inputs'): Engine(p,discover())
        p=document();p['graphs']['Greet']['nodes']['return']['inputs']['length']='wrong'
        with self.assertRaisesRegex(GraphError,'integer'): Engine(p,discover()).run()
        p=document();p['graphs']['Main']['nodes']['call']['function']='Missing'
        with self.assertRaisesRegex(ValueError,'Unknown function'): Engine(p,discover())

    def test_return_exits_loop_and_function(self):
        p=document();g=p['graphs']['Greet'];g['entry']='loop'
        g['nodes']['loop']={'type':'Repeat','inputs':{'count':5},'next':{'body':'return','completed':'bad'}}
        g['nodes']['bad']={'type':'StringLeft','inputs':{'text':'x','length':-1}}
        self.assertEqual(Engine(p,discover()).run()['greeting'],'Hello Ada')

    def test_legacy_call_and_recursion_limit(self):
        p=document();p['graphs']['Main']['nodes']['call']={'type':'CallFunction','inputs':{'graph':'Greet','arguments':{'name':'Bob'}}}
        p['graphs']['Main']['outputs']={'value':{'ref':['call','result']}}
        self.assertEqual(Engine(p,discover()).run()['value'],{'greeting':'Hello Bob','length':3})
        p=document();g=p['graphs']['Greet'];g['entry']='again';g['nodes']['again']={'type':'FunctionCall','function':'Greet','inputs':{'name':'Ada'}}
        with self.assertRaisesRegex(GraphError,'depth limit'): Engine(p,discover(),max_depth=4).run()

    def test_zero_returns_and_comments(self):
        p=document();g=p['graphs']['Greet'];g['return_types']={};g['nodes']['return']['inputs']={}
        p['graphs']['Main']['outputs']={};g['comments']=[{'text':'Notes','position':[0,0],'size':[300,200]}]
        self.assertEqual(Engine(p,discover()).run(),{})


class StringTests(unittest.TestCase):
    def test_regex_match(self):
        registry=discover()
        for text,pattern,expected in [('ABC12',r'[A-Z]+\d{2}',True),
                                      ('ABC',r'[A-Z]+\d{2}',False),
                                      ('x123y',r'\d+',False),('123',r'\d+',True),
                                      ('123\n',r'\d+',False),
                                      ('abc','(?i)ABC',True),
                                      ('','',True),('abc','',False),('',r'\d+',False),
                                      ('abc','[',False),('abc','(',False),
                                      ('abc',r'\q',False),('aaa','a{3,2}',False)]:
            with self.subTest(text=text,pattern=pattern):
                doc={'version':1,'schema_revision':3,'main':'Main','graphs':{
                    'Main':{'entry':'regex','parameters':{},
                            'outputs':{'matches':{'ref':['regex','result']}},
                            'nodes':{'regex':{'type':'StringRegexMatch','inputs':{'text':text,'pattern':pattern}}}}}}
                self.assertEqual(Engine(doc,registry).run(),{'matches':expected})

    def test_string_operations(self):
        registry=discover()
        cases=[('StringAppend',{'a':'a','b':'b'},'ab'),('StringLeft',{'text':'abc','length':2},'ab'),
               ('StringRight',{'text':'abc','length':0},''),('StringRight',{'text':'abc','length':2},'bc'),
               ('StringContains',{'text':'Straße','query':'STRASSE','case_sensitive':False},True),
               ('StringLength',{'text':'a😀'},2),('StringSubstring',{'text':'abcdef','start':-3,'length':2},'de'),
               ('StringReplace',{'text':'aba','old':'a','new':'x'},'xbx'),
               ('StringSplit',{'text':'a,b','separator':','},['a','b']),
               ('StringJoin',{'parts':['a','b'],'separator':'/'},'a/b'),
               ('StringStartsWith',{'text':'abc','prefix':'a'},True),('StringEndsWith',{'text':'abc','suffix':'c'},True),
               ('StringFind',{'text':'abc','query':'z'},-1),('StringTrim',{'text':' a '},'a'),
               ('StringUpper',{'text':'ab'},'AB'),('StringLower',{'text':'AB'},'ab')]
        for name,inputs,expected in cases:
            node=registry[name];result,_=node.execute(None,'',node.defaults|inputs)
            self.assertEqual(next(iter(result.values())),expected,name)
        for name in ('StringLeft','StringRight','StringSubstring'):
            node=registry[name]
            with self.assertRaises(ValueError):node.execute(None,'',node.defaults|{'length':-1})
