"""The d5d6094 owner sitting held in catalog_acceptance (2026-10-16).

The fence, stop and release all worked on the host and r4 was restored, but the
installed catalog phase rejected the task-catalog request in decode_request
(line 114: 'stale or claims its own authority'). The 865a29b request was prepared
from the r5 bootstrap's baseline routing (6a76497a...), while the board's active
policy is the one r4's own launch published on 2026-10-14 (c8444fe2..., bundle
3dab7f2). These tests reproduce that with the installed decode code, check the
re-prepared request, and drive the launcher's request authority and the new
board check that holds before r4 is touched. Host-file tests skip when the
original packages are absent; nothing executes providers or tasks.
"""
import hashlib
import json
from pathlib import Path

import pytest

from pipeline_tests.test_operational_launch_428 import inert_ps
from pipeline_tests.test_operational_recovery_package_428 import package, prepare  # noqa: F401 (fixture)

from cochem_pipeline.task_catalog_acceptance_428 import decode_request
from cochem_pipeline.routing import load_routing_policy

ORIGINAL=Path(r'C:\Users\ansac\CoChem427\r428-op-launch-865a29b')
BUNDLE=Path(r'C:\Users\ansac\CoChem427\r428-bundle-3dab7f2')
ACTIVE='c8444fe2fd46b0f53edeaefc677ef7ff698c3e11cb83348a70255026a81da43d'
BASELINE='6a76497a281e5ec23fca7f4a8d14a5581c5a35e71a94a0757ac95e7687e0e3c4'
host_inputs=pytest.mark.skipif(not (ORIGINAL/'task-catalog-request.json').is_file() or not (BUNDLE/'launch-manifest.json').is_file(),
                               reason='original release and r4 bundle are host inputs')


def original_inputs():
    manifest=json.loads((ORIGINAL/'launch-manifest.json').read_bytes())
    files={name: (ORIGINAL/name).read_bytes() for name in ('task-catalog-request.json', 'pipeline.json')}
    return manifest, files


@host_inputs
def test_active_policy_is_rebuilt_exactly_from_the_r4_launch_bundle():
    policy, basis=prepare.active_routing_policy(BUNDLE)
    assert policy.digest==ACTIVE and basis['baseline_policy_digest']==BASELINE
    assert basis['active_bundle_launch_manifest_sha256']==prepare.ACTIVE_CATALOG_BUNDLE_MANIFEST_SHA256


@host_inputs
def test_original_request_reproduces_the_owner_hold_and_was_built_for_the_baseline():
    manifest, files=original_inputs()
    policy, _=prepare.active_routing_policy(BUNDLE)
    with pytest.raises(ValueError, match='stale or claims its own authority'):
        decode_request(files['task-catalog-request.json'], policy, None, expected_sha256=manifest['request_sha256'])
    baseline=load_routing_policy(json.loads(files['pipeline.json'])['routing'])
    assert baseline.digest==BASELINE
    decode_request(files['task-catalog-request.json'], baseline, None, expected_sha256=manifest['request_sha256'])


@host_inputs
def test_replacement_request_decodes_but_is_refused_with_the_baseline_bootstrap(monkeypatch):
    # The re-prepared request is valid for the installed decode...
    manifest, files=original_inputs()
    policy, _=prepare.active_routing_policy(BUNDLE)
    captured={}
    real_prepare=prepare.prepare_request
    monkeypatch.setattr(prepare, 'prepare_request', lambda *a, **k: captured.setdefault('request', real_prepare(*a, **k)))
    # ...but the r5 bootstrap still routes the baseline, which the installed
    # enabled_candidate rejects only after publication. Preparation refuses.
    with pytest.raises(ValueError, match='Bootstrap routing differs from the request policy'):
        prepare.active_catalog_request(files, manifest, request_id='1'*32, bundle=BUNDLE)
    request=captured['request'];old=json.loads(files['task-catalog-request.json'])
    data=prepare.encoded(request)
    decoded=decode_request(data, policy, None, expected_sha256=hashlib.sha256(data).hexdigest())
    assert request['previous_policy_digest']==ACTIVE and list(decoded.plan.selected_profile_ids)==old['candidate_profile_ids']
    assert {key for key in old if old[key]!=request[key]}=={'request_id', 'previous_policy_digest', 'plan_digest', 'model_limits'}
    assert load_routing_policy(json.loads(files['pipeline.json'])['routing']).digest==BASELINE


@host_inputs
@pytest.mark.parametrize('tamper', ['manifest', 'proposal', 'digest'])
def test_replacement_refuses_any_unpinned_policy_basis(tmp_path, monkeypatch, tamper):
    bundle=tmp_path/'bundle';bundle.mkdir()
    for name in ('launch-manifest.json', 'pipeline.json', 'proposal.json'):
        (bundle/name).write_bytes((BUNDLE/name).read_bytes())
    if tamper=='manifest':
        (bundle/'launch-manifest.json').write_bytes((BUNDLE/'launch-manifest.json').read_bytes()+b' ')
    if tamper=='proposal':
        (bundle/'proposal.json').write_bytes((BUNDLE/'proposal.json').read_bytes().replace(b'"catalog"', b'"catalog" '))
    if tamper=='digest':
        monkeypatch.setattr(prepare, 'ACTIVE_POLICY_DIGEST', '0'*64)
    with pytest.raises(ValueError):
        prepare.active_routing_policy(bundle)


