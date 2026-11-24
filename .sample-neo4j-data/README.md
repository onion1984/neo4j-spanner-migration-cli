# Knowledge graph CSV export: synthetic sample

**All values in these files are synthetic (fake).** File names and column headers
are the real ones from our graph export, so you can see the exact structure. Every
row is invented for illustration. Row counts are **not** representative: each file
has 5 example rows.

## Layout

The graph is exported as **nodes** and **relationships**, one CSV file per kind:

- `kg.nodes.<Label>.csv`: one row per node. When a node has several labels, they
  are joined with `.` in the file name (e.g. `kg.nodes.Component.BE.csv`) and with
  `;` in the `:LABEL` column.
- `kg.relationships.<TYPE>.csv`: one row per relationship (edge) of that type.

## Special columns

| Column | Meaning |
|---|---|
| `:ID` | Node identifier, unique across all node files in this sample |
| `:LABEL` | Node label(s), `;`-separated |
| `:START_ID` / `:END_ID` | The `:ID` of the relationship's source / target node |
| `:TYPE` | Relationship type |

Join a relationship to its nodes with `:START_ID` → `:ID` and `:END_ID` → `:ID`.
In this sample those joins resolve to the synthetic nodes.

## Column types

A suffix on the column name gives its type: `:long` (integer), `:double` (decimal),
`:boolean` (`true`/`false`), `:datetime` (ISO-8601). Columns without a suffix are
text. Text columns that start with `[` or `{` hold JSON (lists or objects). Empty
cells mean the property is not set on that node or relationship.

## Format

