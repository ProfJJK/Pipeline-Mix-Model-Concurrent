"""Inert harness for freeze-stopped-runtime-r5-source.py.

Every freeze runs against fixture trees and fixture git repositories created in tmp_path (git init /
add / commit with an isolated git configuration); the real repository, the real staging path and the
real manifest outputs are never written. The real r4 manifest, installation receipt and frozen tree
are only read, and the real repository is only read by one --print-pins check of the reviewed commit
(those tests skip when the files are absent). The A6 numbers are reproduced exactly
(166 rows, 13 changed, 153 verified unchanged) and also checked on smaller parametrized bases.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'freeze-stopped-runtime-r5-source.py'
R4_WORKSPACE_MANIFEST = HERE / 'stopped-runtime-r4-source-manifest.json'
R4_ROOT = Path(r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4')
R4_MANIFEST_SHA256 = '1202b1d780f1b8624523cf2ff3ea5084671f9d6921ae3b4c05f42b2df2652189'
R4_INSTALL_RECEIPT_SHA256 = '629c87ecb3fb44e6c93ca01cc1e6164cfd3fe34af58b590f9bd3b99c01ce8502'
CONFIG_SHA256 = '135cd9eccf9efcdbc910679bde83b571913e731a4041ece62f60e42442f1709c'
CONTRACT_TARGET_ROOT = r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5'
PLACEHOLDER = 'PIN-AFTER-COMMIT'
# The Commander's reviewed commit and the 13 blob pins --print-pins reported for it (2026-10-11).
REVIEWED_COMMIT = '8554c7645801a7bc9c4abad4861bfcbe4ed014b0'
REVIEWED_PINS = {
    'src/cochem_pipeline/__main__.py': '19f24fc7bcd4d6d0133386aff916efc3ceb6fb359d8604041ef17bdab931b1b3',
    'src/cochem_pipeline/agy_protocol.py': 'eaf8d1f407c8792be1343c657afabcf370992df3f82cd9dfb7fe13cf9d41545e',
    'src/cochem_pipeline/coding.py': '0b97d7bdec4e5c4a1b8f3d1ca8a974f3205d838c6e275e3cc66c5c9826998174',
    'src/cochem_pipeline/config.py': '908e61267a6133379fad7b26b7452e03f1deb97f44f53eb9e26c07de8212bbd4',
    'src/cochem_pipeline/controller_guard.py': 'e18304719af11e0dd5280d777c6157cc9bc873dd29b7dc15527d6b3667656eba',
    'src/cochem_pipeline/failures.py': '625f9c6e045f6a108be04a6a13767593db08ac960bb3839fade0a37e36c6edf5',
    'src/cochem_pipeline/knowledge.py': '1bf720ed5df342704552b3e0996ee1cdaebd8f9d7f26fc345b4e5a848e2d2f0f',
    'src/cochem_pipeline/operator_views.py': '8b6b51e9ef3879ad13f714ee44390fc4bb7e41cc9bf5c7cbdc589413f1efaf42',
    'src/cochem_pipeline/runtime.py': '946adaf95b1755138f0e7bf79576c8290569d7fb98851e8962e00ca73b40a208',
    'src/cochem_pipeline/service.py': '38ab9dc1853dc38b0ee824a1f80f5e4bea503ec2e821c7803b065baa501c5128',
    'src/cochem_pipeline/store.py': 'b3604d227b23d2f3a68e0106b852ad672127089df68b0d512131455fa552d0a0',
    'src/cochem_pipeline/worker.py': '20a084071bfa172aa787d1a96168b8c541089823559e8f00518b164c16ae0f41',
    'src/cochem_supervisor/runner.py': 'adc8ccf33841438f3104e64325ff84b7826c49db297c8bc3f02ebb55ad96cf31',
}
FIXTURE_DATE = '2026-10-11T12:00:00+00:00'

# ARMY_ADDENDUM_20261011 A6, written out independently of the script under test.
A6 = {
    'src/cochem_pipeline/__main__.py': 'CRLF',
    'src/cochem_pipeline/agy_protocol.py': 'LF',
    'src/cochem_pipeline/coding.py': 'CRLF',
    'src/cochem_pipeline/config.py': 'CRLF',
    'src/cochem_pipeline/controller_guard.py': 'CRLF',
    'src/cochem_pipeline/failures.py': 'CRLF',
    'src/cochem_pipeline/knowledge.py': 'CRLF',
    'src/cochem_pipeline/operator_views.py': 'CRLF',
    'src/cochem_pipeline/runtime.py': 'CRLF',
    'src/cochem_pipeline/service.py': 'CRLF',
    'src/cochem_pipeline/store.py': 'CRLF',
    'src/cochem_pipeline/worker.py': 'CRLF',
    'src/cochem_supervisor/runner.py': 'CRLF',
}
# r4 keeps these as mixed CRLF/LF (the commit normalises them to pure CRLF).
R4_MIXED = {'src/cochem_pipeline/worker.py', 'src/cochem_supervisor/runner.py', 'src/cochem_pipeline/store.py',
            'src/cochem_pipeline/service.py', 'src/cochem_pipeline/operator_views.py', 'src/cochem_pipeline/knowledge.py',
            'src/cochem_pipeline/runtime.py'}
PROTECTED = ['README.md', 'pyproject.toml', 'uv.lock',
             'src/cochem_pipeline/specification/4.2.7_SRS.md',
             'src/cochem_pipeline/specification/acceptance_4.2.7.json',
             'src/cochem_pipeline/specification/docs/evidence/VALIDATION_4.2.7-r2.json']
# A source file where the repository head differs from r4 but r5 keeps r4 bytes.
REPO_DRIFT = ['src/cochem_pipeline/resource_telemetry.py', 'src/cochem_pipeline/performance_acceptance.py']
R4_MANIFEST_KEYS = ['schema', 'host', 'captured_utc', 'complete_source_freeze', 'source_repository', 'target_root',
                    'previous_source_manifest_sha256', 'previous_install_receipt_sha256', 'previous_manifest_entries',
                    'max_execution_slots', 'worker_identities', 'configuration_sha256', 'configuration_unchanged', 'scope',
                    'changes_from_previous_source', 'files']
R5_ADDED_KEYS = ['captured_utc_basis', 'source_commit', 'verified_unchanged', 'reviewed_repairs', 'reviewed_repairs_sha256']
EXPECTED_MANIFEST_KEYS = R4_MANIFEST_KEYS[:-1] + R5_ADDED_KEYS + ['files']
DIRECTORY = object()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_freeze():
    """A fresh copy of the script as a module per test, so table/constant patches never leak."""
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location('freeze_stopped_runtime_r5_under_test', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


@pytest.fixture
def freeze():
    return load_freeze()


def source_body(relative, tag, convention, mixed=False):
    eol = b'\r\n' if convention == 'CRLF' else b'\n'
    lines = [f'"""{relative} ({tag})."""', '', f'TAG = {tag!r}', '', 'def value():', f'    return {len(relative)}']
    data = eol.join(line.encode('ascii') for line in lines) + eol
    if mixed:
        data += b'MIXED_TAIL = True\n'
    return data


def text_body(relative, tag):
    return f'{relative} {tag}\r\nsecond line\r\n'.encode('ascii')


def isolated_git_environment(tmp_path):
    config = tmp_path / 'fixture-gitconfig'
    if not config.exists():
        config.write_bytes(b'')
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
    environment.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=str(config),
                       GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                       GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid',
                       GIT_AUTHOR_DATE=FIXTURE_DATE, GIT_COMMITTER_DATE=FIXTURE_DATE)
    return environment


def fixture_git(tmp_path, repo, *arguments):
    return subprocess.run(['git', '-C', str(repo), *arguments], capture_output=True, check=True, timeout=60,
                          stdin=subprocess.DEVNULL, env=isolated_git_environment(tmp_path)).stdout


class World:
    """An r4-like installed tree, its manifest and receipt, and a repository commit with the 13 repairs."""

    def argv(self, **overrides):
        values = {
            'commit': self.commit, 'repo': self.repo, 'r4_source': self.source, 'r4_manifest': self.manifest,
            'r4_manifest_sha256': self.manifest_sha256, 'r4_install_receipt': self.receipt,
            'r4_install_receipt_sha256': self.receipt_sha256, 'output': self.stage,
            'manifest_out': self.manifest_out, 'receipt_out': self.receipt_out,
        }
        values.update(overrides)
        return [f'--{key.replace("_", "-")}={value}' for key, value in values.items() if value is not None]

    def outputs_absent(self):
        return not self.stage.exists() and not self.manifest_out.exists() and not self.receipt_out.exists()

    def write_manifest(self, document):
        self.manifest.write_bytes((json.dumps(document, indent=2) + '\n').encode('utf-8'))
        self.manifest_sha256 = sha(self.manifest.read_bytes())

    def write_receipt(self, document):
        self.receipt.write_bytes(json.dumps(document, indent=4).encode('utf-8'))
        self.receipt_sha256 = sha(self.receipt.read_bytes())

    def receipt_document(self):
        return {'schema': 'cochem-stopped-runtime-update/1', 'mode': 'FRESH_STOPPED_RUNTIME_READY',
                'target_root': r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4',
                'source_manifest_sha256': self.manifest_sha256, 'source_files': len(self.rows),
                'configuration_sha256': CONFIG_SHA256, 'configuration_unchanged': True}


def make_world(tmp_path, rows=166, base_overrides=None, omit_base=(), repo_overrides=None):
    world = World()
    world.source = tmp_path / 'r4' / 'source'
    base = {}
    for relative in PROTECTED:
        base[relative] = text_body(relative, 'r4')
    for relative in REPO_DRIFT:
        base[relative] = source_body(relative, 'r4', 'CRLF', mixed=True)
    for relative, convention in A6.items():
        base[relative] = source_body(relative, 'r4', convention, mixed=relative in R4_MIXED)
    base.update(base_overrides or {})
    for relative in omit_base:
        base.pop(relative)
    index = 0
    while len(base) < rows:
        relative = f'src/cochem_filler/module_{index:03d}.py'
        base[relative] = source_body(relative, 'r4', 'CRLF', mixed=index % 3 == 0)
        index += 1
    assert len(base) == rows
    for relative, data in base.items():
        path = world.source.joinpath(*relative.split('/'))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (world.source / 'build').mkdir()  # the installed r4 source holds a build folder outside the manifest
    (world.source / 'build' / 'ignored.txt').write_bytes(b'not in the manifest\n')
    world.base = base
    world.rows = [{'relative': relative, 'sha256': sha(data), 'length': len(data)} for relative, data in sorted(base.items())]
    world.manifest = tmp_path / 'r4' / 'source-manifest.json'
    world.manifest_document = {'schema': 'cochem-stopped-runtime-source/1', 'host': 'AETHERDESK', 'complete_source_freeze': True,
                               'previous_manifest_entries': rows, 'files': world.rows}
    world.write_manifest(world.manifest_document)
    world.receipt = tmp_path / 'r4' / 'install-after.json'
    world.write_receipt(world.receipt_document())

    world.repo = tmp_path / 'repo'
    world.repo.mkdir()
    committed = {'.gitattributes': b'* -text\n'}
    for relative, convention in A6.items():
        committed[relative] = source_body(relative, 'r5', convention)
    for relative in PROTECTED + REPO_DRIFT:
        committed[relative] = text_body(relative, 'repository head differs from r4')
    committed.update(repo_overrides or {})
    for relative, data in committed.items():
        path = world.repo.joinpath(*relative.split('/'))
        if data is None:
            continue
        if data is DIRECTORY:
            path.mkdir(parents=True)
            (path / 'inner.py').write_bytes(b'x = 1\r\n')
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    fixture_git(tmp_path, world.repo, 'init', '-q', '-b', 'main')
    fixture_git(tmp_path, world.repo, 'add', '-A')
    fixture_git(tmp_path, world.repo, 'commit', '-q', '-m', 'fixture r5 repairs')
    world.commit = fixture_git(tmp_path, world.repo, 'rev-parse', 'HEAD').decode('ascii').strip()
    world.committed = {key: value for key, value in committed.items() if isinstance(value, bytes)}
    for relative, data in world.committed.items():  # no autocrlf or filter touched the fixture bytes
        assert fixture_git(tmp_path, world.repo, 'show', f'HEAD:{relative}') == data
    world.pins = {relative: sha(world.committed[relative]) for relative in A6 if relative in world.committed}
    world.stage = tmp_path / 'out' / 'stopped-runtime-r5-source'
    world.manifest_out = tmp_path / 'out' / 'stopped-runtime-r5-source-manifest.json'
    world.receipt_out = tmp_path / 'out' / 'stopped-runtime-r5-freeze-receipt.json'
    return world


def fill(freeze, pins):
    freeze.REPAIRS = tuple((relative, convention, pins.get(relative, PLACEHOLDER)) for relative, convention, _ in freeze.REPAIRS)


def succeed(freeze, world, capsys, **overrides):
    code = freeze.main(world.argv(**overrides))
    captured = capsys.readouterr()
    assert code == 0, captured.err
    manifest = json.loads(world.manifest_out.read_bytes())
    receipt = json.loads(captured.out)
    return manifest, receipt


def refuse(freeze, world, capsys, *, expect, **overrides):
    code = freeze.main(world.argv(**overrides))
    error = capsys.readouterr().err
    assert code == 1, error
    assert error.startswith('REFUSED: ') and expect in error, error
    return error


@pytest.fixture
def world(tmp_path):
    return make_world(tmp_path)


# ---- the shipped table and constants ---------------------------------------------------------------

def test_shipped_table_is_exactly_a6_with_its_conventions(freeze):
    table = {relative: convention for relative, convention, _pin in freeze.REPAIRS}
    assert len(freeze.REPAIRS) == 13 and table == A6
    assert 'src/cochem_pipeline/__main__.py' in table
    assert [relative for relative, convention in table.items() if convention == 'LF'] == ['src/cochem_pipeline/agy_protocol.py']
    assert not any(r in ('README.md', 'pyproject.toml', 'uv.lock') or r.startswith('src/cochem_pipeline/specification/') for r in table)


def test_shipped_table_is_filled_with_the_reviewed_commit_pins(freeze):
    """The Commander's commit 8554c76 is pinned; no placeholder remains in the table."""
    assert {relative: pin for relative, _convention, pin in freeze.REPAIRS} == REVIEWED_PINS
    assert all(pin != PLACEHOLDER and re.fullmatch(r'[0-9a-f]{64}', pin) for _r, _c, pin in freeze.REPAIRS)
    assert SCRIPT.read_text(encoding='ascii').count('"PIN-AFTER-COMMIT"') == 1  # only the PLACEHOLDER constant


