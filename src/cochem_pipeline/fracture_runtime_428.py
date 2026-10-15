"""Fracture and reassessment runtime without resetting quality budgets (`P428-17`).

Guarantees:
- A selected fracture produces an independently reviewed, reassessed child DAG
  with at least two genuinely narrower implementation fragments and an explicit
  assembly node, closing obsolete parent dispatch and preserving provenance to
  the failed scope and boundary dossier.
- Shared lineage quality failure counts (`10`, `20`, `29`) survive child IDs,
  restarts, and nested fracture descendants without ever resetting budgets.
- Small implementation fragments retain their own lower classification
  `(task_types, complexity)`, while escalation (`min(10, old_floor + 1)` and a
  different underlying model family) remains enforced on the failed scope/assembly.
- Newly high-tier (`8..10`) fracture children hold in `HOLD_OWNER_APPROVAL`
  until an authenticated owner receipt is recorded.
- Interrupted partial fractures reconcile atomically via a durable outbox table.
"""
from __future__ import annotations

from copy import deepcopy
import json
import time
from typing import Any

from .failure_dossier_428 import FailureDossierStore
from .pivot_runtime_428 import PivotHoldError, select_pivot_candidates
from .task_routing import digest, five_model_options, select_candidates
from .workflow_428 import (
    AttemptLedger,
    _id,
    _sha,
    _text,
    compile_fracture_child_graph,
)


def _select_fragment_candidate(
    catalog: dict[str, Any],
    task_types: list[str],
    complexity: int,
    *,
    exclude_family: str | None = None,
) -> dict[str, Any]:
    """Select an eligible catalog profile for a reassessed implementation fragment."""
    models = catalog.get("models") or {}
    excl = (exclude_family,) if exclude_family else ()
    try:
        five_ids = [
            opt["model_id"]
            for opt in five_model_options(catalog, task_types, complexity)
            if opt.get("meets_floor")
        ]
    except (ValueError, KeyError):
        five_ids = []
    try:
        cand_ids = select_candidates(
            catalog,
            task_types,
            complexity,
            exclude_families=excl,
        )
    except (ValueError, KeyError):
        cand_ids = []
    ordered = [
        pid
        for pid in dict.fromkeys(five_ids + cand_ids + list(models.keys()))
        if pid in models
    ]
    tier_str = str(complexity)
    for prof_id in ordered:
        spec = models.get(prof_id) or {}
        family = spec.get("family", "")
        effort = spec.get("effort", "")
        provider = spec.get("provider", "")
        scores = spec.get("scores") or {}
        if exclude_family and family == exclude_family:
            continue
        if complexity == 10:
            req_max = "high" if provider == "gemini" or family.startswith("gemini-") else "max"
            if effort != req_max:
                continue
        if all(
            scores.get(tag) is not None
            and scores[tag] >= catalog["task_types"][tag]["tiers"][tier_str]["floor"]
            for tag in task_types
        ):
            return {
                "profile_id": prof_id,
                "family": family,
                "effort": effort,
            }
    raise PivotHoldError(
        "CAPABILITY_HOLD",
        f"No eligible catalog model meets fragment tier {complexity} for {task_types}",
    )


