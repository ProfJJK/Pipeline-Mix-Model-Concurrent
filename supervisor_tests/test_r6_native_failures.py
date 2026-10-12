"""Typed provider failures never become host faults or paid repair opportunities."""
import pytest
from cochem_supervisor.runner import native_process_error


@pytest.mark.parametrize('status,category', [
    ('RESOURCE_EXHAUSTED', 'quota'), ('UNAUTHENTICATED', 'auth'),
    ('UNAVAILABLE', 'provider'), ('DEADLINE_EXCEEDED', 'provider'),
])
def test_typed_agy_stderr_reaches_supervisor_category(status, category):
    error = native_process_error('gemini', '', 'AGY_ERROR: {"error":{"status":"' + status + '"}}', 1)
    assert error.category == category


@pytest.mark.parametrize('line', [
    'AGY_ERROR: invalid JSON: unknown argument',
    'AGY_ERROR: {"error":{"status":"RESOURCE_EXHAUSTED","status":"UNAVAILABLE"}}',
    'AGY_ERROR: {"message":"unknown flag in generated content"}',
])
def test_untyped_or_ambiguous_agy_error_is_not_paid_compatibility_repair(line):
    assert native_process_error('gemini', '', line, 1).category == 'configuration'
