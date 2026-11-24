# Neo4j to Spanner Graph Migration CLI

Offline migration tool to discover, export, and verify **Neo4j (4.4 LTS & 5.x)** graphs into **Google Cloud Spanner (Spanner Graph)** using sharded CSVs, Dataflow (`GCS_Text_to_Cloud_Spanner`), staged DDL/PDML, and `CREATE PROPERTY GRAPH`.

---

## Recommended Offline Migration Methodology

Because Neo4j is schema-optional and polymorphic while Spanner Graph is strongly typed and table-backed, the recommended offline migration follows a **5-stage deterministic pipeline**:

1. **Quiesce or Snapshot Neo4j (Pre-flight)**
   - Stop application writes against Neo4j or run against a read-only clone / point-in-time backup so node/edge counts and sampled rows remain consistent between `discover`, `export`, and `verify`.
   - Ensure GCP prerequisites are ready: a target Cloud Spanner instance, a GCS bucket for staging CSVs and manifests, and Dataflow/Spanner IAM permissions.

2. **Stage 1 — Schema Discovery & Human Review (`discover`)**
   - Run a **full scan** (omit `--sample-size`) on the quiesced Neo4j database to infer every label, relationship triplet `(src_canonical, rel_type, dst_canonical)`, primary key, property type, and parallel-edge flag.
   - Review `discovery_report.md` and `schema_mapping.yaml` before exporting:
     - Resolve any ambiguous multi-label nodes via `label_priority`.
     - Add `pk_overrides` for composite keys on Neo4j Community Edition (or override synthetic `_neo4j_id` PKs where a natural key exists).
     - Add `table_renames` / `column_renames` for GoogleSQL reserved words or identifier collisions.
     - Inspect any type-widening warnings or `STRING(MAX)` conflicts and set explicit property `override`s if needed.
   - Re-run `discover --input-mapping schema_mapping.yaml` after editing overrides to validate and refresh `discovery_report.md`.

3. **Stage 2 — Sharded CSV Export & Staged Artifact Generation (`export`)**
   - Export nodes and edge triplets into headerless, UTF-8, sharded CSV files (`--chunk-rows`, `--workers`) alongside Dataflow manifests, staged Spanner DDL/PDML scripts (`01` through `05`), and `load_runbook.sh`.
   - The tool fails fast if any literal value collides with `--null-string`, if non-UTC naive datetimes have no `--default-timezone`, or if graph `LABEL` / property aliases conflict across tables.

4. **Stage 3 — Staged Cloud Spanner Load (`load_runbook.sh`)**
   - **01 (`01_create_tables.sql`):** Create the database with node tables, interleaved edge tables (`INTERLEAVE IN PARENT ... ON DELETE CASCADE`), and `__json` staging columns for `ARRAY<T>` properties (created without destination FKs or secondary indexes for faster bulk load).
   - **Upload & Dataflow:** Upload CSV shards and manifests to GCS, run the **Nodes** Dataflow job first, verify `invalid_records/nodes` is empty, then run the **Edges** Dataflow job and verify `invalid_records/edges` is empty.
   - **02 (`02_arrays_*.sql`, `02d_empty_bytes.sql`):** Add native `ARRAY<T>` columns, backfill from `__json` via Partitioned DML (PDML), drop `__json` staging columns, and restore empty `BYTES` values (`""` -> `b""`).
   - **03 (`03_unescape.sql`, optional):** Only needed if `--emit-unescape` was passed.
   - **04 (`04_constraints_indexes.sql`):** Apply destination `FOREIGN KEY` constraints and reverse-traversal indexes after bulk data is loaded.
   - **05 (`05_property_graph.sql`):** Create the Spanner Property Graph (`CREATE OR REPLACE PROPERTY GRAPH`).

5. **Stage 4 — Automated Parity Verification (`verify`)**
   - Compare exact node and edge counts per table, randomly sample rows (`--sample-rows`, `--seed`) across Spanner and Neo4j to verify every property value and `secondary_labels`, and execute paired Cypher ↔ GQL equivalence queries (`--queries-file`).

6. **Stage 5 — Query Adaptation & Cutover**
   - Adapt application Cypher queries to Spanner Graph GQL (including rewriting secondary-label filters to `UNNEST(n.secondary_labels)`), point applications to Cloud Spanner, and decommission the Neo4j staging environment.

