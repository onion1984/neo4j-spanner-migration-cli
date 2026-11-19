"""CLI entrypoint for neo4j-spanner-export (discover | export | verify)."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfoNotFoundError

from neo4j import GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError
from rich.console import Console
import yaml

from .artifacts import generate_artifacts
from .config import ConfigError, load_mapping
from .discovery import DiscoveryError, discover_schema
from .exporter import export_graph
from .naming import NamingError, validate_gcs_prefix, validate_identifier
from .serializer import SentinelCollisionError, SerializerConfig, SerializerConfigError
from .verify import verify_migration

console = Console()
err_console = Console(stderr=True)


def _get_password(args: argparse.Namespace) -> str:
    pw = getattr(args, "password", None) or os.environ.get("NEO4J_PASSWORD")
    if not pw:
        raise SystemExit("NEO4J_PASSWORD environment variable (or --password) is required.")
    return pw


def _cmd_discover(args: argparse.Namespace) -> int:
    pw = _get_password(args)
    out_mapping = Path(args.output_mapping)
    in_mapping = Path(args.input_mapping) if args.input_mapping else (out_mapping if out_mapping.exists() else None)
    report_path = Path(args.report) if args.report else out_mapping.with_name("discovery_report.md")
    label_prio = [s.strip() for s in args.label_priority.split(",") if s.strip()] if args.label_priority else None

    with GraphDatabase.driver(args.uri, auth=(args.user, pw)) as driver:
        mapping = discover_schema(
            driver=driver,
            database=args.database,
            output_mapping_path=out_mapping,
            input_mapping_path=in_mapping,
            label_priority=label_prio,
            sample_size=args.sample_size,
            report_path=report_path,
        )

    console.print(
        f"[green]Discovery complete:[/green] {len(mapping.nodes)} node table(s), "
        f"{len(mapping.edges)} edge triplet(s) -> {out_mapping} (report: {report_path})"
    )
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    pw = _get_password(args)
    if args.chunk_rows <= 0:
        raise ValueError(f"chunk_rows must be > 0, got {args.chunk_rows}")
    if args.workers <= 0:
        raise ValueError(f"workers must be > 0, got {args.workers}")
    validate_gcs_prefix(args.gcs_prefix)
    validate_identifier(args.graph_name, args.graph_name, "graph", "property graph", "graph_name")
    mapping = load_mapping(args.mapping)
    out_dir = Path(args.output_dir)
    serializer_cfg = SerializerConfig(
        delimiter=args.delimiter,
        null_string=args.null_string,
        quote_char=args.quote_char,
        escape_char=args.escape_char,
        default_timezone=args.default_timezone,
    )

    with GraphDatabase.driver(args.uri, auth=(args.user, pw)) as driver:
        summary = export_graph(
            driver=driver,
            database=args.database,
            mapping=mapping,
            output_dir=out_dir,
            serializer_cfg=serializer_cfg,
            chunk_rows=args.chunk_rows,
            workers=args.workers,
            overwrite=args.overwrite,
        )

    generate_artifacts(
        mapping=mapping,
        output_dir=out_dir,
        gcs_prefix=args.gcs_prefix,
        serializer_cfg=serializer_cfg,
        graph_name=args.graph_name,
        emit_unescape=args.emit_unescape,
        summary=summary,
    )

    total_nodes = sum(r.row_count for r in summary.nodes.values())
    total_edges = sum(r.row_count for r in summary.edges.values())
    console.print(
        f"[green]Export complete:[/green] {total_nodes} node row(s), {total_edges} edge row(s) -> {out_dir}"
    )
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    pw = _get_password(args)
    mapping = load_mapping(args.mapping)
    queries_file = Path(args.queries_file) if args.queries_file else None
    report_path = Path(args.output_report) if args.output_report else None

    with GraphDatabase.driver(args.uri, auth=(args.user, pw)) as driver:
        report = verify_migration(
            driver=driver,
            neo4j_db=args.database,
            mapping=mapping,
            project=args.project,
            instance=args.instance,
            database=args.spanner_database,
            graph_name=args.graph,
            sample_rows=args.sample_rows,
            seed=args.seed,
            default_tz=args.default_timezone,
            queries_file=queries_file,
            output_report_path=report_path,
        )

    if report.passed:
        console.print("[green]Verification PASSED:[/green] all counts, sampled rows, and Cypher<->GQL queries match.")
        return 0
    console.print("[red]Verification FAILED:[/red] mismatches detected.")
    for c in report.counts:
        if not c.passed:
            console.print(f"  Count mismatch on {c.table}: neo4j={c.neo4j_count}, spanner={c.spanner_count}")
    for s in report.samples:
        if not s.passed:
            console.print(f"  Sample mismatch on {s.table}: {s.mismatches[:3]}")
    for q in report.queries:
        if not q.passed:
            console.print(f"  Query mismatch {q.name}: error={q.error} diff={q.diff_sample}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neo4j-spanner-export")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    # discover
    p_disc = sub.add_parser("discover", help="Discover Neo4j schema and generate schema_mapping.yaml")
    p_disc.add_argument("--uri", required=True)
    p_disc.add_argument("--user", default="neo4j")
    p_disc.add_argument("--password", default=None)
    p_disc.add_argument("--database", default="neo4j")
    p_disc.add_argument("--output-mapping", required=True)
    p_disc.add_argument("--input-mapping", default=None)
    p_disc.add_argument("--label-priority", default=None, help="Comma-separated label priority list")
    p_disc.add_argument("--sample-size", type=int, default=None, help="Sample size for dry runs only")
    p_disc.add_argument("--report", default=None, help="Path for discovery_report.md")
    p_disc.set_defaults(func=_cmd_discover)

    # export
    p_exp = sub.add_parser("export", help="Export Neo4j graph to sharded CSVs + Spanner artifacts")
    p_exp.add_argument("--uri", required=True)
    p_exp.add_argument("--user", default="neo4j")
    p_exp.add_argument("--password", default=None)
    p_exp.add_argument("--database", default="neo4j")
    p_exp.add_argument("--mapping", required=True)
    p_exp.add_argument("--output-dir", required=True)
    p_exp.add_argument("--gcs-prefix", required=True)
    p_exp.add_argument("--delimiter", default=",")
    p_exp.add_argument("--null-string", default="__NULL__")
    p_exp.add_argument("--quote-char", default='"')
    p_exp.add_argument("--escape-char", default="\\")
    p_exp.add_argument("--default-timezone", default="UTC")
    p_exp.add_argument("--chunk-rows", type=int, default=500_000)
    p_exp.add_argument("--workers", type=int, default=4)
    p_exp.add_argument("--graph-name", default="MigratedGraph")
    p_exp.add_argument("--emit-unescape", action="store_true")
    p_exp.add_argument("--overwrite", action="store_true", help="Overwrite existing export artifacts in --output-dir")
    p_exp.set_defaults(func=_cmd_export)

    # verify
    p_ver = sub.add_parser("verify", help="Verify migrated Cloud Spanner database against Neo4j")
    p_ver.add_argument("--uri", required=True)
    p_ver.add_argument("--user", default="neo4j")
    p_ver.add_argument("--password", default=None)
    p_ver.add_argument("--neo4j-database", dest="database", default="neo4j")
    p_ver.add_argument("--mapping", required=True)
    p_ver.add_argument("--project", required=True)
    p_ver.add_argument("--instance", required=True)
    p_ver.add_argument("--database", dest="spanner_database", required=True)
    p_ver.add_argument("--graph", default="MigratedGraph")
    p_ver.add_argument("--sample-rows", type=int, default=10_000)
    p_ver.add_argument("--seed", type=int, default=42)
    p_ver.add_argument("--default-timezone", default="UTC")
    p_ver.add_argument("--queries-file", default=None)
    p_ver.add_argument("--output-report", default=None)
    p_ver.set_defaults(func=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except (
        ConfigError,
        DiscoveryError,
        NamingError,
        SerializerConfigError,
        SentinelCollisionError,
        DriverError,
        Neo4jError,
        ZoneInfoNotFoundError,
        yaml.YAMLError,
        ValueError,
        FileExistsError,
        FileNotFoundError,
        OSError,
    ) as exc:
        if args.verbose:
            raise
        err_console.print(f"[red]Error:[/red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
