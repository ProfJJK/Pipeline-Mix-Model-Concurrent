"""Real corpus, FTS5, authenticated HTTP and MCP knowledge acceptance."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import ctypes
from dataclasses import replace
import gc
import hashlib
import http.client
import json
import os
from pathlib import Path
import random
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from cochem_pipeline.knowledge import KnowledgeConfig,KnowledgeError,KnowledgeService
from cochem_pipeline.knowledge_authority import KnowledgeAuthority


def ratify(root,documents):
    entries=[]
    for key,text in documents.items():
        target=root/key;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(text.encode('utf-8'))
        entries.append({'path':key,'sha256':hashlib.sha256(text.encode('utf-8')).hexdigest()})
    manifest=root/'v4.1.2_manifest.json'
    manifest.write_text(json.dumps({'manifest_version':'4.2.6','documents':entries,
                                   'srs_documents':[key for key in documents if key.startswith('wiki/')]},ensure_ascii=False),encoding='utf-8')


@pytest.fixture
def portable_knowledge_permissions(monkeypatch):
    if os.name == 'nt':
        # Real SQLite/HTTP/MCP regression coverage, with an explicit permission
        # fixture. Actual Windows creation/ACL behavior has its own test module;
        # these retrieval tests are not SYSTEM acceptance.
        from cochem_pipeline import knowledge
        monkeypatch.setattr(knowledge, '_protected',
            lambda path, *, directory=False, private=False: knowledge._ordinary(path, directory=directory))
        monkeypatch.setattr(knowledge, '_private_directory',
            lambda path, *, exist_ok=False: path.mkdir(mode=0o700, exist_ok=exist_ok))


@pytest.fixture
def corpus(tmp_path,portable_knowledge_permissions):
    root=tmp_path/'corpus';root.mkdir()
    private=tmp_path/'private';private.mkdir(mode=0o700)
    docs={'.sources/reference.md':'# Reference\nPermanent Ψ(r), ΔG°, kJ·mol⁻¹ observations.\n',
          'wiki/00_skeleton.md':'# Catalog\n[Warden](warden.md#safety)\n[Reference](../.sources/reference.md)\n',
          'wiki/warden.md':'# Warden\n## Safety\nSQLite fencing protects native workers.\n'}
    ratify(root,docs)
    config=KnowledgeConfig(enabled=True,source_root=str(root/'.sources'),wiki_root=str(root/'wiki'),
                           manifest_path=str(root/'v4.1.2_manifest.json'),state_root=str(private/'knowledge'))
    service=KnowledgeService(config)
    try:
        yield SimpleNamespace(root=root,private=private,docs=docs,config=config,service=service)
    finally:
        service.close()


def test_real_index_unicode_catalog_links_and_read_only_schema(corpus):
    result=corpus.service.refresh()
    assert result['document_count']==3 and result['section_count']==4
    assert result['relative_links_checked']==2 and result['changed_documents']==3
    assert corpus.service.read('.sources/reference.md')['text']==corpus.docs['.sources/reference.md']
    rows=corpus.service.search('SQLite fencing')
    assert rows[0]['doc_path']=='wiki/warden.md' and rows[0]['score']<0
    assert corpus.service.search('ΔG')[0]['doc_path']=='.sources/reference.md'
    with corpus.service._reader() as (_,reader):
        assert [row[1] for row in reader.execute('PRAGMA table_info(documents)')]==[
            'id','doc_path','title','line_count','sha256','updated_at','authority','authority_revision']
        assert 'porter unicode61' in reader.execute("SELECT sql FROM sqlite_master WHERE name='fts_index'").fetchone()[0]
        with pytest.raises(sqlite3.OperationalError):
            reader.execute('DELETE FROM documents')


def test_incremental_only_reindexes_changed_documents_and_deletion(corpus):
    initial=corpus.service.refresh()
    assert corpus.service.refresh()['changed_documents']==0
    corpus.docs['wiki/warden.md']+='Reliable recovery.\n'
    ratify(corpus.root,corpus.docs)
    updated=corpus.service.refresh()
    assert updated['generation']!=initial['generation'] and updated['changed_documents']==1
    assert corpus.service.search('Reliable recovery')
    corpus.docs['wiki/00_skeleton.md']='# Catalog\n[Reference](../.sources/reference.md)\n'
    corpus.docs.pop('wiki/warden.md');(corpus.root/'wiki/warden.md').unlink()
    ratify(corpus.root,corpus.docs)
    removed=corpus.service.refresh()
    assert removed['removed_documents']==1 and not corpus.service.search('SQLite')


def test_full_reindex_is_atomic_for_real_concurrent_readers(corpus):
    corpus.service.refresh()
    def search():
        for _ in range(25):
            assert corpus.service.search('SQLite')[0]['doc_path']=='wiki/warden.md'
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(search) for _ in range(3)]
        rebuilt=corpus.service.refresh(full=True)
        for future in futures:
            future.result()
    assert rebuilt['changed_documents']==3


def test_failed_ratification_preserves_accepted_generation_and_archive(corpus):
    before=corpus.service.refresh()
    corpus.docs['.sources/reference.md']='Changed historic source\n'
    ratify(corpus.root,corpus.docs)
    with pytest.raises(KnowledgeError,match='immutable'):
        corpus.service.refresh()
    assert corpus.service.status()['generation']==before['generation']
    with pytest.raises(KnowledgeError,match='changed since'):
        corpus.service.read('.sources/reference.md')


def test_corrupt_binary_header_rebuilds_from_real_corpus(corpus):
    before=corpus.service.refresh()
    _,database=corpus.service._current()
    database.write_bytes(b'broken SQLite file')
    result=corpus.service.refresh()
    assert result['rebuilt_corruption'] and result['generation']!=before['generation']
    assert corpus.service.search('fencing')


def test_corruption_cannot_reset_the_permanent_source_archive(corpus):
    corpus.service.refresh()
    _,database=corpus.service._current();database.write_bytes(b'corrupt')
    corpus.docs['.sources/reference.md']='# Replaced history\n'
    ratify(corpus.root,corpus.docs)
    with pytest.raises(KnowledgeError,match='immutable'):
        corpus.service.refresh()


def test_srs_catalog_requires_a_skeleton_link_to_each_chapter(corpus):
    corpus.docs['wiki/00_skeleton.md']='# Catalog\n[Reference](../.sources/reference.md)\n'
    ratify(corpus.root,corpus.docs)
    with pytest.raises(KnowledgeError,match='skeleton must link'):
        corpus.service.refresh()


def test_search_requests_real_background_rebuild_after_corruption(corpus):
    corpus.service.refresh()
    _,database=corpus.service._current();database.write_bytes(b'corrupt')
    with pytest.raises(KnowledgeError,match='background rebuild'):
        corpus.service.search('fencing')
    corpus.service._background.join(timeout=5)
    assert not corpus.service._background.is_alive()
    assert corpus.service.search('fencing')


@pytest.mark.parametrize('path',['../secret.md','wiki/../../secret.md','/etc/passwd','C:/secret.md',
                               'wiki\\file.md','wiki/CON.md','wiki/file.md.','wiki/a//b.md','wiki/a.py'])
def test_read_rejects_unregistered_or_ambiguous_paths(corpus,path):
    corpus.service.refresh()
    with pytest.raises(KnowledgeError):
        corpus.service.read(path)


@pytest.mark.parametrize('text',['# Catalog\n[Absent](absent.md)\n',
    '# Catalog\n[Bad](warden.md#missing)\n','# Catalog\n[Escape](../../secret.md)\n',
    '# Catalog\n[Undefined][missing]\n','# Catalog\n'+'line\n'*400])
def test_invalid_links_and_oversized_chapters_cannot_publish(corpus,text):
    initial=corpus.service.refresh()
    corpus.docs['wiki/00_skeleton.md']=text;ratify(corpus.root,corpus.docs)
    with pytest.raises((KnowledgeError,FileNotFoundError)):
        corpus.service.refresh()
    assert corpus.service.status()['generation']==initial['generation']


def test_code_fences_do_not_invent_links_or_sections(corpus):
    corpus.docs['wiki/warden.md']+="```python\n# not a chapter\n'[missing](missing.md)'\n```\n"
    ratify(corpus.root,corpus.docs)
    assert corpus.service.refresh()['section_count']==4


def test_symlink_rejected(corpus,tmp_path):
    outside=tmp_path/'outside.md';outside.write_text('secret',encoding='utf-8')
    target=corpus.root/'wiki/link.md'
    try:
        target.symlink_to(outside)
    except OSError as error:
        if os.name == 'nt' and error.winerror == 1314:
            pytest.skip('Windows token lacks symlink creation privilege; junction/hardlink checks are separate')
        raise
    with pytest.raises(KnowledgeError,match='without links'):
        corpus.service.refresh()


def test_hardlink_and_manifest_desync_rejected(corpus,tmp_path):
    outside=tmp_path/'outside.md';outside.write_text('secret',encoding='utf-8')
    target=corpus.root/'wiki/link.md';os.link(outside,target)
    with pytest.raises(KnowledgeError,match='without links'):
        corpus.service.refresh()
    target.unlink();target.write_text('# Unratified\n',encoding='utf-8')
    with pytest.raises(KnowledgeError,match='not synchronized'):
        corpus.service.refresh()


def test_manifest_hash_and_bounded_search_do_not_trust_caller_text(corpus):
    corpus.service.refresh()
    assert corpus.service.search('" OR nonexistentword')==[]
    for query,limit in [('',5),('word '*33,5),('valid',True),('valid',21)]:
        with pytest.raises(KnowledgeError):
            corpus.service.search(query,limit)
    (corpus.root/'wiki/warden.md').write_text('# Warden\n## Safety\nUnratified edit',encoding='utf-8')
    with pytest.raises(KnowledgeError,match='Manifest hash'):
        corpus.service.refresh()


def test_config_placement_rejects_worker_or_private_corpus(corpus):
    corpus.config.validate_placement(corpus.private,[])
    with pytest.raises(KnowledgeError,match='disjoint'):
        corpus.config.validate_placement(corpus.private,[corpus.root])
    with pytest.raises(KnowledgeError,match='dedicated child'):
        replace(corpus.config,state_root=str(corpus.root.parent/'other')).validate_placement(corpus.private)
    with pytest.raises(KnowledgeError,match='enabled'):
        KnowledgeService(KnowledgeConfig())


def test_pipeline_loader_registers_real_corpus_and_rejects_worker_overlap(corpus,tmp_path):
    from cochem_pipeline.config import load_config
    from pipeline_tests.test_config import config_document,write_config
    raw=config_document(tmp_path)
    raw['knowledge']=corpus.config.as_dict()
    raw['private_root']=str(corpus.private)
    loaded=load_config(write_config(tmp_path,raw))
    assert loaded.knowledge==corpus.config
    raw['slot_roots']['slot-0']=str(corpus.root/'slot')
    with pytest.raises(KnowledgeError,match='disjoint'):
        load_config(write_config(tmp_path,raw))


def test_real_authenticated_http_mcp_and_cli_retrieval(corpus,tmp_path):
    from cochem_pipeline.service import ControlClient,ControlServer
    from cochem_pipeline.server import create_server,create_knowledge_server
    from mcp.shared.memory import create_connected_server_and_client_session
    corpus.service.refresh()
    runtime=SimpleNamespace(config=SimpleNamespace(port=0),knowledge=corpus.service)
    token=secrets.token_urlsafe(48);token_file=tmp_path/'token';token_file.write_text(token,encoding='utf-8')
    server=ControlServer(runtime,token)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    client=ControlClient(server.server_address[1],token_file)
    try:
        connection=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=3)
        connection.request('GET','/knowledge/status');response=connection.getresponse()
        assert response.status==401;response.read();connection.close()
        status=client.call('/knowledge/status')
        assert status['indexed'] and not status['ready'], 'Tiny fixtures do not meet the 4x SQLite page-size floor'
        token_file.write_text('invalid-token',encoding='utf-8')
        with pytest.raises(RuntimeError,match='Unauthorized'):
            client.call('/knowledge/status')
        token_file.write_text(token,encoding='utf-8')
        async def scenario():
            async with create_connected_server_and_client_session(create_server(client)) as session:
                result=await session.call_tool('knowledge_search',{'query':'fencing'})
                assert not result.isError and result.structuredContent['results'][0]['doc_path']=='wiki/warden.md'
                text=await session.call_tool('knowledge_read',{'doc_path':'.sources/reference.md'})
                assert not text.isError and text.structuredContent['text']==corpus.docs['.sources/reference.md']
                denied=await session.call_tool('knowledge_read',{'doc_path':'../../secret.md'})
                assert denied.isError
            async with create_connected_server_and_client_session(create_knowledge_server(client)) as session:
                tools=await session.list_tools()
                assert {tool.name for tool in tools.tools}=={'knowledge_search','knowledge_read','knowledge_status'}
                # The optimized result envelope must keep the public schema and
                # both MCP representations, including literal scientific UTF-8.
                for tool in tools.tools:
                    assert tool.outputSchema=={'additionalProperties':True,
                        'title':tool.name+'DictOutput','type':'object'}
                result=await session.call_tool('knowledge_search',{'query':'fencing'})
                assert not result.isError and result.structuredContent['results']
                assert json.loads(result.content[0].text)==result.structuredContent
                read=await session.call_tool('knowledge_read',{'doc_path':'.sources/reference.md'})
                assert json.loads(read.content[0].text)==read.structuredContent
                assert 'Ψ(r), ΔG°, kJ·mol⁻¹' in read.content[0].text
                token_file.write_text('invalid-token',encoding='utf-8')
                denied=await session.call_tool('knowledge_search',{'query':'fencing'})
                assert denied.isError and 'Unauthorized' in denied.content[0].text
                token_file.write_text(token,encoding='utf-8')
                restored=await session.call_tool('knowledge_search',{'query':'fencing'})
                assert not restored.isError and restored.structuredContent['results']
                bounded=await session.call_tool('knowledge_search',{'query':'fencing','limit':21})
                assert bounded.isError
        asyncio.run(scenario())
        config=tmp_path/'client.json';config.write_text(json.dumps({'port':server.server_address[1],'token_file':str(token_file)}),encoding='utf-8')
        environment={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src'),'PYTHONIOENCODING':'utf-8'}
        result=subprocess.run([sys.executable,'-m','cochem_pipeline','knowledge-search','--client-config',str(config),'fencing'],
            capture_output=True,text=True,encoding='utf-8',timeout=10,env=environment,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)['results'][0]['doc_path']=='wiki/warden.md'
    finally:
        client.close()
        server.shutdown();server.server_close();thread.join(timeout=3)


def test_authority_badges_are_ratified_metadata_not_self_proclaimed_document_text(corpus):
    path=corpus.root/'v4.1.2_manifest.json'
    manifest=json.loads(path.read_text())
    for item in manifest['documents']:
        item['authority']='historical_source' if item['path'].startswith('.sources/') else 'current_normative'
        item['authority_revision']='owner-amendment-2026-10-06'
    path.write_text(json.dumps(manifest))
    first=corpus.service.refresh()
    assert corpus.service.search('SQLite')[0]['authority']=='current_normative'
    assert corpus.service.read('.sources/reference.md')['authority_label']=='Historical source'
    # Same bytes, different reviewed authority: metadata changes publish a generation.
    for item in manifest['documents']:
        if item['path']=='wiki/warden.md':item['authority']='owner_decision'
    path.write_text(json.dumps(manifest))
    refreshed=corpus.service.refresh()
    assert refreshed['generation']!=first['generation'] and refreshed['changed_documents']==0
    result=corpus.service.search('SQLite')[0]
    assert result['authority']=='owner_decision'
    assert result['authority_label']=='Owner decision'
    assert result['authority_revision']=='owner-amendment-2026-10-06'


def test_uncatalogued_authority_is_never_inferred_from_filename_or_prose(corpus):
    corpus.service.refresh()
    assert corpus.service.search('SQLite')[0]['authority']=='unclassified'
    path=corpus.root/'v4.1.2_manifest.json';manifest=json.loads(path.read_text())
    manifest['documents'][0]['authority']='current_normative'
    path.write_text(json.dumps(manifest))
    with pytest.raises(KnowledgeError,match='authority'):corpus.service.refresh()
    assert corpus.service.search('SQLite')[0]['authority']=='unclassified'


GENERATED_REVISION='r5-controller-memory-fixture'


def sqlite_memory_used():
    """Return sqlite3_memory_used of the SQLite library behind the sqlite3 module.

    The counter is process-wide, so callers compare deltas. A self-check first
    grows a private in-memory database and skips when the counter does not see
    it (a different library copy, or SQLITE_DEFAULT_MEMSTATUS=0).
    """
    import _sqlite3
    library=None
    if os.name=='nt':
        kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel32.GetModuleHandleW.argtypes=[ctypes.c_wchar_p]
        kernel32.GetModuleHandleW.restype=ctypes.c_void_p
        handle=kernel32.GetModuleHandleW('sqlite3.dll')
        if handle:
            library=ctypes.CDLL('sqlite3.dll',handle=handle)
    try:
        used=(library or ctypes.CDLL(_sqlite3.__file__)).sqlite3_memory_used
    except (AttributeError,OSError):
        pytest.skip('The interpreter SQLite does not expose sqlite3_memory_used')
    used.argtypes=[];used.restype=ctypes.c_int64
    with closing(sqlite3.connect(':memory:')) as probe:
        before=used()
        probe.execute('CREATE TABLE pages(payload BLOB)')
        probe.executemany('INSERT INTO pages VALUES (?)',((bytes(4000),) for _ in range(256)))
        grown=used()-before
    if grown<512*1024:
        pytest.skip('sqlite3_memory_used does not observe the sqlite3 module heap')
    return used


@pytest.fixture
def generated(corpus):
    """Deterministic ~1.5 MB corpus whose FTS index spans well over 1 MiB of pages."""
    rng=random.Random(4270)
    syllables=[consonant+vowel for consonant in 'bdfgklmnprstvz' for vowel in 'aeiou']
    vocabulary=sorted({''.join(rng.choice(syllables) for _ in range(rng.randint(2,4))) for _ in range(6000)})
    for number in range(128):
        parts=['# Generated corpus %03d\n'%number]
        for part in range(8):
            words=[rng.choice(vocabulary) for _ in range(200)]
            if part==3 and number%16==0:
                words[100:100]=['quasiperiodic','lattice']
            parts.append('## Part %d\n'%part+''.join(' '.join(words[start:start+12])+'\n'
                                                   for start in range(0,len(words),12)))
        corpus.docs['.sources/generated/%03d.md'%number]='\n'.join(parts)
    specification,amendment='.sources/authority/specification.md','.sources/authority/amendment.md'
    corpus.docs[specification]='# Specification\nThe Warden admits work only within its measured self budget.\n'
    corpus.docs[amendment]='# Amendment\nThe owner amends the Warden self budget for allocator headroom.\n'
    ratify(corpus.root,corpus.docs)
    path=corpus.root/'v4.1.2_manifest.json'
    manifest=json.loads(path.read_text(encoding='utf-8'))
    for item in manifest['documents']:
        if item['path'] in (specification,amendment):
            item.update(authority='current_normative' if item['path']==specification else 'owner_decision',
                        authority_revision=GENERATED_REVISION)
    path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
    digest=lambda key:hashlib.sha256(corpus.docs[key].encode('utf-8')).hexdigest()
    corpus.captured={'specification_sha256':digest(specification),'specification_revision':GENERATED_REVISION,
        'owner_amendments':[{'source':'amendment','sha256':digest(amendment),'revision':GENERATED_REVISION}]}
    return corpus


def test_refresh_quick_check_runs_off_pool_and_pooled_readers_are_shrunk(corpus,monkeypatch):
    service=corpus.service
    service.refresh()
    opened=[];connect=service._connect
    def traced(path):
        conn=connect(path);statements=[]
        conn.set_trace_callback(statements.append)
        opened.append((conn,statements))
        return conn
    monkeypatch.setattr(service,'_connect',traced)
    rows=service.search('SQLite fencing')
    ((pooled,pooled_sql),)=opened
    assert pooled_sql[-1]=='PRAGMA shrink_memory' and service._readers.queue[-1][1] is pooled
    with service._reader() as (_,held):
        assert held is pooled and service._readers.empty()
        assert service.refresh()['changed_documents']==0
        # The overlapping refresh neither borrowed nor pooled a reader.
        assert service._readers.empty()
    assert len(opened)==2
    verifier,verifier_sql=opened[1]
    assert 'PRAGMA quick_check' in verifier_sql
    assert not any('quick_check' in sql for sql in pooled_sql)
    with pytest.raises(sqlite3.ProgrammingError):
        verifier.execute('SELECT 1')
    assert pooled_sql[-1]=='PRAGMA shrink_memory' and service._readers.queue[-1][1] is pooled
    assert service.search('SQLite fencing')==rows and len(opened)==2


def test_pooled_readers_are_reused_without_caching_the_generated_index(generated,monkeypatch):
    service,used=generated.service,sqlite_memory_used()
    published=service.refresh()
    assert published['changed_documents']==len(generated.docs) and published['index_size_sla_met'] is True
    assert service.status()['ready'] is True and service._readers.empty()
    opened=[];connect=service._connect
    def counted(path):
        opened.append(connect(path))
        return opened[-1]
    monkeypatch.setattr(service,'_connect',counted)
    authority=KnowledgeAuthority(service,generated.captured)
    def authority_view():
        status=authority.status(force=True)
        return {key:status.get(key) for key in ('ready','index_ready','authority_matches_capture','authority_reason',
            'authority_source','observed_specification_sha256','owner_amendments','generation','manifest_sha256')}
    queries=('quasiperiodic lattice','measured self budget')
    gc.collect();baseline=used()
    first={query:service.search(query) for query in queries}
    assert len(first['quasiperiodic lattice'])==5
    assert {row['doc_path'][:19] for row in first['quasiperiodic lattice']}=={'.sources/generated/'}
    top=first['measured self budget'][0]
    assert (top['doc_path'],top['authority'],top['authority_label'])==(
        '.sources/authority/specification.md','current_normative','Current normative')
    assert {query:service.search(query) for query in queries}==first
    # Both rounds of searches reused one pooled connection object.
    assert len(opened)==1 and service._readers.qsize()==1 and service._readers.queue[0][1] is opened[0]
    authority_before=authority_view()
    assert authority_before['ready'] is True and authority_before['authority_matches_capture'] is True
    assert authority_before['authority_source']=='.sources/authority/specification.md'
    with service._reader() as (_,held):
        assert held is opened[0] and service._readers.empty()
        # Hold a reader whose page cache spans the whole index, as the 30 s
        # background refresh used to leave a pooled reader.
        assert held.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        held_cache=used()-baseline
        overlapping=service.refresh()
        assert (overlapping['generation'],overlapping['changed_documents'])==(published['generation'],0)
        during={query:service.search(query) for query in queries}
    assert held_cache>1048576, 'The generated index must exceed the 1 MiB bound for this test to discriminate'
    assert len(opened)==3
    with pytest.raises(sqlite3.ProgrammingError):
        opened[1].execute('SELECT 1')  # refresh's dedicated quick_check reader is closed
    pooled=[conn for _,conn in service._readers.queue]
    assert len(pooled)==2 and pooled[0] is opened[2] and pooled[1] is opened[0]
    assert during==first and {query:service.search(query) for query in queries}==first
    assert authority_view()==authority_before
    assert len(opened)==3 and service._readers.qsize()==2
    gc.collect()
    pooled_memory=used()-baseline
    assert pooled_memory<1048576, 'Two pooled readers still hold %d bytes of SQLite memory'%pooled_memory
