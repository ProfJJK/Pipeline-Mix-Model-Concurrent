"""Historical observer ACL contract with real descriptors and inert file ports."""
import hashlib
import json

import pytest

from pipeline_tests.test_operational_launch_428 import ROOT, inert_ps


PRIVATE='O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)'
PROJECTION='O:BAG:BAD:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;SY)'
TASK='CoChem-4.2.7-HeldSupervisorObservation-20261007-r3-v1'


def acl_fixture(tmp_path, *, service=PROJECTION, backing=PRIVATE, name=TASK, fault=''):
    temporary=tmp_path/'synthetic-task.xml'
    raw=b'<Task fixture="synthetic"/>'
    temporary.write_bytes(raw)
    data=dict(path=str(temporary),hash=hashlib.sha256(raw).hexdigest(),length=len(raw),
              name=name,service=service,backing=backing,fault=fault)
    return inert_ps(r'''
$v='VALUES'|ConvertFrom-Json
$script:events=[Collections.Generic.List[string]]::new();$script:stream=$null;$script:writerDenied=$false
$task=[pscustomobject]@{Name=$v.name;Sddl=$v.service}
$task|Add-Member ScriptMethod GetSecurityDescriptor {param($flags)if($flags -ne 7){throw 'descriptor sections'};return $this.Sddl}
$expectedPath='C:\Windows\System32\Tasks\'+(Get-OpHeldObserverExpected).task
function Get-Item {param($LiteralPath,[switch]$Force,$ErrorAction)
 $script:events.Add('ITEM')
 if($LiteralPath -cne $expectedPath -or -not $Force -or $ErrorAction -cne 'Stop'){throw 'metadata binding'}
 if($v.fault -eq 'missing'){throw 'missing fixture'}
 $length=$v.length;$attributes=[IO.FileAttributes]::Normal;$container=$false
 if($v.fault -eq 'empty'){$length=0};if($v.fault -eq 'oversize'){$length=131073}
 if($v.fault -eq 'reparse'){$attributes=[IO.FileAttributes]::ReparsePoint}
 if($v.fault -eq 'directory'){$attributes=[IO.FileAttributes]::Directory;$container=$true}
 return [pscustomobject]@{PSIsContainer=$container;Length=$length;Attributes=$attributes}
}
function Get-FileHash {param($LiteralPath,$Algorithm,$ErrorAction)
 $script:events.Add('HASH')
 if($LiteralPath -cne $expectedPath -or $Algorithm -cne 'SHA256' -or $ErrorAction -cne 'Stop'){throw 'hash binding'}
 $value=$v.hash;if($v.fault -eq 'bad_hash'){$value='not-a-sha'}
 return [pscustomobject]@{Hash=$value}
}
function Open-VerifiedFile {param($Path,$Sha256,$Length)
 $script:events.Add('OPEN')
 if($Path -cne $expectedPath -or $Sha256 -cne $v.hash -or $Length -ne $v.length){throw 'custody binding'}
 if($v.fault -in @('custody','hardlink','changed_hash','ancestor_reparse','resolved_path')){throw 'custody refusal'}
 if($v.fault -eq 'missing_handle'){return $null}
 $script:stream=[IO.File]::Open($v.path,'Open','Read','Read');return $script:stream
}
function Get-Acl {param($LiteralPath,$ErrorAction)
 $script:events.Add('ACL')
 if($LiteralPath -cne $expectedPath -or $ErrorAction -cne 'Stop' -or $null -eq $script:stream -or -not $script:stream.CanRead){throw 'missing retained custody'}
 try{$writer=[IO.File]::Open($v.path,'Open','Write','ReadWrite');$writer.Dispose()}catch [IO.IOException]{$script:writerDenied=$true}
 if(-not $script:writerDenied){throw 'writable fixture under custody'}
 if($v.fault -eq 'acl_failure'){throw 'private proof unavailable'}
 # Raw descriptor witness preserves deliberately hostile ACE bytes. Real
 # FileSecurity canonicalizes duplicates, obscuring those negative cases.
 $acl=[pscustomobject]@{Sddl=$v.backing}
 $acl|Add-Member ScriptMethod GetSecurityDescriptorSddlForm {param($sections)
  if($sections -ne ([Security.AccessControl.AccessControlSections]::Owner -bor [Security.AccessControl.AccessControlSections]::Access)){throw 'backing sections'};return $this.Sddl}
 return $acl
}
$t=$null;$errors=$null;$old=[Management.Automation.Language.Parser]::ParseFile('OLD',[ref]$t,[ref]$errors)
$n=@($old.FindAll({param($x)$x -is [Management.Automation.Language.FunctionDefinitionAst] -and $x.Name -ceq 'Assert-428TaskAcl'},$false))[0]
. ([scriptblock]::Create($n.Extent.Text))
$oldRejected=$false;try{Assert-428TaskAcl $task}catch{$oldRejected=$true}
$accepted=$false;$failure=$null
try{Assert-OpObserverTaskAcl $task;$accepted=$true}catch{$failure=Get-OpFailure $_ 'observer_acl'}
@{accepted=$accepted;old_rejected=$oldRejected;events=$script:events.ToArray();writer_denied=$script:writerDenied;
 closed=($null -eq $script:stream -or -not $script:stream.CanRead);failure=$failure}|ConvertTo-Json -Depth 6 -Compress
'''.replace('VALUES',json.dumps(data).replace("'","''")).replace('OLD',str(ROOT/'scripts/run_428_launch.ps1')))