def test_shipped_pins_equal_print_pins_of_the_reviewed_commit_read_only():
    """Read-only: --print-pins against the real repository must reproduce the embedded table."""
    repository = Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent')
    if not (repository / '.git').exists():
        pytest.skip('repository not present')
    probe = subprocess.run(['git', '-C', str(repository), 'cat-file', '-e', REVIEWED_COMMIT + '^{commit}'],
                           capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    if probe.returncode != 0:
        pytest.skip('reviewed commit not present')
    result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '--print-pins', f'--commit={REVIEWED_COMMIT}'],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert dict(reversed(line.split('  ')) for line in result.stdout.splitlines()) == REVIEWED_PINS


def test_defaults_point_at_the_installed_r4_base_and_the_r5_outputs(freeze):
    assert freeze.R4_ROOT == R4_ROOT and freeze.R4_SOURCE == R4_ROOT / 'source'
    assert freeze.R4_MANIFEST == R4_ROOT / 'source-manifest.json' and freeze.R4_MANIFEST_SHA256 == R4_MANIFEST_SHA256
    assert freeze.R4_INSTALL_RECEIPT == R4_ROOT / 'install-after.json' and freeze.R4_INSTALL_RECEIPT_SHA256 == R4_INSTALL_RECEIPT_SHA256
    assert freeze.CONFIG_SHA256 == CONFIG_SHA256
    assert freeze.STAGE_ROOT == Path(r'C:\Users\ansac\CoChem427\stopped-runtime-r5-source')
    assert freeze.TARGET_ROOT == CONTRACT_TARGET_ROOT
    assert freeze.REPOSITORY == Path(r'C:\Users\ansac\source\repos\Pipeline-Mix-Model-Concurrent')
    assert freeze.MANIFEST_OUT == HERE / 'stopped-runtime-r5-source-manifest.json'
    assert freeze.RECEIPT_OUT == HERE / 'stopped-runtime-r5-freeze-receipt.json'
    assert freeze.EXPECTED_BASE_ROWS == 166 and freeze.EXPECTED_CHANGED == 13
    arguments = freeze.parse_arguments(['--commit', 'abcdef1'])
    assert arguments.output == str(freeze.STAGE_ROOT) and arguments.target_root == CONTRACT_TARGET_ROOT
    assert arguments.r4_manifest_sha256 == R4_MANIFEST_SHA256 and arguments.repo == str(freeze.REPOSITORY)


