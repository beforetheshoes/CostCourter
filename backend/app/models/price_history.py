from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import IdentifierMixin, utcnow

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.product_url import ProductURL


class PriceHistory(IdentifierMixin, SQLModel, table=True):
    __tablename__ = "price_history"

    product_id: int = Field(foreign_key="products.id", nullable=False, index=True)
    product_url_id: int | None = Field(foreign_key="product_urls.id")
    price: float = Field(nullable=False)
    currency: str = Field(default="USD", max_length=3, nullable=False)
    recorded_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    notified: bool = Field(default=False, nullable=False)

    product: "Product" = Relationship(back_populates="price_history")
    product_url: Optional["ProductURL"] = Relationship(back_populates="price_history")


def _ensure_relationship_dependencies() -> None:
    import app.models.product as _product
    import app.models.product_url as _product_url

    _ = (_product, _product_url)


_ensure_relationship_dependencies()