UTF-8, comma-separated, every field double-quoted. Text fields may contain line
breaks inside quotes, so use a real CSV parser (pandas, DuckDB, Excel's import),
not a line count. The format follows the `neo4j-admin database import` CSV
header convention.

## Which node labels each relationship type connects

| Relationship | From | To |
|---|---|---|
| `ACCESSES` | `Component.BE` | `PhysicalDataModel` |
| `ACCESSES` | `IntegrationService` | `PhysicalDataModel` |
| `ACCESSES` | `Application` | `E2EDataObject` |
| `ALIAS_OF` | `IntegrationServiceGlue` | `IntegrationService` |
| `ALIAS_OF` | `IntegrationService` | `IntegrationService` |
| `ALSO_IN_COMPONENT` | `Class` | `Component.FE` |
| `ALSO_IN_COMPONENT` | `Class.SerializableDataModel` | `Component.SharedModule` |
| `ALSO_IN_COMPONENT` | `Class` | `Component.SharedModule` |
| `BELONGS_TO_APP` | `Server` | `Application` |
| `BELONGS_TO_APP` | `Software` | `Application` |
| `BELONGS_TO_APP` | `DatabaseInstance` | `Application` |
| `CALLS` | `Component` | `Component` |
| `CALLS` | `Application` | `IntegrationService` |
| `CALLS` | `Application` | `IntegrationServiceGlue` |
| `CHILD_OF` | `BusinessMainFunction` | `BusinessMainFunction` |
| `CHILD_OF` | `BusinessScenario` | `BusinessService` |
| `CHILD_OF` | `BusinessProcess` | `BusinessProcess` |
| `CHUNK_OF` | `CodeChunk` | `SourceFile` |
| `CONNECTED_TO` | `NetworkDevice` | `Server` |
| `CONNECTED_TO` | `NetworkDevice` | `NetworkDevice` |
| `CONSUMES` | `Application` | `Interaction` |
| `CONSUMES` | `Component.SharedModule` | `MessageChannel` |
| `CONSUMES` | `Component.BE` | `MessageChannel` |
| `CONTAINS_CHUNK` | `Class` | `CodeChunk` |
| `CONTAINS_CHUNK` | `Class.SerializableDataModel` | `CodeChunk` |
| `CONTAINS_CHUNK` | `Class.Enum` | `CodeChunk` |
| `CONTAINS_CLASS` | `Component.BE` | `Class` |
| `CONTAINS_CLASS` | `Component.SharedModule` | `Class` |
| `CONTAINS_CLASS` | `Component.Batch` | `Class` |
| `DECOMPOSES_INTO` | `BusinessProcess` | `BusinessProcessStep` |
| `DECOMPOSES_INTO` | `BusinessMainFunction` | `BusinessMainFunction` |
| `DECOMPOSES_INTO` | `BusinessMainFunction` | `BusinessSubFunction` |
| `DEFINES` | `Document` | `IntegrationService` |
| `DEFINES` | `Document` | `IntegrationServiceGlue` |
| `DEFINES` | `SourceFile` | `SerializableDataModel` |
| `DEFINES_CLASS` | `SourceFile` | `Class` |
| `DEFINES_CLASS` | `SourceFile` | `Class.SerializableDataModel` |
| `DEFINES_CLASS` | `SourceFile` | `Class.SerializableDataModel.Enum` |
| `DEFINES_RECORD` | `Component.FE` | `Record` |
| `DEFINES_RECORD` | `Component.SharedModule.Retired` | `Record` |
| `DEFINES_RECORD` | `Component.SharedModule` | `Record` |
| `DEFINES_ROUTINE` | `Component.FE` | `Routine` |
| `DEFINES_ROUTINE` | `Component.SharedModule.Retired` | `Routine` |
| `DEFINES_ROUTINE` | `Component.BE` | `Routine` |
| `DEPENDS_ON` | `CtmJob` | `CtmJob` |
| `DEPENDS_ON` | `Software` | `Software` |
| `DEPENDS_ON` | `Server` | `Application` |
| `DEPENDS_ON_APP` | `Application` | `Application` |
| `DESCRIBES` | `MDChunk` | `Component.SharedModule` |
| `DESCRIBES` | `MDChunk` | `Component.UNCLASSIFIED` |
| `DESCRIBES` | `MDChunk` | `BusinessMainFunction` |
| `DESCRIBES_APP` | `MDChunk` | `Application` |
| `DRIVES` | `BusinessScenario` | `BusinessService` |
| `DRIVES` | `BusinessService` | `BusinessScenario` |
| `EXECUTES` | `Application` | `BusinessProcess` |
| `EXECUTES` | `Application` | `BusinessService` |
| `EXECUTES` | `Application` | `BusinessScenario` |
| `EXPOSES` | `Application` | `Interaction` |
| `EXPOSES` | `Component.BE` | `IntegrationService` |
| `EXPOSES` | `Component.SharedModule` | `IntegrationService` |
| `FROM_FILE` | `Class` | `SourceFile` |
| `FROM_FILE` | `Class.SerializableDataModel` | `SourceFile` |
| `FROM_FILE` | `Routine` | `SourceFile` |
| `HAS_CONTROL` | `Page` | `Control` |
| `HAS_CONTROL` | `Component.FE` | `Control` |
| `HAS_ENDPOINT` | `IntegrationService` | `Endpoint` |
| `HAS_PAGE` | `Component.FE` | `Page` |
| `HAS_SUB_FUNCTION` | `BusinessMainFunction` | `BusinessMainFunction` |
| `HOSTED_ON` | `CtmHost` | `Server` |
| `IMPLEMENTED_BY` | `Page` | `Page` |
| `IMPLEMENTED_IN` | `SourceFile` | `Technology` |
| `IMPLEMENTED_IN` | `Component.BE` | `Technology` |
| `IMPLEMENTED_IN` | `Component.FE` | `Technology` |
| `IMPLEMENTS` | `Application` | `BusinessMainFunction` |
| `IMPLEMENTS` | `Component.FE` | `BusinessMainFunction` |
| `IMPLEMENTS` | `BusinessProcess` | `BusinessMainFunction` |
| `INSTALLED_ON` | `Application` | `Server` |
| `INVOKES` | `BusinessProcessStep` | `BusinessMainFunction` |
| `INVOLVES` | `BusinessProcessStep` | `Component.Batch.Retired` |
| `INVOLVES` | `BusinessProcessStep` | `Component.BE` |
| `INVOLVES` | `BusinessProcessStep` | `Component.Batch` |
| `IN_CLUSTER` | `Namespace` | `Cluster` |
| `IN_CLUSTER` | `Server` | `Cluster` |
| `IN_CLUSTER` | `Server` | `Server` |
| `IN_COMPONENT` | `CodeChunk` | `Component.SharedModule` |
| `IN_COMPONENT` | `CodeChunk` | `Component.UNCLASSIFIED` |
| `IN_COMPONENT` | `CodeChunk` | `Component.BE` |
| `IN_FOLDER` | `CtmJob` | `CtmFolder` |
| `IN_PACKAGE` | `Class` | `Package` |
| `IN_PACKAGE` | `Class.SerializableDataModel` | `Package` |
| `IN_PACKAGE` | `Class` | `Package.Retired` |
| `IN_REPO` | `SourceFile` | `Repository` |
| `IN_REPO` | `Package` | `Repository` |
| `IN_REPO` | `Component.BE` | `Repository` |
| `IS_BODY_OF` | `CodeChunk` | `Class` |
| `IS_BODY_OF` | `CodeChunk` | `Class.SerializableDataModel` |
| `IS_BODY_OF` | `CodeChunk` | `Class.Enum` |
| `MAPS_TO` | `Class.SerializableDataModel` | `LogicalDataModel` |
| `MAPS_TO` | `Class` | `LogicalDataModel` |
| `MATERIALIZES` | `SerializableDataModel` | `E2EDataObject` |
| `MATERIALIZES` | `SerializableDataModel` | `PhysicalDataModel` |
| `MATERIALIZES` | `LogicalDataModel` | `PhysicalDataModel` |
| `NAVIGATES_TO` | `Page` | `Page` |
| `NEXT` | `BusinessProcessStep` | `BusinessProcessStep` |
| `NEXT` | `BusinessSubFunction` | `BusinessSubFunction` |
| `OPERATES_IN` | `Application` | `BusinessService` |
| `OPERATES_IN` | `BusinessProcess` | `BusinessService` |
| `OPERATES_IN` | `Application` | `BusinessScenario` |
| `OWNS_FILE` | `Component.BE` | `SourceFile` |
| `OWNS_FILE` | `Component.FE` | `SourceFile` |
| `OWNS_FILE` | `Component.SharedModule` | `SourceFile` |
| `PASSES` | `IntegrationService` | `LogicalDataModel` |
| `PRODUCES` | `Component.BE` | `MessageChannel` |
| `PRODUCES` | `Component.SharedModule` | `MessageChannel` |
| `READS_FROM` | `Component.Batch.Retired` | `ExternalSystem` |
| `REFERENCES` | `PhysicalDataModel` | `PhysicalDataModel` |
| `REFERENCES` | `Document` | `Document` |
| `RELATES` | `Interaction` | `BusinessMainFunction` |
| `RELATES_TO_SYSTEM` | `ExternalSystem` | `ExternalSystem` |
| `RUNS_ON` | `Software` | `WebService` |
| `RUNS_ON` | `Server` | `LBService` |
| `RUNS_ON` | `Server` | `Software` |
| `RUNS_ON_HOST` | `CtmJob` | `CtmHost` |
| `SCHEDULED_FOR` | `CtmJob` | `Application` |
| `TRANSFERS` | `Interaction` | `DataObject` |
| `TRANSFERS` | `Interaction` | `E2EDataObject` |
| `TRIGGERS` | `BusinessScenario` | `BusinessProcess` |
| `TRIGGERS` | `BusinessService` | `BusinessProcess` |
| `USES` | `Component.FE` | `SerializableDataModel` |
| `USES` | `Component.BE` | `LogicalDataModel` |
| `USES` | `Component.Batch` | `LogicalDataModel` |
| `USES_CALENDAR` | `CtmJob` | `CtmCalendar` |
| `USES_DATASTORE` | `Server` | `StorageDevice` |
| `USES_LIBRARY` | `Component.BE` | `Library` |
| `USES_LIBRARY` | `Component.FE` | `Library` |
| `USES_LIBRARY` | `Component.SharedModule` | `Library` |
| `USES_SERVICE` | `Person` | `BE` |
| `USES_TECHNOLOGY` | `Application` | `Technology` |
| `USES_TECHNOLOGY` | `Repository` | `Technology` |
| `USES_TECHNOLOGY` | `ExternalSystem` | `Technology` |
| `VIRTUALIZED_BY` | `Server` | `Server` |
| `WRITES_TO` | `Component.Batch.Retired` | `PhysicalDataModel` |
