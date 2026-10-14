"""Protocol fixture tests for Gemini 4 Argon Low/Medium/High native contracts (`P428-04`).

No live Agy process or network call is executed here; physical CLI acceptance
is reserved for owner task P428-28.
"""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from cochem_pipeline.agy_agent_guard import RELATIVES
from cochem_pipeline.agy_tool_registry import AGENT_SHA256, BINARY_SHA256
from cochem_pipeline.argon_catalog import (
    MODEL,
    build_argon_owner_acceptance_spec,
    prepare_argon_candidate,
    verify_argon_probe_fixture,
)


def _base_inputs():
    agy_args = [
        "--agent",
        "cochem-inference-only",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--model",
        "{model}",
        "--disable-slash-commands",
    ]
    spec = {
        "protocol": "agy-stream-json",
        "identity_policy": "reported-model-equality",
        "arguments": list(agy_args),
        "model_bindings": {"gemini-3.8-flash": "gemini-3.8-flash-low"},
        "agent_definition": {
            "name": "cochem-inference-only",
            "sha256": AGENT_SHA256,
            "bytes": 478,
            "relative_paths": list(RELATIVES),
        },
        "inference_only": {
            "executable_sha256": BINARY_SHA256,
            "version": "1.3.1",
            "version_arguments": ["--version"],
            "arguments": list(agy_args),
            "capability_reference": "4.2.8 Argon exact selector protocol fixture",
            "disables_tools": True,
            "disables_mcp": True,
            "disables_hooks": True,
            "disables_subagents": True,
            "disables_model_fallback": True,
        },
    }
    capture = {
        "schema": "cochem-agy-catalog-capture/1",
        "executable_sha256": BINARY_SHA256,
        "version": "1.3.1",
        "catalog_sha256": "c" * 64,
        "model_slugs": [
            "gemini-4-argon-low",
            "gemini-4-argon-medium",
            "gemini-4-argon-high",
        ],
    }
    return spec, capture


def _ndjson_stream(
    reported_model: str,
    *,
    tools: list[str] | None = None,
    agent: str = "cochem-inference-only",
    extra_step: dict | None = None,
    init_extra: dict | None = None,
    terminal_extra: dict | None = None,
) -> str:
    session = "sess-argon-428"
    init_obj = {
        "model": reported_model,
        "agent": agent,
        "tools": [] if tools is None else tools,
    }
    if init_extra:
        init_obj.update(init_extra)
    events = [
        {"event": "init", "conversation_id": session, "init": init_obj},
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": session,
                "step_index": 0,
                "step_type": "user_input",
                "state": "DONE",
            },
        },
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": session,
                "step_index": 1,
                "step_type": "agent_response",
                "state": "DONE",
                **(extra_step or {}),
            },
        },
        {
            "event": "result",
            "result": {
                "conversation_id": session,
                "status": "SUCCESS",
                "num_turns": 1,
                "response": '{"ok":true}',
                "usage": {"input_tokens": 12, "output_tokens": 4},
                **(terminal_extra or {}),
            },
        },
    ]
    return "\n".join(json.dumps(ev, separators=(",", ":")) for ev in events) + "\n"


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_argon_low_medium_high_protocol_fixtures_verify_without_claiming_host_acceptance(effort):
    spec, capture = _base_inputs()
    proposal = prepare_argon_candidate(spec, capture)
    owner_spec = build_argon_owner_acceptance_spec(proposal)
    assert owner_spec["schema"] == "cochem-argon-owner-acceptance-spec/4.2.8"
    assert owner_spec["host_accepted"] is False
    assert owner_spec["source_fixture_only"] is True
    assert owner_spec["owner_acceptance_task"] == "P428-28"
    assert len(owner_spec["probe_plan"]) == 3

    slug = f"{MODEL}-{effort}"
    raw_stdout = _ndjson_stream(slug)
    result = verify_argon_probe_fixture(
        proposal,
        effort,
        raw_stdout=raw_stdout,
        binary_sha256=BINARY_SHA256,
        version_stdout="1.3.1\n",
        cleanup_verified=True,
    )
    assert result["status"] == "PROTOCOL_VERIFIED"
    assert result["argv_slug"] == slug
    assert result["reported_model"] == slug
    assert result["cleanup_verified"] is True
    assert result["source_fixture_only"] is True
    assert result["host_accepted"] is False
    assert result["effort_observation"]["observation_status"] == "not_reported_by_reviewed_cli"


def test_argon_identity_mismatch_and_silent_fallback_are_held():
    spec, capture = _base_inputs()
    proposal = prepare_argon_candidate(spec, capture)

    # Wrong model reported in init
    wrong_init = _ndjson_stream("gemini-3.8-flash-high")
    res1 = verify_argon_probe_fixture(
        proposal,
        "high",
        raw_stdout=wrong_init,
        binary_sha256=BINARY_SHA256,
        version_stdout="1.3.1",
        cleanup_verified=True,
    )
    assert res1["status"] == "COMPATIBILITY_HOLD"
    assert res1["reason"] == "AGY_IDENTITY_OR_FALLBACK_VIOLATION"
    assert res1["host_accepted"] is False

    # Truthy fallback field in terminal result
    rerouted = _ndjson_stream("gemini-4-argon-high", terminal_extra={"fallbackUsed": True})
    res2 = verify_argon_probe_fixture(
        proposal,
        "high",
        raw_stdout=rerouted,
        binary_sha256=BINARY_SHA256,
        version_stdout="1.3.1",
        cleanup_verified=True,
    )
    assert res2["status"] == "COMPATIBILITY_HOLD"
    assert res2["reason"] == "AGY_IDENTITY_OR_FALLBACK_VIOLATION"

    # Stderr fallback diagnostic marker
    res3 = verify_argon_probe_fixture(
        proposal,
        "high",
        raw_stdout=_ndjson_stream("gemini-4-argon-high"),
        raw_stderr="Model gemini-4-argon-high is no longer available. Using gemini-3.8-flash",
        binary_sha256=BINARY_SHA256,
        version_stdout="1.3.1",
        cleanup_verified=True,
    )
    assert res3["status"] == "COMPATIBILITY_HOLD"
    assert res3["reason"] == "AGY_IDENTITY_OR_FALLBACK_VIOLATION"


