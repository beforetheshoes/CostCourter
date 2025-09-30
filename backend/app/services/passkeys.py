from __future__ import annotations

import base64
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Protocol, cast

from fastapi import HTTPException, status
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError
from sqlmodel import Session, select

from app.core.config import Settings, settings
from app.models import PasskeyCredential, User
from app.models.base import utcnow
from app.services.auth import TokenResult, issue_access_token
from app.services.user import ensure_user_with_identity


def _urlsafe_b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _urlsafe_b64decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def _encode_state(settings: Settings, payload: dict[str, Any]) -> str:
    now = datetime.now(UTC)
    data = payload.copy()
    data.setdefault("iat", int(now.timestamp()))
    ttl = settings.passkey_challenge_ttl_seconds
    data["exp"] = int((now + timedelta(seconds=ttl)).timestamp())
    encoded = jwt.encode(
        data, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return cast(str, encoded)


def _decode_state(settings: Settings, token: str) -> dict[str, Any]:
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
            detail="Passkey challenge expired",
        ) from exc
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid passkey state",
        ) from exc


@dataclass
class RegistrationVerification:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: str | None
    backup_eligible: bool
    backup_state: bool
    transports: list[str] | None


@dataclass
class AuthenticationVerification:
    new_sign_count: int
    backup_eligible: bool
    backup_state: bool


class PasskeyRegistrationVerifier(Protocol):
    def __call__(
        self,
        credential: dict[str, Any],
        *,
        expected_challenge: bytes,
        expected_origin: str,
        expected_rp_id: str,
    ) -> RegistrationVerification:
        """Validate a WebAuthn registration response."""


class PasskeyAuthenticationVerifier(Protocol):
    def __call__(
        self,
        credential: dict[str, Any],
        *,
        expected_challenge: bytes,
        credential_record: PasskeyCredential,
        expected_origin: str,
        expected_rp_id: str,
    ) -> AuthenticationVerification:
        """Validate a WebAuthn authentication response."""


@dataclass
class PasskeyRegistrationBegin:
    state: str
    options: dict[str, Any]


@dataclass
class PasskeyAssertionBegin:
    state: str
    options: dict[str, Any]