def test_commit_is_a_required_parameter(freeze):
    with pytest.raises(SystemExit) as raised:
        freeze.parse_arguments([])
    assert raised.value.code == 2


@pytest.mark.parametrize('name', [SCRIPT.name, Path(__file__).name])
def test_sources_are_ascii_only(name):
    data = (HERE / name).read_bytes()
    assert all(byte < 128 for byte in data), name


def test_script_reads_git_only_and_never_overwrites_or_deletes():
    text = SCRIPT.read_text(encoding='ascii')
    subcommands = set(re.findall(r'self\.run\(\["([a-z-]+)"', text))
    assert subcommands == {'rev-parse', 'cat-file', 'ls-tree', 'show'}
    assert text.count('subprocess.run(') == 1 and '--textconv' not in text and '--no-textconv' not in text
    for forbidden in ('rmtree', 'unlink', 'os.remove', 'shutil', 'rename', '"wb"', "'wb'", '"w"', 'write_text', 'write_bytes',
                      'schtasks', 'ScheduledTask', 'Start-Process', '"checkout"', '"reset"', '"add"', '"fetch"', '"config"', '"gc"'):
        assert forbidden not in text, forbidden
    assert text.count('open(path, "xb")') == 1


# ---- placeholders, pins and the table ---------------------------------------------------------------

def test_freeze_refuses_while_any_placeholder_remains(freeze, world, capsys):
    freeze.REPAIRS = tuple((relative, convention, PLACEHOLDER) for relative, convention, _ in freeze.REPAIRS)
    refuse(freeze, world, capsys, expect=PLACEHOLDER)
    assert world.outputs_absent()


def test_freeze_refuses_a_single_remaining_placeholder(freeze, world, capsys):
    pins = dict(world.pins)
    pins.pop('src/cochem_pipeline/runtime.py')
    fill(freeze, pins)
    error = refuse(freeze, world, capsys, expect='1 REPAIRS pin(s) still read PIN-AFTER-COMMIT')
    assert '--print-pins' in error and world.outputs_absent()


def test_shipped_script_cli_refuses_the_fixture_and_writes_nothing(world):
    """With the reviewed pins filled, the fixture blobs do not match them: the real script stops with
    exit 1 and writes nothing."""
    result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), *world.argv()], capture_output=True, text=True, timeout=120)
    assert result.returncode == 1 and result.stdout == ''
    assert result.stderr.startswith('REFUSED: ') and 'not its reviewed pin' in result.stderr
    assert world.outputs_absent()


