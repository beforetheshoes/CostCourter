export type PublicKeyCredentialCreationOptionsJSON = {
    challenge: string
    rp: PublicKeyCredentialRpEntity
    user: PublicKeyCredentialUserEntity & { id: string }
    pubKeyCredParams: PublicKeyCredentialParameters[]
    timeout?: number
    excludeCredentials?: Array<PublicKeyCredentialDescriptor & { id: string }>
    authenticatorSelection?: AuthenticatorSelectionCriteria
    attestation?: AttestationConveyancePreference
    extensions?: AuthenticationExtensionsClientInputs
}

export type PublicKeyCredentialRequestOptionsJSON = {
    challenge: string
    rpId?: string
    allowCredentials?: Array<PublicKeyCredentialDescriptor & { id: string }>
    timeout?: number
    userVerification?: UserVerificationRequirement
    extensions?: AuthenticationExtensionsClientInputs
}

const toBase64 = (value: string): string =>
    value
        .replace(/-/g, '+')
        .replace(/_/g, '/')
        .padEnd(Math.ceil(value.length / 4) * 4, '=')

const decodeBase64 = (value: string): string => {
    if (typeof atob === 'function') {
        return atob(value)
    }
    const bufferCtor = (globalThis as Record<string, unknown>).Buffer as
        | {
              from(
                  data: string,
                  encoding: string,
              ): {
                  toString(encoding: string): string
              }
          }
        | undefined
    if (bufferCtor) {
        return bufferCtor.from(value, 'base64').toString('binary')
    }
    throw new Error('No base64 decoder available in this environment.')
}

const encodeBase64 = (value: string): string => {
    if (typeof btoa === 'function') {
        return btoa(value)
    }
    const bufferCtor = (globalThis as Record<string, unknown>).Buffer as
        | {
              from(
                  data: string,
                  encoding: string,
              ): {
                  toString(encoding: string): string
              }
          }
        | undefined
    if (bufferCtor) {
        return bufferCtor.from(value, 'binary').toString('base64')
    }
    throw new Error('No base64 encoder available in this environment.')
}

const base64UrlToUint8Array = (value: string): Uint8Array => {
    const base64 = toBase64(value)
    const rawData = decodeBase64(base64)
    const output = new Uint8Array(rawData.length)
    for (let i = 0; i < rawData.length; i += 1) {
        output[i] = rawData.charCodeAt(i)
    }
    return output
}

const cloneArrayBuffer = (buffer: ArrayBuffer): ArrayBuffer => buffer.slice(0)

const arrayBufferToBase64Url = (buffer: ArrayBuffer): string => {
    const bytes = new Uint8Array(buffer)
    let binary = ''
    bytes.forEach((byte) => {
        binary += String.fromCharCode(byte)
    })
    const base64 = encodeBase64(binary)
    return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

export const decodeCreationOptions = (
    options: PublicKeyCredentialCreationOptionsJSON,
): PublicKeyCredentialCreationOptions => ({
    ...options,
    challenge: cloneArrayBuffer(
        base64UrlToUint8Array(options.challenge).buffer,
    ),
    user: {
        ...options.user,
        id: cloneArrayBuffer(base64UrlToUint8Array(options.user.id).buffer),
    },
    excludeCredentials: options.excludeCredentials?.map((descriptor) => ({
        ...descriptor,
        id: cloneArrayBuffer(base64UrlToUint8Array(descriptor.id).buffer),
    })),
})

export const decodeRequestOptions = (
    options: PublicKeyCredentialRequestOptionsJSON,
): PublicKeyCredentialRequestOptions => ({
    ...options,
    challenge: cloneArrayBuffer(
        base64UrlToUint8Array(options.challenge).buffer,
    ),
    allowCredentials: options.allowCredentials?.map((descriptor) => {
        const mapped: PublicKeyCredentialDescriptor = {
            type: descriptor.type,
            id: cloneArrayBuffer(base64UrlToUint8Array(descriptor.id).buffer),
        }
        if (Array.isArray(descriptor.transports)) {
            mapped.transports = [...descriptor.transports]
        }
        return mapped
    }),
})

export const publicKeyCredentialToJSON = (
    credential: PublicKeyCredential,
): Record<string, unknown> => {
    const clientExtensionResults =
        typeof credential.getClientExtensionResults === 'function'
            ? credential.getClientExtensionResults()
            : {}
    const json: Record<string, unknown> = {
        id: credential.id,
        rawId: arrayBufferToBase64Url(credential.rawId),
        type: credential.type,
        clientExtensionResults,
    }

    if ('authenticatorAttachment' in credential) {
        json.authenticatorAttachment = credential.authenticatorAttachment
    }

    const response = credential.response
    const isAttestationResponse =
        (typeof AuthenticatorAttestationResponse !== 'undefined' &&
            response instanceof AuthenticatorAttestationResponse) ||
        'attestationObject' in response
    if (isAttestationResponse) {
        const attestation = response as AuthenticatorAttestationResponse & {
            getTransports?: () => AuthenticatorTransport[]
        }
        json.response = {
            clientDataJSON: arrayBufferToBase64Url(attestation.clientDataJSON),
            attestationObject: arrayBufferToBase64Url(
                attestation.attestationObject,
            ),
            transports:
                typeof attestation.getTransports === 'function'
                    ? attestation.getTransports()
                    : undefined,
        }
    } else {
        const assertion = response as AuthenticatorAssertionResponse & {
            userHandle?: ArrayBuffer | null
        }
        json.response = {
            clientDataJSON: arrayBufferToBase64Url(assertion.clientDataJSON),
            authenticatorData: arrayBufferToBase64Url(
                assertion.authenticatorData,
            ),
            signature: arrayBufferToBase64Url(assertion.signature),
            userHandle:
                assertion.userHandle && assertion.userHandle.byteLength > 0
                    ? arrayBufferToBase64Url(assertion.userHandle)
                    : null,
        }
    }

    return json
}

export const ensurePasskeySupport = () => {
    if (typeof window === 'undefined') {
        throw new Error('Passkeys are only available in a browser environment.')
    }
    const secureContext =
        window.isSecureContext ||
        ['localhost', '127.0.0.1'].includes(window.location.hostname)
    if (!secureContext) {
        throw new Error('Passkeys require HTTPS (or localhost) to operate.')
    }
    const hasCredentials =
        typeof navigator !== 'undefined' &&
        !!navigator.credentials &&
        typeof navigator.credentials.create === 'function' &&
        typeof navigator.credentials.get === 'function'
    const hasPublicKey = typeof window.PublicKeyCredential !== 'undefined'
    if (!hasCredentials || !hasPublicKey) {
        throw new Error('Passkeys are not supported in this browser yet.')
    }
}
