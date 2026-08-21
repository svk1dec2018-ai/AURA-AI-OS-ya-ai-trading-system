from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import subprocess
import sys
import tokenize
import tomllib
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from aura.ops.phase_gates import build_phase_zero_records, write_phase_gate_ledger

AUDIT_OUTPUT_DIR = PurePosixPath("artifacts/governance")
PHASE_ZERO_EVIDENCE = {
    "repo_audit.json": "artifacts/governance/repo_audit.json",
    "module_map.md": "artifacts/governance/module_map.md",
    "test_inventory.json": "artifacts/governance/test_inventory.json",
}

_PHASE_BY_PACKAGE = {
    "agents": 9,
    "ai": 9,
    "backtest": 6,
    "connectors": 4,
    "core": 10,
    "data": 5,
    "domain": 1,
    "evolution": 7,
    "execution": 4,
    "forecast": 7,
    "interface": 13,
    "knowledge": 8,
    "markets": 1,
    "maintenance": 15,
    "memory": 9,
    "models": 9,
    "observability": 14,
    "ops": 15,
    "options": 5,
    "persistence": 2,
    "portfolio": 2,
    "research": 7,
    "risk": 3,
    "runtime": 12,
    "strategy": 7,
}

_FILE_PHASE_OVERRIDES = {
    "aura/__init__.py": 0,
    "aura/execution/state.py": 2,
    "aura/execution/reconciliation.py": 2,
    "aura/execution/paper.py": 12,
    "aura/ops/phase_gates.py": 0,
    "aura/ops/repository_audit.py": 0,
    "aura/ops/core_contracts.py": 1,
    "aura/ops/state_engine_gate.py": 2,
    "aura/ops/risk_engine_gate.py": 3,
    "aura/ops/broker_conformance_gate.py": 4,
    "aura/ops/market_data_gate.py": 5,
    "aura/ops/backtest_gate.py": 6,
    "aura/ops/strategy_research_gate.py": 7,
    "aura/ops/knowledge_rag_gate.py": 8,
    "aura/ops/multi_agent_gate.py": 9,
    "aura/ops/ceo_decision_gate.py": 10,
    "aura/ops/broker_evidence_readiness.py": 11,
    "aura/ops/broker_evidence_intake.py": 11,
    "aura/ops/broker_evidence_checkpoint.py": 11,
    "aura/ops/broker_evidence_custody.py": 11,
    "aura/execution/broker_evidence_recorder.py": 11,
    "aura/persistence/broker_evidence_archive.py": 11,
    "aura/ops/health.py": 15,
    "aura/ops/preflight.py": 15,
    "aura/ops/release_gate.py": 15,
}

_ENTRYPOINT_SUFFIXES = {".cmd", ".ps1", ".sh"}
_STUB_COMMENT = re.compile(r"\b(TODO|FIXME|XXX)\b", re.IGNORECASE)


