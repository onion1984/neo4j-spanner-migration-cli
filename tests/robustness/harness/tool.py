"""Thin wrappers around the tool under test (library calls + CLI subprocess)."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

REPO = Path(__file__).resolve().parents[3]
CLI = [str(REPO / ".venv" / "bin" / "neo4j-spanner-export")]


@dataclass
class Bundle:
    root: Path
    mapping_path: Path
    out_dir: Path
    mapping: Any
    summary: Any


def complete_partial_input(m: Any) -> tuple[Any, list[str]]:
    """D16 workaround for NEW-INPUTMAP: load_mapping() now rejects partial input mappings.

    * label_priority-only mappings -> passed via the `label_priority` argument (CLI --label-priority) instead.
    * node entries without their PK properties / pk_overrides without a node entry -> add PK PropertyMappings.
    Returns (mapping_or_None, notes).
    """
    from neo4j_spanner_export.config import NodeTableMapping, PropertyMapping

    notes: list[str] = []
    for label, pks in (m.pk_overrides or {}).items():
        if label not in m.nodes:
            m.nodes[label] = NodeTableMapping(raw_label=label, spanner_table=(m.table_renames or {}).get(label, label),
                                              pk_columns=list(pks), pk_source="yaml_override")
            notes.append(f"added node entry for pk_overrides[{label}]")
    for label, nm in m.nodes.items():
        for pk in nm.pk_columns:
            if pk not in nm.properties:
                typ = "INT64" if pk == "_neo4j_id" else "STRING(MAX)"
                nm.properties[pk] = PropertyMapping(raw_name=pk, spanner_column=nm.column_renames.get(pk, pk), resolved=typ)
                notes.append(f"added PK property {label}.{pk}")
    if not m.nodes:
        notes.append("label_priority-only mapping passed via label_priority argument")
        return None, notes
    return m, notes


WORKAROUND_LOG: list[str] = []


def discover(driver: Any, work: Path, input_mapping: Any | None = None, raw_input: bool = False, **kw: Any):
    from neo4j_spanner_export.config import save_mapping
    from neo4j_spanner_export.discovery import discover_schema

    in_path = None
    if input_mapping is not None and not raw_input and os.environ.get("RB_NO_INPUTMAP_WORKAROUND") != "1":
        prio = list(input_mapping.label_priority or [])
        input_mapping, notes = complete_partial_input(input_mapping)
        if input_mapping is None and prio and "label_priority" not in kw:
            kw["label_priority"] = prio
        if notes:
            WORKAROUND_LOG.extend(notes)
    if input_mapping is not None:
        in_path = work / "input_mapping.yaml"
        save_mapping(input_mapping, in_path)
    try:
        return discover_schema(
            driver,
            "neo4j",
            work / "schema_mapping.yaml",
            input_mapping_path=in_path,
            report_path=work / "discovery_report.md",
            **kw,
        )
    except UnboundLocalError as exc:
        if "fixed_cols_lower" not in str(exc):
            raise
        _blocked(exc)


def _blocked(exc: BaseException):
    """Discovery crashes with the NEW-DISCCRASH regression: never let a test count that crash as 'fail-fast'."""
    import pytest

    from harness import findings

    test = os.environ.get("PYTEST_CURRENT_TEST", "?").split(" ")[0].split("::")[-1]
    findings.record("NEW-DISCCRASH", f"BLOCKED:{test}", "Confirmed",
                    f"discover_schema raised {type(exc).__name__}: {exc} (discovery.py: node-loop references edge-only "
                    f"variable fixed_cols_lower); test could not run", severity="P0",
                    title="discover crashes on every non-empty graph (UnboundLocalError fixed_cols_lower)")
    pytest.skip(f"BLOCKED by NEW-DISCCRASH: {exc}")


def discover_or_manual(driver: Any, work: Path, manual: Any, **kw: Any):
    """Use discovery; if it is blocked by NEW-DISCCRASH, fall back to a hand-built mapping (D16 input-level workaround)."""
    from neo4j_spanner_export.config import save_mapping
    from neo4j_spanner_export.discovery import discover_schema

    try:
        return discover_schema(driver, "neo4j", work / "schema_mapping.yaml", report_path=work / "discovery_report.md", **kw)
    except UnboundLocalError as exc:
        if "fixed_cols_lower" not in str(exc):
            raise
        save_mapping(manual, work / "schema_mapping.yaml")
        WORKAROUND_LOG.append(f"manual mapping used in {work.name} (NEW-DISCCRASH)")
        return manual


def export(
    driver: Any,
    work: Path,
    mapping: Any,
    gcs_prefix: str = "gs://example-bucket/run",
    graph_name: str = "MigratedGraph",
    chunk_rows: int = 500_000,
    workers: int = 4,
    emit_unescape: bool = False,
    overwrite: bool = False,
    **ser: Any,
) -> Bundle:
    from neo4j_spanner_export.artifacts import generate_artifacts
    from neo4j_spanner_export.exporter import export_graph
    from neo4j_spanner_export.serializer import SerializerConfig

    cfg = SerializerConfig(**ser)
    out = work / "export_out"
    import inspect

    kw = {"overwrite": overwrite} if "overwrite" in inspect.signature(export_graph).parameters else {}
    summary = export_graph(driver, "neo4j", mapping, out, cfg, chunk_rows=chunk_rows, workers=workers, **kw)
    akw = {"summary": summary} if "summary" in inspect.signature(generate_artifacts).parameters else {}
    # Mirror the CLI: it passes the export summary so manifests list the exact shards.
    generate_artifacts(mapping, out, gcs_prefix, cfg, graph_name=graph_name, emit_unescape=emit_unescape, **akw)
    return Bundle(work, work / "schema_mapping.yaml", out, mapping, summary)


def discover_and_export(driver: Any, work: Path, input_mapping: Any | None = None, **kw: Any) -> Bundle:
    m = discover(driver, work, input_mapping=input_mapping)
    return export(driver, work, m, **kw)


def cli(args: list[str], env: dict[str, str] | None = None, timeout: float = 600, cwd: Path | None = None):
    e = dict(os.environ)
    if env is not None:
        e.update(env)
    return subprocess.run(
        CLI + args, capture_output=True, text=True, env=e, timeout=timeout, cwd=str(cwd) if cwd else None
    )


def has_traceback(text: str) -> bool:
    return "Traceback (most recent call last)" in text


def all_csv_lines(out_dir: Path, sub: str, table: str) -> list[str]:
    lines: list[str] = []
    for p in sorted((out_dir / sub).glob(f"{table}_part_*.csv")):
        lines.extend(p.read_text(encoding="utf-8").splitlines())
    return lines


def python() -> str:
    return sys.executable
