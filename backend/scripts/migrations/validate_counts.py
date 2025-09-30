from __future__ import annotations

from typing import Annotated

import structlog
import typer
from sqlalchemy import text

from .common import build_engine, engine_scope, info

app = typer.Typer(add_completion=False)
log = structlog.get_logger(__name__)


@app.command()
def main(
    legacy_dsn: Annotated[str, typer.Option(...)],
    postgres_dsn: Annotated[str, typer.Option(...)],
    echo_sql: Annotated[bool, typer.Option()] = False,
) -> None:
    """Compare row counts for key tables between the legacy database and Postgres.

    This is a minimal validator to be expanded with domain-specific checks.
    """

    tables = [
        "users",
        "user_identities",
        "stores",
        "products",
        "tags",
        "product_urls",
        "price_history",
    ]

    src = build_engine(legacy_dsn, echo=echo_sql)
    dst = build_engine(postgres_dsn, echo=echo_sql)

    with engine_scope(src) as src_eng, engine_scope(dst) as dst_eng:
        with src_eng.connect() as sconn, dst_eng.connect() as dconn:
            mismatches: list[tuple[str, int, int]] = []
            for table in tables:
                src_count = sconn.execute(
                    text(f"SELECT COUNT(*) FROM {table}")
                ).scalar_one()
                dst_count = dconn.execute(
                    text(f"SELECT COUNT(*) FROM {table}")
                ).scalar_one()
                info(
                    "etl.validate_counts.rowcount",
                    table=table,
                    legacy=int(src_count),
                    postgres=int(dst_count),
                )
                if int(src_count) != int(dst_count):
                    mismatches.append((table, int(src_count), int(dst_count)))

    if mismatches:
        raise typer.Exit(code=1)

    info("etl.validate_counts.ok")


if __name__ == "__main__":
    typer.run(main)