def test_placeholder_copy_of_the_script_refuses_as_a_program(world, tmp_path):
    """The placeholder refusal, kept on a patched copy whose table is back at PIN-AFTER-COMMIT."""
    text = SCRIPT.read_text(encoding='ascii')
    reverted, count = re.subn(r'\("(src/[^"]+)", "(LF|CRLF)", "([^"]*)"\)',
                              lambda match: f'("{match[1]}", "{match[2]}", "{PLACEHOLDER}")', text)
    assert count == 13
    copy = tmp_path / 'freeze-placeholder-copy.py'
    copy.write_text(reverted, encoding='ascii')
    result = subprocess.run([sys.executable, '-I', '-B', str(copy), *world.argv()], capture_output=True, text=True, timeout=120)
    assert result.returncode == 1 and result.stdout == ''
    assert result.stderr.startswith('REFUSED: 13 REPAIRS pin(s) still read PIN-AFTER-COMMIT')
    assert world.outputs_absent()
    pins = subprocess.run([sys.executable, '-I', '-B', str(copy), '--print-pins', f'--commit={world.commit}', f'--repo={world.repo}'],
                          capture_output=True, text=True, timeout=120)
    assert pins.returncode == 0 and len(pins.stdout.splitlines()) == 13


def test_freeze_refuses_a_pin_that_is_not_sha256(freeze, world, capsys):
    pins = dict(world.pins, **{'src/cochem_pipeline/store.py': 'A' * 64})
    fill(freeze, pins)
    refuse(freeze, world, capsys, expect='is not a lowercase sha256')
    assert world.outputs_absent()


@pytest.mark.parametrize('relative', ['src/cochem_pipeline/agy_protocol.py', 'src/cochem_pipeline/worker.py', 'src/cochem_pipeline/__main__.py'])
def test_freeze_refuses_a_blob_whose_sha_differs_from_its_pin(freeze, world, capsys, relative):
    fill(freeze, dict(world.pins, **{relative: sha(b'some other reviewed bytes')}))
    error = refuse(freeze, world, capsys, expect='not its reviewed pin')
    assert relative in error and world.outputs_absent()


@pytest.mark.parametrize('case', ['extra_path', 'replaced_path', 'readme', 'pyproject', 'uv_lock', 'specification', 'duplicate', 'missing', 'convention_flip', 'malformed'])
def test_freeze_refuses_any_table_other_than_a6(freeze, world, capsys, case):
    fill(freeze, world.pins)
    rows = list(freeze.REPAIRS)
    other = ('src/cochem_pipeline/routing_store.py', 'CRLF', sha(b'x'))
    expect = 'exactly the 13 A6 paths'
    if case == 'extra_path':
        rows.append(other)
    elif case == 'replaced_path':
        rows[2] = other
    elif case in ('readme', 'pyproject', 'uv_lock', 'specification'):
        name = {'readme': 'README.md', 'pyproject': 'pyproject.toml', 'uv_lock': 'uv.lock',
                'specification': 'src/cochem_pipeline/specification/4.2.7_SRS.md'}[case]
        rows.append((name, 'CRLF', sha(b'x')))
        expect = 'must stay at r4 bytes'
    elif case == 'duplicate':
        rows.append(rows[0])
        expect = 'Duplicate REPAIRS path'
    elif case == 'missing':
        rows.pop()
    elif case == 'convention_flip':
        rows = [(r, 'CRLF' if c == 'LF' else c, p) for r, c, p in rows]
        expect = 'A6 requires pure LF'
    elif case == 'malformed':
        rows[0] = rows[0][:2]
        expect = 'Malformed REPAIRS entry'
    freeze.REPAIRS = tuple(rows)
    refuse(freeze, world, capsys, expect=expect)
    assert world.outputs_absent()


# ---- success: the A6 numbers and the manifest schema ------------------------------------------------

def test_freeze_reproduces_a6_exactly_166_rows_13_changed_153_unchanged(freeze, world, capsys):
    fill(freeze, world.pins)
    manifest, receipt = succeed(freeze, world, capsys)
    changes = manifest['changes_from_previous_source']
    assert len(manifest['files']) == 166 and manifest['previous_manifest_entries'] == 166
    assert sorted(changes['changed']) == sorted(A6) and len(changes['changed']) == 13
    assert changes['added'] == [] and changes['removed'] == []
    assert manifest['verified_unchanged'] == 153 and receipt['unchanged_from_r4'] == 153 and receipt['files'] == 166
    assert manifest['configuration_unchanged'] is True and manifest['configuration_sha256'] == CONFIG_SHA256
    assert manifest['previous_source_manifest_sha256'] == world.manifest_sha256
    assert manifest['previous_install_receipt_sha256'] == world.receipt_sha256
    assert manifest['source_commit'] == world.commit and receipt['source_commit'] == world.commit
    assert manifest['captured_utc'] == FIXTURE_DATE and manifest['captured_utc_basis'] == 'committer timestamp of source_commit'
    assert manifest['source_repository'] == str(world.stage) and manifest['host'] == 'AETHERDESK'
    assert manifest['max_execution_slots'] == 4 and manifest['worker_identities'] == 6
    by_name = {row['relative']: row for row in manifest['files']}
    for relative in A6:
        assert by_name[relative] == {'relative': relative, 'sha256': world.pins[relative], 'length': len(world.committed[relative])}
        assert (world.stage.joinpath(*relative.split('/'))).read_bytes() == world.committed[relative]
    for row in world.rows:
        if row['relative'] not in A6:
            assert by_name[row['relative']] == row
            assert world.stage.joinpath(*row['relative'].split('/')).read_bytes() == world.base[row['relative']]


def test_manifest_keeps_r4_field_names_order_and_row_shape_and_only_adds_r5_fields(freeze, world, capsys):
    fill(freeze, world.pins)
    manifest, _receipt = succeed(freeze, world, capsys)
    assert list(manifest) == EXPECTED_MANIFEST_KEYS
    assert [key for key in manifest if key in R4_MANIFEST_KEYS] == R4_MANIFEST_KEYS
    assert list(manifest['changes_from_previous_source']) == ['added', 'removed', 'changed']
    assert all(list(row) == ['relative', 'sha256', 'length'] for row in manifest['files'])
    assert all(isinstance(row['length'], int) and re.fullmatch(r'[0-9a-f]{64}', row['sha256']) for row in manifest['files'])
    assert [row['relative'] for row in manifest['files']] == [row['relative'] for row in world.rows]
    if R4_WORKSPACE_MANIFEST.exists():  # the real r4 manifest (read only) has exactly the r4 keys and row shape
        real = json.loads(R4_WORKSPACE_MANIFEST.read_bytes())
        assert list(real) == R4_MANIFEST_KEYS and list(real['files'][0]) == ['relative', 'sha256', 'length']
        assert list(real['changes_from_previous_source']) == list(manifest['changes_from_previous_source'])