def build_repository_audit(root: Path) -> tuple[dict[str, object], dict[str, object], str]:
    root = root.resolve()
    paths = _repository_paths(root)
    file_records = [_file_record(root, path) for path in paths]
    python_paths = [path for path in paths if path.suffix == ".py"]
    module_names = {path: _module_name(path) for path in python_paths}
    modules_by_name = {name: path for path, name in module_names.items()}

    parsed: dict[PurePosixPath, ast.Module] = {}
    parse_errors: list[dict[str, object]] = []
    raw_imports: dict[PurePosixPath, tuple[str, ...]] = {}
    stub_findings: list[dict[str, object]] = []
    test_details: dict[PurePosixPath, dict[str, object]] = {}
    python_entrypoints: list[dict[str, str]] = []

    for path in python_paths:
        source = (root / path).read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=path.as_posix())
        except SyntaxError as exc:
            parse_errors.append(
                {
                    "path": path.as_posix(),
                    "line": exc.lineno,
                    "message": exc.msg,
                }
            )
            continue
        parsed[path] = tree
        raw_imports[path] = tuple(sorted(_extract_imports(tree, module_names[path])))
        stub_findings.extend(_find_stub_candidates(path, tree, source))
        if _has_main_guard(tree):
            python_entrypoints.append({"path": path.as_posix(), "kind": "python-main"})
        if path.parts and path.parts[0] == "tests":
            test_details[path] = _test_file_details(tree)

    dependency_map: dict[PurePosixPath, tuple[PurePosixPath, ...]] = {}
    standard_library_map: dict[PurePosixPath, tuple[str, ...]] = {}
    third_party_map: dict[PurePosixPath, tuple[str, ...]] = {}
    unresolved_imports: list[dict[str, str]] = []
    for path, imports in raw_imports.items():
        internal: set[PurePosixPath] = set()
        standard_library: set[str] = set()
        third_party: set[str] = set()
        for imported in imports:
            if imported == "aura" or imported.startswith("aura."):
                resolved = _resolve_internal_import(imported, modules_by_name)
                if resolved is None:
                    unresolved_imports.append(
                        {"path": path.as_posix(), "import": imported}
                    )
                elif resolved != path:
                    internal.add(resolved)
            else:
                package = imported.split(".", 1)[0]
                if package in sys.stdlib_module_names:
                    standard_library.add(package)
                else:
                    third_party.add(package)
        dependency_map[path] = tuple(sorted(internal))
        standard_library_map[path] = tuple(sorted(standard_library))
        third_party_map[path] = tuple(sorted(third_party))

    base_classifications = {
        path: _base_python_classification(path) for path in python_paths
    }
    classifications: dict[PurePosixPath, dict[str, object]] = {}
    for path in python_paths:
        classification = dict(base_classifications[path])
        dependency_phases = sorted(
            {
                int(base_classifications[item]["primary_phase"])
                for item in dependency_map.get(path, ())
                if item in base_classifications
            }
        )
        if classification["role"] in {"test", "entrypoint"}:
            classification["phase_coverage"] = dependency_phases or [0]
            classification["primary_phase"] = min(dependency_phases, default=0)
        else:
            classification["phase_coverage"] = [classification["primary_phase"]]
        classifications[path] = classification

    direct_tests: dict[PurePosixPath, list[str]] = defaultdict(list)
    for test_path in test_details:
        for dependency in dependency_map.get(test_path, ()):
            if dependency.parts and dependency.parts[0] == "aura":
                direct_tests[dependency].append(test_path.as_posix())

    module_records: list[dict[str, object]] = []
    for path in python_paths:
        classification = classifications[path]
        module_records.append(
            {
                "path": path.as_posix(),
                "module": module_names[path],
                "role": classification["role"],
                "component": classification["component"],
                "primary_phase": classification["primary_phase"],
                "phase_coverage": classification["phase_coverage"],
                "internal_dependencies": [
                    item.as_posix() for item in dependency_map.get(path, ())
                ],
                "standard_library_dependencies": list(standard_library_map.get(path, ())),
                "third_party_dependencies": list(third_party_map.get(path, ())),
                "direct_test_files": sorted(direct_tests.get(path, [])),
                "sha256": _file_sha256(root / path),
                "lines": _line_count(root / path),
                "parsed": path in parsed,
            }
        )

    entrypoints = sorted(
        python_entrypoints + _non_python_entrypoints(root, paths),
        key=lambda item: (item["path"], item["kind"]),
    )
    unclassified = [
        item["path"]
        for item in module_records
        if item["role"] == "unknown"
        or item["component"] == "unknown"
        or not 0 <= int(item["primary_phase"]) <= 15
    ]
    unknown_assets = [item["path"] for item in file_records if item["asset_class"] == "unknown"]
    criteria = {
        "module_classification_complete": not unclassified,
        "all_python_modules_parse": not parse_errors,
        "all_internal_imports_resolve": not unresolved_imports,
        "entrypoints_identified": bool(entrypoints),
        "no_unknown_components": not unclassified and not unknown_assets,
    }
    decision = "PASS" if all(criteria.values()) else "FAIL"
    source_modules = [item for item in module_records if item["role"] == "source"]
    tested_source_modules = [item for item in source_modules if item["direct_test_files"]]
    repository_hash_payload = [
        f"{item['path']}:{item['sha256']}" for item in file_records
    ]

    test_inventory = _build_test_inventory(
        root,
        test_details,
        dependency_map,
        classifications,
    )
    audit: dict[str, object] = {
        "schema_version": 1,
        "scope": {
            "root": ".",
            "source": "git tracked plus non-ignored untracked files",
            "excluded": [
                f"{AUDIT_OUTPUT_DIR.as_posix()}/**",
                "**/*.egg-info/**",
                "build/**",
                "dist/**",
            ],
        },
        "gate": {
            "phase": 0,
            "name": "Repository audit and baseline",
            "decision": decision,
            "criteria": criteria,
            "stop_condition_triggered": decision != "PASS",
        },
        "summary": {
            "repository_files": len(file_records),
            "python_modules": len(module_records),
            "source_modules": len(source_modules),
            "directly_tested_source_modules": len(tested_source_modules),
            "test_modules": len(test_details),
            "static_test_functions": test_inventory["summary"]["static_test_functions"],
            "entrypoints": len(entrypoints),
            "stub_candidates": len(stub_findings),
            "parse_errors": len(parse_errors),
            "unresolved_internal_imports": len(unresolved_imports),
            "unclassified_modules": len(unclassified),
            "unknown_assets": len(unknown_assets),
        },
        "repository_tree_sha256": hashlib.sha256(
            "\n".join(repository_hash_payload).encode()
        ).hexdigest(),
        "files": file_records,
        "modules": module_records,
        "dependency_graph": {
            "internal_edges": [
                {"from": path.as_posix(), "to": dependency.as_posix()}
                for path in sorted(dependency_map)
                for dependency in dependency_map[path]
            ],
            "third_party_packages": sorted(
                {package for values in third_party_map.values() for package in values}
            ),
            "standard_library_packages": sorted(
                {
                    package
                    for values in standard_library_map.values()
                    for package in values
                }
            ),
            "declared_dependencies": _declared_dependencies(root),
        },
        "entrypoints": entrypoints,
        "stub_and_incomplete_candidates": sorted(
            stub_findings,
            key=lambda item: (str(item["path"]), int(item["line"]), str(item["kind"])),
        ),
        "broken_components": {
            "parse_errors": parse_errors,
            "unresolved_internal_imports": unresolved_imports,
        },
        "unclassified_modules": unclassified,
        "unknown_assets": unknown_assets,
        "known_gaps": {
            "source_modules_without_direct_test_import": [
                item["path"] for item in source_modules if not item["direct_test_files"]
            ],
            "review_required_stub_candidates": [
                item
                for item in sorted(
                    stub_findings,
                    key=lambda finding: (
                        str(finding["path"]),
                        int(finding["line"]),
                        str(finding["kind"]),
                    ),
                )
                if item["classification"] == "review-required"
            ],
        },
        "limitations": [
            "Static discovery does not execute credential-gated or broker-hosted entrypoints.",
            "Direct test mapping is import-based and does not claim behavioral coverage.",
            "Stub candidates are classified inventory findings, not automatic proof of a defect.",
        ],
    }
    return audit, test_inventory, _render_module_map(audit)


