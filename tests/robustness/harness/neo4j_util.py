"""Neo4j container + data helpers (4.4 and 5.x Community)."""

from __future__ import annotations

import subprocess
import time
from typing import Any


def ensure_container(name: str, port: int, ver: str, password: str, heap: str = "2G") -> None:
    out = subprocess.run(
        ["podman", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Status}}"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    image = "docker.io/library/neo4j:5" if ver == "v5" else "docker.io/library/neo4j:4.4"
    heap_env = (f"NEO4J_server_memory_heap_max__size={heap}" if ver == "v5" else f"NEO4J_dbms_memory_heap_max__size={heap}")
    if not out:
        subprocess.run(
            ["podman", "run", "-d", "--name", name, "-p", f"{port}:7687",
             "-e", f"NEO4J_AUTH=neo4j/{password}", "-e", heap_env, image],
            check=True, capture_output=True,
        )
    elif not out.startswith("Up"):
        subprocess.run(["podman", "start", name], check=True, capture_output=True)


def wait_ready(driver: Any, timeout: float = 120) -> None:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            driver.verify_connectivity()
            with driver.session(database="neo4j") as s:
                s.run("RETURN 1").consume()
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2)
    raise RuntimeError(f"Neo4j not ready: {last}")


def is_v4(driver: Any) -> bool:
    with driver.session(database="neo4j") as s:
        v = s.run(
            "CALL dbms.components() YIELD name, versions WHERE name='Neo4j Kernel' RETURN versions[0] AS v"
        ).single()["v"]
    return str(v).startswith("4.")


def wipe(driver: Any) -> None:
    """Delete all data, constraints and (non-lookup) indexes."""
    with driver.session(database="neo4j") as s:
        while True:
            n = s.run(
                "MATCH (n) WITH n LIMIT 20000 DETACH DELETE n RETURN count(*) AS c"
            ).single()["c"]
            if n == 0:
                break
        for r in list(s.run("SHOW CONSTRAINTS YIELD name RETURN name")):
            s.run(f"DROP CONSTRAINT `{r['name']}`").consume()
        for r in list(s.run("SHOW INDEXES YIELD name, type RETURN name, type")):
            if str(r["type"]).upper() != "LOOKUP":
                s.run(f"DROP INDEX `{r['name']}`").consume()


def run(driver: Any, cypher: str, **params: Any) -> list[dict[str, Any]]:
    with driver.session(database="neo4j") as s:
        return [dict(r) for r in s.run(cypher, **params)]


def unique(driver: Any, label: str, prop: str) -> None:
    v4 = is_v4(driver)
    name = "u_" + "".join(c if c.isalnum() else "_" for c in f"{label}_{prop}")[:60]
    if v4:
        q = f"CREATE CONSTRAINT {name} IF NOT EXISTS ON (n:`{label}`) ASSERT n.`{prop}` IS UNIQUE"
    else:
        q = f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR (n:`{label}`) REQUIRE n.`{prop}` IS UNIQUE"
    with driver.session(database="neo4j") as s:
        s.run(q).consume()


def counts(driver: Any) -> tuple[int, int]:
    with driver.session(database="neo4j") as s:
        n = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        r = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    return int(n), int(r)
