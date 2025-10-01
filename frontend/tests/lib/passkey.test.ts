import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
    decodeCreationOptions,
    decodeRequestOptions,
    ensurePasskeySupport,
    publicKeyCredentialToJSON,
} from '../../src/lib/passkey'

const base64Url = (bytes: number[]): string =>
    Buffer.from(Uint8Array.from(bytes)).toString('base64url')

describe('passkey utilities', () => {
    const originalWindow = {
        isSecureContext: globalThis.window?.isSecureContext,
        location: globalThis.window?.location,
        PublicKeyCredential: (globalThis as Record<string, unknown>)
            .PublicKeyCredential,
    }
    const originalNavigator = globalThis.navigator

    beforeEach(() => {
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: {
                hostname: 'localhost',
                pathname: '/dashboard',
                search: '?foo=bar',
                hash: '#section',
            },
        })
        Object.defineProperty(window, 'isSecureContext', {
            configurable: true,
            value: true,
        })
        Object.defineProperty(window, 'PublicKeyCredential', {
            configurable: true,
            value: class PublicKeyCredential {},
        })
        Object.defineProperty(globalThis, 'navigator', {
            configurable: true,
            value: {
                credentials: {
                    create: vi.fn(),
                    get: vi.fn(),
                },
            },
        })
    })

    afterEach(() => {
        Object.defineProperty(window, 'isSecureContext', {
            configurable: true,
            value: originalWindow.isSecureContext,
        })
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: originalWindow.location,
        })
        if (originalWindow.PublicKeyCredential) {
            Object.defineProperty(window, 'PublicKeyCredential', {
                configurable: true,
                value: originalWindow.PublicKeyCredential,
            })
        } else {
            delete (window as Record<string, unknown>).PublicKeyCredential
        }
        Object.defineProperty(globalThis, 'navigator', {
            configurable: true,
            value: originalNavigator,
        })
        vi.restoreAllMocks()
    })

    it('decodes creation options and converts identifiers', () => {
        const options = decodeCreationOptions({
            challenge: base64Url([1, 2, 3]),
            rp: { id: 'localhost', name: 'CostCourter' },
            user: {
                id: base64Url([4, 5]),
                name: 'user@example.com',
                displayName: 'User Example',
            },
            pubKeyCredParams: [],
            excludeCredentials: [
                {
                    id: base64Url([6, 7]),
                    type: 'public-key',
                    transports: ['hybrid'],
                },
            ],
        })

        expect(options.challenge).toBeInstanceOf(ArrayBuffer)
        expect(new Uint8Array(options.challenge)).toEqual(
            Uint8Array.from([1, 2, 3]),
        )
        expect(new Uint8Array(options.user.id)).toEqual(Uint8Array.from([4, 5]))
        expect(options.excludeCredentials?.[0].id).toBeInstanceOf(ArrayBuffer)
    })

    it('decodes request options and clones credential descriptors', () => {
        const options = decodeRequestOptions({
            challenge: base64Url([9, 8, 7]),
            allowCredentials: [
                {
                    id: base64Url([3, 2, 1]),
                    type: 'public-key',
                    transports: ['internal'],
                },
            ],
        })

        expect(options.challenge).toBeInstanceOf(ArrayBuffer)
        const descriptor = options.allowCredentials?.[0]
        expect(descriptor?.id).toBeInstanceOf(ArrayBuffer)
        expect(descriptor?.transports).toEqual(['internal'])
    })

    it('serialises attestation and assertion responses to JSON', () => {
        const attestationCredential = {
            id: 'att-id',
            rawId: Uint8Array.from([1, 2, 3]).buffer,
            type: 'public-key',
            response: {
                clientDataJSON: Uint8Array.from([4]).buffer,
                attestationObject: Uint8Array.from([5]).buffer,
                getTransports: () => ['usb'],
            },
            getClientExtensionResults: () => ({ foo: 'bar' }),
        } as unknown as PublicKeyCredential

        const assertionCredential = {
            id: 'assert-id',
            rawId: Uint8Array.from([9]).buffer,
            type: 'public-key',
            response: {
                clientDataJSON: Uint8Array.from([10]).buffer,
                authenticatorData: Uint8Array.from([11]).buffer,
                signature: Uint8Array.from([12]).buffer,
                userHandle: Uint8Array.from([13]).buffer,
            },
            getClientExtensionResults: () => ({}),
        } as unknown as PublicKeyCredential

        const attestationJson = publicKeyCredentialToJSON(attestationCredential)
        const assertionJson = publicKeyCredentialToJSON(assertionCredential)

        expect(attestationJson.response).toMatchObject({
            attestationObject: expect.any(String),
            clientDataJSON: expect.any(String),
            transports: ['usb'],
        })
        expect(assertionJson.response).toMatchObject({
            authenticatorData: expect.any(String),
            signature: expect.any(String),
            userHandle: expect.any(String),
        })
    })

    it('validates browser support for passkeys', () => {
        expect(() => ensurePasskeySupport()).not.toThrow()

        Object.defineProperty(window, 'isSecureContext', {
            configurable: true,
            value: false,
        })
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: {
                hostname: 'example.com',
            },
        })
        expect(() => ensurePasskeySupport()).toThrow('Passkeys require HTTPS')

        Object.defineProperty(window, 'isSecureContext', {
            configurable: true,
            value: true,
        })
        Object.defineProperty(globalThis, 'navigator', {
            configurable: true,
            value: {
                credentials: undefined,
            },
        })
        expect(() => ensurePasskeySupport()).toThrow('not supported')
    })
})
