from __future__ import annotations

import base64
from typing import Any, cast

import pytest
from fastapi import HTTPException
from pydantic import AnyHttpUrl

from app.core.config import Settings
from app.models import PasskeyCredential
from app.services.passkeys_webauthn import (
    WebAuthnAuthenticationVerifier,
    WebAuthnRegistrationVerifier,
)


@pytest.fixture(name="settings")
def settings_fixture() -> Settings:
    return Settings(
        passkey_relying_party_id="example.com",
        passkey_relying_party_name="Example",
        passkey_origin=cast(AnyHttpUrl, "https://example.com"),
    )


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def test_registration_verifier_success(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    from webauthn.helpers.structs import CredentialDeviceType

    verifier = WebAuthnRegistrationVerifier(settings=settings)
    payload = {
        "id": _encode(b"cred"),
        "rawId": _encode(b"cred"),
        "type": "public-key",
        "response": {
            "clientDataJSON": _encode(b"client"),
            "attestationObject": _encode(b"attestation"),
        },
    }

    class Result:
        credential_id = b"cred"
        credential_public_key = b"public"
        sign_count = 5
        aaguid = "uuid"
        credential_device_type = CredentialDeviceType.MULTI_DEVICE
        credential_backed_up = True
        transports = ["internal"]

    captured: dict[str, Any] = {}

    def fake_verify(**kwargs: Any) -> Result:
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(
        "app.services.passkeys_webauthn.verify_registration_response",
        fake_verify,
    )

    result = verifier(
        payload,
        expected_challenge=b"challenge",
        expected_origin="https://example.com",
        expected_rp_id="example.com",
    )

    assert result.credential_id == b"cred"
    assert result.public_key == b"public"
    assert result.sign_count == 5
    assert result.aaguid == "uuid"
    assert result.backup_eligible is True
    assert result.backup_state is True
    assert result.transports == ["internal"]

    assert captured["credential"].id == _encode(b"cred")
    assert captured["expected_origin"] == "https://example.com"
    assert captured["expected_rp_id"] == "example.com"
    assert captured["expected_challenge"] == b"challenge"


def test_registration_verifier_handles_invalid_response(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    from webauthn.helpers.exceptions import InvalidRegistrationResponse

    verifier = WebAuthnRegistrationVerifier(settings=settings)

    def fail(**kwargs: Any) -> None:
        _ = kwargs
        raise InvalidRegistrationResponse("invalid")

    monkeypatch.setattr(
        "app.services.passkeys_webauthn.verify_registration_response",
        fail,
    )

    with pytest.raises(HTTPException) as exc:
        verifier(
            {
                "id": _encode(b"cred"),
                "rawId": _encode(b"cred"),
                "type": "public-key",
                "response": {
                    "clientDataJSON": _encode(b"client"),
                    "attestationObject": _encode(b"attestation"),
                },
            },
            expected_challenge=b"challenge",
            expected_origin="https://example.com",
            expected_rp_id="example.com",
        )
    assert exc.value.status_code == 400


def test_authentication_verifier_success(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    verifier = WebAuthnAuthenticationVerifier(settings=settings)
    credential_record = PasskeyCredential(
        user_id=1,
        credential_id=_encode(b"cred"),
        public_key=_encode(b"public"),
        sign_count=3,
    )

    class Result:
        new_sign_count = 7
        credential_backed_up = False
        credential_device_type = "single_device"

    captured: dict[str, Any] = {}

    def fake_verify(**kwargs: Any) -> Result:
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(
        "app.services.passkeys_webauthn.verify_authentication_response",
        fake_verify,
    )

    payload = {
        "id": _encode(b"cred"),
        "rawId": _encode(b"cred"),
        "type": "public-key",
        "response": {
            "authenticatorData": _encode(b"auth"),
            "clientDataJSON": _encode(b"client"),
            "signature": _encode(b"sig"),
        },
    }

    result = verifier(
        payload,
        expected_challenge=b"challenge",
        credential_record=credential_record,
        expected_origin="https://example.com",
        expected_rp_id="example.com",
    )

    assert result.new_sign_count == 7
    assert result.backup_state is False
    assert result.backup_eligible is False

    assert captured["credential"].id == _encode(b"cred")
    assert captured["credential_public_key"] == _decode(credential_record.public_key)


def test_authentication_verifier_handles_invalid_response(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    from webauthn.helpers.exceptions import InvalidAuthenticationResponse

    verifier = WebAuthnAuthenticationVerifier(settings=settings)
    credential_record = PasskeyCredential(
        user_id=1,
        credential_id=_encode(b"cred"),
        public_key=_encode(b"public"),
        sign_count=3,
    )

    def fail(**kwargs: Any) -> None:
        _ = kwargs
        raise InvalidAuthenticationResponse("invalid")

    monkeypatch.setattr(
        "app.services.passkeys_webauthn.verify_authentication_response",
        fail,
    )

    with pytest.raises(HTTPException) as exc:
        verifier(
            {
                "id": _encode(b"cred"),
                "rawId": _encode(b"cred"),
                "type": "public-key",
                "response": {
                    "authenticatorData": _encode(b"auth"),
                    "clientDataJSON": _encode(b"client"),
                    "signature": _encode(b"sig"),
                },
            },
            expected_challenge=b"challenge",
            credential_record=credential_record,
            expected_origin="https://example.com",
            expected_rp_id="example.com",
        )
    assert exc.value.status_code == 400