---

## How the CLI Works

`neo4j-spanner-export` separates migration into **three decoupled, resumable subcommands** connected by a declarative `schema_mapping.yaml` contract:

```text
Neo4j (4.4 / 5.x)
   │
   ├─► 1. discover ──► schema_mapping.yaml + discovery_report.md
   │                        ▲ (edit & re-run discover to validate)
   │
   ├─► 2. export   ──► export_out/ (nodes/*.csv, edges/*.csv, manifests/*.json,
   │                                schema/01..05*.sql, load_runbook.sh)
   │                        │
   │                        ▼
   │                   load_runbook.sh (gcloud + Dataflow GCS_Text_to_Cloud_Spanner)
   │                        │
   │                        ▼
   └─► 3. verify   ◄── Cloud Spanner (counts, sampled rows, Cypher ↔ GQL queries)
```

1. **`discover` (Read-only Neo4j probe):** Connects to Neo4j over Bolt, inspects version/edition and constraints, scans node label-sets and edge triplets, infers Spanner column types, and writes `schema_mapping.yaml` and `discovery_report.md`. Manual adjustments (`label_priority`, `pk_overrides`, `table_renames`, `column_renames`, property `override`s) live in `schema_mapping.yaml` and are re-validated whenever you re-run `discover`.
2. **`export` (Local extraction & artifact generation):** Reads the validated `schema_mapping.yaml` (without re-inferring schema), streams Neo4j nodes and edge triplets in parallel workers into sharded headerless CSVs (`nodes/`, `edges/`), and emits Dataflow import manifests (`manifests/`), staged Spanner DDL/PDML scripts (`schema/01`–`05`), and `load_runbook.sh`. It does **not** touch GCP directly.
3. **`load_runbook.sh` (GCP execution):** Runs outside the Python CLI using `gcloud` to create the Spanner database (`01_create_tables.sql`), upload CSVs/manifests to GCS, launch and monitor the Dataflow `GCS_Text_to_Cloud_Spanner` jobs (nodes first, then edges), convert staged `__json` arrays to `ARRAY<T>` and restore empty `BYTES` (`02_*`), apply destination FKs/indexes (`04_*`), and create the Spanner Property Graph (`05_property_graph.sql`).
4. **`verify` (Dual-database parity check):** Connects to both Neo4j and Cloud Spanner to verify exact table/triplet row counts, randomly sampled row properties and `secondary_labels`, and paired Cypher ↔ GQL equivalence queries.

---

## Key Features

- **Cross-version Neo4j support (4.4 LTS & 5.x):** Probes `dbms.components()`, normalizes `SHOW CONSTRAINTS` (`UNIQUENESS`, `NODE_PROPERTY_UNIQUENESS`, `NODE_KEY`), and uses compatible Cypher dialects (`elementId()` vs `id()`).
- **Canonical label & PK resolution:**
  - Multi-label nodes map to one canonical table (`label_priority` → constraint-bearing label → single label → fail-fast on ambiguity) with extra labels preserved in `secondary_labels` (`ARRAY<STRING(MAX)>`).
  - Primary keys resolve via `yaml_override` → `NODE_KEY` → non-null `UNIQUENESS` → bit-reversed `_neo4j_id` (`INT64`, prevents hotspotting).
- **Interleaved edge triplets & parallel edges:**
  - Maps `(src_canonical, rel_type, dst_canonical)` triplets to edge tables `INTERLEAVE IN PARENT <SrcTable> ON DELETE CASCADE`.
  - Automatically adds `edge_id INT64` only for triplets with parallel edges (`count(r) > 1` between the same `(src, dst)` pair).
- **Deterministic type widening & array staging:**
  - Full-scan type inference with deterministic widening (`INT64 + FLOAT64 → FLOAT64`, conflicts → `STRING(MAX)`, etc.) recorded in `schema_mapping.yaml`.
  - Homogeneous scalar lists stage as `<col>__json JSON` and are converted post-load to native `ARRAY<T>` via Partitioned DML.
