from __future__ import annotations

import base64
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from pydantic import AnyHttpUrl
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

import app.models as models
from app.core.config import settings
from app.main import app
from app.services.auth import AuthService, OIDCUserInfo, get_auth_service
from app.services.passkeys import (
    AuthenticationVerification,
    PasskeyService,
    RegistrationVerification,
    get_passkey_service,
)


class FakeOIDCProvider:
    def __init__(self) -> None:
        self.last_state: str | None = None
        self.last_code_challenge: str | None = None
        self.exchanged: list[tuple[str, str, str]] = []

    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        redirect_uri: str,
        scope: str,
    ) -> str:
        self.last_state = state
        self.last_code_challenge = code_challenge
        return (
            "https://auth.example.com/authorize"
            f"?state={state}&code_challenge={code_challenge}&redirect_uri={redirect_uri}"
        )

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        self.exchanged.append((code, code_verifier, redirect_uri))
        return {
            "access_token": "provider-access-token",
            "refresh_token": "provider-refresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "id_token": "dummy-id-token",
        }

    def fetch_userinfo(self, *, access_token: str) -> OIDCUserInfo:
        assert access_token == "provider-access-token"
        return OIDCUserInfo(
            subject="oidc|123",
            email="alice@example.com",
            full_name="Alice Example",
        )


@pytest.fixture(autouse=True)
def configure_auth_settings() -> None:
    settings.oidc_client_id = "costcourter-test"
    settings.oidc_authorization_endpoint = cast(
        AnyHttpUrl, "https://auth.example.com/authorize"
    )
    settings.oidc_token_endpoint = cast(AnyHttpUrl, "https://auth.example.com/token")
    settings.oidc_userinfo_endpoint = cast(
        AnyHttpUrl, "https://auth.example.com/userinfo"
    )
    settings.oidc_redirect_uri = cast(
        AnyHttpUrl, "https://frontend.example.com/auth/callback"
    )
    settings.oidc_scopes = ["openid", "email", "profile"]
    settings.oidc_issuer = None
    settings.passkey_relying_party_id = "localhost"
    settings.passkey_relying_party_name = "CostCourter"
    settings.passkey_origin = cast(AnyHttpUrl, "https://frontend.example.com")


def test_oidc_flow_creates_user_and_issues_token(
    client: TestClient, engine: Engine
) -> None:
    provider = FakeOIDCProvider()

    def override_service() -> AuthService:
        return AuthService(settings=settings, provider=provider)

    app.dependency_overrides[get_auth_service] = override_service
    try:
        start = client.post(
            "/api/auth/oidc/start",
            json={"redirect_uri": "https://frontend.example.com/auth/callback"},
        )
        assert start.status_code == 200
        start_data = start.json()
        state = start_data["state"]
        assert start_data["authorization_url"].startswith(
            "https://auth.example.com/authorize"
        )
        assert provider.last_state == state
        assert provider.last_code_challenge is not None

        callback = client.post(
            "/api/auth/oidc/callback",
            json={"state": state, "code": "auth-code"},
        )
        assert callback.status_code == 200
        token_payload = callback.json()
        token = token_payload["access_token"]
        decoded = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        assert decoded["token_type"] == "access"

        with Session(engine) as session:
            user = session.exec(
                select(models.User).where(models.User.email == "alice@example.com")
            ).one()
            assert user.email == "alice@example.com"
            identities = session.exec(select(models.UserIdentity)).all()
            assert len(identities) == 1
            assert identities[0].provider == "oidc"
            assert identities[0].provider_subject == "oidc|123"
    finally:
        app.dependency_overrides.pop(get_auth_service, None)


def _complete_oidc_flow(client: TestClient, provider: FakeOIDCProvider) -> str:
    start = client.post(
        "/api/auth/oidc/start",
        json={"redirect_uri": "https://frontend.example.com/auth/callback"},
    )
    assert start.status_code == 200
    state = start.json()["state"]
    callback = client.post(
        "/api/auth/oidc/callback",
        json={"state": state, "code": "auth-code"},
    )
    assert callback.status_code == 200
    payload = callback.json()
    return cast(str, payload["access_token"])