def test_manifest_satisfies_the_retarget_and_installer_contract(freeze, world, capsys):
    """retarget-warden-r5.ps1 Assert-R5InstalledBindings and the installer read these keys."""
    fill(freeze, world.pins)
    manifest, _receipt = succeed(freeze, world, capsys)
    assert manifest['schema'] == 'cochem-stopped-runtime-source/1'
    assert manifest['target_root'] == CONTRACT_TARGET_ROOT
    assert manifest['complete_source_freeze'] is True
    assert isinstance(manifest['files'], list) and len(manifest['files']) == 166
    changes = manifest['changes_from_previous_source']
    assert isinstance(changes['changed'], list) and len(set(changes['changed'])) == len(changes['changed']) == 13
    assert isinstance(changes['added'], list) and changes['added'] == []
    assert isinstance(changes['removed'], list) and changes['removed'] == []
    assert manifest['reviewed_repairs'] == changes['changed']
    assert manifest['reviewed_repairs_sha256'] == {relative: world.pins[relative] for relative in changes['changed']}
    assert list(manifest['reviewed_repairs_sha256']) == manifest['reviewed_repairs']
    assert 'src/cochem_pipeline/__main__.py' in manifest['reviewed_repairs']
    for relative in manifest['reviewed_repairs']:
        assert re.fullmatch(r'src/cochem_(pipeline|supervisor)/[A-Za-z0-9_]+(/[A-Za-z0-9_]+)*\.py', relative)
    assert re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', manifest['source_commit'])
    assert manifest['previous_source_manifest_sha256'] == world.manifest_sha256


def test_manifest_bytes_are_ascii_indented_json_and_the_receipt_reports_their_sha(freeze, world, capsys):
    fill(freeze, world.pins)
    manifest, receipt = succeed(freeze, world, capsys)
    raw = world.manifest_out.read_bytes()
    assert all(byte < 128 for byte in raw) and raw.endswith(b'}\n')
    assert raw == (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
    assert receipt['manifest_sha256'] == sha(raw) and receipt['manifest_path'] == str(world.manifest_out)
    assert json.loads(world.receipt_out.read_bytes()) == receipt


def test_receipt_shape_and_per_repair_line_ending_record(freeze, world, capsys):
    fill(freeze, world.pins)
    _manifest, receipt = succeed(freeze, world, capsys)
    assert receipt['schema'] == 'cochem-stopped-runtime-freeze-receipt/2'
    assert receipt['production_runtime_started'] is False and receipt['production_state_opened'] is False
    assert receipt['stage_root'] == str(world.stage) and receipt['base_source'] == str(world.source)
    assert [item['relative'] for item in receipt['repairs']] == receipt['changed']
    for item in receipt['repairs']:
        relative = item['relative']
        assert item['repository_commit'] == world.commit and item['repository_sha256'] == item['staged_sha256'] == world.pins[relative]
        assert item['line_endings'] == A6[relative] and item['r4_sha256'] == sha(world.base[relative])
        counts = item['line_ending_counts']
        assert counts['crlf_lines'] == (counts['lf_lines'] if A6[relative] == 'CRLF' else 0)
        expected_frozen = 'LF' if A6[relative] == 'LF' else ('CRLF (mixed)' if relative in R4_MIXED else 'CRLF')
        assert item['frozen_tree_line_endings'] == expected_frozen


@pytest.mark.parametrize('rows', [21, 50, 166])
def test_counts_scale_with_the_base_and_always_change_exactly_13(freeze, tmp_path, capsys, rows):
    world = make_world(tmp_path, rows=rows)
    freeze.EXPECTED_BASE_ROWS = rows
    fill(freeze, world.pins)
    manifest, receipt = succeed(freeze, world, capsys)
    assert len(manifest['files']) == rows and manifest['previous_manifest_entries'] == rows
    assert len(manifest['changes_from_previous_source']['changed']) == 13
    assert manifest['verified_unchanged'] == receipt['unchanged_from_r4'] == rows - 13


def test_freeze_is_deterministic(freeze, world, capsys):
    fill(freeze, world.pins)
    _manifest, first_receipt = succeed(freeze, world, capsys)
    first = world.manifest_out.read_bytes()
    first_tree = {path.relative_to(world.stage).as_posix(): path.read_bytes() for path in world.stage.rglob('*') if path.is_file()}
    shutil.rmtree(world.stage)
    world.manifest_out.unlink()
    world.receipt_out.unlink()
    _manifest, second_receipt = succeed(load_freeze_filled(world), world, capsys)
    assert world.manifest_out.read_bytes() == first
    assert second_receipt == first_receipt and second_receipt['manifest_sha256'] == sha(first)
    second_tree = {path.relative_to(world.stage).as_posix(): path.read_bytes() for path in world.stage.rglob('*') if path.is_file()}
    assert second_tree == first_tree and len(second_tree) == 166


def load_freeze_filled(world):
    module = load_freeze()
    fill(module, world.pins)
    return module


def test_readme_pyproject_uvlock_specification_and_repo_drift_stay_r4_bytes(freeze, world, capsys):
    fill(freeze, world.pins)
    manifest, _receipt = succeed(freeze, world, capsys)
    by_name = {row['relative']: row for row in manifest['files']}
    for relative in PROTECTED + REPO_DRIFT:
        assert world.committed[relative] != world.base[relative]  # the commit differs, r5 keeps r4
        assert world.stage.joinpath(*relative.split('/')).read_bytes() == world.base[relative]
        assert by_name[relative]['sha256'] == sha(world.base[relative])
        assert relative not in manifest['changes_from_previous_source']['changed']
    assert not (world.stage / '.gitattributes').exists() and not (world.stage / 'build').exists()


def test_cli_end_to_end_with_a_filled_copy_of_the_table(world, tmp_path):
    """The Commander's procedure: replace the 13 pins in a copy of the script, run it as a program."""
    text = SCRIPT.read_text(encoding='ascii')
    filled, count = re.subn(r'\("(src/[^"]+)", "(LF|CRLF)", "([^"]*)"\)',
                            lambda match: f'("{match[1]}", "{match[2]}", "{world.pins[match[1]]}")', text)
    assert count == 13
    copy = tmp_path / 'freeze-filled-copy.py'
    copy.write_text(filled, encoding='ascii')
    result = subprocess.run([sys.executable, '-I', '-B', str(copy), *world.argv()], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    raw = world.manifest_out.read_bytes()
    assert receipt['manifest_sha256'] == sha(raw)
    manifest = json.loads(raw)
    assert (len(manifest['files']), len(manifest['changes_from_previous_source']['changed']), manifest['verified_unchanged']) == (166, 13, 153)
    again = subprocess.run([sys.executable, '-I', '-B', str(copy), *world.argv()], capture_output=True, text=True, timeout=180)
    assert again.returncode == 1 and 'refusing to overwrite' in again.stderr
    assert world.manifest_out.read_bytes() == raw


# ---- line endings ------------------------------------------------------------------------------------

def test_lf_file_committed_as_crlf_is_refused(freeze, tmp_path, capsys):
    relative = 'src/cochem_pipeline/agy_protocol.py'
    world = make_world(tmp_path, repo_overrides={relative: source_body(relative, 'r5', 'CRLF')})
    fill(freeze, world.pins)
    error = refuse(freeze, world, capsys, expect='line-ending convention is CRLF; A6 requires pure LF')
    assert relative in error and world.outputs_absent()


@pytest.mark.parametrize('relative', ['src/cochem_pipeline/worker.py', 'src/cochem_pipeline/__main__.py', 'src/cochem_pipeline/coding.py', 'src/cochem_supervisor/runner.py'])
def test_crlf_file_committed_as_lf_is_refused(freeze, tmp_path, capsys, relative):
    world = make_world(tmp_path, repo_overrides={relative: source_body(relative, 'r5', 'LF')})
    fill(freeze, world.pins)
    error = refuse(freeze, world, capsys, expect='line-ending convention is LF; A6 requires pure CRLF')
    assert relative in error and world.outputs_absent()


@pytest.mark.parametrize('relative', ['src/cochem_pipeline/agy_protocol.py', 'src/cochem_pipeline/store.py', 'src/cochem_pipeline/controller_guard.py'])
def test_mixed_line_endings_are_refused(freeze, tmp_path, capsys, relative):
    data = source_body(relative, 'r5', A6[relative]) + (b'EXTRA = 1\r\n' if A6[relative] == 'LF' else b'EXTRA = 1\n')
    world = make_world(tmp_path, repo_overrides={relative: data})
    fill(freeze, world.pins)
    error = refuse(freeze, world, capsys, expect='mixed line endings')
    assert relative in error and world.outputs_absent()


@pytest.mark.parametrize('data,expect', [(b'x = 1\r\ny = 2\rz = 3\r\n', 'bare carriage return'), (b'x = 1', 'no line endings')])
def test_bare_carriage_return_or_no_line_ending_is_refused(freeze, tmp_path, capsys, data, expect):
    relative = 'src/cochem_pipeline/failures.py'
    world = make_world(tmp_path, repo_overrides={relative: data})
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect=expect)
    assert world.outputs_absent()


def test_r4_convention_must_equal_the_a6_convention(freeze, tmp_path, capsys):
    relative = 'src/cochem_pipeline/agy_protocol.py'
    world = make_world(tmp_path, base_overrides={relative: source_body(relative, 'r4', 'CRLF')})
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect='r4 keeps src/cochem_pipeline/agy_protocol.py as CRLF; A6 says LF')
    assert world.outputs_absent()