- **GoogleSQL-safe naming & original-name preservation:**
  - Sanitizes identifiers to `[A-Za-z][A-Za-z0-9_]*` (≤ 128 chars, deterministic `_<8-hex>` hash suffix on truncation) and fails fast on case-insensitive collisions or GoogleSQL reserved words.
  - Preserves original Neo4j label, relationship type, and property names in `CREATE PROPERTY GRAPH` via backtick-quoted `LABEL` and `PROPERTIES (... AS ...)`.
- **Lossless CSV serialization:**
  - Distinguishes `NULL` (`--null-string`, default `__NULL__`) from empty string `""` and fails fast if any literal value equals the null sentinel.
  - Escapes `\`, LF (`\n`), CR (`\r`), and quotes cleanly. Verified end-to-end with Dataflow `GCS_Text_to_Cloud_Spanner` (`escape=\`): the template decodes `\n`, `\r`, and `\\` natively on load, so `03_unescape.sql` is only needed as an opt-in fallback (`--emit-unescape`).

---

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Set `NEO4J_PASSWORD` in your environment before running commands (or pass `--password`):

```bash
export NEO4J_PASSWORD="your-neo4j-password"
```

---

## Stage-by-Stage CLI Usage

### Stage 1: Discover Schema (`discover`)

Run a full scan of the quiesced Neo4j database to generate `schema_mapping.yaml` and `discovery_report.md`:

```bash
neo4j-spanner-export discover \
  --uri bolt://localhost:7687 \
  --user neo4j \
  --database neo4j \
  --output-mapping schema_mapping.yaml \
  --report discovery_report.md
```

- Use `--sample-size N` only for fast dry-run previews; always run a full scan (omit `--sample-size`) before production export so no rare property types or parallel edges are missed.
- Use `--label-priority LabelA,LabelB` to resolve multi-label nodes from the CLI, or edit `schema_mapping.yaml` directly (`label_priority`, `pk_overrides`, `table_renames`, `column_renames`, property `override`s).

> [!IMPORTANT]
> **Always re-run `discover` after editing `schema_mapping.yaml`** to validate your overrides/renames (such as `pk_overrides`, `label_priority`, `table_renames`, `column_renames`, and property `override`s) and refresh `discovery_report.md` before proceeding to `export`. If `--output-mapping` already exists, `discover` automatically reuses it as `--input-mapping` (or pass `--input-mapping schema_mapping.yaml` explicitly).

#### Sample `schema_mapping.yaml` (with inline explanations)

```yaml
version: 1
neo4j_version: "5.23.0"
neo4j_edition: "community"

# Canonical label tie-breaker for multi-label nodes (e.g. :Person:Employee -> Person)
label_priority:
  - Person
  - Company

# Rename Neo4j labels or edge triplets to safe Spanner table names (e.g. GoogleSQL reserved words).
# Note: 05_property_graph.sql still preserves the original Neo4j name as the Graph LABEL.
table_renames:
  Order: Orders
  Person__WORKS_AT__Company: PersonWorksAtCompany

# Force natural/composite primary keys when Neo4j lacks NODE_KEY (e.g. Community Edition).
pk_overrides:
  Order:
    - tenant_id
    - order_id

# Align graph-wide property types across all node and edge tables (case-insensitive).
# Per-table `override` still takes precedence over `property_type_overrides`.
property_type_overrides:
  updatedAt: STRING(MAX)

nodes:
  Person:
    raw_label: Person
    spanner_table: Person
    pk_columns: [pid]
    pk_source: uniqueness_constraint   # yaml_override | node_key | uniqueness_constraint | neo4j_id_fallback
    is_synthetic_pk: false             # true when using bit-reversed _neo4j_id
    monotonic_pk_warning: false        # true if sequential numeric PK may hotspot Spanner splits
    row_count: 1000
    has_secondary_labels: true         # true when nodes carry extra labels (e.g. :Person:Employee)
    secondary_labels_column: secondary_labels
    label_sets:
      - [Person]
      - [Person, Employee]
    excluded_labels: []                # Higher-priority labels excluded when scanning this table
    column_renames:                    # Optional per-table property -> Spanner column / Graph alias renames
      group: user_group
    properties:
      pid:
        raw_name: pid
        spanner_column: pid
        observed: { STRING: 1000 }
        null_count: 0
        resolved: STRING(MAX)
        override: null                 # Set to a valid Spanner type (e.g. STRING(MAX)) to override `resolved`
        is_conflict: false
      age:
        raw_name: age
        spanner_column: age
        observed: { INT64: 990, FLOAT64: 10 }
        null_count: 0
        resolved: FLOAT64              # Widened automatically from INT64 + FLOAT64
        override: null
        is_conflict: true

