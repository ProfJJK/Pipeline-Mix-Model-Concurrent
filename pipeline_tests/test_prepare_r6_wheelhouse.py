"""Offline packaging fixtures; no downloads, installs or subprocesses."""
import hashlib
import io

import pytest
from packaging.tags import Tag

from scripts.prepare_r6_wheelhouse import select_wheels, copy_verified


def fixture():
    payload = b'fixture wheel bytes, never installed'
    wheel = dict(url='https://files.pythonhosted.org/packages/fixture/demo-1.0-py3-none-any.whl',
        hash='sha256:' + hashlib.sha256(payload).hexdigest(), size=len(payload))
    lock = {'package': [dict(name='demo', version='1.0',
        source={'registry': 'https://pypi.org/simple'}, wheels=[wheel])]}
    return payload, wheel, lock


def select(lock, text='demo==1.0'):
    return select_wheels(lock, text, [Tag('cp312', 'cp312', 'win_amd64'), Tag('py3', 'none', 'any')],
                         {'python_version': '3.12', 'sys_platform': 'win32'})


def test_selects_one_hash_pinned_compatible_wheel_and_skips_foreign_markers():
    payload, _, lock = fixture()
    rows = select(lock, 'demo==1.0\nmissing==4 ; sys_platform == "linux"')
    assert len(rows) == 1
    assert rows[0]['filename'] == 'demo-1.0-py3-none-any.whl'
    assert rows[0]['sha256'] == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize('requirement', ['demo>=1', 'demo', 'demo @ https://example.org/a.whl',
    '--index-url https://example.org', 'demo==2', 'demo==1.0\ndemo==1.0'])
def test_export_must_be_exact_unique_locked_registry_versions(requirement):
    _, _, lock = fixture()
    with pytest.raises(ValueError): select(lock, requirement)


@pytest.mark.parametrize('mutation', ['no_wheel', 'foreign_tag', 'foreign_host', 'wrong_name', 'huge', 'hash'])
def test_missing_or_untrusted_wheels_hold_before_download(mutation):
    _, wheel, lock = fixture()
    if mutation == 'no_wheel': lock['package'][0]['wheels'] = []
    if mutation == 'foreign_tag': wheel['url'] = wheel['url'].replace('py3-none-any', 'cp313-cp313-win_amd64')
    if mutation == 'foreign_host': wheel['url'] = wheel['url'].replace('files.pythonhosted.org', 'example.org')
    if mutation == 'wrong_name': wheel['url'] = wheel['url'].replace('demo-1.0', 'other-1.0')
    if mutation == 'huge': wheel['size'] = 1024 ** 3
    if mutation == 'hash': wheel['hash'] = 'sha256:wrong'
    with pytest.raises(ValueError): select(lock)


def test_download_stream_is_bounded_verified_and_exclusive(tmp_path):
    payload, _, lock = fixture()
    row = select(lock)[0]
    target = tmp_path / row['filename']
    copy_verified(io.BytesIO(payload), target, row)
    assert target.read_bytes() == payload
    with pytest.raises(FileExistsError): copy_verified(io.BytesIO(payload), target, row)
    assert target.read_bytes() == payload


@pytest.mark.parametrize('payload', [b'short', b'x' * 100, b'x' * 34])
def test_partial_or_wrong_hash_is_preserved_without_success(tmp_path, payload):
    _, _, lock = fixture()
    row = select(lock)[0]
    with pytest.raises(ValueError): copy_verified(io.BytesIO(payload), tmp_path / row['filename'], row)
    assert (tmp_path / row['filename']).exists()