def test_runtime_source_guard_refuses_source_past_the_installed_r5_and_other_imports(monkeypatch):
    # The r6 runtime fixes moved src beyond 865a29b: no package from this
    # checkout may claim the installed r5 runtime any more.
    with pytest.raises(ValueError, match='installed r5 source'):
        prepare._require_runtime_source(prepare.SCRIPTS.parent)
    import cochem_pipeline
    monkeypatch.setattr(cochem_pipeline, '__file__', r'C:\elsewhere\src\cochem_pipeline\__init__.py')
    with pytest.raises(ValueError, match='repository runtime source'):
        prepare._require_runtime_source(prepare.SCRIPTS.parent)


def test_active_package_carries_the_replacement_and_needs_the_board_check_launcher(package, monkeypatch):
    replacement=json.dumps(dict(schema='cochem-task-catalog-request/4.2.8', request_id='e'*32,
        previous_policy_digest=ACTIVE, previous_task_catalog_sha256=None, activation_authorized=False)).encode()
    monkeypatch.setattr(prepare, '_require_runtime_source', lambda repository: None)
    monkeypatch.setattr(prepare, 'active_catalog_request',
        lambda files, original, *, request_id, bundle: (replacement, json.loads(replacement), dict(schema='cochem-428-catalog-request-basis/1')))
    older=b'function Assert-OpRecoveryManifest { }\nfunction Assert-OpRunningRecoveryEvidence { }\n'
    monkeypatch.setattr(prepare, '_committed_script', lambda repo, commit, name: older)
    with pytest.raises(ValueError, match='cannot submit a replacement'):
        prepare.prepare_operational_recovery(**package, scenario='running', catalog_request='active')
    launcher=b'function Assert-OpRecoveryManifest { }\nfunction Assert-OpRunningRecoveryEvidence { }\nfunction Assert-OpCatalogRequestBoard { }\n'
    monkeypatch.setattr(prepare, '_committed_script', lambda repo, commit, name: launcher)
    result=prepare.prepare_operational_recovery(**package, scenario='running', catalog_request='active')
    manifest=json.loads((package['destination']/'launch-manifest.json').read_bytes())
    assert (package['destination']/prepare.CATALOG_REQUEST_NAME).read_bytes()==replacement
    assert manifest['catalog_request']==prepare.CATALOG_REQUEST_NAME and manifest['catalog_request_id']=='e'*32
    assert manifest['catalog_request_sha256']==hashlib.sha256(replacement).hexdigest()==result['catalog_request_sha256']
    assert manifest['catalog_request_previous_policy_digest']==ACTIVE and manifest['request_sha256']!=manifest['catalog_request_sha256']
    assert {row['name'] for row in manifest['files']}>={prepare.CATALOG_REQUEST_NAME, 'task-catalog-request.json'}


def test_preparer_cli_requires_an_explicit_catalog_request_choice(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['prepare', '--destination', 'd', '--repository', 'r', '--recovery-source-tests', 't',
        '--launcher-source-commit', 'b'*40, '--recovery-source-tests-sha256', 'c'*64, '--scenario', 'running'])
    monkeypatch.setattr(prepare, 'prepare_operational_recovery', lambda **kw: pytest.fail('must not prepare'))
    with pytest.raises(SystemExit):
        prepare.main()
    assert '--catalog-request' in capsys.readouterr().err


# --- Launcher: request authority and the pre-stop board check -------------------

RESOLVE=r"""
$dir='DIR'
function Open-428Pin {param($p,$h)$raw=[IO.File]::ReadAllBytes($p)
    $sha=[BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($raw)).Replace('-','').ToLowerInvariant()
    if($sha -cne $h){throw 'Pinned record mismatch'};[IO.MemoryStream]::new($raw)}
function Read-428Json {param($s)$r=[IO.StreamReader]::new($s);try{$r.ReadToEnd()|ConvertFrom-Json}finally{$r.Dispose()}}
$m=Get-Content -LiteralPath (Join-Path $dir 'manifest.json') -Raw|ConvertFrom-Json
$pins=[Collections.Generic.List[IO.Stream]]::new()
$result=$null;$message=$null
try{$result=Resolve-OpCatalogRequest $m $dir $pins RECOVERY}catch{$message=$_.Exception.Message}
foreach($p in $pins){$p.Dispose()}
@{result=$result;message=$message}|ConvertTo-Json -Depth 4 -Compress
"""


