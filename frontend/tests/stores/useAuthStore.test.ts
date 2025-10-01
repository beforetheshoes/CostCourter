import { Buffer } from 'node:buffer'

import {
    beforeAll,
    afterAll,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const post = vi.fn()
    const get = vi.fn()
    const interceptors = {
        request: { use: vi.fn() },
        response: { use: vi.fn() },
    }
    const attachAuthInterceptor = vi.fn()
    return {
        apiClient: { post, get, interceptors },
        createApiClient: vi.fn(),
        attachAuthInterceptor,
        __mock: { post, get, interceptors, attachAuthInterceptor },
    }
})

import { apiClient, attachAuthInterceptor } from '../../src/lib/http'
import {
    registerAuthInterceptor,
    useAuthStore,
} from '../../src/stores/useAuthStore'

const mockedHttp = apiClient as unknown as {
    post: ReturnType<typeof vi.fn>
    get: ReturnType<typeof vi.fn>
    interceptors: {
        request: { use: ReturnType<typeof vi.fn> }
        response: { use: ReturnType<typeof vi.fn> }
    }
}
const mockedAttach = attachAuthInterceptor as unknown as ReturnType<
    typeof vi.fn
>

let credentialCreateMock: ReturnType<typeof vi.fn>
let credentialGetMock: ReturnType<typeof vi.fn>

const readStoredState = () =>
    window.localStorage.getItem('costcourter.oidc.state')

const readStoredTokens = () => window.localStorage.getItem('costcourter.tokens')

const createJwt = (payload: Record<string, unknown>) => {
    const header = {
        alg: 'none',
        typ: 'JWT',
    }
    const encode = (value: object) =>
        Buffer.from(JSON.stringify(value)).toString('base64url')
    return `${encode(header)}.${encode(payload)}.`
}

const toBase64Url = (value: Uint8Array | string) => {
    const buffer =
        typeof value === 'string'
            ? Buffer.from(value, 'utf8')
            : Buffer.from(value)
    return buffer
        .toString('base64')
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/g, '')
}

const bufferFrom = (...bytes: number[]) => Uint8Array.from(bytes).buffer

beforeAll(() => {
    credentialCreateMock = vi.fn()
    credentialGetMock = vi.fn()
    Object.defineProperty(window, 'isSecureContext', {
        configurable: true,
        value: true,
    })
    Object.defineProperty(window, 'PublicKeyCredential', {
        configurable: true,
        value: class PublicKeyCredential {},
    })
    Object.defineProperty(navigator, 'credentials', {
        configurable: true,
        get() {
            return {
                create: (...args: unknown[]) => credentialCreateMock(...args),
                get: (...args: unknown[]) => credentialGetMock(...args),
            }
        },
    })
})

afterAll(() => {
    delete (navigator as unknown as Record<string, unknown>).credentials
    delete (window as Record<string, unknown>).PublicKeyCredential
})