edges:
  Person__WORKS_AT__Company:
    triplet_key: Person__WORKS_AT__Company
    src_label: Person
    rel_type: WORKS_AT
    dst_label: Company
    spanner_table: PersonWorksAtCompany
    src_table: Person
    dst_table: Company
    has_parallel_edges: false          # true adds edge_id INT64 to support multiple edges between same (src, dst)
    edge_id_column: null
    row_count: 850
    column_renames: {}
    properties:
      since:
        raw_name: since
        spanner_column: since
        observed: { INT64: 850 }
        null_count: 0
        resolved: INT64
        override: null
        is_conflict: false
```

### Stage 2: Export CSVs & Spanner Artifacts (`export`)

```bash
neo4j-spanner-export export \
  --uri bolt://localhost:7687 \
  --user neo4j \
  --database neo4j \
  --mapping schema_mapping.yaml \
  --output-dir ./export_out \
  --gcs-prefix gs://YOUR_BUCKET/run-01 \
  --delimiter '|' \
  --null-string '__NULL__' \
  --chunk-rows 500000 \
  --workers 4 \
  --graph-name MigratedGraph
```

Use `--overwrite` if writing into an existing non-empty `--output-dir`.

- **About `--emit-unescape` (opt-in fallback, default `false`):** During export, `\` (`\\`), LF (`\n`), and CR (`\r`) are escaped so every CSV row stays on a single physical line. Dataflow's `GCS_Text_to_Cloud_Spanner` template (invoked with `escape=\`) decodes those sequences natively on load. Only pass `--emit-unescape` if you use an alternate loader that leaves literal `\n`, `\r`, or `\\` sequences in Spanner and need `schema/03_unescape.sql` (Partitioned DML `UPDATE` on non-PK `STRING(MAX)` columns) to decode them post-load.

> [!CAUTION]
> **Do not enable `--emit-unescape` with the standard `GCS_Text_to_Cloud_Spanner` (`escape=\`) Dataflow load:** because Dataflow already unescapes once on load, running `03_unescape.sql` afterward will **double-unescape** strings that legitimately contained literal `\n`, `\r`, or `\\`.

This generates `./export_out/`:

```text
export_out/
├── nodes/                      # Sharded headerless UTF-8 CSVs per node table
├── edges/                      # Sharded headerless UTF-8 CSVs per edge triplet
├── manifests/
│   ├── nodes_manifest.json     # Dataflow GCS_Text_to_Cloud_Spanner manifest
│   └── edges_manifest.json
├── schema/
│   ├── 01_create_tables.sql    # Node + interleaved edge tables (arrays staged as __json)
│   ├── 02_arrays_add.sql       # ALTER TABLE ADD COLUMN ... ARRAY<T>
│   ├── 02_arrays_backfill.sql  # PDML backfill from __json
│   ├── 02_arrays_drop.sql      # Drop __json staging columns
│   ├── 02d_empty_bytes.sql     # PDML restore for empty BYTES values
│   ├── 03_unescape.sql         # (Optional, with --emit-unescape) PDML unescape
│   ├── 04_constraints_indexes.sql  # Destination FKs + reverse-traversal indexes
│   └── 05_property_graph.sql   # CREATE OR REPLACE PROPERTY GRAPH
└── load_runbook.sh             # Ordered gcloud / Dataflow execution script
```

### Stage 3: Load into Cloud Spanner (`load_runbook.sh`)

Review and run the generated `load_runbook.sh`:

```bash
PROJECT_ID=my-gcp-project \
INSTANCE=my-spanner-instance \
DATABASE=neo4j_graph \
REGION=us-central1 \
GCS_PREFIX=gs://YOUR_BUCKET/run-01 \
./export_out/load_runbook.sh
```

If Dataflow workers must run in a specific region, subnetwork, or without public IPs (for example, when there is no `default` VPC network or an org policy blocks external IPs), set:

```bash
DATAFLOW_REGION=asia-southeast1 \
DATAFLOW_SUBNETWORK=regions/asia-southeast1/subnetworks/my-subnet \
DATAFLOW_DISABLE_PUBLIC_IPS=true \
...
```

### Stage 4: Verify Migration (`verify`)

```bash
neo4j-spanner-export verify \
  --uri bolt://localhost:7687 \
  --user neo4j \
  --neo4j-database neo4j \
  --mapping schema_mapping.yaml \
  --project my-gcp-project \
  --instance my-spanner-instance \
  --database neo4j_graph \
  --graph MigratedGraph \
  --sample-rows 10000 \
  --seed 42 \
  --output-report verify_report.json