def write_repository_audit(root: Path) -> dict[str, object]:
    root = root.resolve()
    audit, tests, module_map = build_repository_audit(root)
    output_dir = root / AUDIT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "repo_audit.json", audit)
    _write_json(output_dir / "test_inventory.json", tests)
    (output_dir / "module_map.md").write_text(module_map, encoding="utf-8")
    if audit["gate"]["decision"] != "PASS":
        raise RuntimeError("Phase 0 audit failed; inspect repo_audit.json")
    records = build_phase_zero_records(root, PHASE_ZERO_EVIDENCE)
    write_phase_gate_ledger(output_dir / "phase_gate_status.json", records, root=root)
    return audit


def check_repository_audit(root: Path) -> tuple[str, ...]:
    root = root.resolve()
    audit, tests, module_map = build_repository_audit(root)
    expected = {
        "repo_audit.json": json.dumps(audit, indent=2, sort_keys=True) + "\n",
        "test_inventory.json": json.dumps(tests, indent=2, sort_keys=True) + "\n",
        "module_map.md": module_map,
    }
    errors: list[str] = []
    for name, content in expected.items():
        path = root / AUDIT_OUTPUT_DIR / name
        if not path.is_file():
            errors.append(f"missing generated audit artifact: {path.relative_to(root)}")
        elif path.read_text(encoding="utf-8") != content:
            errors.append(f"stale generated audit artifact: {path.relative_to(root)}")
    if audit["gate"]["decision"] != "PASS":
        errors.append("Phase 0 audit decision is not PASS")
    return tuple(errors)


