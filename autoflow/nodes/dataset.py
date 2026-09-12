"""Modular dataset nodes, shared by all function graphs in a run."""
from copy import deepcopy
from pathlib import Path
from autoflow import datasets as ds
from autoflow.registry import NodeType


def execute(operation):
    def run(context, node_id, inputs):
        table = inputs['dataset']
        if not isinstance(table, ds.Dataset): raise ValueError('Connect a Dataset object from GetDataset')
        if operation == 'LoadDataset':
            loaded, _ = ds.read((context.engine.base_dir / inputs['path']).read_bytes(), Path(inputs['path']).suffix, inputs['sheet'] or None)
            table.clear()
            table.update(loaded)
            return {}, 'then'
        if operation == 'DatasetToDict': return {'result': {i: deepcopy(row) for i, row in enumerate(table['rows'])}}, None
        if operation == 'DatasetToSet': return {'result': {tuple(row[c] for c in table['columns']) for row in table['rows']}}, None
        if operation == 'GetRow': return {'row': deepcopy(ds.row_at(table, inputs['index']))}, None
        if operation == 'GetField': return {'value': ds.row_at(table, inputs['index'])[ds.column(table, inputs['column'])]}, None
        if operation == 'GetRows': return {'rows': deepcopy(table['rows'])}, None
        if operation == 'RowCount': return {'count': len(table['rows'])}, None
        if operation == 'FindRows':
            col = ds.column(table, inputs['column'])
            indices = [i for i,r in enumerate(table['rows']) if str(inputs['query']).casefold() in str(r[col]).casefold()]
            return {'indices': indices}, None
        updated = deepcopy(table)
        if operation == 'SetField': ds.row_at(updated, inputs['index'])[ds.column(updated, inputs['column'])] = inputs['value']
        elif operation == 'SetRow':
            ds.row_at(updated, inputs['index'])
            updated['rows'][inputs['index']] = deepcopy(inputs['row'])
        elif operation == 'AppendRow': updated['rows'].append(deepcopy(inputs['row']))
        elif operation == 'DeleteRow':
            ds.row_at(updated, inputs['index'])
            del updated['rows'][inputs['index']]
        elif operation == 'SortDataset': ds.sort(updated, inputs['column'], inputs['descending'])
        elif operation == 'SaveDataset':
            path = context.engine.base_dir / inputs['path']
            path.write_bytes(ds.write(table, path.suffix.lower()))
            return {}, 'then'
        ds.validate(updated)
        table.clear()
        table.update(updated)
        return {}, 'then'
    return run


NODES = [NodeType('GetDataset', {'name': 'string'}, {'dataset': 'reference:Dataset'}, (),
                  lambda c, n, i: ({'dataset': ds.get_dataset(c.engine.project, i['name'])}, None),
                  'Get a shared dataset object by name. Drag a dataset from the sidebar to create this node.',
                  defaults={'name': 'Data'}, pure=True, title='Get Dataset', category='Datasets')]
for name, inputs, outputs, defaults in [
    ('DatasetToDict', {}, {'result':'dict'}, {}),
    ('DatasetToSet', {}, {'result':'set'}, {}),
    ('GetRow', {'index':'integer'}, {'row':'dict'}, {'index':0}),
    ('GetField', {'index':'integer','column':'string'}, {'value':'reference'}, {'index':0,'column':''}),
    ('GetRows', {}, {'rows':'reference:list'}, {}),
    ('RowCount', {}, {'count':'integer'}, {}),
    ('FindRows', {'column':'string','query':'string'}, {'indices':'reference:list'}, {'column':'','query':''}),
    ('SetField', {'index':'integer','column':'string','value':'reference'}, {}, {'index':0,'column':'','value':''}),
    ('SetRow', {'index':'integer','row':'dict'}, {}, {'index':0,'row':{}}),
    ('AppendRow', {'row':'dict'}, {}, {'row':{}}),
    ('DeleteRow', {'index':'integer'}, {}, {'index':0}),
    ('SortDataset', {'column':'string','descending':'bool'}, {}, {'column':'','descending':False}),
    ('LoadDataset', {'path':'string','sheet':'string'}, {}, {'path':'data.csv','sheet':''}),
    ('SaveDataset', {'path':'string'}, {}, {'path':'data.xlsx'}),
]:
    NODES.append(NodeType(name, {'dataset':'reference:Dataset', **inputs}, outputs, () if outputs else ('then',), execute(name),
                          defaults=defaults, pure=bool(outputs), category='Datasets',
                          description='Connect a Dataset object from GetDataset. Row indices start at 0. Load/Save support CSV and XLSX.'))


NODES.append(NodeType('GetRowField', {'row': 'dict', 'column': 'string'}, {'value': 'reference'}, (),
                      lambda c, n, i: ({'value': i['row'][i['column']]}, None),
                      'Read a named field from a row supplied by For Each Row or Get Row.',
                      defaults={'column': ''}, pure=True, title='Get Row Field', category='Datasets'))
