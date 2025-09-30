from __future__ import annotations

from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, EmailStr, Field


class OIDCStartRequest(BaseModel):
    redirect_uri: AnyHttpUrl | None = None


class OIDCStartResponse(BaseModel):
    state: str
    authorization_url: str


class OIDCCallbackRequest(BaseModel):
    state: str
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = Field(default="bearer")


class PasskeyRegisterBeginRequest(BaseModel):
    email: EmailStr
    full_name: str | None = None


class PublicKeyCredentialDescriptor(BaseModel):
    type: str
    id: str
    transports: list[str] | None = None


class PasskeyRegistrationOptions(BaseModel):
    challenge: str
    rp: dict[str, Any]
    user: dict[str, str]
    pub_key_cred_params: list[dict[str, Any]] = Field(
        alias="pubKeyCredParams", serialization_alias="pubKeyCredParams"
    )
    timeout: int | None = None

    model_config = ConfigDict(populate_by_name=True)


class PasskeyRegisterBeginResponse(BaseModel):
    state: str
    options: PasskeyRegistrationOptions


class PasskeyCredentialPayload(BaseModel):
    id: str
    type: str
    raw_id: str | None = Field(default=None, alias="rawId", serialization_alias="rawId")
    response: dict[str, Any]

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class PasskeyRegisterCompleteRequest(BaseModel):
    state: str
    credential: PasskeyCredentialPayload


class PasskeyAssertBeginRequest(BaseModel):
    email: EmailStr


class PasskeyAssertionOptions(BaseModel):
    challenge: str
    rp_id: str = Field(alias="rpId", serialization_alias="rpId")
    allow_credentials: list[PublicKeyCredentialDescriptor] = Field(
        alias="allowCredentials", serialization_alias="allowCredentials"
    )
    timeout: int | None = None
    user_verification: str | None = Field(
        default=None, alias="userVerification", serialization_alias="userVerification"
    )

    model_config = ConfigDict(populate_by_name=True)


class PasskeyAssertBeginResponse(BaseModel):
    state: str
    options: PasskeyAssertionOptions


class PasskeyAssertCompleteRequest(BaseModel):
    state: str
    credential: PasskeyCredentialPayload
