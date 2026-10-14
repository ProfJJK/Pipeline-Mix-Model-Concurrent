"""User-facing 4.2.8 task projection and human-owner SRS review interface (`P428-10`).

Provides:
- `build_public_task_view`: enriches `PlanningController.task_status(task_id)`
  for normal MCP/HTTP clients with `workflow_id` compatibility, `status`,
  `current_artifacts`, and `actionable_decisions` (surfacing the exact `plan`,
  `architecture`, `srs`, `requirements`, `release_criteria`, and `revision` when
  human owner approval is required) while stripping all private lease/token/nonce
  fields.
- `OwnerReviewUI`: local human-owner review console backed by `OwnerApprovalBroker`
  and `PlanningController`/`PlanningJournal`. Requires the dedicated high-entropy
  human owner credential (never a shared agent bearer token).
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .owner_approval_428 import OwnerApprovalBroker, VALID_OWNER_DECISIONS
from .task_routing import digest
from .workflow_428 import _id


_PRIVATE_TASK_KEYS = frozenset({
    "fencing_token",
    "attempt_id",
    "lease_owner",
    "owner",
    "reservation_id",
    "route_reservation_id",
    "challenge_nonce",
    "hmac_sha256",
    "owner_secret",
    "raw_log",
    "stderr",
})


def _strip_private(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: _strip_private(v)
            for k, v in value.items()
            if k not in _PRIVATE_TASK_KEYS
        }
    if isinstance(value, list):
        return [_strip_private(item) for item in value]
    return deepcopy(value)


def build_public_task_view(
    status_payload: dict[str, Any],
    *,
    owner_broker: OwnerApprovalBroker | None = None,
) -> dict[str, Any]:
    """Build a safe, redacted public projection of a 4.2.8 task for MCP/HTTP clients."""
    if not isinstance(status_payload, dict) or not isinstance(status_payload.get("task"), dict):
        raise ValueError("Invalid 4.2.8 task status payload")

    clean = _strip_private(status_payload)
    task = clean["task"]
    controller = clean.get("controller") or {}
    task_id = task.get("task_id", "")
    stage = task.get("stage", "SRS")
    deliverable_completed = bool(clean.get("deliverable_completed", False))

    if deliverable_completed or stage == "COMPLETED":
        overall_status = "COMPLETED"
    elif stage in ("OWNER_REJECTED", "FAILED", "CANCELLED") or controller.get("status") == "CANCELLED":
        overall_status = "FAILED"
    elif stage == "LOCKED" or controller.get("status") == "LOCKED":
        overall_status = "LOCKED"
    else:
        overall_status = "IN_PROGRESS"

    current_artifacts: dict[str, Any] = {}
    if isinstance(task.get("document"), dict):
        doc = task["document"]
        current_artifacts["srs_document"] = {
            "revision": task.get("revision"),
            "srs_sha256": task.get("srs_sha256"),
            "plan": doc.get("plan"),
            "architecture": doc.get("architecture"),
            "srs": doc.get("srs"),
            "requirements": doc.get("requirements"),
            "assessment": doc.get("assessment"),
            "release_criteria": doc.get("release_criteria"),
        }
    if isinstance(task.get("review_document"), dict):
        current_artifacts["plan_review"] = deepcopy(task["review_document"])
    if isinstance(task.get("research_excerpts"), dict):
        current_artifacts["research_excerpts"] = deepcopy(task["research_excerpts"])
    if isinstance(task.get("wbs"), list):
        current_artifacts["wbs"] = deepcopy(task["wbs"])
    if isinstance(task.get("microtasks"), list):
        current_artifacts["microtasks"] = deepcopy(task["microtasks"])
    if isinstance(clean.get("execution"), dict):
        current_artifacts["execution"] = deepcopy(clean["execution"])

    actionable_decisions: list[dict[str, Any]] = []
    if stage == "OWNER_APPROVAL" and isinstance(task.get("document"), dict):
        doc = task["document"]
        req_info = None
        reusable = None
        if owner_broker is not None:
            reusable = owner_broker.find_reusable_approval(task)
            req_info = owner_broker.create_request(task)
        actionable_decisions.append(
            {
                "decision_kind": "owner_srs_approval",
                "task_id": task_id,
                "request_id": req_info["request_id"] if req_info else None,
                "revision": task.get("revision"),
                "srs_sha256": task.get("srs_sha256"),
                "objective_sha256": digest(task.get("objective", "")),
                "reusable_receipt_id": reusable["receipt_id"] if reusable else None,
                "allowed_decisions": list(VALID_OWNER_DECISIONS),
                "plan": doc.get("plan"),
                "architecture": doc.get("architecture"),
                "srs": doc.get("srs"),
                "requirements": doc.get("requirements"),
                "release_criteria": doc.get("release_criteria"),
            }
        )

    # Surface newly high-tier (8..10) reassessed microtasks needing owner approval
    for mt in task.get("microtasks") or []:
        if isinstance(mt, dict) and isinstance(mt.get("complexity"), int) and 8 <= mt["complexity"] <= 10:
            if not mt.get("owner_approved"):
                actionable_decisions.append(
                    {
                        "decision_kind": "microtask_owner_approval",
                        "task_id": task_id,
                        "microtask_id": mt.get("id"),
                        "complexity": mt["complexity"],
                        "task_types": mt.get("task_types"),
                        "allowed_decisions": list(VALID_OWNER_DECISIONS),
                    }
                )

    if stage == "LOCKED" or controller.get("status") == "LOCKED":
        actionable_decisions.append(
            {
                "decision_kind": "locked_task_owner_decision",
                "task_id": task_id,
                "allowed_decisions": ["reapprove_plan", "narrow_scope", "assign_profile", "abort_task"],
            }
        )

    clean["workflow_id"] = task_id
    clean["task_id"] = task_id
    clean["status"] = overall_status
    clean["current_artifacts"] = current_artifacts
    clean["actionable_decisions"] = actionable_decisions
    return clean


class OwnerReviewUI:
    """Inert/local human-owner SRS review interface backed by `OwnerApprovalBroker`."""

    def __init__(self, planning_controller, owner_broker: OwnerApprovalBroker):
        self.planning = planning_controller
        self.journal = planning_controller.journal
        self.broker = owner_broker
        if self.journal.owner_receipt is None:
            self.journal.owner_receipt = self.broker.load_for_journal

    def inspect_task(self, task_id: str) -> dict[str, Any]:
        _id(task_id)
        return build_public_task_view(
            self.planning.task_status(task_id),
            owner_broker=self.broker,
        )

    def list_pending_approvals(self) -> list[dict[str, Any]]:
        pending: list[dict[str, Any]] = []
        with self.journal._write() as conn:
            rows = conn.execute("SELECT task_id FROM planning428_tasks ORDER BY task_id").fetchall()
        for row in rows:
            view = self.inspect_task(row["task_id"])
            for decision in view.get("actionable_decisions", []):
                if decision.get("decision_kind") == "owner_srs_approval":
                    pending.append(decision)
        return pending

    def render_review_markdown(self, task_id: str) -> str:
        view = self.inspect_task(task_id)
        task = view["task"]
        doc = task.get("document") or {}
        lines = [
            f"# Owner SRS Review — Task `{task['task_id']}` (Revision {task.get('revision')})",
            f"- **Stage:** `{task.get('stage')}`",
            f"- **Complexity:** `{(task.get('assessment') or {}).get('complexity')}`",
            f"- **SRS Digest (`srs_sha256`):** `{task.get('srs_sha256')}`",
            "",
            "## Plan",
            str(doc.get("plan", "")),
            "",
            "## Architecture",
            str(doc.get("architecture", "")),
            "",
            "## Requirements",
        ]
        for req in doc.get("requirements") or []:
            if isinstance(req, dict):
                lines.append(f"- **{req.get('id')}**: {req.get('text')}")
        return "\n".join(lines)

    def decide(
        self,
        task_id: str,
        *,
        decision: str,
        owner_token: str,
        notes: str = "",
    ) -> dict[str, Any]:
        """Authenticate the human owner and apply their decision to the planning journal."""
        _id(task_id)
        state = self.journal.status(task_id)
        if state.get("stage") != "OWNER_APPROVAL":
            raise ValueError("Task is not currently awaiting human owner SRS approval")

        if decision == "approved":
            # Verify owner_token before reusing any prior approval receipt
            self.broker._authenticate_owner_token(owner_token)
            reusable = self.broker.find_reusable_approval(state)
            if reusable is not None:
                receipt = reusable
            else:
                req = self.broker.create_request(state)
                receipt = self.broker.record_decision(
                    req["request_id"],
                    decision=decision,
                    owner_token=owner_token,
                    notes=notes,
                )
        else:
            req = self.broker.create_request(state)
            receipt = self.broker.record_decision(
                req["request_id"],
                decision=decision,
                owner_token=owner_token,
                notes=notes,
            )

        self.journal.apply_owner_approval(
            task_id,
            state["journal_version"],
            receipt["receipt_id"],
        )
        self.planning.step()
        return self.inspect_task(task_id)
