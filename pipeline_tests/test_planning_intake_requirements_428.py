import pytest

from pipeline_tests.test_planning_runtime_428 import pump


def test_explicit_requirements_survive_capture_and_replay(pump):
    reqs = ['Write Markdown only', 'Include exact artifact hash']
    task = pump.journal.create('requested', 'Produce a report', requested_requirements=reqs)
    assert task['requested_requirements'] == reqs
    assert pump.journal.intent('requested')['task']['requested_requirements'] == reqs
    assert pump.journal.create('requested', 'Produce a report', requested_requirements=reqs) == task
    with pytest.raises(ValueError, match='another objective'):
        pump.journal.create('requested', 'Produce a report', requested_requirements=['Different format'])


@pytest.mark.parametrize('reqs', [[''], ['same', 'same'], ['x' * 16001], ['x'] * 201, 'not-an-array', [None]])
def test_invalid_requirements_rejected_before_intake(pump, reqs):
    with pytest.raises(ValueError, match='Requested requirements'):
        pump.journal.create('requested', 'Produce a report', requested_requirements=reqs)
    assert not pump.journal.has_task('requested')


def test_missing_and_empty_requirements_keep_legacy_replay(pump):
    assert pump.journal.create('task', 'Produce the specified deliverable', requested_requirements=[]) == pump.journal.status('task')