```

Pass `--queries-file custom_queries.yaml` to run extra paired `{name, cypher, gql}` equivalence checks.

### Stage 5: Querying Secondary Labels in Spanner Graph (GQL)

Spanner `CREATE PROPERTY GRAPH` binds `LABEL`s at the `NODE TABLE` level rather than per row. When a Neo4j node has multiple labels (for example `:Person:Employee`), it is stored in its canonical node table (`Person`) with extra labels recorded in `secondary_labels` (`ARRAY<STRING(MAX)>`).

Because `Employee` is a property value rather than a GQL `LABEL`, `MATCH (n:Employee)` will fail in Spanner Graph with `Failed to find element label [Employee]`. Rewrite queries on secondary labels to filter via `UNNEST`:

```sql
GRAPH MigratedGraph
MATCH (n:Person)
WHERE 'Employee' IN UNNEST(n.secondary_labels)
RETURN n
```

(Or across all node tables if the canonical table is not known ahead of time: `MATCH (n) WHERE 'Employee' IN UNNEST(n.secondary_labels) RETURN n`.)

---

## Testing

### Unit Tests

```bash
.venv/bin/pytest tests/test_core.py tests/test_remediation.py tests/robustness/test_t0_static_review.py -v
```

### Integration Tests (Neo4j 4.4 & 5.x via Podman)

```bash
podman run -d --name neo4j-v5 -p 7687:7687 -e NEO4J_AUTH=neo4j/testpassword123 docker.io/library/neo4j:5
podman run -d --name neo4j-v4 -p 7688:7687 -e NEO4J_AUTH=neo4j/testpassword123 docker.io/library/neo4j:4.4