def _repository_paths(root: Path) -> list[PurePosixPath]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    paths = {
        PurePosixPath(item.decode())
        for item in result.stdout.split(b"\0")
        if item
    }
    return sorted(
        path
        for path in paths
        if not _is_audit_excluded(path) and (root / path).is_file()
    )


def _is_audit_excluded(path: PurePosixPath) -> bool:
    return (
        path.is_relative_to(AUDIT_OUTPUT_DIR)
        or path.parts[0] in {"build", "dist"}
        or any(part.endswith(".egg-info") for part in path.parts)
    )


def _file_record(root: Path, path: PurePosixPath) -> dict[str, object]:
    file_path = root / path
    return {
        "path": path.as_posix(),
        "asset_class": _asset_class(path),
        "bytes": file_path.stat().st_size,
        "sha256": _file_sha256(file_path),
    }


def _asset_class(path: PurePosixPath) -> str:
    if path.suffix == ".py":
        return "python_module"
    if path.parts and path.parts[0] == ".github":
        return "ci_or_repository_policy"
    if path.parts and path.parts[0] == "docs":
        return "documentation"
    if path.parts and path.parts[0] == "knowledge":
        return "knowledge_corpus_asset"
    if path.suffix in {".md", ".txt"}:
        return "documentation_or_validation_evidence"
    if path.suffix in {".json", ".jsonl", ".toml", ".yml", ".yaml"}:
        return "configuration_or_structured_evidence"
    if path.suffix in _ENTRYPOINT_SUFFIXES:
        return "automation_entrypoint"
    if path.name in {"Dockerfile", ".dockerignore"}:
        return "container_configuration"
    if path.name in {".gitignore", ".env.example"}:
        return "repository_configuration"
    return "repository_asset"


def _module_name(path: PurePosixPath) -> str:
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _base_python_classification(path: PurePosixPath) -> dict[str, object]:
    path_text = path.as_posix()
    if path.parts[0] == "aura":
        component = path.parts[1] if len(path.parts) > 2 else "package"
        phase = _FILE_PHASE_OVERRIDES.get(path_text, _PHASE_BY_PACKAGE.get(component, -1))
        return {
            "role": "source" if path.name != "__init__.py" else "package_marker",
            "component": component,
            "primary_phase": phase,
        }
    if path.parts[0] == "tests":
        return {"role": "test", "component": "validation", "primary_phase": 0}
    if path.parts[0] == "examples":
        return {"role": "entrypoint", "component": "examples", "primary_phase": 0}
    return {"role": "tooling", "component": "repository_tooling", "primary_phase": 0}


def _extract_imports(tree: ast.Module, current_module: str) -> set[str]:
    imports: set[str] = set()
    package = current_module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                prefix_parts = package.split(".") if package else []
                keep = max(0, len(prefix_parts) - node.level + 1)
                prefix = ".".join(prefix_parts[:keep])
                base = ".".join(item for item in (prefix, node.module or "") if item)
            else:
                base = node.module or ""
            if not base:
                continue
            imports.add(base)
            imports.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    return imports


def _resolve_internal_import(
    imported: str,
    modules_by_name: dict[str, PurePosixPath],
) -> PurePosixPath | None:
    candidate = imported
    while candidate:
        if candidate in modules_by_name:
            return modules_by_name[candidate]
        if "." not in candidate:
            break
        candidate = candidate.rpartition(".")[0]
    return None


