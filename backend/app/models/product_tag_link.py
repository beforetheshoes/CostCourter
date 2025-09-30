from __future__ import annotations

from sqlmodel import Field, SQLModel


class ProductTagLink(SQLModel, table=True):
    __tablename__ = "product_tag_link"

    product_id: int = Field(foreign_key="products.id", primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", primary_key=True)
