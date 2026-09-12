"""Unicode string operations with Python slicing and search semantics."""
from autoflow.registry import NodeType


def count(value):
    if value < 0: raise ValueError('Length must be nonnegative')
    return value


def node(name, inputs, outputs, operation, defaults):
    return NodeType(name, inputs, outputs, (), lambda c, n, i: (operation(i), None),
                    pure=True, defaults=defaults, category='Strings', title=name.replace('String', 'String '))


NODES = [
    node('StringAppend', {'a':'string','b':'string'}, {'result':'string'}, lambda i: {'result':i['a']+i['b']}, {'a':'','b':''}),
    node('StringLeft', {'text':'string','length':'integer'}, {'result':'string'}, lambda i: {'result':i['text'][:count(i['length'])]}, {'text':'','length':1}),
    node('StringRight', {'text':'string','length':'integer'}, {'result':'string'}, lambda i: {'result':i['text'][-count(i['length']):] if i['length'] else ''}, {'text':'','length':1}),
    node('StringContains', {'text':'string','query':'string','case_sensitive':'bool'}, {'result':'bool'},
         lambda i: {'result':i['query'] in i['text'] if i['case_sensitive'] else i['query'].casefold() in i['text'].casefold()}, {'text':'','query':'','case_sensitive':True}),
    node('StringLength', {'text':'string'}, {'length':'integer'}, lambda i: {'length':len(i['text'])}, {'text':''}),
    node('StringSubstring', {'text':'string','start':'integer','length':'integer'}, {'result':'string'},
         lambda i: {'result':i['text'][i['start']:][:count(i['length'])]}, {'text':'','start':0,'length':1}),
    node('StringReplace', {'text':'string','old':'string','new':'string'}, {'result':'string'},
         lambda i: {'result':i['text'].replace(i['old'],i['new'])}, {'text':'','old':'','new':''}),
    node('StringSplit', {'text':'string','separator':'string'}, {'parts':'reference:list'},
         lambda i: {'parts':i['text'].split(i['separator'])}, {'text':'','separator':','}),
    node('StringJoin', {'parts':'reference:list','separator':'string'}, {'result':'string'},
         lambda i: {'result':i['separator'].join(i['parts'])}, {'parts':[],'separator':','}),
    node('StringStartsWith', {'text':'string','prefix':'string'}, {'result':'bool'}, lambda i: {'result':i['text'].startswith(i['prefix'])}, {'text':'','prefix':''}),
    node('StringEndsWith', {'text':'string','suffix':'string'}, {'result':'bool'}, lambda i: {'result':i['text'].endswith(i['suffix'])}, {'text':'','suffix':''}),
    node('StringFind', {'text':'string','query':'string'}, {'index':'integer'}, lambda i: {'index':i['text'].find(i['query'])}, {'text':'','query':''}),
] + [node('String'+name, {'text':'string'}, {'result':'string'}, lambda i, op=op: {'result':op(i['text'])}, {'text':''})
     for name, op in [('Trim',str.strip),('Upper',str.upper),('Lower',str.lower)]]