def _has_main_guard(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:
            continue
        left_is_name = isinstance(test.left, ast.Name) and test.left.id == "__name__"
        right_is_main = any(
            isinstance(item, ast.Constant) and item.value == "__main__"
            for item in test.comparators
        )
        if left_is_name and right_is_main:
            return True
    return False


def _non_python_entrypoints(
    root: Path,
    paths: Iterable[PurePosixPath],
) -> list[dict[str, str]]:
    entrypoints: list[dict[str, str]] = []
    for path in paths:
        if path.suffix in _ENTRYPOINT_SUFFIXES:
            entrypoints.append({"path": path.as_posix(), "kind": "shell-launcher"})
        elif path.name == "Dockerfile":
            content = (root / path).read_text(encoding="utf-8")
            if re.search(r"^(CMD|ENTRYPOINT)\b", content, flags=re.MULTILINE):
                entrypoints.append({"path": path.as_posix(), "kind": "container-entrypoint"})
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        for name in sorted(project.get("scripts", {})):
            entrypoints.append({"path": "pyproject.toml", "kind": f"console-script:{name}"})
    return entrypoints


def _find_stub_candidates(
    path: PurePosixPath,
    tree: ast.Module,
    source: str,
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    class_contracts: dict[ast.ClassDef, bool] = {}
    marker_classes: set[ast.ClassDef] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {_expression_name(base) for base in node.bases}
        class_contracts[node] = bool(bases & {"Protocol", "ABC", "ABCMeta"})
        if any(name.endswith(("Error", "Exception")) for name in bases):
            marker_classes.add(node)

    for node in ast.walk(tree):
        if isinstance(node, ast.Pass):
            parent = parents.get(node)
            if isinstance(parent, ast.ClassDef) and parent in marker_classes:
                kind, classification = "marker-exception", "intentional"
            elif isinstance(parent, ast.ExceptHandler):
                kind, classification = "suppressed-exception", "review-required"
            elif isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = parents.get(parent)
                intentional = isinstance(owner, ast.ClassDef) and class_contracts.get(owner, False)
                kind = "interface-pass" if intentional else "empty-implementation"
                classification = "intentional" if intentional else "review-required"
            else:
                kind, classification = "empty-block", "review-required"
            findings.append(_stub_finding(path, node.lineno, kind, classification))
        elif isinstance(node, ast.Raise) and _is_not_implemented(node.exc):
            function = _nearest_parent(node, parents, (ast.FunctionDef, ast.AsyncFunctionDef))
            owner = parents.get(function) if function is not None else None
            intentional = isinstance(owner, ast.ClassDef) and class_contracts.get(owner, False)
            findings.append(
                _stub_finding(
                    path,
                    node.lineno,
                    "abstract-contract" if intentional else "not-implemented",
                    "intentional" if intentional else "review-required",
                )
            )
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if node.value.value is Ellipsis:
                function = _nearest_parent(
                    node,
                    parents,
                    (ast.FunctionDef, ast.AsyncFunctionDef),
                )
                owner = parents.get(function) if function is not None else None
                intentional = isinstance(owner, ast.ClassDef) and class_contracts.get(owner, False)
                findings.append(
                    _stub_finding(
                        path,
                        node.lineno,
                        "protocol-contract" if intentional else "ellipsis",
                        "intentional" if intentional else "review-required",
                    )
                )

    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        match = _STUB_COMMENT.search(token.string)
        if match:
            findings.append(
                _stub_finding(path, token.start[0], match.group(1).lower(), "review-required")
            )
    return findings


def _expression_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _nearest_parent(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
    types: tuple[type[ast.AST], ...],
) -> ast.AST | None:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, types):
            return current
        current = parents.get(current)
    return None


def _is_not_implemented(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "NotImplementedError"
    if isinstance(node, ast.Call):
        return isinstance(node.func, ast.Name) and node.func.id == "NotImplementedError"
    return False


def _stub_finding(
    path: PurePosixPath,
    line: int,
    kind: str,
    classification: str,
) -> dict[str, object]:
    return {
        "path": path.as_posix(),
        "line": line,
        "kind": kind,
        "classification": classification,
    }


def _test_file_details(tree: ast.Module) -> dict[str, object]:
    functions = sorted(
        {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        }
    )
    classes = sorted(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test")
    )
    async_tests = sum(
        isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_")
        for node in ast.walk(tree)
    )
    return {
        "static_test_functions": len(functions),
        "async_test_functions": async_tests,
        "test_classes": classes,
        "test_functions": functions,
    }


def _build_test_inventory(
    root: Path,
    details: dict[PurePosixPath, dict[str, object]],
    dependencies: dict[PurePosixPath, tuple[PurePosixPath, ...]],
    classifications: dict[PurePosixPath, dict[str, object]],
) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(details):
        source_dependencies = [
            item.as_posix()
            for item in dependencies.get(path, ())
            if item.parts and item.parts[0] == "aura"
        ]
        files.append(
            {
                "path": path.as_posix(),
                **details[path],
                "source_dependencies": source_dependencies,
                "phase_coverage": classifications[path]["phase_coverage"],
                "sha256": _file_sha256(root / path),
            }
        )
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_config = pyproject.get("tool", {}).get("pytest", {}).get("ini_options", {})
    return {
        "schema_version": 1,
        "discovery": {
            "framework": "pytest",
            "configured_testpaths": pytest_config.get("testpaths", []),
            "configured_addopts": pytest_config.get("addopts", ""),
            "method": "static AST inventory; runtime collection is separately validated by CI",
        },
        "summary": {
            "test_modules": len(files),
            "static_test_functions": sum(int(item["static_test_functions"]) for item in files),
            "async_test_functions": sum(int(item["async_test_functions"]) for item in files),
            "modules_without_static_tests": [
                item["path"] for item in files if not item["static_test_functions"]
            ],
        },
        "files": files,
    }


def _declared_dependencies(root: Path) -> dict[str, list[str]]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    return {
        "runtime": sorted(str(item) for item in project.get("dependencies", [])),
        "optional": sorted(
            str(item)
            for values in project.get("optional-dependencies", {}).values()
            for item in values
        ),
        "build_system": sorted(
            str(item) for item in pyproject.get("build-system", {}).get("requires", [])
        ),
    }


def _render_module_map(audit: dict[str, object]) -> str:
    summary = audit["summary"]
    gate = audit["gate"]
    files = audit["files"]
    modules = audit["modules"]
    directory_counts = Counter(str(item["path"]).split("/", 1)[0] for item in files)
    lines = [
        "# AURA Phase 0 repository module map",
        "",
        "This file is generated by `python -m aura.ops.repository_audit --write`.",
        "It inventories the repository; it does not certify later implementation phases.",
        "",
        "## Gate decision",
        "",
        f"**Phase 0: {gate['decision']}**",
        "",
        f"- Repository files: {summary['repository_files']}",
        f"- Python modules: {summary['python_modules']}",
        f"- Source modules: {summary['source_modules']}",
        f"- Test modules: {summary['test_modules']}",
        f"- Static test functions: {summary['static_test_functions']}",
        f"- Entrypoints: {summary['entrypoints']}",
        f"- Known stub/incomplete candidates: {summary['stub_candidates']}",
        "",
        "## Repository structure",
        "",
        "| Top-level path | Files |",
        "|---|---:|",
    ]
    lines.extend(f"| `{name}` | {count} |" for name, count in sorted(directory_counts.items()))
    lines.extend(
        [
            "",
            "## Entrypoints",
            "",
            "| Path | Kind |",
            "|---|---|",
        ]
    )
    lines.extend(
        f"| `{item['path']}` | {item['kind']} |" for item in audit["entrypoints"]
    )
    lines.extend(
        [
            "",
            "## Module inventory",
            "",
            "| Module | Role | Component | Primary phase | Internal deps | Direct tests |",
            "|---|---|---|---:|---:|---:|",
        ]
    )
    for item in modules:
        lines.append(
            f"| `{item['path']}` | {item['role']} | {item['component']} | "
            f"{item['primary_phase']} | {len(item['internal_dependencies'])} | "
            f"{len(item['direct_test_files'])} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "- Classification coverage means each module has an owner and phase; it is not a claim that the phase is complete.",
            "- Import-based test mapping is not line, branch, mutation, or behavioral coverage.",
            "- Stub candidates remain visible in `repo_audit.json`; intentional interfaces and marker exceptions are distinguished from review-required findings.",
            "- Credential-backed broker behavior and external infrastructure cannot be proven by this static audit.",
            "",
        ]
    )
    return "\n".join(lines)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or verify AURA Phase 0 audit evidence")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write deterministic audit artifacts")
    mode.add_argument("--check", action="store_true", help="fail if artifacts are stale")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.write:
        audit = write_repository_audit(args.root)
        print(f"Phase 0: {audit['gate']['decision']}")
        return 0
    errors = check_repository_audit(args.root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Phase 0 audit artifacts are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
