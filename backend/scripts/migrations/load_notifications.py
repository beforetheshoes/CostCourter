from __future__ import annotations

import json
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
    echo_sql: Annotated[bool, typer.Option()] = False,
) -> None:
    """Migrate settings into app_settings and leave per-user NotificationSetting customization for later.

    Legacy `settings` rows become Postgres `app_settings` entries with key = `${group}.${name}` and value = JSON string of payload.
    """

    info("etl.load_notifications.start")
    src = build_engine(legacy_dsn, echo=echo_sql)
    dst = build_engine(postgres_dsn, echo=echo_sql)

    with engine_scope(src) as src_eng, engine_scope(dst) as dst_eng:
        with src_eng.begin() as sconn, dst_eng.begin() as dconn:
            rows = _fetch_rows(
                sconn,
                "SELECT `group`, `name`, `payload` FROM settings ORDER BY id",
                {},
            )
            migrated = 0
            for row in rows:
                key = f"{row['group']}.{row['name']}"
                # Store as raw JSON string for compatibility
                value = (
                    json.dumps(row["payload"])
                    if isinstance(row["payload"], (dict, list))
                    else str(row["payload"])
                )
                dconn.execute(
                    text(
                        """
                        INSERT INTO app_settings (key, value, description)
                        VALUES (:key, :value, NULL)
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                        """
                    ),
                    {"key": key, "value": value},
                )
                migrated += 1
            info("etl.load_notifications.settings_complete", migrated=migrated)

    info("etl.load_notifications.complete")


if __name__ == "__main__":
    typer.run(main)