def test_auth_me_returns_current_user(client: TestClient, engine: Engine) -> None:
    provider = FakeOIDCProvider()

    def override_service() -> AuthService:
        return AuthService(settings=settings, provider=provider)

    app.dependency_overrides[get_auth_service] = override_service
    try:
        token = _complete_oidc_flow(client, provider)
    finally:
        app.dependency_overrides.pop(get_auth_service, None)

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "alice@example.com"
    assert payload["roles"] == []


def test_auth_me_includes_role_assignments(
    client: TestClient,
    create_user: Callable[..., models.User],
    make_auth_headers: Callable[[models.User], dict[str, str]],
    assign_role: Callable[[models.User, str], None],
) -> None:
    user = create_user(email="staff@example.com")
    assign_role(user, "admin")
    headers = make_auth_headers(user)

    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "staff@example.com"
    assert payload["roles"] == ["admin"]


def test_auth_me_requires_token(client: TestClient) -> None:
    client.headers.pop("Authorization", None)
    response = client.get("/api/auth/me")
    assert response.status_code in {401, 403}


class FakePasskeyBackend:
    def __init__(self) -> None:
        self.registration_calls: list[dict[str, Any]] = []
        self.authentication_calls: list[dict[str, Any]] = []
        self.registration_result = RegistrationVerification(
            credential_id=b"credential-1",
            public_key=b"public-key-bytes",
            sign_count=1,
            aaguid="test-aaguid",
            backup_eligible=True,
            backup_state=False,
            transports=["internal"],
        )
        self.authentication_result = AuthenticationVerification(
            new_sign_count=5,
            backup_eligible=True,
            backup_state=True,
        )
        self._challenge_log: list[bytes] = []

    def registration_verifier(
        self,
        credential: dict[str, Any],
        *,
        expected_challenge: bytes,
        expected_origin: str,
        expected_rp_id: str,
    ) -> RegistrationVerification:
        normalized_origin = str(settings.passkey_origin).rstrip("/")
        assert expected_origin == normalized_origin
        assert expected_rp_id == settings.passkey_relying_party_id
        self.registration_calls.append(credential)
        self._challenge_log.append(expected_challenge)
        return self.registration_result

    def authentication_verifier(
        self,
        credential: dict[str, Any],
        *,
        expected_challenge: bytes,
        credential_record: models.PasskeyCredential,
        expected_origin: str,
        expected_rp_id: str,
    ) -> AuthenticationVerification:
        assert credential_record.credential_id == credential["id"]
        normalized_origin = str(settings.passkey_origin).rstrip("/")
        assert expected_origin == normalized_origin
        assert expected_rp_id == settings.passkey_relying_party_id
        self.authentication_calls.append(credential)
        self._challenge_log.append(expected_challenge)
        return self.authentication_result


