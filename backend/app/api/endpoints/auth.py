from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models import User
from app.schemas import (
    CurrentUserRead,
    OIDCCallbackRequest,
    OIDCStartRequest,
    OIDCStartResponse,
    PasskeyAssertBeginRequest,
    PasskeyAssertBeginResponse,
    PasskeyAssertCompleteRequest,
    PasskeyAssertionOptions,
    PasskeyRegisterBeginRequest,
    PasskeyRegisterBeginResponse,
    PasskeyRegisterCompleteRequest,
    PasskeyRegistrationOptions,
    TokenResponse,
)
from app.services import user as user_service
from app.services.auth import AuthService, get_auth_service
from app.services.passkeys import PasskeyService, get_passkey_service

router = APIRouter()


@router.post(
    "/oidc/start", response_model=OIDCStartResponse, status_code=status.HTTP_200_OK
)
def oidc_start(
    payload: OIDCStartRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> OIDCStartResponse:
    redirect_uri = str(payload.redirect_uri) if payload.redirect_uri else None
    result = auth_service.start_oidc_flow(redirect_uri=redirect_uri)
    return OIDCStartResponse(
        state=result.state,
        authorization_url=result.authorization_url,
    )


@router.post("/oidc/callback", response_model=TokenResponse)
def oidc_callback(
    payload: OIDCCallbackRequest,
    session: Session = Depends(get_session),
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    result = auth_service.complete_oidc_flow(
        session=session,
        state=payload.state,
        code=payload.code,
    )
    return TokenResponse(access_token=result.access_token, token_type=result.token_type)


@router.post(
    "/passkeys/register/begin",
    response_model=PasskeyRegisterBeginResponse,
    status_code=status.HTTP_200_OK,
)
def passkey_register_begin(
    payload: PasskeyRegisterBeginRequest,
    session: Session = Depends(get_session),
    service: PasskeyService = Depends(get_passkey_service),
) -> PasskeyRegisterBeginResponse:
    result = service.register_begin(
        session,
        email=payload.email,
        full_name=payload.full_name,
    )
    options_model = PasskeyRegistrationOptions.model_validate(result.options)
    return PasskeyRegisterBeginResponse(state=result.state, options=options_model)


@router.post(
    "/passkeys/register/complete",
    response_model=TokenResponse,
)
def passkey_register_complete(
    payload: PasskeyRegisterCompleteRequest,
    session: Session = Depends(get_session),
    service: PasskeyService = Depends(get_passkey_service),
) -> TokenResponse:
    result = service.register_complete(
        session,
        state=payload.state,
        credential=payload.credential.model_dump(),
    )
    return TokenResponse(access_token=result.access_token, token_type=result.token_type)


@router.post(
    "/passkeys/assert/begin",
    response_model=PasskeyAssertBeginResponse,
    status_code=status.HTTP_200_OK,
)
def passkey_assert_begin(
    payload: PasskeyAssertBeginRequest,
    session: Session = Depends(get_session),
    service: PasskeyService = Depends(get_passkey_service),
) -> PasskeyAssertBeginResponse:
    result = service.assert_begin(session, email=payload.email)
    options_model = PasskeyAssertionOptions.model_validate(result.options)
    return PasskeyAssertBeginResponse(state=result.state, options=options_model)


@router.post(
    "/passkeys/assert/complete",
    response_model=TokenResponse,
)
def passkey_assert_complete(
    payload: PasskeyAssertCompleteRequest,
    session: Session = Depends(get_session),
    service: PasskeyService = Depends(get_passkey_service),
) -> TokenResponse:
    result = service.assert_complete(
        session,
        state=payload.state,
        credential=payload.credential.model_dump(),
    )
    return TokenResponse(access_token=result.access_token, token_type=result.token_type)


@router.get("/me", response_model=CurrentUserRead)
def read_current_user(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CurrentUserRead:
    return user_service.build_current_user_response(session, current_user)
