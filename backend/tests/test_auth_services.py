from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from fastapi import HTTPException
from jose import jwt
from pydantic import AnyHttpUrl
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.services.auth as auth_services
import app.services.passkeys as passkey_services
from app.core.config import Settings
from app.models import User, UserIdentity
from app.services.auth import (
    AuthService,
    OIDCProvider,
    OIDCUserInfo,
)
from app.services.passkeys import (
    AuthenticationVerification,
    PasskeyService,
    RegistrationVerification,
)
from app.services.user import ensure_user_with_identity


@pytest.fixture(name="settings")
def settings_fixture() -> Settings:
    return Settings(
        oidc_client_id="client",
        oidc_authorization_endpoint=cast(
            AnyHttpUrl, "https://auth.example.com/authorize"
        ),
        oidc_token_endpoint=cast(AnyHttpUrl, "https://auth.example.com/token"),
        oidc_userinfo_endpoint=cast(AnyHttpUrl, "https://auth.example.com/userinfo"),
        oidc_redirect_uri=cast(AnyHttpUrl, "https://app.example.com/callback"),
        passkey_relying_party_id="example.com",
        passkey_relying_party_name="Example",
        passkey_origin=cast(AnyHttpUrl, "https://app.example.com"),
    )


@pytest.fixture(name="engine")
def engine_fixture() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(name="session")
def session_fixture(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def test_decode_state_token_invalid(settings: Settings) -> None:
    with pytest.raises(HTTPException) as exc:
        auth_services._decode_state_token(settings, "not-a-jwt")
    assert exc.value.status_code == 400


def test_decode_state_token_expired(settings: Settings) -> None:
    expired = jwt.encode(
        {
            "exp": int((datetime.now(UTC) - timedelta(seconds=5)).timestamp()),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as exc:
        auth_services._decode_state_token(settings, expired)
    assert exc.value.detail == "OIDC state expired"


def _unused_registration_verifier(
    *args: Any, **kwargs: Any
) -> RegistrationVerification:
    raise AssertionError("registration verifier should not be used")


def _unused_authentication_verifier(
    *args: Any, **kwargs: Any
) -> AuthenticationVerification:
    raise AssertionError("authentication verifier should not be used")


def _authentication_success(*args: Any, **kwargs: Any) -> AuthenticationVerification:
    return AuthenticationVerification(
        new_sign_count=1,
        backup_eligible=False,
        backup_state=False,
    )


class _DummyProvider:
    def authorization_url(self, **_: Any) -> str:
        raise AssertionError("should not be called")

    def exchange_code(self, **_: Any) -> dict[str, Any]:
        return {}

    def fetch_userinfo(self, *, access_token: str) -> OIDCUserInfo:
        raise AssertionError(access_token)


def test_auth_service_requires_redirect(settings: Settings) -> None:
    custom = settings.model_copy(update={"oidc_redirect_uri": None})
    service = AuthService(settings=custom, provider=_DummyProvider())
    with pytest.raises(HTTPException) as exc:
        service.start_oidc_flow()
    assert exc.value.status_code == 500


def test_auth_service_complete_requires_access_token(
    settings: Settings, session: Session
) -> None:
    state = auth_services._encode_state_token(
        settings,
        {
            "type": "oidc",
            "cv": "code-verifier",
            "redirect_uri": str(settings.oidc_redirect_uri),
            "scope": "openid",
        },
    )
    service = AuthService(settings=settings, provider=_DummyProvider())
    with pytest.raises(HTTPException) as exc:
        service.complete_oidc_flow(session=session, state=state, code="abc")
    assert exc.value.status_code == 502


def test_auth_service_complete_success_flow(
    settings: Settings, session: Session
) -> None:
    class SuccessfulProvider:
        def __init__(self) -> None:
            self.exchanged: list[tuple[str, str, str]] = []

        def authorization_url(self, **kwargs: Any) -> str:
            return "https://example.com/auth"

        def exchange_code(self, **kwargs: Any) -> dict[str, Any]:
            self.exchanged.append(
                (kwargs["code"], kwargs["code_verifier"], kwargs["redirect_uri"])
            )
            return {"access_token": "provider-access-token", "token_type": "Bearer"}

        def fetch_userinfo(self, *, access_token: str) -> OIDCUserInfo:
            assert access_token == "provider-access-token"
            return OIDCUserInfo(
                subject="oidc|success",
                email="success@example.com",
                full_name="Success Case",
            )

    provider = SuccessfulProvider()
    service = AuthService(settings=settings, provider=provider)
    start = service.start_oidc_flow()

    result = service.complete_oidc_flow(
        session=session,
        state=start.state,
        code="dummy-code",
    )

    assert result.access_token
    assert provider.exchanged

    identities = session.exec(select(UserIdentity)).all()
    assert len(identities) == 1
    user = session.exec(select(User)).one()
    assert user.email == "success@example.com"
    assert user.last_login_at is not None


def test_auth_service_complete_rejects_mismatched_state(
    settings: Settings, session: Session
) -> None:
    state = auth_services._encode_state_token(
        settings,
        {
            "type": "unexpected",
        },
    )
    service = AuthService(settings=settings, provider=_DummyProvider())
    with pytest.raises(HTTPException) as exc:
        service.complete_oidc_flow(session=session, state=state, code="abc")
    assert exc.value.status_code == 400


def test_auth_service_complete_raises_when_user_missing_id(
    settings: Settings, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Provider:
        def authorization_url(self, **kwargs: Any) -> str:
            return "https://auth"

        def exchange_code(self, **kwargs: Any) -> dict[str, Any]:
            return {"access_token": "token"}

        def fetch_userinfo(self, *, access_token: str) -> OIDCUserInfo:
            return OIDCUserInfo(subject="oidc|missing", email="missing@example.com")

    service = AuthService(settings=settings, provider=Provider())
    start = service.start_oidc_flow()

    def fake_ensure_user(*args: Any, **kwargs: Any) -> User:
        return User(email="missing@example.com")

    monkeypatch.setattr(auth_services, "ensure_user_with_identity", fake_ensure_user)

    original_refresh = Session.refresh

    def fake_refresh(
        self: Session, instance: Any, attribute_names: Any | None = None
    ) -> None:
        original_refresh(self, instance, attribute_names=attribute_names)
        if isinstance(instance, User):
            instance.id = None

    monkeypatch.setattr(Session, "refresh", fake_refresh)

    with pytest.raises(HTTPException) as exc:
        service.complete_oidc_flow(session=session, state=start.state, code="code")
    assert exc.value.status_code == 500


def test_oidc_provider_authorization_url(settings: Settings) -> None:
    provider = OIDCProvider(settings)
    url = provider.authorization_url(
        state="state",
        nonce="nonce",
        code_challenge="challenge",
        redirect_uri=str(settings.oidc_redirect_uri),
        scope="openid",
    )
    assert "client_id=client" in url
    assert url.startswith(str(settings.oidc_authorization_endpoint))


def test_oidc_provider_authorization_url_missing_config(settings: Settings) -> None:
    provider = OIDCProvider(settings.model_copy(update={"oidc_client_id": None}))
    with pytest.raises(HTTPException) as exc:
        provider.authorization_url(
            state="state",
            nonce="nonce",
            code_challenge="challenge",
            redirect_uri=str(settings.oidc_redirect_uri),
            scope="openid",
        )
    assert exc.value.status_code == 500


def test_oidc_provider_discovers_metadata(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    discovered = {
        "authorization_endpoint": "https://issuer.example.com/oauth2/auth",
        "token_endpoint": "https://issuer.example.com/oauth2/token",
        "userinfo_endpoint": "https://issuer.example.com/oauth2/userinfo",
        "issuer": "https://issuer.example.com/",
    }

    class DiscoveryClient:
        def __enter__(self) -> DiscoveryClient:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def get(self, url: str) -> Any:
            assert url == "https://issuer.example.com/.well-known/openid-configuration"

            class Response:
                def raise_for_status(self) -> None:
                    return None

                def json(self) -> dict[str, Any]:
                    return discovered

            return Response()

        def post(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("token exchange should not occur during discovery")

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: DiscoveryClient())

    configured = settings.model_copy(
        update={
            "oidc_authorization_endpoint": None,
            "oidc_token_endpoint": None,
            "oidc_userinfo_endpoint": None,
            "oidc_issuer": cast(AnyHttpUrl, "https://issuer.example.com"),
        }
    )

    provider = OIDCProvider(configured)
    url = provider.authorization_url(
        state="s",
        nonce="n",
        code_challenge="c",
        redirect_uri=str(settings.oidc_redirect_uri),
        scope="openid",
    )
    assert url.startswith("https://issuer.example.com/oauth2/auth")


def test_oidc_provider_discovery_failure(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    class FailingClient:
        def __enter__(self) -> FailingClient:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def get(self, url: str) -> Any:
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: FailingClient())

    configured = settings.model_copy(
        update={
            "oidc_authorization_endpoint": None,
            "oidc_token_endpoint": None,
            "oidc_userinfo_endpoint": None,
            "oidc_issuer": cast(AnyHttpUrl, "https://issuer.example.com"),
        }
    )

    with pytest.raises(HTTPException) as exc:
        OIDCProvider(configured)
    assert exc.value.status_code == 502


def test_oidc_provider_exchange_code_handles_http_error(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    provider = OIDCProvider(settings)

    class FailingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "Client", FailingClient)

    with pytest.raises(HTTPException) as exc:
        provider.exchange_code(code="abc", code_verifier="cv", redirect_uri="https://")
    assert exc.value.status_code == 502


def test_oidc_provider_fetch_userinfo_handles_http_error(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    provider = OIDCProvider(settings)

    class BrokenClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise httpx.HTTPError("nope")

    monkeypatch.setattr(httpx, "Client", BrokenClient)

    with pytest.raises(HTTPException) as exc:
        provider.fetch_userinfo(access_token="token")
    assert exc.value.status_code == 502


def test_oidc_provider_exchange_code_success(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    updated = settings.model_copy(update={"oidc_client_secret": "s3cret"})
    provider = OIDCProvider(updated)
    calls: list[dict[str, Any]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"access_token": "token"}

    class FakeClient:
        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def post(self, url: str, *, data: dict[str, Any]) -> FakeResponse:
            calls.append({"url": url, "data": data})
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: FakeClient())

    result = provider.exchange_code(
        code="code", code_verifier="cv", redirect_uri="https://app"
    )
    assert result["access_token"] == "token"
    assert calls[0]["data"]["client_secret"] == "s3cret"


def test_oidc_provider_fetch_userinfo_success(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    provider = OIDCProvider(settings)
    responses: list[dict[str, Any]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"sub": "sub", "email": "user@example.com", "name": "User"}

    class FakeClient:
        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def get(self, url: str, *, headers: dict[str, str]) -> FakeResponse:
            responses.append({"url": url, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: FakeClient())

    info = provider.fetch_userinfo(access_token="token")
    assert info.email == "user@example.com"
    assert responses[0]["headers"]["Authorization"] == "Bearer token"


def test_oidc_provider_fetch_userinfo_requires_endpoint(settings: Settings) -> None:
    provider = OIDCProvider(
        settings.model_copy(update={"oidc_userinfo_endpoint": None})
    )
    with pytest.raises(HTTPException) as exc:
        provider.fetch_userinfo(access_token="token")
    assert exc.value.status_code == 500


def test_passkey_service_provides_default_verifiers(
    settings: Settings, session: Session
) -> None:
    service = PasskeyService(settings=settings)
    assert callable(service._require_registration_verifier())
    assert callable(service._require_authentication_verifier())


def test_passkey_register_begin_requires_configuration(
    settings: Settings, session: Session
) -> None:
    incomplete = settings.model_copy(update={"passkey_relying_party_id": None})
    service = PasskeyService(settings=incomplete)
    with pytest.raises(HTTPException) as exc:
        service.register_begin(session, email="user@example.com", full_name="User")
    assert exc.value.status_code == 500


def test_passkey_register_complete_mismatched_state(
    settings: Settings, session: Session
) -> None:
    service = PasskeyService(
        settings=settings,
        registration_verifier=_unused_registration_verifier,
        authentication_verifier=_unused_authentication_verifier,
    )
    bad_state = auth_services._encode_state_token(settings, {"type": "other"})
    with pytest.raises(HTTPException) as exc:
        service.register_complete(
            session,
            state=bad_state,
            credential={"id": base64.urlsafe_b64encode(b"id").decode()},
        )
    assert exc.value.status_code == 400


def test_passkey_register_complete_identifier_mismatch(
    settings: Settings, session: Session
) -> None:
    def verifier(*args: Any, **kwargs: Any) -> RegistrationVerification:
        return RegistrationVerification(
            credential_id=b"different",
            public_key=b"pk",
            sign_count=1,
            aaguid=None,
            backup_eligible=False,
            backup_state=False,
            transports=None,
        )

    service = PasskeyService(
        settings=settings,
        registration_verifier=verifier,
        authentication_verifier=_unused_authentication_verifier,
    )
    state = auth_services._encode_state_token(
        settings,
        {
            "type": "passkey-register",
            "challenge": base64.urlsafe_b64encode(b"challenge").decode(),
            "email": "user@example.com",
        },
    )
    with pytest.raises(HTTPException) as exc:
        service.register_complete(
            session,
            state=state,
            credential={"id": base64.urlsafe_b64encode(b"actual").decode()},
        )
    assert exc.value.status_code == 400


def test_passkey_assert_begin_user_not_found(
    settings: Settings, session: Session
) -> None:
    def verifier(*args: Any, **kwargs: Any) -> RegistrationVerification:
        return RegistrationVerification(
            credential_id=b"id",
            public_key=b"pk",
            sign_count=1,
            aaguid=None,
            backup_eligible=False,
            backup_state=False,
            transports=None,
        )

    service = PasskeyService(
        settings=settings,
        registration_verifier=verifier,
        authentication_verifier=_authentication_success,
    )
    with pytest.raises(HTTPException) as exc:
        service.assert_begin(session, email="missing@example.com")
    assert exc.value.status_code == 404


def test_passkey_assert_begin_no_credentials(
    settings: Settings, session: Session
) -> None:
    user = User(email="user@example.com")
    session.add(user)
    session.commit()
    service = PasskeyService(
        settings=settings,
        registration_verifier=_unused_registration_verifier,
        authentication_verifier=_authentication_success,
    )
    with pytest.raises(HTTPException) as exc:
        service.assert_begin(session, email=user.email)
    assert exc.value.status_code == 400


def test_passkey_assert_complete_unknown_credential(
    settings: Settings, session: Session
) -> None:
    user = User(email="user@example.com")
    session.add(user)
    session.commit()
    service = PasskeyService(
        settings=settings,
        registration_verifier=_unused_registration_verifier,
        authentication_verifier=_authentication_success,
    )
    state = auth_services._encode_state_token(
        settings,
        {
            "type": "passkey-assert",
            "challenge": base64.urlsafe_b64encode(b"challenge").decode(),
            "user_id": user.id,
        },
    )
    with pytest.raises(HTTPException) as exc:
        service.assert_complete(
            session,
            state=state,
            credential={"id": base64.urlsafe_b64encode(b"missing").decode()},
        )
    assert exc.value.status_code == 400


def test_passkey_state_decode_invalid(settings: Settings) -> None:
    with pytest.raises(HTTPException) as exc:
        passkey_services._decode_state(settings, "invalid")
    assert exc.value.status_code == 400


def test_ensure_user_with_identity_updates_full_name(session: Session) -> None:
    user = User(email="user@example.com")
    session.add(user)
    session.commit()

    updated = ensure_user_with_identity(
        session,
        email=user.email,
        full_name="Updated User",
        provider="oidc",
        provider_subject="sub",
    )
    assert updated.full_name == "Updated User"
    identity = session.exec(select(UserIdentity)).one()
    assert identity.provider_subject == "sub"


def test_ensure_user_with_identity_missing_user_reference(session: Session) -> None:
    identity = UserIdentity(user_id=999, provider="oidc", provider_subject="sub")
    session.add(identity)
    session.commit()

    with pytest.raises(HTTPException) as exc:
        ensure_user_with_identity(
            session,
            email="user@example.com",
            full_name=None,
            provider="oidc",
            provider_subject="sub",
        )
    assert exc.value.status_code == 500
