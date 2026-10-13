"""Build a fresh ordinary-user auth-only package; never run native providers."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT/'docs/deployment/windows-deployment-next'
LEGACY_FILES = (
    'login_pipeline_worker_interactive_agy_r4_v1.ps1',
    'worker_agy_login_bridge_r4_v1.py', 'worker-native-auth-status-six-r4-v1.py',
    'check-worker-native-status-r3.ps1', 'check-worker-native-auth-status-six-r4-v1.ps1',
    'register-stopped-warden-r3.ps1', 'protected-code-inspection-v4.ps1',
    'claude-code-input-v6.ps1', 'login_pipeline_worker_interactive_r3_v6.ps1',
    'agy-session-history-r4-v1.ps1',
)


def prepare(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Preserve an existing package; choose a new directory')
    files = [LEGACY/name for name in LEGACY_FILES]
    files += [ROOT/'scripts'/name for name in (
        'signin_agy_profiles.ps1','worker_agy_signin_batch.py','worker_agy_terminal_bridge.py',
        'login_pipeline_worker_agy_terminal.ps1','stage_aetherdesk_427_payloads.ps1')]
    files += [ROOT/'src/cochem_pipeline/attended_agy_terminal.py']
    rows = []
    destination.mkdir(parents=True)
    for path in files:
        raw = path.read_bytes()
        with (destination/path.name).open('xb') as stream:
            stream.write(raw)
        rows.append(dict(relative=path.name, length=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    manifest = dict(schema='cochem-agy-signin-package/1', host='AETHERDESK', files=rows)
    raw = (json.dumps(manifest, indent=2)+'\n').encode()
    with (destination/'manifest.json').open('xb') as stream:
        stream.write(raw)
    return dict(package=str(destination), files=len(rows), manifest_sha256=hashlib.sha256(raw).hexdigest(),
                provider_commands_executed=0, deployment_attempted=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    print(json.dumps(prepare(parser.parse_args().destination)))