def test_argon_missing_catalog_target_and_unsupported_effort():
    spec, capture = _base_inputs()
    capture["model_slugs"] = ["gemini-4-argon-high"]
    proposal = prepare_argon_candidate(spec, capture)
    owner_spec = build_argon_owner_acceptance_spec(proposal)
    assert len(owner_spec["probe_plan"]) == 1
    assert [h["effort"] for h in owner_spec["held_efforts"]] == ["low", "medium"]

    for missing_effort in ("low", "medium"):
        held = verify_argon_probe_fixture(
            proposal,
            missing_effort,
            raw_stdout=_ndjson_stream(f"gemini-4-argon-{missing_effort}"),
            binary_sha256=BINARY_SHA256,
            version_stdout="1.3.1",
            cleanup_verified=True,
        )
        assert held["status"] == "UNAVAILABLE_HELD"
        assert held["reason"] == "NOT_IN_CAPTURED_CLI_CATALOG"
        assert held["host_accepted"] is False

    with pytest.raises(ValueError, match="Unsupported Argon reasoning effort"):
        verify_argon_probe_fixture(
            proposal,
            "xhigh",
            raw_stdout="",
            binary_sha256=BINARY_SHA256,
            version_stdout="1.3.1",
            cleanup_verified=True,
        )


def test_argon_auth_and_quota_classify_as_availability_wait_and_unclean_quarantines():
    spec, capture = _base_inputs()
    proposal = prepare_argon_candidate(spec, capture)

    quota_res = verify_argon_probe_fixture(
        proposal,
        "high",
        raw_stdout="",
        raw_stderr='AGY_ERROR: {"error": {"code": "resource_exhausted", "message": "Rate limit reached"}}',
        exit_code=1,
        binary_sha256=BINARY_SHA256,
        version_stdout="1.3.1",
        cleanup_verified=True,
    )
    assert quota_res["status"] == "AVAILABILITY_WAIT"
    assert quota_res["category"] == "quota"
    assert quota_res["host_accepted"] is False

    auth_res = verify_argon_probe_fixture(
        proposal,
        "high",
        raw_stdout="",
        raw_stderr='AGY_ERROR: {"error": {"code": "authentication_failed", "message": "Not logged in"}}',
        exit_code=1,
        binary_sha256=BINARY_SHA256,
        version_stdout="1.3.1",
        cleanup_verified=True,
    )
    assert auth_res["status"] == "AVAILABILITY_WAIT"
    assert auth_res["category"] == "auth"

    unclean = verify_argon_probe_fixture(
        proposal,
        "high",
        raw_stdout=_ndjson_stream("gemini-4-argon-high"),
        binary_sha256=BINARY_SHA256,
        version_stdout="1.3.1",
        cleanup_verified=False,
    )
    assert unclean["status"] == "QUARANTINED_UNCLEAN"
    assert unclean["cleanup_verified"] is False
    assert unclean["host_accepted"] is False


def test_argon_tool_advertisement_versus_execution_step_enforcement():
    spec, capture = _base_inputs()
    proposal = prepare_argon_candidate(spec, capture)

    # 1. Advertised builtin CLI tools under the reviewed 1.3.1 binary + guarded agent succeed when no tool step runs
    advertised_only = _ndjson_stream("gemini-4-argon-high", tools=["read_file", "grep_search"])
    ok_res = verify_argon_probe_fixture(
        proposal,
        "high",
        raw_stdout=advertised_only,
        binary_sha256=BINARY_SHA256,
        version_stdout="1.3.1",
        cleanup_verified=True,
        use_agent_registry=True,
    )
    assert ok_res["status"] == "PROTOCOL_VERIFIED"
    assert ok_res["tool_registry"]["advertised_count"] == 2
    assert ok_res["tool_registry"]["advertised_tools_are_agent_permissions"] is False

    # 2. Without the reviewed agent registry binding, advertised tools are rejected
    unreviewed_adv = verify_argon_probe_fixture(
        proposal,
        "high",
        raw_stdout=advertised_only,
        binary_sha256=BINARY_SHA256,
        version_stdout="1.3.1",
        cleanup_verified=True,
        use_agent_registry=False,
    )
    assert unreviewed_adv["status"] == "COMPATIBILITY_HOLD"
    assert unreviewed_adv["reason"] == "AGY_TOOL_REGISTRY_VIOLATION"

    # 3. Any actual tool execution or subagent step is rejected even under the reviewed registry
    executed_tool = _ndjson_stream(
        "gemini-4-argon-high",
        tools=["read_file"],
        extra_step={"tool_name": "read_file"},
    )
    exec_res = verify_argon_probe_fixture(
        proposal,
        "high",
        raw_stdout=executed_tool,
        binary_sha256=BINARY_SHA256,
        version_stdout="1.3.1",
        cleanup_verified=True,
        use_agent_registry=True,
    )
    assert exec_res["status"] == "COMPATIBILITY_HOLD"
    assert exec_res["reason"] == "AGY_TOOL_REGISTRY_VIOLATION"
