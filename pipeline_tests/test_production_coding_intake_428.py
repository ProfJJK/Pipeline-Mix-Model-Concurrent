"""Authenticated loopback fixture boundaries; no provider or native execution."""
from types import SimpleNamespace

import pytest

from cochem_pipeline.coding import CodingCoordinator, CodingProject
from pipeline_tests.test_service import endpoint, request


@pytest.mark.parametrize('route', ['/coding/submit', '/tasks/submit', '/submit'])
def test_fixture_rejected_before_dispatch(endpoint, route, tmp_path):
    fixture = CodingProject('windows-acceptance', tmp_path, 'main', ('src',))
    endpoint.controller.config.coding_projects = {'windows-acceptance': fixture}
    endpoint.controller.task_planning = SimpleNamespace(submit=lambda *a, **kw: pytest.fail('dispatched'))
    endpoint.controller.submit_coding = lambda *a, **kw: pytest.fail('dispatched')
    code, body = request(endpoint, 'POST', route,
                         {'project_id': 'windows-acceptance', 'objective': 'Real production work'},
                         authorization='Bearer ' + endpoint.token)
    assert code == 400
    assert 'acceptance fixture' in body['error']
    assert endpoint.controller.store.active_jobs() == []


def test_discovery_separates_fixture_from_real_projects(endpoint, tmp_path):
    endpoint.controller.config.coding_projects = {
        name: CodingProject(name, tmp_path / name, 'main', ('src',))
        for name in ('windows-acceptance', 'real-project')}
    code, body = request(endpoint, 'GET', '/coding/projects', authorization='Bearer ' + endpoint.token)
    assert code == 200
    assert body == {'projects': ['real-project'], 'acceptance_fixtures': ['windows-acceptance']}


def test_direct_coordinator_rejects_fixture_before_reading_source(tmp_path):
    coordinator = object.__new__(CodingCoordinator)
    coordinator.config = SimpleNamespace(
        coding_projects={'windows-acceptance': CodingProject('windows-acceptance', tmp_path, 'main', ('src',))},
        ramdisk=SimpleNamespace(enabled=True), docker=SimpleNamespace(enabled=True))
    with pytest.raises(ValueError, match='acceptance fixture'):
        coordinator.submit('windows-acceptance', 'Real work', ['REQ-1'])
