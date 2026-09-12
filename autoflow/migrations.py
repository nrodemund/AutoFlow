"""Upgrade existing saved graphs without overwriting their files on load."""
from copy import deepcopy


def upgrade_dataset_nodes(project):
    if project.get('schema_revision', 1) >= 3: return project
    operations = {'DatasetToDict', 'DatasetToSet', 'GetRow', 'GetField', 'GetRows', 'RowCount',
                  'FindRows', 'SetField', 'SetRow', 'AppendRow', 'DeleteRow', 'SortDataset',
                  'LoadDataset', 'SaveDataset'}
    for graph in project['graphs'].values():
        nodes = graph.get('nodes', {})
        getters = [(node.get('inputs', {}).get('name', 'Data'), key) for key, node in nodes.items()
                   if node.get('type') == 'GetDataset']
        for node_id, node in list(nodes.items()):
            if node.get('type') not in operations: continue
            inputs = node.setdefault('inputs', {})
            binding = inputs.get('dataset', 'Data')
            if isinstance(binding, dict):
                if 'ref' in binding:
                    source = nodes.get(binding['ref'][0], {})
                    if source.get('type') == 'GetDataset': continue
                if 'param' in binding and graph.get('parameters', {}).get(binding['param']) == 'reference:Dataset': continue
            getter = next((key for name, key in getters if name == binding), None)
            if getter is None:
                getter = node_id + '_dataset'
                while getter in nodes: getter += '_'
                x, y = node.get('position', [300, 100])
                nodes[getter] = {'type': 'GetDataset', 'inputs': {'name': binding}, 'position': [x - 270, y]}
                getters.append((binding, getter))
            inputs['dataset'] = {'ref': [getter, 'dataset']}
            if node['type'] == 'LoadDataset' and isinstance(binding, str):
                project.setdefault('datasets', {}).setdefault(binding, {'columns': [], 'rows': []})
    project['schema_revision'] = 3
    return project


def upgrade_project(document):
    if not isinstance(document, dict) or document.get("version") != 1 or not isinstance(document.get("graphs"), dict):
        return document
    project = deepcopy(document)
    from autoflow.datatypes import canonical
    for graph in project['graphs'].values():
        graph['parameters'] = {key: canonical(value) for key, value in graph.get('parameters', {}).items()}
    for table in project.get('datasets', {}).values():
        if 'types' in table:
            table['types'] = {key: canonical(value) for key, value in table['types'].items()}
    if project.get("schema_revision", 1) >= 2:
        return upgrade_dataset_nodes(project)
    for graph in project["graphs"].values():
        nodes = graph.get("nodes", {})
        if not isinstance(nodes, dict):
            continue
        original = list(nodes.items())
        split = {}

        def helper(base, kind, inputs, near):
            name = base
            suffix = 1
            while name in nodes:
                name = base + str(suffix)
                suffix += 1
            pos = near.get("position", [100, 100])
            nodes[name] = {"type": kind, "inputs": inputs, "position": [pos[0] - 270, pos[1] + 150]}
            return {"ref": [name, "point" if kind == "MakePoint" else "result"]}

        for node_id, node in original:
            inputs = node.setdefault("inputs", {})
            if node["type"] in ("FindOnScreen", "IfOnScreen", "IsOnScreen"):
                confidence = inputs.get("confidence")
                if type(confidence) in (int, float):
                    inputs["confidence"] = round(confidence * 100)
            if node["type"] in ("FindOnScreen", "IfOnScreen", "Offset"):
                split[node_id] = None
            if node["type"] in ("Offset", "Click") and "point" not in inputs:
                inputs["point"] = helper(node_id + "_make_point", "MakePoint",
                                         {"x": inputs.pop("x", 0), "y": inputs.pop("y", 0)}, node)
            if node["type"] == "Offset":
                inputs["offset"] = helper(node_id + "_make_offset", "MakePoint",
                                          {"x": inputs.pop("dx", 50), "y": inputs.pop("dy", 50)}, node)
            if node["type"] == "Wait" and "seconds" in inputs:
                seconds = inputs.pop("seconds")
                inputs["milliseconds"] = round(seconds * 1000) if type(seconds) in (int, float) else helper(
                    node_id + "_milliseconds", "MultiplyInt", {"a": seconds, "b": 1000}, node)

        def rewrite(value):
            if isinstance(value, dict):
                if set(value) == {"ref"} and isinstance(value["ref"], list) and len(value["ref"]) == 2:
                    source, pin = value["ref"]
                    if source in split and pin in ("x", "y"):
                        if split[source] is None:
                            binding = helper(source + "_break_point", "BreakPoint", {"point": {"ref": [source, "point"]}}, nodes[source])
                            split[source] = binding["ref"][0]
                        return {"ref": [split[source], pin]}
                return {key: rewrite(child) for key, child in value.items()}
            if isinstance(value, list):
                return [rewrite(child) for child in value]
            return value
        for node in list(nodes.values()):
            node["inputs"] = rewrite(node.get("inputs", {}))
        graph["outputs"] = rewrite(graph.get("outputs", {}))
        graph["parameters"] = {key: "integer" if value == "number" else value for key, value in graph.get("parameters", {}).items()}
    project["schema_revision"] = 2
    return upgrade_dataset_nodes(project)
