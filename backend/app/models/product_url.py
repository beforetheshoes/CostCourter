from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import IdentifierMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.price_history import PriceHistory
    from app.models.product import Product
    from app.models.store import Store
    from app.models.user import User


class ProductURL(IdentifierMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "product_urls"

    product_id: int = Field(foreign_key="products.id", nullable=False, index=True)
    store_id: int = Field(foreign_key="stores.id", nullable=False, index=True)
    created_by_id: int | None = Field(foreign_key="users.id")
    url: str = Field(nullable=False, max_length=1000)
    is_primary: bool = Field(default=False)
    active: bool = Field(default=True)

    product: "Product" = Relationship(back_populates="urls")
    store: "Store" = Relationship(back_populates="product_urls")
    created_by: Optional["User"] = Relationship(back_populates="product_urls")
    price_history: list["PriceHistory"] = Relationship(back_populates="product_url")


def _ensure_relationship_dependencies() -> None:
    import app.models.price_history as _price_history
    import app.models.product as _product
    import app.models.store as _store
    import app.models.user as _user

    _ = (_price_history, _product, _store, _user)


_ensure_relationship_dependencies()