def test_historical_installer_projection_rejected_by_warden_but_verified_for_observer(tmp_path):
    value=acl_fixture(tmp_path)
    assert value['old_rejected'] and value['accepted'],json.dumps(value,indent=2)
    assert value['events']==['ITEM','HASH','OPEN','ACL']
    assert value['writer_denied'] and value['closed']


@pytest.mark.parametrize('service',[PRIVATE,PRIVATE+'(A;;FR;;;SY)'])
def test_historical_protected_shapes_need_no_backing_projection_exception(tmp_path,service):
    value=acl_fixture(tmp_path,service=service,fault='missing')
    assert value['accepted'] and value['events']==[] and value['closed'],value


@pytest.mark.parametrize('service',[
    '','not-sddl',PRIVATE.replace('O:BA','O:WD'),PRIVATE.replace('D:P','D:'),
    PROJECTION.replace('(A;;FR;;;SY)','(A;;FR;;;BA)'),
    PROJECTION.replace('(A;;FR;;;SY)','(A;;FW;;;SY)'),
    PROJECTION.replace('(A;;FA;;;BA)','(A;;FA;;;WD)'),
    PROJECTION.replace('(A;;FR;;;SY)','(A;ID;FR;;;SY)'),
    PROJECTION.replace('(A;;FA;;;BA)','(D;;FA;;;BA)'),
    PROJECTION+'(A;;FR;;;SY)',PRIVATE.replace('(A;;FA;;;BA)','(A;;FA;;;SY)'),
])
def test_unsafe_service_descriptors_hold_before_backing_file_operations(tmp_path,service):
    value=acl_fixture(tmp_path,service=service)
    assert not value['accepted'] and value['events']==[] and value['closed'],value


@pytest.mark.parametrize('name',['CoChem-4.2.7-Warden',TASK+'-other','../'+TASK,''])
def test_projection_exception_is_only_for_exact_observer_name(tmp_path,name):
    value=acl_fixture(tmp_path,name=name)
    assert not value['accepted'] and value['events']==[] and value['closed'],value


@pytest.mark.parametrize('fault',[
    'missing','empty','oversize','reparse','directory','bad_hash','custody',
    'hardlink','changed_hash','ancestor_reparse','resolved_path','missing_handle','acl_failure',
])
def test_projection_never_passes_without_bounded_pinned_private_backing_proof(tmp_path,fault):
    value=acl_fixture(tmp_path,fault=fault)
    assert not value['accepted'] and value['closed'],value
    assert any(f['function']=='Assert-OpObserverTaskAcl' for f in value['failure']['frames'])
    assert 'C:\\' not in json.dumps(value['failure'])


@pytest.mark.parametrize('backing',[
    PRIVATE.replace('D:P','D:'),PRIVATE.replace('O:BA','O:WD'),
    PRIVATE.replace('(A;;FA;;;BA)','(A;;FA;;;WD)'),
    PRIVATE.replace('(A;;FA;;;BA)','(A;;FR;;;BA)'),
    PRIVATE.replace('(A;;FA;;;BA)','(A;;FA;;;SY)'),
    PRIVATE.replace('(A;;FA;;;SY)','(A;ID;FA;;;SY)'),
    PRIVATE.replace('(A;;FA;;;SY)','(D;;FA;;;SY)'),
    PRIVATE+'(A;;FR;;;SY)','O:BAG:BAD:P','O:BAG:BAD:NO_ACCESS_CONTROL',
])
def test_private_backing_dacl_must_be_exact_protected_system_admin_pair(tmp_path,backing):
    value=acl_fixture(tmp_path,backing=backing)
    assert not value['accepted'] and value['closed'] and value['writer_denied'],value
    assert value['events']==['ITEM','HASH','OPEN','ACL']


def test_common_warden_acl_function_remains_strict_and_observer_helper_is_local():
    source=(ROOT/'scripts/run_operational_428_launch.ps1').read_text()
    observer=source.split('function Assert-OpObserverTask {',1)[1].split('\nfunction ',1)[0]
    assert 'Assert-OpObserverTaskAcl $Task' in observer
    assert 'Assert-428TaskAcl $Task' not in observer
    # New helper name is eligible for existing sanitized observer frame filter.
    assert 'function Assert-OpObserverTaskAcl {' in source
