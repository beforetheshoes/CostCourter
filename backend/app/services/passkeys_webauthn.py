from __future__ import annotations

import base64
from typing import Any, Literal

from fastapi import HTTPException, status
from webauthn import (
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticationCredential,
    AuthenticatorAssertionResponse,
    AuthenticatorAttachment,
    AuthenticatorAttestationResponse,
    CredentialDeviceType,
    PublicKeyCredentialType,
    RegistrationCredential,
)

from app.core.config import Settings
from app.models import PasskeyCredential
from app.services.passkeys import (
    AuthenticationVerification,
    PasskeyAuthenticationVerifier,
    PasskeyRegistrationVerifier,
    RegistrationVerification,
)


def _urlsafe_b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _urlsafe_b64decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded + padding)


def _is_multi_device(device_type: CredentialDeviceType | str | None) -> bool:
    if device_type is None:
        return False
    if isinstance(device_type, CredentialDeviceType):
        return device_type == CredentialDeviceType.MULTI_DEVICE
    return str(device_type).lower() == CredentialDeviceType.MULTI_DEVICE.value


def _parse_attachment(value: Any) -> AuthenticatorAttachment | None:
    if value is None:
        return None
    if isinstance(value, AuthenticatorAttachment):
        return value
    if isinstance(value, str):
        try:
            return AuthenticatorAttachment(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported authenticator attachment",
            ) from exc
    return None


def _parse_registration_credential(
    credential: dict[str, Any],
) -> RegistrationCredential:
    try:
        response_data = credential["response"]
        client_data = _urlsafe_b64decode(response_data["clientDataJSON"])
        attestation_object = _urlsafe_b64decode(response_data["attestationObject"])
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incomplete passkey registration payload",
        ) from exc

    response = AuthenticatorAttestationResponse(
        client_data_json=client_data,
        attestation_object=attestation_object,
    )
    raw_id_encoded = credential.get("rawId") or credential["id"]
    raw_id = _urlsafe_b64decode(raw_id_encoded)
    attachment = _parse_attachment(credential.get("authenticatorAttachment"))
    credential_type_value: Literal[PublicKeyCredentialType.PUBLIC_KEY] = (
        PublicKeyCredentialType.PUBLIC_KEY
    )
    credential_type = credential.get("type", "public-key")
    if isinstance(credential_type, str):
        if credential_type != "public-key":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported credential type",
            )
    elif (
        isinstance(credential_type, PublicKeyCredentialType)
        and credential_type is not PublicKeyCredentialType.PUBLIC_KEY
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported credential type",
        )
    return RegistrationCredential(
        id=credential["id"],
        raw_id=raw_id,
        response=response,
        authenticator_attachment=attachment,
        type=credential_type_value,
    )


def _parse_authentication_credential(
    credential: dict[str, Any],
) -> AuthenticationCredential:
    try:
        response_data = credential["response"]
        client_data = _urlsafe_b64decode(response_data["clientDataJSON"])
        authenticator_data = _urlsafe_b64decode(response_data["authenticatorData"])
        signature = _urlsafe_b64decode(response_data["signature"])
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incomplete passkey assertion payload",
        ) from exc

    user_handle_value = response_data.get("userHandle")
    user_handle = None
    if isinstance(user_handle_value, str):
        user_handle = _urlsafe_b64decode(user_handle_value)
    elif isinstance(user_handle_value, bytes):
        user_handle = user_handle_value

    response = AuthenticatorAssertionResponse(
        client_data_json=client_data,
        authenticator_data=authenticator_data,
        signature=signature,
        user_handle=user_handle,
    )
    raw_id_encoded = credential.get("rawId") or credential["id"]
    raw_id = _urlsafe_b64decode(raw_id_encoded)
    attachment = _parse_attachment(credential.get("authenticatorAttachment"))
    credential_type_value: Literal[PublicKeyCredentialType.PUBLIC_KEY] = (
        PublicKeyCredentialType.PUBLIC_KEY
    )
    credential_type = credential.get("type", "public-key")
    if isinstance(credential_type, str):
        if credential_type != "public-key":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported credential type",
            )
    elif (
        isinstance(credential_type, PublicKeyCredentialType)
        and credential_type is not PublicKeyCredentialType.PUBLIC_KEY
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported credential type",
        )
    return AuthenticationCredential(
        id=credential["id"],
        raw_id=raw_id,
        response=response,
        authenticator_attachment=attachment,
        type=credential_type_value,
    )


class WebAuthnRegistrationVerifier(PasskeyRegistrationVerifier):
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    def __call__(
        self,
        credential: dict[str, Any],
        *,
        expected_challenge: bytes,
        expected_origin: str,
        expected_rp_id: str,
    ) -> RegistrationVerification:
        registration_credential = _parse_registration_credential(credential)
        try:
            verification = verify_registration_response(
                credential=registration_credential,
                expected_challenge=expected_challenge,
                expected_origin=expected_origin,
                expected_rp_id=expected_rp_id,
                require_user_verification=self._settings.passkey_require_user_verification,
            )
        except InvalidRegistrationResponse as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid passkey attestation: {exc}",
            ) from exc

        transports = getattr(verification, "transports", None)
        return RegistrationVerification(
            credential_id=verification.credential_id,
            public_key=verification.credential_public_key,
            sign_count=verification.sign_count,
            aaguid=getattr(verification, "aaguid", None),
            backup_eligible=_is_multi_device(
                getattr(verification, "credential_device_type", None)
            ),
            backup_state=getattr(verification, "credential_backed_up", False),
            transports=list(transports) if transports else None,
        )


class WebAuthnAuthenticationVerifier(PasskeyAuthenticationVerifier):
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    def __call__(
        self,
        credential: dict[str, Any],
        *,
        expected_challenge: bytes,
        credential_record: PasskeyCredential,
        expected_origin: str,
        expected_rp_id: str,
    ) -> AuthenticationVerification:
        authentication_credential = _parse_authentication_credential(credential)
        current_sign_count = credential_record.sign_count or 0
        public_key_bytes = _urlsafe_b64decode(credential_record.public_key)

        try:
            verification = verify_authentication_response(
                credential=authentication_credential,
                expected_challenge=expected_challenge,
                expected_origin=expected_origin,
                expected_rp_id=expected_rp_id,
                credential_public_key=public_key_bytes,
                credential_current_sign_count=current_sign_count,
                require_user_verification=self._settings.passkey_require_user_verification,
            )
        except InvalidAuthenticationResponse as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid passkey assertion: {exc}",
            ) from exc

        device_type = getattr(verification, "credential_device_type", None)
        return AuthenticationVerification(
            new_sign_count=verification.new_sign_count,
            backup_eligible=_is_multi_device(device_type),
            backup_state=getattr(verification, "credential_backed_up", False),
        )


__all__ = [
    "WebAuthnAuthenticationVerifier",
    "WebAuthnRegistrationVerifier",
]
