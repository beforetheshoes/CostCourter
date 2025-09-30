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
    postgres_dsn: Annotated[str, typer.Option(...)],
    echo_sql: Annotated[bool, typer.Option()] = False,
) -> None:
    """Run basic referential integrity checks against PostgreSQL."""

    engine = build_engine(postgres_dsn, echo=echo_sql)
    queries = {
        "product_urls_product_fk": "SELECT COUNT(*) FROM product_urls pu LEFT JOIN products p ON pu.product_id = p.id WHERE p.id IS NULL",
        "product_urls_store_fk": "SELECT COUNT(*) FROM product_urls pu LEFT JOIN stores s ON pu.store_id = s.id WHERE s.id IS NULL",
        "price_history_product_fk": "SELECT COUNT(*) FROM price_history ph LEFT JOIN products p ON ph.product_id = p.id WHERE p.id IS NULL",
    }

    with engine_scope(engine) as eng, eng.connect() as conn:
        violations = 0
        for name, sql in queries.items():
            count = conn.execute(text(sql)).scalar_one()
            info("etl.validate_fks.check", name=name, violations=int(count))
            violations += int(count)

    if violations:
        raise typer.Exit(code=1)

    info("etl.validate_fks.ok")


if __name__ == "__main__":
    typer.run(main)
