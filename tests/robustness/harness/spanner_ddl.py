"""T2 helper: apply the tool's staged DDL to an empty Spanner database, capturing per-statement errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any


def split_sql(text: str) -> list[str]:
    """Split a tool-generated SQL file into statements (comments stripped)."""
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    stmts = [s.strip() for s in re.split(r";\s*(?:\n|$)", body)]
    return [s for s in stmts if s]


@dataclass
class DdlResult:
    file: str
    statements: int
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _committed(op: Any) -> int:
    try:
        return len(op.metadata.commit_timestamps)
    except Exception:  # noqa: BLE001
        return 0


def apply_statements(db: Any, stmts: list[str], label: str, timeout: float = 1800) -> DdlResult:
    res = DdlResult(label, len(stmts))
    i = 0
    while i < len(stmts):
        batch = stmts[i:]
        op = db.update_ddl(batch)
        try:
            op.result(timeout)
            break
        except Exception as exc:  # noqa: BLE001
            done = _committed(op)
            bad = i + done
            res.errors.append({"index": str(bad), "statement": stmts[bad][:3000], "error": str(exc)[:3000]})
            i = bad + 1
    return res


def create_empty_db(gcp: Any, db_id: str) -> Any:
    db = gcp.database(db_id)
    if db.exists():
        db.drop()
    op = db.create()
    op.result(900)
    return db


def apply_bundle_ddl(gcp: Any, db_id: str, out_dir: Path, include_fk: bool = True, include_graph: bool = True,
                     include_arrays: bool = True) -> dict[str, DdlResult]:
    """01 → 02_add (+ drop of __json) → 04 → 05 on an empty DB (no data, no Dataflow)."""
    db = create_empty_db(gcp, db_id)
    schema = out_dir / "schema"
    results: dict[str, DdlResult] = {}
    order = ["01_create_tables.sql"]
    if include_arrays:
        order += ["02_arrays_add.sql", "02_arrays_drop.sql"]
    if include_fk:
        order.append("04_constraints_indexes.sql")
    if include_graph:
        order.append("05_property_graph.sql")
    for f in order:
        stmts = split_sql((schema / f).read_text(encoding="utf-8"))
        if not stmts:
            results[f] = DdlResult(f, 0)
            continue
        results[f] = apply_statements(db, stmts, f)
    return results


def summarize(results: dict[str, DdlResult]) -> str:
    out = []
    for f, r in results.items():
        if r.ok:
            out.append(f"{f}: OK ({r.statements} stmt)")
        else:
            for e in r.errors:
                out.append(f"{f}: stmt#{e['index']} ERROR {e['error'][:600]} :: {e['statement'][:600]}")
    return "\n".join(out)


def query(db: Any, sql: str, params: dict | None = None, param_types: dict | None = None) -> list[dict[str, Any]]:
    with db.snapshot() as snap:
        rs = snap.execute_sql(sql, params=params, param_types=param_types)
        rows = list(rs)
        names = [f.name for f in rs.metadata.row_type.fields]
    return [dict(zip(names, r)) for r in rows]


def execute_dml(db: Any, sql: str) -> int:
    def _tx(tx):
        return tx.execute_update(sql)

    return db.run_in_transaction(_tx)
