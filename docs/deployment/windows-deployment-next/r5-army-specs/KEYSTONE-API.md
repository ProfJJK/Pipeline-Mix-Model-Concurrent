# Keystone public API (as implemented, 2026-10-11) - code against this, not the older spec wording

## cochem_pipeline.agy_protocol (KEYSTONE-G1, tests: pipeline_tests/test_agy_protocol.py, 111 passed)

- PROTOCOL = 'agy-stream-json' (unchanged)
- IDENTITY_POLICY = 'reported-model-equality'
- class AgyIdentityError(ValueError): raised for identity mismatch or absence, fallback/reroute keys, stderr markers,
  tool-registry violations (init.tools non-empty or missing; a step carrying tool_name/tool_info/subagent_info).
  Callers map it to failure category 'compatibility'. Malformed/structural stream errors stay plain ValueError = 'protocol'.
  CATCH AgyIdentityError BEFORE ValueError (it is a subclass).
- validate_identity_policy(spec) -> str | None: None if 'identity_policy' absent; IDENTITY_POLICY if equal and
  spec['protocol'] == 'agy-stream-json'; ValueError otherwise (including a present None).
- require_serving_model_contract(spec) -> None: no policy + stream protocol raises
  ValueError('Agy stream actual-model identity has no verified native contract') (byte-identical, exact type);
  invalid policy raises; then validate_model_bindings(spec). Non-stream protocols without policy/bindings return None.
- validate_model_bindings(spec) -> dict[key, {'argv': slug, 'reports': slug}] (insertion order, fresh dicts).
  No policy: {} (ValueError if 'model_bindings' present). With policy: dict of 1..32; key regex
  ^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}(:(extended|high))?$; value = slug string (argv = reports) or exactly {'argv','reports'};
  slug regex ^[a-z0-9][a-z0-9.-]{0,127}$; effort_contracts (default {}) must be a dict; every ':effort' key needs
  effort_contracts[key] dict; if its arguments == ['--effort', X], any -low/-medium/-high suffix on argv or reports must equal X;
  every effort_contracts key must have a binding.
- native_model_binding(spec, model, effort) -> {'argv','reports'}: effort is REQUIRED positional (pass None explicitly).
  No policy: {'argv': model, 'reports': model}. With policy: key = model if effort is None else f'{model}:{effort}';
  missing key raises ValueError('Gemini route has no reviewed native model binding') (plain ValueError).
- parse_stream(raw, expected_model, *, identity_policy=None, stderr=None) -> dict
  (second parameter renamed from requested_model; existing callers pass it positionally).
  identity_policy other than None/IDENTITY_POLICY raises ValueError. stderr must be str <= 8 MiB chars; any of five markers
  raises AgyIdentityError (case-sensitive). Always-on recursive scan: a truthy key containing fallback/rerout/
  deprecated_model/deprecatedmodel (case-insensitive) raises AgyIdentityError. model/selected_model/model_id anywhere
  (top level, init, step_update, result) must equal expected_model. Missing result.model passes.
  Returns {'content', 'session_id', 'native_selected_model': init['model'], 'reported_model', 'terminal_success': True, 'usage'};
  'reported_model' = init.model ONLY when identity_policy == IDENTITY_POLICY, else None.
  G2 calls parse_stream(raw, binding['reports'], identity_policy=..., stderr=...) and takes native_reported_model from
  result['reported_model'].

## cochem_pipeline.store (KEYSTONE-W1, tests: pipeline_tests/test_store.py, 68 passed)

- reconcile_chapter_wbs(payload, output) -> (output, evidence | None), module-level, pure (mutates neither argument).
  Returns (output, None) with the SAME object when payload is not a dict, payload['wbs_tasks_defined'] is not a non-empty
  list, or output is not a dict. Otherwise ({**output, 'wbs_tasks_defined': new_list}, evidence): declared tasks first
  (manifest order, canonical_json round-trip copies), then model tasks with undeclared ids in model order; a model task
  reusing a declared id is dropped; missing/non-list model list = empty; invalid extras KEPT so the store still rejects them.
  Calls output_digest(output) first, so non-canonical output (e.g. NaN) raises that error.
  evidence = {'schema': 'cochem-chapter-wbs-reconciliation/1', 'model_output_sha256', 'declared_task_ids',
  'restored_omitted_ids', 'restored_rewritten_ids', 'additional_task_ids'}.
  THE STORE NEVER CALLS IT. The worker (W2) calls it for CHAPTER_DRAFT before building the receipt, so
  receipt['output_sha256'] == output_digest(reconciled); add receipt['wbs_reconciliation'] only when evidence is not None.
- JobStore._sibling_wbs(conn, job, output) -> None (staticmethod), called by complete() for CHAPTER_DRAFT right after
  self._chapter(job, output) in the same write transaction; raises
  ValueError('Chapter WBS task IDs must not reuse a sibling chapter task ID') on overlap with other chapters' manifest
  ids or COMPLETED sibling CHAPTER_DRAFT output ids.