def write_resolve_package(tmp_path, change=None):
    original=json.dumps(dict(schema='cochem-task-catalog-request/4.2.8', request_id='a'*32, previous_policy_digest=BASELINE,
        previous_task_catalog_sha256=None, activation_authorized=False)).encode()
    active=json.dumps(dict(schema='cochem-task-catalog-request/4.2.8', request_id='e'*32, previous_policy_digest=ACTIVE,
        previous_task_catalog_sha256=None, activation_authorized=False)).encode()
    (tmp_path/'task-catalog-request.json').write_bytes(original)
    (tmp_path/'task-catalog-request-active.json').write_bytes(active)
    sha=lambda b: hashlib.sha256(b).hexdigest()
    manifest=dict(request_sha256=sha(original), files=[dict(name='task-catalog-request.json', sha256=sha(original), length=len(original)),
        dict(name='task-catalog-request-active.json', sha256=sha(active), length=len(active))],
        catalog_request='task-catalog-request-active.json', catalog_request_sha256=sha(active), catalog_request_id='e'*32,
        catalog_request_previous_policy_digest=ACTIVE)
    if change:
        change(manifest)
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    return sha(original), sha(active)


def resolve(tmp_path, change=None, recovery=True):
    original, active=write_resolve_package(tmp_path, change)
    result=inert_ps(RESOLVE.replace('DIR', str(tmp_path)).replace('RECOVERY', '$true' if recovery else '$false'))
    return result, original, active


def test_replacement_request_becomes_the_sitting_authority(tmp_path):
    result, original, active=resolve(tmp_path)
    assert result['message'] is None, result
    assert result['result']=={'name': 'task-catalog-request-active.json', 'sha256': active, 'request_id': 'e'*32,
                               'previous_policy_digest': ACTIVE, 'previous_task_catalog_sha256': None}


def test_without_a_replacement_the_original_request_is_the_authority(tmp_path):
    def drop(m):
        for key in ('catalog_request', 'catalog_request_sha256', 'catalog_request_id', 'catalog_request_previous_policy_digest'):
            del m[key]
    result, original, _=resolve(tmp_path, drop, recovery=False)
    assert result['message'] is None and result['result']['sha256']==original
    assert result['result']['previous_policy_digest']==BASELINE


@pytest.mark.parametrize('change,recovery,message', [
    (None, False, 'Catalog request replacement identity differs.'),                       # fresh installs never replace
    (lambda m: m.update(catalog_request='other.json'), True, 'Catalog request replacement identity differs.'),
    (lambda m: m.update(catalog_request_sha256='0'*64), True, 'Catalog request replacement identity differs.'),
    (lambda m: m.update(catalog_request_sha256=m['request_sha256']), True, 'Catalog request replacement identity differs.'),
    (lambda m: m.update(catalog_request_id='f'*32), True, 'Catalog request identity differs.'),
    (lambda m: m.update(catalog_request_previous_policy_digest=BASELINE), True, 'Catalog request identity differs.'),
    (lambda m: m.pop('catalog_request'), True, 'Incomplete catalog request replacement.'),
])
def test_replacement_identity_is_exact(tmp_path, change, recovery, message):
    result, _, _=resolve(tmp_path, change, recovery)
    assert result['message']==message, result


@pytest.mark.parametrize('submitted,catalog,held', [
    ("@{previous_policy_digest='p';previous_task_catalog_sha256=$null}", "@{active_policy_sha256='p';active_catalog_sha256=$null}", None),
    ("@{previous_policy_digest='p';previous_task_catalog_sha256=$null}", "@{active_policy_sha256='q';active_catalog_sha256=$null}", 'routing policy'),
    ("@{previous_policy_digest='p';previous_task_catalog_sha256=$null}", "@{active_policy_sha256='p';active_catalog_sha256='t'}", 'task catalog'),
    ("@{previous_policy_digest='p';previous_task_catalog_sha256='t'}", "@{active_policy_sha256='p';active_catalog_sha256=$null}", 'task catalog'),
    ("@{previous_policy_digest='p';previous_task_catalog_sha256='t'}", "@{active_policy_sha256='p';active_catalog_sha256='t'}", None),
    ("@{previous_policy_digest='p';previous_task_catalog_sha256=$null}", '$null', 'routing policy'),   # no live identity is never a match
])
def test_board_check_requires_the_request_to_name_the_live_authority(submitted, catalog, held):
    result=inert_ps(r"""$m=$null;try{Assert-OpCatalogRequestBoard SUBMITTED CATALOG}catch{$m=$_.Exception.Message}
@{message=$m}|ConvertTo-Json -Compress""".replace('SUBMITTED', submitted).replace('CATALOG', catalog))
    assert (result['message'] is None) if held is None else (held in result['message']), result


def test_catalog_request_authority_is_required_before_use():
    result=inert_ps(r"""$m=$null;try{$null=Get-OpCatalogRequest}catch{$m=$_.Exception.Message}
@{message=$m}|ConvertTo-Json -Compress""")
    assert result['message']=='Catalog request authority was not established.'