@pytest.mark.parametrize('data,kind', [(b'a\nb\n', 'LF'), (b'a\r\nb\r\n', 'CRLF'), (b'a\r\nb\n', 'MIXED'), (b'a\rb\r\n', 'LONE-CR'), (b'a', 'NONE'), (b'', 'NONE')])
def test_line_ending_classifier(freeze, data, kind):
    assert freeze.line_endings(data) == kind


# ---- the commit ---------------------------------------------------------------------------------------

def test_missing_repair_path_in_the_commit_is_refused(freeze, tmp_path, capsys):
    relative = 'src/cochem_pipeline/__main__.py'
    world = make_world(tmp_path, repo_overrides={relative: None})
    pins = dict(world.pins, **{relative: sha(b'reviewed __main__ bytes')})
    fill(freeze, pins)
    refuse(freeze, world, capsys, expect=f'{relative} is missing from commit')
    assert world.outputs_absent()


def test_repair_path_that_is_not_a_regular_blob_is_refused(freeze, tmp_path, capsys):
    relative = 'src/cochem_pipeline/__main__.py'
    world = make_world(tmp_path, repo_overrides={relative: DIRECTORY})
    fill(freeze, dict(world.pins, **{relative: sha(b'x')}))
    refuse(freeze, world, capsys, expect='is not a regular file blob')
    assert world.outputs_absent()


def test_repair_identical_to_r4_is_refused(freeze, tmp_path, capsys):
    relative = 'src/cochem_pipeline/config.py'  # pure CRLF in r4, so the identical blob passes the line-ending rule
    base_bytes = source_body(relative, 'r4', 'CRLF')
    world = make_world(tmp_path, repo_overrides={relative: base_bytes})
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect='equals the r4 bytes')
    assert world.outputs_absent()


def test_repair_absent_from_the_r4_manifest_is_refused(freeze, tmp_path, capsys):
    world = make_world(tmp_path, omit_base=('src/cochem_pipeline/__main__.py',))
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect='is not an r4 source asset; r5 adds no files')
    assert world.outputs_absent()


@pytest.mark.parametrize('commit', ['HEAD', 'main', 'ABCDEF1', 'abc12', 'g123456', '--output=x', '-x', 'abcdef1\n'])
def test_commit_must_be_lowercase_hex(freeze, world, capsys, commit):
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect='--commit must be a lowercase hexadecimal commit id', commit=commit)
    assert world.outputs_absent()


def test_unknown_commit_is_refused(freeze, world, capsys):
    fill(freeze, world.pins)
    unknown = '0123456789abcdef0123456789abcdef01234567'
    assert unknown != world.commit
    refuse(freeze, world, capsys, expect='git rev-parse failed', commit=unknown)
    assert world.outputs_absent()


def test_abbreviated_commit_resolves_to_the_full_id(freeze, world, capsys):
    fill(freeze, world.pins)
    manifest, _receipt = succeed(freeze, world, capsys, commit=world.commit[:12])
    assert manifest['source_commit'] == world.commit


