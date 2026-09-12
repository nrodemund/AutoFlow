const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('autoflow/web/app.js', 'utf8');
vm.runInThisContext("const object = v => v !== null && typeof v === 'object' && !Array.isArray(v); const typeBase = t => (t || 'reference').replace('?', '');");
for (const [start, end] of [['function parseLiteral(', 'function valueEditor('],
                           ['function datasetColumnType(', 'function renderDatasetTable(']]) {
  vm.runInThisContext(source.slice(source.indexOf(start), source.indexOf(end)));
}
for (const [values, expected] of [[[], 'string'], [[null], 'string'], [['001', '002'], 'string'],
  [['1', '2'], 'integer'], [['1', '2.5'], 'float'], [[true, false], 'bool'],
  [[1, 'maybe'], 'string'], [[{$type: 'bytes', value: '/w=='}], 'bytes']]) {
  assert.equal(datasetColumnType({rows: values.map(x => ({x}))}, 'x'), expected);
}
assert.equal(datasetCellValue('1.5', 'float'), 1.5);
assert.equal(datasetCellValue('12', 'integer'), 12);
assert.equal(datasetCellValue('true', 'bool'), true);
assert.equal(datasetCellValue(null, 'string'), '');
assert.throws(() => datasetCellValue('1.5', 'integer'));
assert.throws(() => datasetCellValue('maybe', 'bool'));
assert.throws(() => datasetCellValue('Infinity', 'float'));
assert.deepEqual(parseLiteral('[1,2]', 'set'), {$type: 'set', value: [1, 2]});
assert.deepEqual(parseLiteral('[1,2]', 'reference:tuple'), {$type: 'tuple', value: [1, 2]});
assert.deepEqual(parseLiteral('hi', 'bytes'), {$type: 'bytes', value: 'aGk='});
assert.deepEqual(parseLiteral('{"$type":"bytes","value":"/w=="}', 'bytes'), {$type: 'bytes', value: '/w=='});
console.log('Datatype editor checks passed');

// A stale server must report the missing node without changing history or data.
const context = {catalog: {}, reported: null, report(error) { this.reported = error; }};
vm.createContext(context);
vm.runInContext('let message; function kind(node) { return catalog[node.type]; } function report(error) { message = error.message; }', context);
vm.runInContext(source.slice(source.indexOf('function addNode('), source.indexOf('function renderGraphs(')), context);
vm.runInContext("addNode('GetDataset', undefined, {name:'Data'});", context);
assert.match(vm.runInContext('message', context), /Restart AutoFlow/);
console.log('Stale node catalog check passed');