describe('useAuthStore', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        window.localStorage.clear()
        mockedHttp.post.mockReset()
        mockedHttp.get.mockReset()
        mockedHttp.interceptors.request.use.mockReset()
        mockedHttp.interceptors.response.use.mockReset()
        mockedAttach.mockReset()
        credentialCreateMock = vi.fn()
        credentialGetMock = vi.fn()
    })

    it('stores OIDC state on begin and returns redirect URL', async () => {
        mockedHttp.post.mockResolvedValue({
            data: {
                state: 'state-123',
                authorization_url: 'https://auth.example.com/authorize',
            },
        })

        vi.useFakeTimers()
        const store = useAuthStore()
        const result = await store.beginOidcLogin('https://app/callback')

        expect(mockedHttp.post).toHaveBeenCalledWith('/auth/oidc/start', {
            redirect_uri: 'https://app/callback',
        })
        expect(result.authorization_url).toContain('https://auth.example.com')
        expect(store.oidcState?.state).toBe('state-123')
        expect(readStoredState()).toContain('state-123')
        vi.useRealTimers()
    })

    it('completes OIDC login and stores tokens', async () => {
        mockedHttp.post.mockResolvedValueOnce({
            data: {
                state: 'state-abc',
                authorization_url: 'https://auth.example.com',
            },
        })
        const token = createJwt({
            sub: '1',
            scope: 'openid email profile admin',
            exp: Math.floor(Date.now() / 1000) + 3600,
        })
        mockedHttp.post.mockResolvedValueOnce({
            data: {
                access_token: token,
                token_type: 'Bearer',
            },
        })
        mockedHttp.get.mockResolvedValueOnce({
            data: {
                id: 1,
                email: 'user@example.com',
                full_name: 'User Example',
                is_superuser: true,
                roles: ['catalog'],
            },
        })

        const store = useAuthStore()
        await store.beginOidcLogin()
        await store.completeOidcLogin({ state: 'state-abc', code: 'auth-code' })

        expect(mockedHttp.post).toHaveBeenLastCalledWith(
            '/auth/oidc/callback',
            { state: 'state-abc', code: 'auth-code' },
        )
        expect(mockedHttp.get).toHaveBeenCalledWith('/auth/me')
        expect(store.isAuthenticated).toBe(true)
        const stored = readStoredTokens()
        expect(stored).not.toBeNull()
        expect(JSON.parse(stored as string)).toMatchObject({
            accessToken: token,
            tokenType: 'Bearer',
        })
        expect(store.roles).toContain('admin')
        expect(readStoredState()).toBeNull()
    })

    it('clears state and tokens on logout', () => {
        window.localStorage.setItem(
            'costcourter.tokens',
            JSON.stringify({ accessToken: 'abc', tokenType: 'Bearer' }),
        )
        window.localStorage.setItem(
            'costcourter.oidc.state',
            JSON.stringify({ state: 's', createdAt: new Date().toISOString() }),
        )

        const store = useAuthStore()
        store.logout(false)
        expect(store.isAuthenticated).toBe(false)
        expect(readStoredTokens()).toBeNull()
        expect(readStoredState()).toBeNull()
    })

    it('registers auth interceptor', () => {
        registerAuthInterceptor()
        expect(mockedAttach).toHaveBeenCalled()
        const provider = mockedAttach.mock.calls[0][1] as () => string | null
        const store = useAuthStore()
        expect(provider()).toBeNull()
        const token = createJwt({
            exp: Math.floor(Date.now() / 1000) + 3600,
        })
        store.setTokens({ accessToken: token, tokenType: 'Bearer' })
        expect(provider()).toBe(token)
        store.logout(false)
    })

    it('extracts roles from claims and current user data', () => {
        const store = useAuthStore()
        const token = createJwt({
            scope: 'profile admin',
            exp: Math.floor(Date.now() / 1000) + 600,
        })
        store.setTokens({ accessToken: token, tokenType: 'Bearer' })
        store.currentUser = {
            id: 2,
            email: 'admin@example.com',
            full_name: 'Admin Example',
            is_superuser: true,
            roles: ['support'],
        }
        expect(store.roles).toContain('admin')
        store.setTokens(null)
        expect(store.claims).toBeNull()
        expect(store.roles).toEqual([])
    })

    it('schedules and clears token refresh timers', () => {
        vi.useFakeTimers()
        const store = useAuthStore()
        const expSoon = Math.floor(Date.now() / 1000) + 120
        store.claims = { exp: expSoon }
        const logoutSpy = vi.spyOn(store, 'logout').mockImplementation(() => {})

        store.scheduleTokenRefresh()
        expect(store.refreshTimer).not.toBeNull()
        vi.advanceTimersByTime(70_000)
        expect(store.error).toBe('Session expired. Please sign in again.')
        expect(logoutSpy).toHaveBeenCalledWith(false)

        logoutSpy.mockReset()
        store.claims = { exp: Math.floor(Date.now() / 1000) + 3_600 }
        store.scheduleTokenRefresh()
        expect(store.refreshTimer).not.toBeNull()
        store.clearRefreshTimer()
        expect(store.refreshTimer).toBeNull()
        vi.useRealTimers()
        logoutSpy.mockRestore()
    })

    it('handles error cases for auth flows', async () => {
        mockedHttp.post.mockRejectedValueOnce(new Error('network down'))
        const store = useAuthStore()
        await expect(store.beginOidcLogin()).rejects.toThrow('network down')
        expect(store.error).toBe('network down')

        mockedHttp.post.mockResolvedValueOnce({
            data: { state: 's', authorization_url: 'x' },
        })
        await store.beginOidcLogin()
        mockedHttp.post.mockRejectedValueOnce(new Error('callback failed'))
        await expect(
            store.completeOidcLogin({ state: 's', code: 'bad' }),
        ).rejects.toThrow('callback failed')
        expect(store.error).toBe('callback failed')

        mockedHttp.get.mockRejectedValueOnce(new Error('me failed'))
        const validToken = createJwt({
            exp: Math.floor(Date.now() / 1000) + 3600,
        })
        store.setTokens({ accessToken: validToken, tokenType: 'Bearer' })
        await store.fetchCurrentUser()
        expect(store.error).toBe('me failed')
        store.clearRefreshTimer()
    })

    it('registers a passkey and stores tokens', async () => {
        const challenge = Uint8Array.from([1, 2, 3])
        const rawId = Uint8Array.from([4, 5, 6])
        const userEmail = 'user@example.com'
        mockedHttp.post.mockResolvedValueOnce({
            data: {
                state: 'passkey-state',
                options: {
                    challenge: toBase64Url(challenge),
                    rp: { id: 'localhost', name: 'CostCourter' },
                    user: {
                        id: toBase64Url(userEmail),
                        name: userEmail,
                        displayName: 'User Example',
                    },
                    pubKeyCredParams: [],
                    timeout: 60_000,
                },
            },
        })
        const token = createJwt({
            sub: '1',
            exp: Math.floor(Date.now() / 1000) + 3600,
        })
        mockedHttp.post.mockResolvedValueOnce({
            data: { access_token: token, token_type: 'Bearer' },
        })
        mockedHttp.get.mockResolvedValueOnce({
            data: {
                id: 1,
                email: userEmail,
                full_name: 'User Example',
                is_superuser: false,
                roles: ['catalog'],
            },
        })

        const fakeCredential = {
            id: 'cred-id',
            rawId: rawId.buffer,
            type: 'public-key',
            response: {
                clientDataJSON: bufferFrom(10, 11, 12),
                attestationObject: bufferFrom(20, 21, 22),
                getTransports: vi.fn(() => ['internal']),
            },
            getClientExtensionResults: () => ({}),
        } as unknown as PublicKeyCredential

        credentialCreateMock.mockResolvedValue(fakeCredential)

        const store = useAuthStore()
        await store.registerPasskey({
            email: userEmail,
            fullName: 'User Example',
        })

        expect(mockedHttp.post).toHaveBeenNthCalledWith(
            1,
            '/auth/passkeys/register/begin',
            {
                email: userEmail,
                full_name: 'User Example',
            },
        )
        const createArgs = credentialCreateMock.mock.calls[0][0]
        expect(createArgs.publicKey.challenge).toBeInstanceOf(ArrayBuffer)
        expect(mockedHttp.post).toHaveBeenNthCalledWith(
            2,
            '/auth/passkeys/register/complete',
            expect.objectContaining({ state: 'passkey-state' }),
        )
        expect(store.isAuthenticated).toBe(true)
        expect(store.currentUser?.email).toBe(userEmail)
    })

    it('authenticates with an existing passkey', async () => {
        const challenge = Uint8Array.from([7, 8, 9])
        const credentialId = Uint8Array.from([9, 8, 7])
        const userEmail = 'admin@example.com'
        mockedHttp.post.mockResolvedValueOnce({
            data: {
                state: 'assert-state',
                options: {
                    challenge: toBase64Url(challenge),
                    rpId: 'localhost',
                    allowCredentials: [
                        {
                            type: 'public-key',
                            id: toBase64Url(credentialId),
                        },
                    ],
                    timeout: 60_000,
                },
            },
        })
        const token = createJwt({
            sub: '42',
            exp: Math.floor(Date.now() / 1000) + 3600,
        })
        mockedHttp.post.mockResolvedValueOnce({
            data: { access_token: token, token_type: 'Bearer' },
        })
        mockedHttp.get.mockResolvedValueOnce({
            data: {
                id: 42,
                email: userEmail,
                full_name: 'Admin User',
                is_superuser: true,
                roles: ['admin'],
            },
        })

        const assertionCredential = {
            id: 'cred-id',
            rawId: credentialId.buffer,
            type: 'public-key',
            response: {
                clientDataJSON: bufferFrom(1, 2, 3),
                authenticatorData: bufferFrom(4, 5, 6),
                signature: bufferFrom(7, 8, 9),
                userHandle: bufferFrom(10, 11, 12),
            },
            getClientExtensionResults: () => ({}),
        } as unknown as PublicKeyCredential

        credentialGetMock.mockResolvedValue(assertionCredential)

        const store = useAuthStore()
        await store.authenticatePasskey(userEmail)

        expect(mockedHttp.post).toHaveBeenNthCalledWith(
            1,
            '/auth/passkeys/assert/begin',
            { email: userEmail },
        )
        const getArgs = credentialGetMock.mock.calls[0][0]
        expect(getArgs.publicKey.challenge).toBeInstanceOf(ArrayBuffer)
        expect(mockedHttp.post).toHaveBeenNthCalledWith(
            2,
            '/auth/passkeys/assert/complete',
            expect.objectContaining({ state: 'assert-state' }),
        )
        expect(store.isAuthenticated).toBe(true)
        expect(store.currentUser?.email).toBe(userEmail)
    })

    it('handles unauthorized responses via auth interceptor', async () => {
        const store = useAuthStore()
        const logoutSpy = vi.spyOn(store, 'logout').mockImplementation(() => {})
        registerAuthInterceptor()

        const onRejected = mockedHttp.interceptors.response.use.mock.calls[0][1]
        const replaceSpy = vi.fn()
        const originalLocation = window.location
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: {
                pathname: '/products',
                search: '?q=1',
                hash: '#section',
                replace: replaceSpy,
            },
        })

        await expect(
            onRejected({ response: { status: 401 } }),
        ).rejects.toBeTruthy()
        expect(logoutSpy).toHaveBeenCalledWith(false)
        expect(
            window.localStorage.getItem('costcourter.postLoginRedirect'),
        ).toBe('/products?q=1#section')
        expect(replaceSpy).toHaveBeenCalledWith('/')
        logoutSpy.mockRestore()
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: originalLocation,
        })
    })

    it('clears state and redirects to home on logout', () => {
        const store = useAuthStore()
        store.tokens = {
            accessToken: 'token',
            tokenType: 'Bearer',
        }
        store.claims = { exp: Math.floor(Date.now() / 1000) + 3600 }
        store.roles = ['admin']
        store.currentUser = {
            id: 1,
            email: 'person@example.com',
            full_name: 'Person Example',
            is_superuser: true,
            roles: ['admin'],
        }

        let href = 'http://localhost/login'
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: {
                get href() {
                    return href
                },
                set href(value: string) {
                    href = value
                },
            },
        })

        store.logout()

        expect(store.isAuthenticated).toBe(false)
        expect(href).toBe('/')

        Object.defineProperty(window, 'location', {
            configurable: true,
            value: {
                href,
            },
        })
    })
})
