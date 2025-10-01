from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Protocol, cast
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from sqlmodel import Session

from app.core.config import Settings, settings
from app.models.base import utcnow
from app.services.user import ensure_user_with_identity


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _decode_state_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        decoded = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return cast(dict[str, Any], decoded)
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OIDC state expired",
        ) from exc
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OIDC state",
        ) from exc


def _encode_state_token(settings: Settings, payload: dict[str, Any]) -> str:
    now = datetime.now(UTC)
    data = payload.copy()
    data.setdefault("iat", int(now.timestamp()))
    ttl = settings.oidc_state_ttl_seconds
    data["exp"] = int((now + timedelta(seconds=ttl)).timestamp())
    encoded = jwt.encode(
        data, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return cast(str, encoded)


def issue_access_token(
    settings: Settings, *, user_id: int, scope: str | None = None
) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "token_type": "access",
        "exp": expire,
    }
    if scope:
        payload["scope"] = scope
    token = jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return cast(str, token)


@dataclass
class OIDCUserInfo:
    subject: str
    email: str
    full_name: str | None = None


@dataclass
class OIDCStart:
    state: str
    authorization_url: str


@dataclass
class TokenResult:
    access_token: str
    token_type: str = "bearer"


class OIDCProviderProtocol(Protocol):
    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
        scope: str,
    ) -> str:
        """Construct an authorization URL for the provider."""

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        """Exchange an authorization code for tokens."""

    def fetch_userinfo(self, *, access_token: str) -> OIDCUserInfo:
        """Retrieve the user's profile information from the provider."""


class OIDCProvider(OIDCProviderProtocol):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._authorization_endpoint: str | None = (
            str(settings.oidc_authorization_endpoint)
            if settings.oidc_authorization_endpoint
            else None
        )
        self._token_endpoint: str | None = (
            str(settings.oidc_token_endpoint) if settings.oidc_token_endpoint else None
        )
        self._userinfo_endpoint: str | None = (
            str(settings.oidc_userinfo_endpoint)
            if settings.oidc_userinfo_endpoint
            else None
        )
        self._issuer: str | None = (
            str(settings.oidc_issuer) if settings.oidc_issuer else None
        )
        self._ensure_discovery()

    def _ensure_discovery(self) -> None:
        if (
            self._authorization_endpoint
            and self._token_endpoint
            and self._userinfo_endpoint
        ):
            return
        if self._issuer is None:
            return

        metadata = self._discover_metadata(self._issuer)
        self._authorization_endpoint = self._authorization_endpoint or metadata.get(
            "authorization_endpoint"
        )
        self._token_endpoint = self._token_endpoint or metadata.get("token_endpoint")
        self._userinfo_endpoint = self._userinfo_endpoint or metadata.get(
            "userinfo_endpoint"
        )
        if self._issuer is None:
            self._issuer = metadata.get("issuer")

    def _discover_metadata(self, issuer: str) -> dict[str, str | None]:
        base = issuer.rstrip("/")
        url = f"{base}/.well-known/openid-configuration"
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch OIDC discovery document",
            ) from exc
        data = cast(dict[str, Any], response.json())
        return {
            "authorization_endpoint": cast(
                str | None, data.get("authorization_endpoint")
            ),
            "token_endpoint": cast(str | None, data.get("token_endpoint")),
            "userinfo_endpoint": cast(str | None, data.get("userinfo_endpoint")),
            "issuer": cast(str | None, data.get("issuer")),
        }

    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
        scope: str,
    ) -> str:
        endpoint = self._authorization_endpoint
        client_id = self._settings.oidc_client_id
        if endpoint is None or client_id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OIDC authorization endpoint not configured",
            )
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{endpoint}?{urlencode(params)}"

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        endpoint = self._token_endpoint
        client_id = self._settings.oidc_client_id
        if endpoint is None or client_id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OIDC token endpoint not configured",
            )
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        }
        if self._settings.oidc_client_secret:
            data["client_secret"] = self._settings.oidc_client_secret
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(endpoint, data=data)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to exchange authorization code",
            ) from exc
        return cast(dict[str, Any], response.json())

    def fetch_userinfo(self, *, access_token: str) -> OIDCUserInfo:
        endpoint = self._userinfo_endpoint
        if endpoint is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OIDC userinfo endpoint not configured",
            )
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(endpoint, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch userinfo",
            ) from exc
        data = cast(dict[str, Any], response.json())
        return OIDCUserInfo(
            subject=data.get("sub") or data["id"],
            email=data["email"],
            full_name=data.get("name"),
        )


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        provider: OIDCProviderProtocol | None = None,
    ) -> None:
        self._settings = settings
        self._provider = provider or OIDCProvider(settings)

    def start_oidc_flow(self, *, redirect_uri: str | None = None) -> OIDCStart:
        redirect = redirect_uri or (
            str(self._settings.oidc_redirect_uri)
            if self._settings.oidc_redirect_uri
            else None
        )
        if redirect is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OIDC redirect URI not configured",
            )
        scope = " ".join(self._settings.oidc_scopes)
        nonce = _urlsafe_b64(secrets.token_bytes(16))
        code_verifier = _urlsafe_b64(secrets.token_bytes(32))
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = _urlsafe_b64(digest)
        state = _encode_state_token(
            self._settings,
            {
                "type": "oidc",
                "cv": code_verifier,
                "nonce": nonce,
                "redirect_uri": redirect,
                "scope": scope,
            },
        )
        authorization_url = self._provider.authorization_url(
            state=state,
            nonce=nonce,
            code_challenge=code_challenge,
            redirect_uri=redirect,
            scope=scope,
        )
        return OIDCStart(state=state, authorization_url=authorization_url)

    def complete_oidc_flow(
        self, *, session: Session, state: str, code: str
    ) -> TokenResult:
        decoded = _decode_state_token(self._settings, state)
        if decoded.get("type") != "oidc":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mismatched OIDC state",
            )
        code_verifier = decoded["cv"]
        redirect_uri = decoded["redirect_uri"]
        tokens = self._provider.exchange_code(
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
        )
        access_token = tokens.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OIDC provider did not return an access token",
            )
        userinfo = self._provider.fetch_userinfo(access_token=access_token)
        user = ensure_user_with_identity(
            session,
            email=userinfo.email,
            full_name=userinfo.full_name,
            provider="oidc",
            provider_subject=userinfo.subject,
        )
        user.last_login_at = utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
        if user.id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User missing identifier",
            )
        token = issue_access_token(
            self._settings, user_id=user.id, scope=decoded.get("scope")
        )
        return TokenResult(access_token=token)


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    return AuthService(settings=settings)


__all__ = [
    "AuthService",
    "OIDCProvider",
    "OIDCProviderProtocol",
    "OIDCStart",
    "OIDCUserInfo",
    "TokenResult",
    "issue_access_token",
    "get_auth_service",
]
