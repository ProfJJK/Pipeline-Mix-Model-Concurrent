"""Operator-scoped coding intake. Registrations never enlarge protected roots.

Prepared projects are isolated controller-owned Git repositories. Source projects
are read-only inputs, including explicitly scoped working changes. A completed
job publishes a reviewable commit in the prepared repository, not a reset of the
owner's checkout.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import threading

from .coding import CodingProject, digest, validate_production_coding_project


@dataclass(frozen=True)
class RegistrationPolicy:
    source_roots: tuple[Path, ...]

    @classmethod
    def from_dict(cls, raw):
        if raw is None:
            return None
        if not isinstance(raw, dict) or set(raw) != {'source_roots'}:
            raise ValueError('coding_registration requires operator-owned source_roots')
        roots = raw['source_roots']
        if not isinstance(roots, list) or not 1 <= len(roots) <= 32:
            raise ValueError('Configure 1..32 coding source roots')
        paths = tuple(cls.local_path(value) for value in roots)
        if len(set(paths)) != len(paths):
            raise ValueError('Coding source roots must be distinct')
        return cls(paths)

    @staticmethod
    def local_path(value):
        if not isinstance(value, str) or not value or '\x00' in value:
            raise ValueError('Repository must be an absolute local path')
        path = Path(value)
        if not path.is_absolute() or str(path).startswith(('\\\\', '//')) or '..' in path.parts:
            raise ValueError('Repository must be an absolute local path')
        # Reviewed roots remain the authority; block known sync locations as an
        # additional guard rather than guessing that every other path is safe.
        if any(any(token in part.casefold() for token in ('gdrive', 'google drive', 'googledrive', 'onedrive', 'dropbox'))
               for part in path.parts):
            raise ValueError('Coding work must be outside synchronized folders')
        return path.absolute()

    def authorize(self, repository):
        path = self.local_path(str(repository))
        from .coding_git import _reject_links
        _reject_links(path)
        if not any(path != root and root in path.parents for root in self.source_roots):
            raise ValueError('Repository is outside the operator-approved source roots')
        return path


class ProjectRegistry:
    def __init__(self, root, policy, *, git_executable, static_projects):
        self.root, self.policy = Path(root), policy
        self.git_executable, self.static_projects = git_executable, static_projects
        self._lock = threading.Lock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'registry.sqlite3'
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS projects(project_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, descriptor TEXT NOT NULL, evidence TEXT NOT NULL)')

    def projects(self):
        projects = dict(self.static_projects)
        with sqlite3.connect(self.db) as conn:
            for project_id, raw, evidence in conn.execute('SELECT project_id, descriptor, evidence FROM projects'):
                if project_id in projects:
                    raise ValueError('Dynamic project conflicts with operator registry')
                proof = json.loads(evidence)
                self.policy.authorize(proof['source_repository'])
                project = validate_production_coding_project(CodingProject.from_dict(project_id, json.loads(raw)))
                if self.root not in project.repository.parents:
                    raise ValueError('Prepared repository escaped its private root')
                projects[project_id] = project
        return projects

    def prepare(self, project_id, raw):
        from .coding_git import prepare_isolated_project
        if not isinstance(raw, dict) or set(raw) - {'repository', 'branch', 'allowed_paths', 'test_paths', 'context_paths'}:
            raise ValueError('Registration accepts source repository, branch and explicit source/test/context paths only')
        descriptor = {key: value for key, value in raw.items() if key != 'context_paths'}
        project = validate_production_coding_project(CodingProject.from_dict(project_id, descriptor))
        self.policy.authorize(project.repository)
        if project_id in self.static_projects:
            raise ValueError('Registration cannot override an operator-configured project')
        fixture = self.static_projects.get('windows-acceptance')
        if fixture and os.path.normcase(str(fixture.repository)) == os.path.normcase(str(project.repository)):
            raise ValueError('Acceptance fixture cannot be aliased as a production repository')
        from .coding import safe_path
        context = raw.get('context_paths', [])
        if not isinstance(context, list) or len(context) > 128:
            raise ValueError('context_paths must be a bounded list')
        context = tuple(safe_path(path) for path in context)
        request_digest = digest(raw)
        with self._lock, sqlite3.connect(self.db) as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT request_digest, evidence FROM projects WHERE project_id=?', (project_id,)).fetchone()
            if existing:
                if existing[0] != request_digest:
                    raise ValueError('Project ID already binds a different source or scope')
                return json.loads(existing[1])
            prepared, evidence = prepare_isolated_project(project, self.root / 'repositories', context,
                                                          git_executable=self.git_executable)
            proof = dict(evidence, project_id=project_id, request_digest=request_digest,
                         original_checkout_modified=False, source_integration='REVIEW_REQUIRED')
            conn.execute('INSERT INTO projects VALUES(?,?,?,?)',
                         (project_id, request_digest, json.dumps(prepared.as_dict()), json.dumps(proof)))
            return proof