class PasskeyService:
    def __init__(
        self,
        *,
        settings: Settings,
        registration_verifier: PasskeyRegistrationVerifier | None = None,
        authentication_verifier: PasskeyAuthenticationVerifier | None = None,
        challenge_generator: Callable[[], bytes] | None = None,
    ) -> None:
        self._settings = settings
        self._registration_verifier = registration_verifier
        self._authentication_verifier = authentication_verifier
        self._challenge_generator = challenge_generator or (
            lambda: secrets.token_bytes(32)
        )

    def _require_registration_verifier(self) -> PasskeyRegistrationVerifier:
        if self._registration_verifier is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Passkey registration verifier is not configured",
            )
        return self._registration_verifier

    def _require_authentication_verifier(self) -> PasskeyAuthenticationVerifier:
        if self._authentication_verifier is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Passkey authentication verifier is not configured",
            )
        return self._authentication_verifier

    def register_begin(
        self, session: Session, *, email: str, full_name: str | None
    ) -> PasskeyRegistrationBegin:
        rp_id = self._settings.passkey_relying_party_id
        rp_name = self._settings.passkey_relying_party_name or self._settings.app_name
        origin = self._settings.passkey_origin
        if rp_id is None or origin is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Passkey relying party configuration is incomplete",
            )
        challenge = self._challenge_generator()
        state = _encode_state(
            self._settings,
            {
                "type": "passkey-register",
                "challenge": _urlsafe_b64encode(challenge),
                "email": email,
                "full_name": full_name,
            },
        )
        user_display = full_name or email
        options = {
            "challenge": _urlsafe_b64encode(challenge),
            "rp": {"id": rp_id, "name": rp_name},
            "user": {
                "id": _urlsafe_b64encode(email.encode("utf-8")),
                "name": email,
                "displayName": user_display,
            },
            "pubKeyCredParams": [
                {"type": "public-key", "alg": -7},
                {"type": "public-key", "alg": -257},
            ],
            "timeout": self._settings.passkey_timeout_ms,
        }
        return PasskeyRegistrationBegin(state=state, options=options)

    def register_complete(
        self,
        session: Session,
        *,
        state: str,
        credential: dict[str, Any],
    ) -> TokenResult:
        decoded = _decode_state(self._settings, state)
        if decoded.get("type") != "passkey-register":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mismatched passkey registration state",
            )
        challenge_bytes = _urlsafe_b64decode(decoded["challenge"])
        verifier = self._require_registration_verifier()
        rp_id = self._settings.passkey_relying_party_id
        origin = self._settings.passkey_origin
        assert rp_id is not None  # safeguarded earlier
        assert origin is not None
        origin_str = str(origin)
        verification = verifier(
            credential,
            expected_challenge=challenge_bytes,
            expected_origin=origin_str,
            expected_rp_id=rp_id,
        )
        credential_id_str = credential["id"]
        decoded_id = _urlsafe_b64decode(credential_id_str)
        if decoded_id != verification.credential_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Credential identifier mismatch",
            )
        existing = session.exec(
            select(PasskeyCredential).where(
                PasskeyCredential.credential_id == credential_id_str
            )
        ).first()
        if existing and existing.user is not None:
            user = existing.user
        else:
            user = ensure_user_with_identity(
                session,
                email=decoded["email"],
                full_name=decoded.get("full_name"),
                provider="passkey",
                provider_subject=credential_id_str,
            )
        if user.id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User missing identifier",
            )
        transports = (
            ",".join(verification.transports) if verification.transports else None
        )
        if existing is None:
            existing = PasskeyCredential(
                user_id=user.id,
                credential_id=credential_id_str,
                public_key=_urlsafe_b64encode(verification.public_key),
                sign_count=verification.sign_count,
                aaguid=verification.aaguid,
                backup_eligible=verification.backup_eligible,
                backup_state=verification.backup_state,
                transports=transports,
            )
            session.add(existing)
        else:
            existing.user_id = user.id
            existing.public_key = _urlsafe_b64encode(verification.public_key)
            existing.sign_count = verification.sign_count
            existing.aaguid = verification.aaguid
            existing.backup_eligible = verification.backup_eligible
            existing.backup_state = verification.backup_state
            existing.transports = transports
            existing.updated_at = utcnow()
        user.last_login_at = utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
        token = issue_access_token(self._settings, user_id=user.id)
        return TokenResult(access_token=token)

    def assert_begin(self, session: Session, *, email: str) -> PasskeyAssertionBegin:
        user = session.exec(select(User).where(User.email == email)).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        if user.id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User missing identifier",
            )
        credentials = session.exec(
            select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)
        ).all()
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User has no registered passkeys",
            )
        challenge = self._challenge_generator()
        state = _encode_state(
            self._settings,
            {
                "type": "passkey-assert",
                "challenge": _urlsafe_b64encode(challenge),
                "user_id": user.id,
            },
        )
        allow = []
        for credential in credentials:
            transports = (
                credential.transports.split(",") if credential.transports else None
            )
            allow.append(
                {
                    "type": "public-key",
                    "id": credential.credential_id,
                    "transports": transports,
                }
            )
        options = {
            "challenge": _urlsafe_b64encode(challenge),
            "rpId": self._settings.passkey_relying_party_id,
            "allowCredentials": allow,
            "timeout": self._settings.passkey_timeout_ms,
            "userVerification": "preferred",
        }
        return PasskeyAssertionBegin(state=state, options=options)

    def assert_complete(
        self,
        session: Session,
        *,
        state: str,
        credential: dict[str, Any],
    ) -> TokenResult:
        decoded = _decode_state(self._settings, state)
        if decoded.get("type") != "passkey-assert":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mismatched passkey authentication state",
            )
        challenge = _urlsafe_b64decode(decoded["challenge"])
        credential_id = credential["id"]
        record = session.exec(
            select(PasskeyCredential).where(
                PasskeyCredential.credential_id == credential_id
            )
        ).one_or_none()
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unknown passkey credential",
            )
        verifier = self._require_authentication_verifier()
        rp_id = self._settings.passkey_relying_party_id
        origin = self._settings.passkey_origin
        assert rp_id is not None and origin is not None
        origin_str = str(origin)
        verification = verifier(
            credential,
            expected_challenge=challenge,
            credential_record=record,
            expected_origin=origin_str,
            expected_rp_id=rp_id,
        )
        record.sign_count = verification.new_sign_count
        record.backup_state = verification.backup_state
        record.backup_eligible = verification.backup_eligible
        record.last_used_at = utcnow()
        session.add(record)
        user = session.get(User, record.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Credential references missing user",
            )
        if user.id is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User missing identifier",
            )
        user.last_login_at = utcnow()
        session.add(user)
        session.commit()
        session.refresh(user)
        token = issue_access_token(self._settings, user_id=user.id)
        return TokenResult(access_token=token)


@lru_cache(maxsize=1)
def get_passkey_service() -> PasskeyService:
    return PasskeyService(settings=settings)


__all__ = [
    "AuthenticationVerification",
    "PasskeyAssertionBegin",
    "PasskeyAuthenticationVerifier",
    "PasskeyRegistrationBegin",
    "PasskeyRegistrationVerifier",
    "PasskeyService",
    "RegistrationVerification",
    "get_passkey_service",
]
