from __future__ import annotations

from typing import Annotated

import typer
from sqlmodel import Session

from app.fixtures import install_reference_data

from .common import build_engine, engine_scope, info

app = typer.Typer(add_completion=False)


@app.command()
def main(
    postgres_dsn: Annotated[
        str,
        typer.Option(
            "postgresql+psycopg://costcourter:costcourter@127.0.0.1:5432/costcourter"
        ),
    ],
    echo_sql: Annotated[bool, typer.Option()] = False,
) -> None:
    """Seed reference data like roles and app settings into Postgres.

    This script is idempotent.
    """

    info("etl.load_reference_data.start")
    engine = build_engine(postgres_dsn, echo=echo_sql)
    with engine_scope(engine) as eng:
        with Session(eng) as session:
            install_reference_data(session)
    info("etl.load_reference_data.complete")


if __name__ == "__main__":
    typer.run(main)
