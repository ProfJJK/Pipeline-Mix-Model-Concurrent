from pathlib import Path
from types import SimpleNamespace

import pytest

from cochem_pipeline.r6_agent_acceptance import verify_worker


class Checks:
    def __init__(self, failure=None):
        self.failure, self.calls, self.closed, self.released = failure, 0, False, False
    def token(self, identity): return 'restricted-token'
    def close_token(self, token): self.closed = True
    def profile(self, token): return Path('profile')
    def sid(self, identity): return 'fixture-sid'
    def guard(self, token, sid, contract):
        if self.failure == 'guard': raise ValueError('fixture guard error')
        return SimpleNamespace(handles=list(range(9)), close=self.release)
    def release(self): self.released = True
    def check(self, token, requests):
        self.calls += 1
        if self.failure == 'exception' and self.calls == 2: raise OSError('fixture')
        if self.calls == 2:
            return [0 if self.failure == 'allowed' else 32] + [5] * (len(requests)-1)
        rows = [0] + [5] * (len(requests)-1)
        if self.failure == 'missing': rows[-1] = 2
        if self.failure == 'cleanup' and self.calls == 3: rows[0] = 32
        return rows


def test_rg4_checks_actual_guard_window_and_release_without_mutating_paths():
    api = Checks()
    result = verify_worker(api, {}, {})
    assert result['handle_requests'] == 11
    assert result['cleanup_verified'] and result['replacement_denied']
    assert result['path_mutations'] == result['native_model_jobs_executed'] == 0
    assert api.calls == 3 and api.closed and api.released


@pytest.mark.parametrize('failure', ['guard', 'missing', 'allowed', 'exception', 'cleanup'])
def test_missing_content_and_failed_custody_never_count_as_acceptance(failure):
    api = Checks(failure)
    with pytest.raises((ValueError, OSError)):
        verify_worker(api, {}, {})
    assert api.closed
    if failure in ('allowed', 'exception', 'cleanup'):
        assert api.released
