"""Marimo notebook for exploring CostCourter catalog data via the FastAPI stack."""

from __future__ import annotations

from typing import Any, cast

import marimo

__generated_with = "0.16.0"
app = marimo.App(width="wide")

# Populated dynamically by marimo cells; declared for static type checking.
owner_picker: Any
product_snapshot: Any


@app.cell
def overview() -> tuple[Any]:
    import marimo as mo
    import pandas as pd

    return (pd,)


@app.cell
def connection_details() -> None:
    def _() -> None:
        import marimo as mo
        import pandas as pd

        from app.core.config import settings

        connection_snapshot = pd.DataFrame(
            [
                {
                    "Environment": settings.environment,
                    "Database host": settings.postgres_host,
                    "Database name": settings.postgres_db,
                    "SQL echo": settings.debug,
                }
            ]
        )
        return None

    _()
    return None


app._unparsable_cell(
    r"""
    from sqlmodel import Session, select

    from app.core.database import engine
    from app.models import User, ensure_core_model_mappings

    ensure_core_model_mappings()
    with Session(engine) as session:
        owners = session.exec(select(User)).all()

    if not owners:
        return mo.md(\"⚠️ No users found. Seed the database before exploring.\")

    owner_options = {
        f\"{owner.full_name or owner.email} (id={owner.id})\": owner.id
        for owner in owners
        if owner.id is not None
    }
    default_owner = next(iter(owner_options.values()))
    selector = mo.ui.dropdown(owner_options, value=default_owner, label=\"Catalog owner\")
    """,
    name="owner_picker",
)


app._unparsable_cell(
    r"""
    from sqlmodel import Session

    from app.core.database import engine
    from app.models import User
    from app.services import catalog

    owner_id = owner_picker.value
    with Session(engine) as session:
        owner = session.get(User, owner_id)
        if owner is None:
            return mo.md(\"⚠️ Selected owner missing. Refresh the dropdown.\"), None
        products = catalog.list_products(
            session,
            owner=owner,
            limit=100,
            offset=0,
            search=None,
            is_active=None,
            tag=None,
            for_user_id=None,
        )

    if not products:
        return mo.md(\"No products for this owner yet.\"), None

    frame = pd.DataFrame([product.model_dump(mode=\"json\") for product in products])
    table = mo.ui.table(frame)
    product_options = {
        f\"{product.name or product.slug} (id={product.id})\": product.id
        for product in products
        if product.id is not None
    }
    default_product = next(iter(product_options.values()))
    selector = mo.ui.dropdown(product_options, value=default_product, label=\"Product\")

    block = mo.vstack(
        [
            mo.md(\"### Product snapshots\"),
            table,
            mo.md(
                \"Payloads originate from `catalog.list_products`, so the table matches\"
                \" the REST response used by the Vue admin and public API.\"
            ),
        ]
    )
    """,
    name="product_snapshot",
)


app._unparsable_cell(
    r"""
    from sqlmodel import Session, select

    from app.core.database import engine
    from app.models import PriceHistory, ProductURL, Store

    block, selector = product_snapshot
    if selector is None:
        return block

    product_id = selector.value
    with Session(engine) as session:
        url_stmt = (
            select(ProductURL, Store)
            .join(Store, isouter=True)
            .where(ProductURL.product_id == product_id)
            .order_by(ProductURL.is_primary.desc(), ProductURL.id)
        )
        history_stmt = (
            select(PriceHistory)
            .where(PriceHistory.product_id == product_id)
            .order_by(PriceHistory.recorded_at.desc())
        )
        url_rows = session.exec(url_stmt).all()
        history_rows = session.exec(history_stmt).all()

    url_payload = []
    for url, store in url_rows:
        data = url.model_dump(mode=\"json\")
        data[\"store_name\"] = store.name if store else None
        data[\"store_slug\"] = store.slug if store else None
        url_payload.append(data)

    history_payload = [row.model_dump(mode=\"json\") for row in history_rows]
    urls_df = pd.DataFrame(url_payload)
    history_df = pd.DataFrame(history_payload)

    urls_block = mo.vstack(
        [
            mo.md(\"### Product URLs\"),
            mo.ui.table(urls_df) if not urls_df.empty else mo.md(\"No URLs attached.\"),
        ]
    )
    history_block = mo.vstack(
        [
            mo.md(\"### Price history\"),
            mo.ui.table(history_df)
            if not history_df.empty
            else mo.md(\"No price history entries recorded.\"),
        ]
    )
    """,
    name="product_details",
)


@app.cell
def aggregate_metrics(pd: Any) -> None:
    from sqlalchemy import func
    from sqlmodel import Session, select

    from app.core.database import engine
    from app.models import Product, ProductURL

    owner_value = getattr(owner_picker, "value", 0)
    owner_id = cast(int, owner_value)
    with Session(engine) as session:
        product_count_result = session.exec(
            select(func.count()).select_from(Product).where(Product.user_id == owner_id)
        ).first()
        join_condition = cast(Any, ProductURL.product_id == Product.id)
        url_count_result = session.exec(
            select(func.count())
            .select_from(ProductURL)
            .join(Product, join_condition)
            .where(Product.user_id == owner_id)
        ).first()

    product_count = int(product_count_result or 0)
    url_count = int(url_count_result or 0)

    metrics = pd.DataFrame(
        [
            {"Metric": "Products", "Value": product_count},
            {"Metric": "Product URLs", "Value": url_count},
        ]
    )
    return None


if __name__ == "__main__":
    app.run()
