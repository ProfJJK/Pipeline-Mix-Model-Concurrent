from pathlib import Path
from types import SimpleNamespace

import pytest

from cochem_pipeline.r6_host_acceptance import _claude_logged_out, fresh_knowledge, read_bound


@pytest.mark.parametrize(('text', 'expected'), [('{}', False), ('garbage', False),
    ('{"loggedIn":false}', True), ('{"loggedIn":true}', False), ('{"loggedIn":0}', False),
    ('{"loggedIn":false,"loggedIn":true}', False)])
def test_only_explicit_native_logout_enables_front_loaded_login(text, expected):
    assert _claude_logged_out(text) is expected


def test_knowledge_existing_generation_never_rebuilt(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr('cochem_pipeline.knowledge.KnowledgeService', lambda _: called.append(True))
    with pytest.raises(ValueError, match='Preserve'):
        fresh_knowledge(SimpleNamespace(knowledge=SimpleNamespace(state_root=str(tmp_path))))
    assert not called


def test_bound_read_refuses_different_bytes_and_multiple_links(tmp_path):
    file = tmp_path/'payload'; file.write_bytes(b'fixture')
    win = SimpleNamespace(validate_code_path=lambda _: None)
    with pytest.raises(ValueError, match='pinned'):
        read_bound(win, file, 'a'*64)
    with pytest.raises(ValueError, match='bounds'):
        read_bound(win, file, maximum=2)