def test_passkey_registration_and_authentication_flow(
    client: TestClient, engine: Engine
) -> None:
    backend = FakePasskeyBackend()
    challenges = deque(
        [
            b"register-challenge",
            b"authenticate-challenge",
            b"anonymous-challenge",
        ]
    )

    def challenge_generator() -> bytes:
        if challenges:
            return challenges.popleft()
        return b"anonymous-challenge"

    def override_passkey_service() -> PasskeyService:
        return PasskeyService(
            settings=settings,
            registration_verifier=backend.registration_verifier,
            authentication_verifier=backend.authentication_verifier,
            challenge_generator=challenge_generator,
        )

    app.dependency_overrides[get_passkey_service] = override_passkey_service
    try:
        begin = client.post(
            "/api/auth/passkeys/register/begin",
            json={"email": "bob@example.com", "full_name": "Bob Example"},
        )
        assert begin.status_code == 200
        begin_data = begin.json()
        registration_state = begin_data["state"]
        assert (
            begin_data["options"]["challenge"]
            == base64.urlsafe_b64encode(b"register-challenge").decode()
        )

        complete = client.post(
            "/api/auth/passkeys/register/complete",
            json={
                "state": registration_state,
                "credential": {
                    "id": base64.urlsafe_b64encode(b"credential-1").decode(),
                    "type": "public-key",
                    "rawId": base64.urlsafe_b64encode(b"credential-1").decode(),
                    "response": {
                        "clientDataJSON": "",
                        "attestationObject": "",
                    },
                },
            },
        )
        assert complete.status_code == 200
        registration_token = complete.json()["access_token"]
        decoded = jwt.decode(
            registration_token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = int(decoded["sub"])

        with Session(engine) as session:
            user = session.exec(
                select(models.User).where(models.User.id == user_id)
            ).one()
            assert user.email == "bob@example.com"
            identity = session.exec(select(models.UserIdentity)).one()
            assert identity.provider == "passkey"
            credential = session.exec(select(models.PasskeyCredential)).one()
            assert credential.user_id == user.id
            assert (
                credential.credential_id
                == base64.urlsafe_b64encode(b"credential-1").decode()
            )
            assert credential.sign_count == backend.registration_result.sign_count
            assert credential.backup_state is backend.registration_result.backup_state
            assert (
                credential.backup_eligible
                is backend.registration_result.backup_eligible
            )

        auth_begin = client.post(
            "/api/auth/passkeys/assert/begin",
            json={"email": "bob@example.com"},
        )
        assert auth_begin.status_code == 200
        auth_data = auth_begin.json()
        auth_state = auth_data["state"]
        allow = auth_data["options"]["allowCredentials"]
        assert allow[0]["id"] == base64.urlsafe_b64encode(b"credential-1").decode()

        anonymous_begin = client.post(
            "/api/auth/passkeys/assert/begin",
            json={},
        )
        assert anonymous_begin.status_code == 200
        anon_data = anonymous_begin.json()
        assert anon_data["options"]["allowCredentials"] == []

        auth_complete = client.post(
            "/api/auth/passkeys/assert/complete",
            json={
                "state": auth_state,
                "credential": {
                    "id": base64.urlsafe_b64encode(b"credential-1").decode(),
                    "type": "public-key",
                    "response": {
                        "authenticatorData": "",
                        "signature": "",
                        "clientDataJSON": "",
                    },
                },
            },
        )
        assert auth_complete.status_code == 200
        auth_token = auth_complete.json()["access_token"]
        decoded_auth = jwt.decode(
            auth_token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        assert int(decoded_auth["sub"]) == user_id

        with Session(engine) as session:
            credential = session.exec(select(models.PasskeyCredential)).one()
            assert credential.sign_count == backend.authentication_result.new_sign_count
            assert credential.last_used_at is not None
            # ensure last_used_at is recent
            assert credential.last_used_at > datetime.now(UTC) - timedelta(seconds=60)
    finally:
        app.dependency_overrides.pop(get_passkey_service, None)


def test_get_current_user_requires_authorization_header(client: TestClient) -> None:
    client.headers.pop("Authorization", None)
    response = client.get("/api/product-urls")
    assert response.status_code in {401, 403}
    assert "not authenticated" in response.json()["detail"].lower()


def test_get_current_user_rejects_invalid_token(client: TestClient) -> None:
    client.headers["Authorization"] = "Bearer invalid"
    response = client.get("/api/product-urls")
    assert response.status_code == 401


def test_get_current_user_rejects_missing_subject(client: TestClient) -> None:
    token = jwt.encode(
        {"token_type": "access"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    client.headers["Authorization"] = f"Bearer {token}"
    response = client.get("/api/product-urls")
    assert response.status_code == 401


def test_get_current_user_rejects_non_numeric_subject(client: TestClient) -> None:
    token = jwt.encode(
        {"token_type": "access", "sub": "abc"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    client.headers["Authorization"] = f"Bearer {token}"
    response = client.get("/api/product-urls")
    assert response.status_code == 401


def test_get_current_user_rejects_unknown_user(client: TestClient) -> None:
    token = jwt.encode(
        {"token_type": "access", "sub": "404"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    client.headers["Authorization"] = f"Bearer {token}"
    response = client.get("/api/product-urls")
    assert response.status_code == 401
