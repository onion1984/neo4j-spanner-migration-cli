"""Seed the synthetic Neo4j 4.4 / 5.x test graph for integration and E2E verification."""

from __future__ import annotations

import argparse
import datetime
import os

from neo4j import GraphDatabase
from neo4j.spatial import CartesianPoint
from neo4j.time import Date as Neo4jDate
from neo4j.time import Duration as Neo4jDuration
import pytz


def _create_uniqueness_constraint(session, label: str, prop: str, is_v4: bool) -> None:
    cname = f"uniq_{label}_{prop}".replace(" ", "_").replace("-", "_")
    if is_v4:
        session.run(
            f"CREATE CONSTRAINT {cname} IF NOT EXISTS ON (n:`{label}`) ASSERT n.`{prop}` IS UNIQUE"
        )
    else:
        session.run(
            f"CREATE CONSTRAINT {cname} IF NOT EXISTS FOR (n:`{label}`) REQUIRE n.`{prop}` IS UNIQUE"
        )


def seed_graph(uri: str, user: str, password: str, database: str, include_ambiguous: bool = False) -> None:
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        with driver.session(database=database) as session:
            rec = session.run(
                "CALL dbms.components() YIELD name, versions WHERE name = 'Neo4j Kernel' RETURN versions[0] AS v"
            ).single()
            is_v4 = str(rec["v"]).startswith("4.")

            # Wipe existing data
            session.run("MATCH (n) DETACH DELETE n")

            # Uniqueness constraints
            _create_uniqueness_constraint(session, "Product", "sku", is_v4)
            _create_uniqueness_constraint(session, "Service", "service_code", is_v4)
            _create_uniqueness_constraint(session, "Category", "category_id", is_v4)
            _create_uniqueness_constraint(session, "Account", "account_id", is_v4)
            _create_uniqueness_constraint(session, "VIP - Customer", "cust_id", is_v4)

            long_label = "VeryLongEntityLabelName_" + ("X" * 95)
            _create_uniqueness_constraint(session, long_label, "item_id", is_v4)

            # Categories (self-referential PART_OF)
            session.run(
                """
                CREATE (c1:Category {category_id: 'CAT-ROOT', name: 'Root', created_date: $d1})
                CREATE (c2:Category {category_id: 'CAT-ELEC', name: 'Electronics & Gadgets | Tech', created_date: $d2})
                CREATE (c3:Category {category_id: 'CAT-CLOUD', name: 'Cloud Services', created_date: $d2})
                CREATE (c2)-[:PART_OF {depth: 1}]->(c1)
                CREATE (c3)-[:PART_OF {depth: 1}]->(c1)
                """,
                d1=Neo4jDate(2025, 1, 1),
                d2=Neo4jDate(2025, 6, 15),
            )

            # Products (including :Product:Promoted, type conflicts on price/rating, adversarial values)
            ny_dt = pytz.timezone("America/New_York").localize(datetime.datetime(2026, 3, 15, 14, 30, 0))
            local_dt = datetime.datetime(2026, 3, 15, 14, 30, 0)
            session.run(
                """
                MATCH (elec:Category {category_id: 'CAT-ELEC'})
                CREATE (p1:Product:Promoted {
                    sku: 'SKU-001',
                    title: 'Widget "Pro" | Edition\\v2\nLine2\r\nLine3 🚀 café 日本語',
                    subtitle: '',
                    price: 100,
                    rating: 5,
                    tags: ['featured', 'sale', 'pipe|tag'],
                    scores: [10, 20, 30],
                    flags: [true, false],
                    mixed_meta: [1, 2],
                    location: $pt,
                    payload: $raw_bytes,
                    updated_at: $zoned_dt,
                    local_ts: $local_dt,
                    warranty: $dur,
                    `order`: 1
                })
                CREATE (p2:Product {
                    sku: 'SKU-002',
                    title: 'Standard Cable',
                    subtitle: null,
                    price: 19.95,
                    rating: '4.5-stars',
                    tags: ['cable'],
                    scores: [5],
                    flags: [false],
                    mixed_meta: ['only_str'],
                    location: $pt,
                    payload: $raw_bytes2,
                    updated_at: $zoned_dt,
                    local_ts: $local_dt,
                    warranty: $dur,
                    `order`: 2
                })
                CREATE (p1)-[:PART_OF {aisle: 'A1', featured: true}]->(elec)
                CREATE (p2)-[:PART_OF {aisle: 'A2', featured: false}]->(elec)
                """,
                pt=CartesianPoint((12.5, 45.25)),
                raw_bytes=b"\x00\x01\x02hello\xff",
                raw_bytes2=b"abc",
                zoned_dt=ny_dt,
                local_dt=local_dt,
                dur=Neo4jDuration(days=365, seconds=60),
            )

            # Services
            session.run(
                """
                MATCH (cloud:Category {category_id: 'CAT-CLOUD'})
                CREATE (s1:Service {service_code: 'SVC-SUPPORT', title: '24/7 Support'})
                CREATE (s1)-[:PART_OF {sla_tier: 'gold', billable: true}]->(cloud)
                """
            )

            # Accounts + parallel TRANSFERRED edges + composite Orders + AuditNote (no constraint)
            session.run(
                """
                MATCH (p1:Product {sku: 'SKU-001'}), (p2:Product {sku: 'SKU-002'})
                CREATE (a1:Account {account_id: 'ACC-1', owner: 'Alice'})
                CREATE (a2:Account {account_id: 'ACC-2', owner: 'Bob'})
                CREATE (a1)-[:TRANSFERRED {amount: 50.0, currency: 'USD', tx_ts: $t1}]->(a2)
                CREATE (a1)-[:TRANSFERRED {amount: 75.5, currency: 'USD', tx_ts: $t2}]->(a2)
                CREATE (o1:Order {tenant_id: 'T1', order_id: 'ORD-100', status: 'PAID'})
                CREATE (o2:Order {tenant_id: 'T2', order_id: 'ORD-100', status: 'PENDING'})
                CREATE (a1)-[:PLACED]->(o1)
                CREATE (a2)-[:PLACED]->(o2)
                CREATE (o1)-[:CONTAINS {qty: 2, unit_price: 100.0}]->(p1)
                CREATE (o2)-[:CONTAINS {qty: 1, unit_price: 19.95}]->(p2)
                CREATE (n1:AuditNote {note: 'Checked order\\ok\nsecond line', severity: 'INFO'})
                CREATE (n1)-[:ATTACHED_TO]->(o1)
                """,
                t1=ny_dt,
                t2=ny_dt + datetime.timedelta(hours=1),
            )

            # Naming edge cases: label with space + hyphen, over-long triplet name
            session.run(
                f"""
                CREATE (vc:`VIP - Customer` {{cust_id: 'VC-1', name: 'VIP One'}})
                CREATE (ll:`{long_label}` {{item_id: 'LL-1', val: 42}})
                CREATE (vc)-[:LONG_RELATIONSHIP_TYPE_NAME_FOR_TESTING_TRUNCATION]->(ll)
                """
            )

            if include_ambiguous:
                session.run("CREATE (:AmbigA:AmbigB {x: 1})")

    print(f"Seeded synthetic graph on {uri} (database={database}, include_ambiguous={include_ambiguous})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default="bolt://localhost:7687")
    parser.add_argument("--user", default="neo4j")
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", "testpassword"))
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--include-ambiguous", action="store_true")
    args = parser.parse_args()
    seed_graph(args.uri, args.user, args.password, args.database, args.include_ambiguous)


if __name__ == "__main__":
    main()
