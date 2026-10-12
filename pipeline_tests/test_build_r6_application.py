import importlib.util
from pathlib import Path
import zipfile

import pytest

spec = importlib.util.spec_from_file_location('build_r6_application', Path(__file__).parents[1] / 'scripts/build_r6_application.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.mark.parametrize('mutation', ['', 'changed', 'extra', 'duplicate', 'escape', 'missing'])
def test_wheel_must_exactly_preserve_application_source_and_assets(tmp_path, mutation):
    source = tmp_path / 'src/cochem_pipeline'
    source.mkdir(parents=True)
    (source / '__init__.py').write_bytes(b'# fixture')
    (source / 'policy.json').write_bytes(b'{}')
    (tmp_path / 'src/x.py').write_bytes(b'# outside setuptools cochem* package selection')
    wheel = tmp_path / 'cochem.whl'
    with zipfile.ZipFile(wheel, 'w') as output:
        output.writestr('cochem_pipeline/__init__.py', b'changed' if mutation == 'changed' else b'# fixture')
        if mutation != 'missing': output.writestr('cochem_pipeline/policy.json', b'{}')
        output.writestr('cochem-4.2.7.dist-info/METADATA', b'fixture metadata')
        if mutation == 'extra': output.writestr('cochem_pipeline/extra.py', b'')
        if mutation == 'duplicate': output.writestr('COCHEM_PIPELINE/POLICY.JSON', b'{}')
        if mutation == 'escape': output.writestr('../escape', b'')
    if mutation:
        with pytest.raises(ValueError): builder.verify_wheel(wheel, tmp_path)
    else:
        assert builder.verify_wheel(wheel, tmp_path)['files'] == 2