def test_git_show_output_must_equal_the_blob_object(freeze, world, capsys):
    fill(freeze, world.pins)
    original = freeze.Git.run

    def tampered(self, arguments):
        data = original(self, arguments)
        if arguments[0] == 'show' and arguments[1].endswith(':src/cochem_pipeline/knowledge.py'):
            return data + b'# filtered\r\n'
        return data
    freeze.Git.run = tampered
    refuse(freeze, world, capsys, expect='git show output for src/cochem_pipeline/knowledge.py differs from blob')
    assert world.outputs_absent()


def test_ambient_git_redirection_is_ignored(freeze, world, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv('GIT_DIR', str(tmp_path / 'not-a-repository'))
    monkeypatch.setenv('GIT_OBJECT_DIRECTORY', str(tmp_path / 'not-objects'))
    fill(freeze, world.pins)
    manifest, _receipt = succeed(freeze, world, capsys)
    assert manifest['source_commit'] == world.commit


def test_missing_git_executable_is_refused(freeze, world, capsys, tmp_path):
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect='could not run', git=str(tmp_path / 'no-git.exe'))
    assert world.outputs_absent()


# ---- the r4 base -----------------------------------------------------------------------------------

def test_base_manifest_sha_mismatch_is_refused(freeze, world, capsys):
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect='r4 source manifest does not match its pinned digest', r4_manifest_sha256='0' * 64)
    assert world.outputs_absent()


@pytest.mark.parametrize('case', ['schema', 'incomplete', 'rows', 'unsafe', 'duplicate', 'row_key', 'length', 'hash', 'not_object'])
def test_base_manifest_shape_is_enforced(freeze, world, capsys, case):
    document = json.loads(json.dumps(world.manifest_document))
    expect = 'Unexpected r4 manifest shape'
    if case == 'schema':
        document['schema'] = 'cochem-stopped-runtime-source/2'
    elif case == 'incomplete':
        document['complete_source_freeze'] = False
    elif case == 'rows':
        document['files'] = document['files'][:-1]
    elif case == 'unsafe':
        document['files'][5]['relative'] = 'src/../../outside.py'
        expect = 'Unsafe, unexpected or duplicate r4 manifest path'
    elif case == 'duplicate':
        twin = document['files'][4]['relative']
        document['files'][5]['relative'] = twin[:4] + twin[4:].upper()  # same path, case-insensitively
        expect = 'Unsafe, unexpected or duplicate r4 manifest path'
    elif case == 'row_key':
        document['files'][5]['mode'] = '100644'
        expect = 'r4 manifest row is not {relative, sha256, length}'
    elif case == 'length':
        document['files'][5]['length'] = True
        expect = 'Invalid r4 manifest length'
    elif case == 'hash':
        document['files'][5]['sha256'] = 'Z' * 64
        expect = 'Invalid r4 manifest sha256'
    elif case == 'not_object':
        document = [document]
    world.write_manifest(document)
    world.write_receipt(world.receipt_document())
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect=expect)
    assert world.outputs_absent()


@pytest.mark.parametrize('case', ['modified', 'deleted', 'replaced_by_directory', 'repair_modified'])
def test_base_tree_drift_from_the_r4_manifest_is_refused(freeze, world, capsys, case):
    relative = 'src/cochem_pipeline/worker.py' if case == 'repair_modified' else 'uv.lock'
    path =world.source.joinpath(*relative.split('/'))
    if case in ('modified', 'repair_modified'):
        path.write_bytes(path.read_bytes() + b'drift\r\n')
    elif case == 'deleted':
        path.unlink()
    else:
        path.unlink()
        path.mkdir()
    fill(freeze, world.pins)
    error = refuse(freeze, world, capsys, expect='Installed r4 frozen source drifted from its manifest')
    assert relative in error and world.outputs_absent()


@pytest.mark.parametrize('case', ['sha', 'mode', 'manifest', 'files', 'configuration', 'unchanged', 'not_json'])
def test_r4_install_receipt_must_bind_the_pinned_manifest(freeze, world, capsys, case):
    document = world.receipt_document()
    expect = 'r4 installation receipt does not bind the pinned r4 manifest and configuration'
    overrides = {}
    if case == 'sha':
        overrides['r4_install_receipt_sha256'] = '1' * 64
        expect = 'r4 installation receipt does not match its pinned digest'
    elif case == 'mode':
        document['mode'] = 'READ_ONLY_PLAN'
    elif case == 'manifest':
        document['source_manifest_sha256'] = '2' * 64
    elif case == 'files':
        document['source_files'] = 165
    elif case == 'configuration':
        document['configuration_sha256'] = '3' * 64
    elif case == 'unchanged':
        document['configuration_unchanged'] = False
    if case == 'not_json':
        world.receipt.write_bytes(b'not json')
        world.receipt_sha256 = sha(b'not json')
        expect = 'r4 installation receipt is not JSON'
    else:
        world.write_receipt(document)
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect=expect, **overrides)
    assert world.outputs_absent()


# ---- outputs ------------------------------------------------------------------------------------------

@pytest.mark.parametrize('case', ['stage_empty', 'stage_non_empty', 'manifest_exists', 'receipt_exists'])
def test_existing_outputs_are_preserved_and_refused(freeze, world, capsys, case):
    world.stage.parent.mkdir(parents=True)
    keep = b'preserve me\n'
    if case == 'stage_empty':
        world.stage.mkdir()
        expect = 'refusing to reuse'
    elif case == 'stage_non_empty':
        world.stage.mkdir()
        (world.stage / 'keep.txt').write_bytes(keep)
        expect = 'refusing to reuse'
    elif case == 'manifest_exists':
        world.manifest_out.write_bytes(keep)
        expect = 'refusing to overwrite'
    else:
        world.receipt_out.write_bytes(keep)
        expect = 'refusing to overwrite'
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect=expect)
    if case == 'stage_non_empty':
        assert (world.stage / 'keep.txt').read_bytes() == keep and len(list(world.stage.iterdir())) == 1
    if case == 'stage_empty':
        assert list(world.stage.iterdir()) == []
    if case == 'manifest_exists':
        assert world.manifest_out.read_bytes() == keep and not world.stage.exists()
    if case == 'receipt_exists':
        assert world.receipt_out.read_bytes() == keep and not world.stage.exists()


@pytest.mark.parametrize('field', ['output', 'manifest_out', 'receipt_out'])
def test_relative_output_paths_are_refused(freeze, world, capsys, field):
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect='must be an absolute path', **{field: 'relative-output'})
    assert world.outputs_absent()


def test_stage_inside_the_repository_is_refused(freeze, world, capsys):
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect='must lie outside the repository', output=world.repo / 'staged')
    assert not (world.repo / 'staged').exists()


