"""Portable project archives: embedded datasets and referenced texture assets."""
import io
from autoflow import datatypes as json
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from copy import deepcopy


def export(project, base):
    project = deepcopy(project)
    assets = {}
    def visit(value, texture=False):
        if isinstance(value, dict): return {k: visit(v, k == 'texture') for k,v in value.items()}
        if isinstance(value, list): return [visit(v) for v in value]
        if isinstance(value, str) and value and (texture or value.replace('\\', '/').startswith('assets/')):
            source = Path(base) / value
            raw = source.read_bytes()
            name = 'assets/' + hashlib.sha256(raw).hexdigest()[:24] + source.suffix.lower()
            assets[name] = raw
            return name
        return value
    project = visit(project)
    stream = io.BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('project.json', json.dumps(project, ensure_ascii=False, indent=2))
        for name, raw in assets.items(): archive.writestr(name, raw)
        archive.writestr('README.txt', 'Open project.json with AutoFlow, or import this ZIP in the editor. Datasets are embedded in project.json. Keep assets beside project.json.\n')
    return stream.getvalue()


def unpack(raw, base, check):
    with ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or sum(i.file_size for i in archive.infolist()) > 100_000_000: raise ValueError('Invalid or oversized project archive')
        assets = {}
        for name in names:
            if name in ('project.json', 'README.txt'): continue
            p = Path(name)
            if '\\' in name or len(p.parts) != 2 or p.parts[0] != 'assets' or p.name in ('.','..'): raise ValueError('Unsafe archive member')
            content = archive.read(name)
            assets[name] = ('assets/' + hashlib.sha256(content).hexdigest()[:24] + p.suffix.lower(), content)
        project = json.loads(archive.read('project.json'))
        def visit(v):
            if isinstance(v, dict): return {k:visit(x) for k,x in v.items()}
            if isinstance(v, list): return [visit(x) for x in v]
            return assets[v][0] if isinstance(v, str) and v in assets else v
        project = visit(project)
        check(project)
        for name, content in assets.values():
            target = Path(base) / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(content)
        return project
