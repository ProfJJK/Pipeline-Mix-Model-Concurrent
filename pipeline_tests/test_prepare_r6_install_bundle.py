import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('prepare_r6_install_bundle', SCRIPTS / 'prepare_r6_install_bundle.py')
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'name:stream', 'a\\b', 'a/CON.txt', 'a/../b', 'a.', 'a//b'])
def test_bundle_rejects_unsafe_names(name):
    with pytest.raises(ValueError): bundle.relative(name)


def fixture(tmp_path, monkeypatch):
    freeze, wheels, dest = (tmp_path / n for n in ('freeze', 'wheels', 'bundle'))
    freeze.mkdir(); wheels.mkdir()
    source_rows = []
    for name in ('uv.lock', 'pyproject.toml'):
        data = ('fixture ' + name).encode()
        (freeze / name).write_bytes(data)
        source_rows.append(dict(relative=name, sha256=bundle.digest(data), length=len(data)))
    source = dict(schema='cochem-r6-source-preparation/1', commit='a'*40, files=source_rows)
    (freeze / 'source-preparation.json').write_text(json.dumps(source))
    wheel = wheels / 'fixture-1.0-py3-none-any.whl'
    wheel.write_bytes(b'dependency')
    (wheels / 'wheelhouse-verified.json').write_text(json.dumps(dict(status='LOCKED_RUNTIME_WHEELS_VERIFIED',
        lock_sha256=source_rows[0]['sha256'], pyproject_sha256=source_rows[1]['sha256'], files=[dict(name='fixture',
            version='1.0', filename=wheel.name, sha256=bundle.digest(wheel.read_bytes()), size=wheel.stat().st_size)])))
    app = tmp_path / 'cochem-4.2.7-py3-none-any.whl'; app.write_bytes(b'application')
    app_record = dict(status='APPLICATION_WHEEL_VERIFIED', source_commit='a'*40,
        source_manifest_sha256=bundle.digest((freeze/'source-preparation.json').read_bytes()),
        wheel=str(app), sha256=bundle.digest(app.read_bytes()), size=app.stat().st_size, files=1)
    application = tmp_path / 'application.json'; application.write_text(json.dumps(app_record))
    base = tmp_path / 'base.json'; base.write_bytes(b'base')
    monkeypatch.setitem(sys.modules, 'build_r6_application', SimpleNamespace(verify_wheel=lambda *args: app_record))
    monkeypatch.setattr(bundle, 'from_commissioned_bytes', lambda _: ({'candidate': 'fixture'}, {'plan_sha256': 'p'*64}))
    monkeypatch.setattr(bundle, 'load_config', lambda _: SimpleNamespace(max_execution_slots=4))
    return dict(freeze=freeze, wheelhouse=wheels, application=application, commissioned=base, destination=dest)


def test_prepared_install_is_never_mislabelled_as_launch_ready(tmp_path, monkeypatch):
    args = fixture(tmp_path, monkeypatch)
    result = bundle.prepare(**args)
    assert result['installation_inputs_ready']
    assert not result['administrator_launch_ready'] and not result['activation_ready']
    manifest = json.loads((args['destination']/'install-manifest.json').read_text())
    assert len(manifest['files']) == 6
    requirements = (args['destination']/'runtime-requirements.txt').read_text()
    assert 'fixture==1.0 --hash=sha256:' in requirements
    assert 'cochem==4.2.7 --hash=sha256:' in requirements


@pytest.mark.parametrize('mutation', ['source', 'wheel', 'commit', 'lock'])
def test_changed_offline_inputs_refuse_before_creating_bundle(tmp_path, monkeypatch, mutation):
    args = fixture(tmp_path, monkeypatch)
    if mutation == 'source': (args['freeze']/'pyproject.toml').write_bytes(b'changed')
    if mutation == 'wheel': next(args['wheelhouse'].glob('*.whl')).write_bytes(b'changed')
    if mutation == 'commit':
        row = json.loads(args['application'].read_text()); row['source_commit'] = 'b'*40
        args['application'].write_text(json.dumps(row))
    if mutation == 'lock': (args['freeze']/'uv.lock').write_bytes(b'changed')
    with pytest.raises(ValueError): bundle.prepare(**args)
    assert not args['destination'].exists()
