import { Buffer } from 'node:buffer'

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const post = vi.fn()
    const get = vi.fn()
    const interceptors = { request: { use: vi.fn() } }
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
    interceptors: { request: { use: ReturnType<typeof vi.fn> } }
}
const mockedAttach = attachAuthInterceptor as unknown as ReturnType<
    typeof vi.fn
>

const originalBypass = import.meta.env.VITE_AUTH_BYPASS

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

describe('useAuthStore', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        window.localStorage.clear()
        mockedHttp.post.mockReset()
        mockedHttp.get.mockReset()
        mockedHttp.interceptors.request.use.mockReset()
        mockedAttach.mockReset()
        import.meta.env.VITE_AUTH_BYPASS = 'false'
    })

    afterEach(() => {
        import.meta.env.VITE_AUTH_BYPASS = originalBypass
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
        // simulate stored state step
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
        expect(store.accessToken).toBe(token)
        expect(store.tokenType).toBe('Bearer')
        expect(readStoredState()).toBeNull()
        expect(store.roles).toContain('admin')
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
        vi.useRealTimers()
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

    it('respects auth bypass configuration', () => {
        import.meta.env.VITE_AUTH_BYPASS = 'true'
        const store = useAuthStore()
        expect(store.isAuthenticated).toBe(true)
        expect(store.hasRole('admin')).toBe(true)
    })
})
