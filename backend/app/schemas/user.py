from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr


class UserIdentityRead(BaseModel):
    provider: str
    provider_subject: str

    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = None


class UserCreate(UserBase):
    provider: str
    provider_subject: str


class UserRead(UserBase):
    id: int
    identities: list[UserIdentityRead]

    model_config = ConfigDict(from_attributes=True)


class CurrentUserRead(UserRead):
    is_superuser: bool
    roles: list[str] = []
