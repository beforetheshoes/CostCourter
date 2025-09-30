from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

import structlog
import typer
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .common import build_engine, engine_scope, info

app = typer.Typer(add_completion=False)
log = structlog.get_logger(__name__)


def _fetch_rows(
    conn: Connection,
    sql: str,
    params: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result = conn.execute(text(sql), params)
    return [dict(row) for row in result.mappings().all()]


@app.command()
def main(
    legacy_dsn: Annotated[
        str,
        typer.Option(
            "postgresql+psycopg://legacy:legacy@127.0.0.1:5433/costcourter_legacy",
            help="Source legacy database DSN",
        ),
    ],
    postgres_dsn: Annotated[
        str,
        typer.Option(
            "postgresql+psycopg://costcourter:change-me@127.0.0.1:5432/costcourter",
            help="Target Postgres DSN",
        ),
    ],
    batch_size: Annotated[int, typer.Option(min=100, max=50000)] = 5000,
    echo_sql: Annotated[bool, typer.Option()] = False,
) -> None:
    """Migrate users from the legacy CostCourter database into the new users table.

    Identity providers and passkeys are not present in the legacy DB; these will be
    established post-cutover.
    """

    info("etl.load_users.start", batch_size=batch_size)
    src = build_engine(legacy_dsn, echo=echo_sql)
    dst = build_engine(postgres_dsn, echo=echo_sql)

    with engine_scope(src) as src_eng, engine_scope(dst) as dst_eng:
        with src_eng.begin() as sconn, dst_eng.begin() as dconn:
            count_val = sconn.execute(text("SELECT COUNT(*) FROM users")).scalar()
            total = int(count_val or 0)
            offset = 0
            migrated = 0
            while offset < total:
                rows = _fetch_rows(
                    sconn,
                    "SELECT id, name, email FROM users ORDER BY id LIMIT :limit OFFSET :offset",
                    {"limit": batch_size, "offset": offset},
                )
                for row in rows:
                    dconn.execute(
                        text(
                            """
                            INSERT INTO users (email, full_name, is_active, is_superuser)
                            VALUES (:email, :full_name, TRUE, FALSE)
                            ON CONFLICT (email) DO UPDATE SET full_name = EXCLUDED.full_name
                            """
                        ),
                        {"email": row["email"], "full_name": row["name"]},
                    )
                    migrated += 1
                offset += batch_size
    info("etl.load_users.complete", migrated=migrated)


if __name__ == "__main__":
    typer.run(main)