NEO4J_INTEGRATION=1 PYTHONPATH=. .venv/bin/pytest -v
```

---

## Troubleshooting Tips

- **Ambiguous multi-label node error during `discover`:**
  - *Symptom:* Discovery fails because a label combination (e.g., `:Person:Employee`) has multiple candidate labels and no tie-breaker.
  - *Fix:* Pass `--label-priority Person,Employee` to `discover` or set `label_priority` in `schema_mapping.yaml` and re-run `discover`.
- **Composite primary keys on Neo4j Community Edition:**
  - *Symptom:* `NODE_KEY` constraints are an Enterprise-only Neo4j feature, so Community Edition falls back to synthetic bit-reversed `_neo4j_id` PKs.
  - *Fix:* Define `pk_overrides` in `schema_mapping.yaml` (e.g., `Order: [tenant_id, order_id]`) and re-run `discover --input-mapping schema_mapping.yaml`.
- **Identifier collision or GoogleSQL reserved word error:**
  - *Symptom:* `NamingError` during `discover` or `export` (e.g., `Order`, `Group`, `User`, or case-insensitive duplicates).
  - *Fix:* Add entries under `table_renames` or `column_renames` in `schema_mapping.yaml`. Note that `table_renames` renames the underlying Spanner table while preserving the original Neo4j name as the `LABEL` in `05_property_graph.sql`.
- **Null sentinel collision during `export`:**
  - *Symptom:* `SentinelCollisionError` because a literal string property in Neo4j equals `--null-string` (default `__NULL__`).
  - *Fix:* Re-run `export` with an unused sentinel such as `--null-string '__SPANNER_NULL_9F2A__'`.
- **Type conflicts on primary keys or heterogeneous lists:**
  - *Symptom:* Discovery rejects mixed-type primary keys (e.g., `INT64` and `STRING` on the same PK property) or heterogeneous lists (`[1, "a"]`).
  - *Fix:* Clean/normalize the key values in Neo4j before exporting, or override non-PK properties in `schema_mapping.yaml`.
- **Dataflow worker startup failures (`default` network / external IP policy):**
  - *Symptom:* `GCS_Text_to_Cloud_Spanner` fails to launch workers when `default` VPC is absent or org policy forbids public IPs.
  - *Fix:* Set `DATAFLOW_REGION`, `DATAFLOW_SUBNETWORK`, and `DATAFLOW_DISABLE_PUBLIC_IPS=true` when invoking `load_runbook.sh`.
- **Dataflow `check_invalid_records` failure:**
  - *Symptom:* `load_runbook.sh` aborts after Dataflow completes because files were written to `invalid_records/nodes` or `invalid_records/edges`.
  - *Fix:* Inspect the rejected rows in `${GCS_PREFIX}/invalid_records/`, check for unescaped delimiters or stale CSV shards in GCS (note `load_runbook.sh` cleans `${GCS_PREFIX}/nodes/**`, `edges/**`, and `manifests/**` before uploading), fix the mapping or delimiter (`--delimiter '|'`), re-export with `--overwrite`, and re-run.
- **Resuming a partially completed `load_runbook.sh` run:**
  - *Fix:* `load_runbook.sh` supports idempotency skip flags so you do not have to re-run completed stages: `SKIP_DB_CREATE=true`, `SKIP_UPLOAD=true`, `SKIP_DATAFLOW=true`, `SKIP_STAGE_02=true`, `SKIP_STAGE_03=true`, `SKIP_STAGE_04=true`, `SKIP_STAGE_05=true`.
- **Debugging CLI failures with stack traces:**
  - *Fix:* Pass `--verbose` **before** the subcommand (`neo4j-spanner-export --verbose discover ...`) to enable `DEBUG` logging and print full Python tracebacks.

---

## Appendix: Complete CLI Reference

### Global Options

| Option | Default | Description |
|---|---|---|
| `--verbose` | `false` | Enable `DEBUG` logging and print full tracebacks on error (must appear before the subcommand). |

*(All subcommands require Neo4j credentials via `NEO4J_PASSWORD` environment variable or `--password`.)*

### `neo4j-spanner-export discover`

Discover Neo4j schema and generate `schema_mapping.yaml` and `discovery_report.md`.

| Option | Required | Default | Description |
|---|---|---|---|
| `--uri` | Yes | — | Neo4j Bolt/Neo4j URI (e.g. `bolt://localhost:7687`). |
| `--user` | No | `neo4j` | Neo4j username. |
| `--password` | No | `None` | Neo4j password (falls back to `NEO4J_PASSWORD`). |
| `--database` | No | `neo4j` | Source Neo4j database name. |
| `--output-mapping` | Yes | — | Output path for `schema_mapping.yaml`. |
| `--input-mapping` | No | `None` | Existing `schema_mapping.yaml` to preserve manual overrides (defaults to `--output-mapping` if it already exists). |
| `--label-priority` | No | `None` | Comma-separated canonical label priority order for multi-label nodes. |
| `--sample-size` | No | `None` | Max rows to scan per table for quick dry runs (omit for full scan). |
| `--report` | No | `<output-mapping dir>/discovery_report.md` | Output path for the Markdown discovery report. |

### `neo4j-spanner-export export`

Export Neo4j nodes and edge triplets to sharded CSVs, Dataflow manifests, Spanner DDL/PDML scripts, and `load_runbook.sh`.

| Option | Required | Default | Description |
|---|---|---|---|
| `--uri` | Yes | — | Neo4j Bolt/Neo4j URI. |
| `--user` | No | `neo4j` | Neo4j username. |
| `--password` | No | `None` | Neo4j password (falls back to `NEO4J_PASSWORD`). |
| `--database` | No | `neo4j` | Source Neo4j database name. |
| `--mapping` | Yes | — | Path to reviewed `schema_mapping.yaml`. |
| `--output-dir` | Yes | — | Directory to write CSV shards, `manifests/`, `schema/`, and `load_runbook.sh`. |
| `--gcs-prefix` | Yes | — | Target GCS prefix (`gs://<bucket>/<path>`) embedded in manifests and `load_runbook.sh`. |
| `--delimiter` | No | `,` | Single-character CSV field delimiter. |
| `--null-string` | No | `__NULL__` | Sentinel string representing SQL `NULL` in CSVs and Dataflow. |
| `--quote-char` | No | `"` | Single-character CSV quote character (`fieldQualifier`). |
| `--escape-char` | No | `\` | Single-character CSV escape character (`escape`). |
| `--default-timezone` | No | `UTC` | IANA timezone applied to naive Neo4j `LocalDateTime` / `LocalTime` values. |
| `--chunk-rows` | No | `500000` | Maximum rows per CSV shard (`> 0`). |
| `--workers` | No | `4` | Number of parallel export worker threads (`> 0`). |
| `--graph-name` | No | `MigratedGraph` | Spanner Property Graph name in `05_property_graph.sql`. |
| `--emit-unescape` | No | `false` | Emit and invoke `03_unescape.sql` in `load_runbook.sh` (only needed as fallback). |
| `--overwrite` | No | `false` | Overwrite existing export artifacts in `--output-dir`. |

### `neo4j-spanner-export verify`

Verify migrated Cloud Spanner counts, sampled rows, and Cypher ↔ GQL equivalence queries against Neo4j.

| Option | Required | Default | Description |
|---|---|---|---|
| `--uri` | Yes | — | Neo4j Bolt/Neo4j URI. |
| `--user` | No | `neo4j` | Neo4j username. |
| `--password` | No | `None` | Neo4j password (falls back to `NEO4J_PASSWORD`). |
| `--neo4j-database` | No | `neo4j` | Source Neo4j database name. |
| `--mapping` | Yes | — | Path to `schema_mapping.yaml`. |
| `--project` | Yes | — | GCP project ID hosting Cloud Spanner. |
| `--instance` | Yes | — | Cloud Spanner instance ID. |
| `--database` | Yes | — | Target Cloud Spanner database ID. |
| `--graph` | No | `MigratedGraph` | Spanner Property Graph name to query in GQL checks. |
| `--sample-rows` | No | `10000` | Number of rows to randomly sample and compare per table. |
| `--seed` | No | `42` | Random seed for deterministic sampling. |
| `--default-timezone` | No | `UTC` | IANA timezone matching the one used during `export`. |
| `--queries-file` | No | `None` | Path to YAML file containing extra paired `{name, cypher, gql}` checks. |
| `--output-report` | No | `None` | Optional path to write JSON verification report. |

### `load_runbook.sh` Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PROJECT_ID` | `YOUR_PROJECT_ID` | Target GCP project ID. |
| `INSTANCE` | `YOUR_SPANNER_INSTANCE` | Target Cloud Spanner instance ID. |
| `DATABASE` | `neo4j_graph` | Target Cloud Spanner database ID. |
| `REGION` | `us-central1` | Default GCP region. |
| `DATAFLOW_REGION` | `${REGION}` | Region for Dataflow template and jobs. |
| `DATAFLOW_SUBNETWORK` | `""` | Optional subnetwork URI passed as `--subnetwork=...`. |
| `DATAFLOW_DISABLE_PUBLIC_IPS` | `false` | Set `true` to pass `--disable-public-ips` to Dataflow. |
| `GCS_PREFIX` | `<--gcs-prefix>` | GCS prefix for shards, manifests, and `invalid_records/`. |
| `SKIP_DB_CREATE` | `false` | Set `true` to skip Stage 01 database creation. |
| `SKIP_UPLOAD` | `false` | Set `true` to skip uploading CSVs and manifests to GCS. |
| `SKIP_DATAFLOW` | `false` | Set `true` to skip Nodes and Edges Dataflow load jobs. |
| `SKIP_STAGE_02` | `false` | Set `true` to skip `ARRAY<T>` backfill and empty-`BYTES` PDML. |
| `SKIP_STAGE_03` | `false` | Set `true` to skip optional `03_unescape.sql` (if enabled). |
| `SKIP_STAGE_04` | `false` | Set `true` to skip destination FKs and reverse-traversal indexes. |
| `SKIP_STAGE_05` | `false` | Set `true` to skip `05_property_graph.sql`. |
