from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class AppSetting(TimestampMixin, SQLModel, table=True):
    __tablename__ = "app_settings"

    key: str = Field(primary_key=True, max_length=128)
    value: str | None = Field(default=None, max_length=2048)
    description: str | None = Field(default=None, max_length=512)


__all__ = ["AppSetting"]