class FractureRuntime:
    """Materializes and reconciles reassessed fracture child graphs without resetting budgets (`P428-17`)."""

    def __init__(
        self,
        ledger: AttemptLedger,
        catalog: dict[str, Any],
        *,
        dossier_store: FailureDossierStore | None = None,
        job_store=None,
        clock=time.time,
    ):
        self.ledger = ledger
        self.catalog = deepcopy(catalog)
        self.dossier_store = dossier_store or FailureDossierStore(ledger, clock=clock)
        self.job_store = job_store
        self.clock = clock
        with self.ledger._write() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task428_fractures(
                    fracture_id TEXT PRIMARY KEY,
                    lineage_root TEXT NOT NULL,
                    failed_scope_id TEXT NOT NULL,
                    after_failures INTEGER NOT NULL,
                    dossier_id TEXT NOT NULL,
                    dossier_sha256 TEXT NOT NULL,
                    graph_sha256 TEXT NOT NULL,
                    escalated_floor INTEGER NOT NULL,
                    assembly_model_family TEXT NOT NULL,
                    graph_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task428_fracture_nodes(
                    child_id TEXT PRIMARY KEY,
                    fracture_id TEXT NOT NULL,
                    lineage_root TEXT NOT NULL,
                    failed_scope_id TEXT NOT NULL,
                    dossier_id TEXT NOT NULL,
                    dossier_sha256 TEXT NOT NULL,
                    graph_sha256 TEXT NOT NULL,
                    role TEXT NOT NULL,
                    complexity INTEGER NOT NULL,
                    task_types_json TEXT NOT NULL,
                    requirement_ids_json TEXT NOT NULL,
                    deliverables_json TEXT NOT NULL,
                    release_criteria_json TEXT NOT NULL,
                    depends_on_json TEXT NOT NULL,
                    selected_profile_id TEXT NOT NULL,
                    selected_model_family TEXT NOT NULL,
                    selected_effort TEXT NOT NULL,
                    escalated_scope INTEGER NOT NULL,
                    needs_owner_approval INTEGER NOT NULL,
                    owner_approval_json TEXT,
                    status TEXT NOT NULL,
                    artifact_sha256 TEXT,
                    node_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task428_fracture_outbox(
                    fracture_id TEXT PRIMARY KEY,
                    lineage_root TEXT NOT NULL,
                    failed_scope_id TEXT NOT NULL,
                    after_failures INTEGER NOT NULL,
                    dossier_id TEXT NOT NULL,
                    dossier_sha256 TEXT NOT NULL,
                    graph_sha256 TEXT NOT NULL,
                    escalated_floor INTEGER NOT NULL,
                    assembly_model_family TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    sync_status TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task428_obsolete_scopes(
                    scope_id TEXT PRIMARY KEY,
                    lineage_root TEXT NOT NULL,
                    superseded_by_fracture_id TEXT NOT NULL,
                    closed_at REAL NOT NULL
                );
                """
            )
        self.reconcile_partial_fractures()

    def _resolve_dossier(self, lineage_root: str, failures: int, dossier_boundary: int | None) -> dict[str, Any]:
        target_boundary = dossier_boundary or (failures if failures in (10, 20) else 20)
        dossier = self.dossier_store.get_dossier(lineage_root, target_boundary)
        if dossier is None and failures == 29 and dossier_boundary is None:
            dossier = self.dossier_store.get_dossier(lineage_root, 10)
        if dossier is None:
            raise PivotHoldError(
                "MISSING_FAILURE_DOSSIER",
                f"Fracture at {failures} failures requires a compiled boundary dossier",
            )
        if not dossier.get("research_complete"):
            raise PivotHoldError(
                "PIVOT_RESEARCH_HOLD",
                "Fracture dossier has unavailable research channels; holding in PIVOT_RESEARCH_HOLD",
            )
        return dossier

    def execute_fracture(
        self,
        lineage_root: str,
        *,
        failed_scope: dict[str, Any],
        children: list[dict[str, Any]],
        review: dict[str, Any],
        dossier_boundary: int | None = None,
        crash_after_ledger_commit_for_test: bool = False,
    ) -> dict[str, Any]:
        """Validate, register, and materialize a reassessed fracture child graph without resetting quality budgets."""
        _id(lineage_root)
        self.reconcile_partial_fractures()

        state = self.ledger.status(lineage_root)
        failures = int(state["failures"])
        if failures not in (10, 20, 29):
            raise ValueError(f"Lineage '{lineage_root}' is at {failures} failures; fracture requires 10, 20, or 29")

        dossier = self._resolve_dossier(lineage_root, failures, dossier_boundary)
        last_model = state.get("last_model") or dossier["last_failed_model"]
        parent_floor = int(state["floor"])

        scope_spec = {
            **deepcopy(failed_scope),
            "lineage_root": lineage_root,
            "parent_floor": parent_floor,
            "last_failed_model": last_model,
        }
        compiled_graph = compile_fracture_child_graph(scope_spec, children, review)
        escalated_floor = compiled_graph["escalated_floor"]

        # Assign profiles per child: lower fragments keep their own classification,
        # while assembly/final_test enforce the escalated floor and a different model family.
        child_models: dict[str, str] = {}
        enriched_children: list[dict[str, Any]] = []
        assembly_node: dict[str, Any] | None = None

        for child in compiled_graph["children"]:
            cid = child["id"]
            if child["role"] == "implementation":
                sel = _select_fragment_candidate(
                    self.catalog,
                    child["task_types"],
                    child["complexity"],
                )
            else:
                candidates = select_pivot_candidates(
                    self.catalog,
                    child["task_types"],
                    child["complexity"],
                    last_failed_model=last_model,
                )
                if not candidates:
                    raise PivotHoldError(
                        "CAPABILITY_HOLD",
                        f"No eligible different model meets escalated assembly tier {child['complexity']}",
                    )
                sel = candidates[0]
            child_models[cid] = sel["family"]
            enriched = {
                **child,
                "selected_profile_id": sel["profile_id"],
                "selected_model_family": sel["family"],
                "selected_effort": sel["effort"],
                "dossier_id": dossier["dossier_id"],
                "dossier_sha256": dossier["dossier_sha256"],
                "graph_sha256": compiled_graph["graph_sha256"],
            }
            if child["role"] == "assembly" and assembly_node is None:
                assembly_node = enriched
            enriched_children.append(enriched)

        assert assembly_node is not None
        fracture_id = f"frac428-{lineage_root[:24]}-{failures}-{compiled_graph['graph_sha256'][:12]}"
        proposal = {
            "strategy": "fracture",
            "task_types": assembly_node["task_types"],
            "complexity": assembly_node["complexity"],
            "rationale": f"Fracture {scope_spec['scope_id']} into {len(enriched_children)} nodes",
            "next_model": assembly_node["selected_model_family"],
            "children": [c["id"] for c in enriched_children],
        }

        outbox_payload = {
            "fracture_id": fracture_id,
            "lineage_root": lineage_root,
            "failed_scope_id": scope_spec["scope_id"],
            "after_failures": failures,
            "dossier_id": dossier["dossier_id"],
            "dossier_sha256": dossier["dossier_sha256"],
            "graph_sha256": compiled_graph["graph_sha256"],
            "escalated_floor": escalated_floor,
            "assembly_model_family": assembly_node["selected_model_family"],
            "compiled_graph": {
                **compiled_graph,
                "children": enriched_children,
            },
        }
        now = float(self.clock())
        with self.ledger._write() as conn:
            # Membership, inherited counters and the complete child graph must
            # commit together. A crash cannot leave READY members without a
            # recoverable graph outbox.
            updated_state = self.ledger.fracture_lineage(
                lineage_root, dossier["research"], proposal, dossier["dossier_sha256"],
                child_models=child_models, _connection=conn)
            conn.execute(
                "INSERT OR REPLACE INTO task428_fracture_outbox VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    fracture_id,
                    lineage_root,
                    scope_spec["scope_id"],
                    failures,
                    dossier["dossier_id"],
                    dossier["dossier_sha256"],
                    compiled_graph["graph_sha256"],
                    escalated_floor,
                    assembly_node["selected_model_family"],
                    json.dumps(outbox_payload, sort_keys=True),
                    "PENDING_SYNC",
                    now,
                ),
            )

        if crash_after_ledger_commit_for_test:
            raise RuntimeError("Simulated crash after ledger fracture commit before node materialization")

        self.reconcile_partial_fractures()
        return {
            "fracture_id": fracture_id,
            "lineage_root": lineage_root,
            "failed_scope_id": scope_spec["scope_id"],
            "inherited_failures": int(updated_state["failures"]),
            "escalated_floor": int(updated_state["floor"]),
            "assembly_model_family": assembly_node["selected_model_family"],
            "graph_sha256": compiled_graph["graph_sha256"],
            "children": self.list_fracture_children(lineage_root, fracture_id=fracture_id),
            "lineage_state": updated_state,
        }

    def reconcile_partial_fractures(self) -> int:
        """Atomically complete any interrupted fracture materialization and close obsolete parent scopes."""
        with self.ledger._write() as conn:
            pending = conn.execute(
                "SELECT * FROM task428_fracture_outbox WHERE sync_status='PENDING_SYNC' ORDER BY updated_at ASC"
            ).fetchall()
            reconciled = 0
            now = float(self.clock())
            for row in pending:
                payload = json.loads(row["payload_json"])
                fracture_id = payload["fracture_id"]
                lineage_root = payload["lineage_root"]
                failed_scope_id = payload["failed_scope_id"]
                graph = payload["compiled_graph"]

                # Close obsolete parent scope in fracture nodes and record in obsolete_scopes
                conn.execute(
                    "INSERT OR REPLACE INTO task428_obsolete_scopes VALUES(?,?,?,?)",
                    (failed_scope_id, lineage_root, fracture_id, now),
                )
                conn.execute(
                    "UPDATE task428_fracture_nodes SET status='FRACTURED_OBSOLETE', updated_at=? WHERE child_id=?",
                    (now, failed_scope_id),
                )

                conn.execute(
                    "INSERT OR REPLACE INTO task428_fractures VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        fracture_id,
                        lineage_root,
                        failed_scope_id,
                        int(payload["after_failures"]),
                        payload["dossier_id"],
                        payload["dossier_sha256"],
                        payload["graph_sha256"],
                        int(payload["escalated_floor"]),
                        payload["assembly_model_family"],
                        json.dumps(graph, sort_keys=True),
                        now,
                    ),
                )

                for child in graph["children"]:
                    if child["needs_owner_approval"]:
                        status = "HOLD_OWNER_APPROVAL"
                    elif child["depends_on"]:
                        status = "BLOCKED_DAG"
                    else:
                        status = "READY"
                    conn.execute(
                        "INSERT OR IGNORE INTO task428_fracture_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            child["id"],
                            fracture_id,
                            lineage_root,
                            failed_scope_id,
                            child["dossier_id"],
                            child["dossier_sha256"],
                            child["graph_sha256"],
                            child["role"],
                            int(child["complexity"]),
                            json.dumps(child["task_types"]),
                            json.dumps(child["requirement_ids"]),
                            json.dumps(child["deliverables"]),
                            json.dumps(child["release_criteria"]),
                            json.dumps(child["depends_on"]),
                            child["selected_profile_id"],
                            child["selected_model_family"],
                            child["selected_effort"],
                            int(bool(child["escalated_scope"])),
                            int(bool(child["needs_owner_approval"])),
                            json.dumps(child.get("owner_approval")) if child.get("owner_approval") else None,
                            status,
                            None,
                            json.dumps(child, sort_keys=True),
                            now,
                        ),
                    )

                conn.execute(
                    "UPDATE task428_fracture_outbox SET sync_status='COMMITTED', updated_at=? WHERE fracture_id=?",
                    (now, fracture_id),
                )
                reconciled += 1
        return reconciled

    def is_scope_obsolete(self, scope_id: str) -> bool:
        _id(scope_id)
        with self.ledger._write() as conn:
            row = conn.execute(
                "SELECT 1 FROM task428_obsolete_scopes WHERE scope_id=?",
                (scope_id,),
            ).fetchone()
            return row is not None

    def approve_fracture_child(
        self,
        lineage_root: str,
        child_id: str,
        authenticated_owner_receipt_id: str,
    ) -> dict[str, Any]:
        """Record authenticated human-owner approval for a high-tier (`8..10`) fracture child."""
        _id(lineage_root)
        _id(child_id)
        _id(authenticated_owner_receipt_id)
        now = float(self.clock())
        with self.ledger._write() as conn:
            row = conn.execute(
                "SELECT * FROM task428_fracture_nodes WHERE lineage_root=? AND child_id=?",
                (lineage_root, child_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown fracture child '{child_id}' in lineage '{lineage_root}'")
            if not 8 <= int(row["complexity"]) <= 10:
                raise ValueError("Only complexity 8..10 fracture children require owner approval")
            deps = json.loads(row["depends_on_json"])
            deps_done = True
            if deps:
                placeholders = ",".join("?" for _ in deps)
                done_rows = conn.execute(
                    f"SELECT child_id FROM task428_fracture_nodes WHERE lineage_root=? AND status='COMPLETED' AND child_id IN ({placeholders})",
                    (lineage_root, *deps),
                ).fetchall()
                deps_done = len(done_rows) == len(deps)
            new_status = "READY" if deps_done else "BLOCKED_DAG"
            approval_obj = {
                "receipt_id": authenticated_owner_receipt_id,
                "graph_sha256": row["graph_sha256"],
                "approved_at": now,
            }
            conn.execute(
                "UPDATE task428_fracture_nodes SET needs_owner_approval=0, owner_approval_json=?, status=?, updated_at=? WHERE child_id=?",
                (json.dumps(approval_obj, sort_keys=True), new_status, now, child_id),
            )
        return self.get_fracture_child(child_id)

    def complete_fracture_child(
        self,
        lineage_root: str,
        child_id: str,
        artifact_sha256: str,
    ) -> dict[str, Any]:
        """Mark a fracture child `COMPLETED` and advance dependent nodes when all prerequisites finish."""
        _id(lineage_root)
        _id(child_id)
        _sha(artifact_sha256)
        now = float(self.clock())
        with self.ledger._write() as conn:
            row = conn.execute(
                "SELECT * FROM task428_fracture_nodes WHERE lineage_root=? AND child_id=?",
                (lineage_root, child_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown fracture child '{child_id}'")
            if row["status"] != "READY":
                raise ValueError(f"Fracture child '{child_id}' is in status '{row['status']}', not READY")
            conn.execute(
                "UPDATE task428_fracture_nodes SET status='COMPLETED', artifact_sha256=?, updated_at=? WHERE child_id=?",
                (artifact_sha256, now, child_id),
            )
            # Re-evaluate blocked siblings in the same fracture
            siblings = conn.execute(
                "SELECT * FROM task428_fracture_nodes WHERE fracture_id=?",
                (row["fracture_id"],),
            ).fetchall()
            completed_ids = {
                s["child_id"] for s in siblings if s["status"] == "COMPLETED" or s["child_id"] == child_id
            }
            for sib in siblings:
                if sib["child_id"] == child_id or sib["status"] == "COMPLETED":
                    continue
                deps = set(json.loads(sib["depends_on_json"]))
                if deps <= completed_ids:
                    next_st = "HOLD_OWNER_APPROVAL" if sib["needs_owner_approval"] else "READY"
                    conn.execute(
                        "UPDATE task428_fracture_nodes SET status=?, updated_at=? WHERE child_id=?",
                        (next_st, now, sib["child_id"]),
                    )
        return self.get_fracture_child(child_id)

    def get_fracture_child(self, child_id: str) -> dict[str, Any]:
        _id(child_id)
        with self.ledger._write() as conn:
            row = conn.execute(
                "SELECT * FROM task428_fracture_nodes WHERE child_id=?",
                (child_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown fracture child '{child_id}'")
            lstate = self.ledger._read(conn, child_id)
        return self._row_to_dict(row, lstate["failures"])

    def list_fracture_children(
        self,
        lineage_root: str,
        *,
        fracture_id: str | None = None,
    ) -> list[dict[str, Any]]:
        _id(lineage_root)
        with self.ledger._write() as conn:
            lstate = self.ledger._read(conn, lineage_root)
            if fracture_id is not None:
                rows = conn.execute(
                    "SELECT * FROM task428_fracture_nodes WHERE lineage_root=? AND fracture_id=? ORDER BY child_id ASC",
                    (lineage_root, fracture_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM task428_fracture_nodes WHERE lineage_root=? ORDER BY child_id ASC",
                    (lineage_root,),
                ).fetchall()
        return [self._row_to_dict(r, lstate["failures"]) for r in rows]

    @staticmethod
    def _row_to_dict(row, inherited_failures: int) -> dict[str, Any]:
        return {
            "child_id": row["child_id"],
            "fracture_id": row["fracture_id"],
            "lineage_root": row["lineage_root"],
            "failed_scope_id": row["failed_scope_id"],
            "dossier_id": row["dossier_id"],
            "dossier_sha256": row["dossier_sha256"],
            "graph_sha256": row["graph_sha256"],
            "role": row["role"],
            "complexity": int(row["complexity"]),
            "task_types": json.loads(row["task_types_json"]),
            "requirement_ids": json.loads(row["requirement_ids_json"]),
            "deliverables": json.loads(row["deliverables_json"]),
            "release_criteria": json.loads(row["release_criteria_json"]),
            "depends_on": json.loads(row["depends_on_json"]),
            "selected_profile_id": row["selected_profile_id"],
            "selected_model_family": row["selected_model_family"],
            "selected_effort": row["selected_effort"],
            "escalated_scope": bool(row["escalated_scope"]),
            "needs_owner_approval": bool(row["needs_owner_approval"]),
            "owner_approval": json.loads(row["owner_approval_json"]) if row["owner_approval_json"] else None,
            "status": row["status"],
            "artifact_sha256": row["artifact_sha256"],
            "inherited_failures": int(inherited_failures),
        }
