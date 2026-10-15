"""Real temporary SQLite failure injection; no external execution."""
import sqlite3

import pytest

from cochem_pipeline.attempt_runtime_428 import AttemptAccountingRuntime
from cochem_pipeline.fracture_runtime_428 import FractureRuntime
from cochem_pipeline.task_routing import digest
from pipeline_tests.test_fracture_runtime_428 import _load_catalog, _charge_failures, _three_channel_research


def test_outbox_write_failure_rolls_back_ledger_members_and_pivot(tmp_path):
    accounting = AttemptAccountingRuntime(tmp_path / 'attempts.db')
    runtime = FractureRuntime(accounting.ledger, _load_catalog())
    root = 'atomic-fracture'
    accounting.ensure_lineage(root, complexity=5)
    _charge_failures(accounting, root, root, start_idx=1, count=10, model_family='gpt-6.1-sol', complexity=5)
    runtime.dossier_store.record_dossier(root, 10, research_channels=_three_channel_research(),
        root_cause_synthesis='Two coupled functions fail their interface', hypotheses=['Separate the two fragments'])
    children = [dict(id='child-'+name, role='implementation', complexity=3, task_types=['COD-TERM'],
        rationale='Narrow function', requirement_ids=[req], deliverables=[name+'.py'],
        release_criteria=['Requirement demonstrated'], depends_on=[])
        for name, req in [('parse', 'R1'), ('write', 'R2')]]
    children.append(dict(id='child-assembly', role='assembly', complexity=6, task_types=['COD-TERM'],
        rationale='Integrate both interfaces', requirement_ids=['R1', 'R2'], deliverables=['parse.py', 'write.py'],
        release_criteria=['Both requirements demonstrated'], depends_on=['child-parse', 'child-write']))
    args = dict(failed_scope=dict(scope_id=root, requirement_ids=['R1', 'R2'], deliverables=['parse.py', 'write.py']),
        children=children, review=dict(reviewer_model='claude-opus-5-5', reviewer_tier=6,
                                     effort='high', accepted=True, review_sha256=digest('inert-review')))
    with accounting.ledger._write() as conn:
        conn.execute("CREATE TRIGGER inject_outbox_failure BEFORE INSERT ON task428_fracture_outbox "
                     "BEGIN SELECT RAISE(ABORT,'injected outbox failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='injected outbox failure'):
        runtime.execute_fracture(root, **args)
    state = accounting.ledger.status(root)
    assert state['failures'] == 10 and state['stage'] == 'PIVOT_RESEARCH' and state['pivots'] == []
    with accounting.ledger._write() as conn:
        assert conn.execute("SELECT count(*) FROM task428_members WHERE task_id LIKE 'child-%'").fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM task428_fracture_outbox').fetchone()[0] == 0
        conn.execute('DROP TRIGGER inject_outbox_failure')
    result = runtime.execute_fracture(root, **args)
    assert result['inherited_failures'] == 10
    assert len(result['children']) == 3
    assert len(accounting.ledger.status(root)['pivots']) == 1