@pytest.mark.parametrize('target', [r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261009-r4', r'C:\Program Files\CoChem\Pipeline4.2.7-windows-2026101-r5',
                                    r'D:\Pipeline4.2.7-windows-20261011-r5', r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261011-r5\sub',
                                    CONTRACT_TARGET_ROOT + '\n'])
def test_target_root_must_be_a_dated_r5_root(freeze, world, capsys, target):
    fill(freeze, world.pins)
    refuse(freeze, world, capsys, expect='--target-root must be', target_root=target)
    assert world.outputs_absent()


def test_target_root_parameter_is_recorded_verbatim(freeze, world, capsys):
    fill(freeze, world.pins)
    target = r'C:\Program Files\CoChem\Pipeline4.2.7-windows-20261012-r5'
    manifest, _receipt = succeed(freeze, world, capsys, target_root=target)
    assert manifest['target_root'] == target


def test_staged_bytes_are_reverified_from_disk(freeze, world, capsys):
    fill(freeze, world.pins)
    original = freeze.write_new

    def corrupting(path, data):
        original(path, data + b'#' if path.name == 'runtime.py' else data)
    freeze.write_new = corrupting
    refuse(freeze, world, capsys, expect='Staged file does not match its manifest row: src/cochem_pipeline/runtime.py')
    assert not world.manifest_out.exists() and not world.receipt_out.exists()


def test_stage_holding_anything_outside_the_manifest_is_refused(freeze, world, capsys):
    fill(freeze, world.pins)
    original = freeze.write_new

    def adding(path, data):
        original(path, data)
        if path.name == 'uv.lock':
            original(path.with_name('stray.txt'), b'stray\n')
    freeze.write_new = adding
    refuse(freeze, world, capsys, expect='holds files outside its manifest')
    assert not world.manifest_out.exists() and not world.receipt_out.exists()


def test_an_unexpected_extra_differing_path_is_refused(freeze, world, capsys):
    """Any staged row that differs from r4 outside the 13 repairs stops the freeze before staging."""
    fill(freeze, world.pins)
    original = freeze.sha256

    def skewed(data):
        digest = original(data)
        return '0' * 64 if data == world.base['pyproject.toml'] and skewed.armed else digest
    skewed.armed = False
    original_load = freeze.load_base

    def load_then_arm(arguments):
        loaded = original_load(arguments)
        skewed.armed = True
        return loaded
    freeze.sha256 = skewed
    freeze.load_base = load_then_arm
    refuse(freeze, world, capsys, expect='must change exactly the 13 reviewed repairs and nothing else')
    assert world.outputs_absent()


# ---- --print-pins -----------------------------------------------------------------------------------

def test_print_pins_prints_the_13_blob_sha256_values_in_table_order(world, tmp_path):
    result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '--print-pins', f'--commit={world.commit}', f'--repo={world.repo}',
                             f'--output={world.stage}', f'--manifest-out={world.manifest_out}', f'--receipt-out={world.receipt_out}'],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert len(lines) == 13 and result.stdout.endswith('\n')
    order = [relative for relative, _c, _p in load_freeze().REPAIRS]
    for line, relative in zip(lines, order):
        assert re.fullmatch(r'[0-9a-f]{64}  src/[A-Za-z0-9_/]+\.py', line), line
        assert line == f'{world.pins[relative]}  {relative}'
    assert world.commit in result.stderr
    assert world.outputs_absent()


def test_print_pins_works_while_placeholders_remain(freeze, world, capsys):
    freeze.REPAIRS = tuple((relative, convention, PLACEHOLDER) for relative, convention, _ in freeze.REPAIRS)
    assert freeze.main(['--print-pins', f'--commit={world.commit[:10]}', f'--repo={world.repo}']) == 0
    output = capsys.readouterr().out.splitlines()
    assert {line.split('  ')[1]: line.split('  ')[0] for line in output} == world.pins


def test_print_pins_refuses_a_commit_that_breaks_the_line_ending_rule(tmp_path):
    bad = 'src/cochem_pipeline/agy_protocol.py'
    mixed = 'src/cochem_pipeline/service.py'
    world = make_world(tmp_path, repo_overrides={bad: source_body(bad, 'r5', 'CRLF'), mixed: source_body(mixed, 'r5', 'CRLF') + b'x = 1\n'})
    result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '--print-pins', f'--commit={world.commit}', f'--repo={world.repo}'],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 1 and result.stdout == ''
    assert bad in result.stderr and mixed in result.stderr and 'cannot be pinned' in result.stderr


def test_print_pins_refuses_a_missing_repair(freeze, tmp_path, capsys):
    world = make_world(tmp_path, repo_overrides={'src/cochem_supervisor/runner.py': None})
    assert freeze.main(['--print-pins', f'--commit={world.commit}', f'--repo={world.repo}']) == 1
    captured = capsys.readouterr()
    assert captured.out == '' and 'src/cochem_supervisor/runner.py is missing from commit' in captured.err


@pytest.mark.parametrize('commit', ['HEAD', '--version'])
def test_print_pins_requires_a_hex_commit(freeze, world, capsys, commit):
    assert freeze.main(['--print-pins', f'--commit={commit}', f'--repo={world.repo}']) == 1
    assert 'lowercase hexadecimal' in capsys.readouterr().err


# ---- the real r4 base, read only ------------------------------------------------------------------

def test_real_r4_manifest_pin_rows_and_a6_paths():
    if not R4_WORKSPACE_MANIFEST.exists():
        pytest.skip('r4 workspace manifest not present')
    raw = R4_WORKSPACE_MANIFEST.read_bytes()
    assert sha(raw) == R4_MANIFEST_SHA256
    rows = {row['relative']: row for row in json.loads(raw)['files']}
    assert len(rows) == 166 and set(A6) <= set(rows)
    assert {'README.md', 'pyproject.toml', 'uv.lock'} <= set(rows)
    assert any(relative.startswith('src/cochem_pipeline/specification/') for relative in rows)


def test_real_installed_r4_receipt_and_conventions_satisfy_the_freeze_checks(freeze):
    """Read-only dry run of the base checks against the installed r4 tree (no staging, no git)."""
    if not (R4_ROOT / 'source-manifest.json').exists():
        pytest.skip('installed r4 runtime not readable')
    arguments = freeze.parse_arguments(['--commit', 'abcdef1'])
    rows, contents = freeze.load_base(arguments)
    assert len(rows) == 166 and len(contents) == 166
    for relative, convention in A6.items():
        assert freeze.frozen_convention(contents[relative]) == convention, relative
    assert freeze.line_endings(contents['src/cochem_pipeline/agy_protocol.py']) == 'LF'
