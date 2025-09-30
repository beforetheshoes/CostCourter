import { Buffer } from 'node:buffer'

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { render, waitFor } from '@testing-library/vue'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../../src/lib/http', () => {
    const post = vi.fn()
    const get = vi.fn()
    return {
        apiClient: { post, get },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { post, get },
    }
})

import AuthCallbackView from '../../src/views/AuthCallbackView.vue'
import { apiClient } from '../../src/lib/http'

const httpClient = apiClient as unknown as {
    post: ReturnType<typeof vi.fn>
    get: ReturnType<typeof vi.fn>
}

const mockedPost = httpClient.post
const mockedGet = httpClient.get

const createJwt = (payload: Record<string, unknown>) => {
    const header = {
        alg: 'none',
        typ: 'JWT',
    }
    const encode = (value: object) =>
        Buffer.from(JSON.stringify(value)).toString('base64url')
    return `${encode(header)}.${encode(payload)}.`
}

const createTestRouter = () =>
    createRouter({
        history: createMemoryHistory(),
        routes: [
            {
                path: '/auth/callback',
                name: 'auth-callback',
                component: AuthCallbackView,
            },
            {
                path: '/',
                name: 'home',
                component: { template: '<div>Home</div>' },
            },
            {
                path: '/settings',
                name: 'settings',
                component: { template: '<div>Settings</div>' },
            },
        ],
    })

describe('AuthCallbackView', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        window.localStorage.clear()
        mockedPost.mockReset()
        mockedGet.mockReset()
    })

    it('completes login and redirects', async () => {
        window.localStorage.setItem(
            'costcourter.postLoginRedirect',
            '/settings',
        )
        const token = createJwt({
            sub: '1',
            scope: 'openid profile admin',
            exp: Math.floor(Date.now() / 1000) + 3600,
        })
        mockedPost.mockResolvedValue({
            data: {
                access_token: token,
                token_type: 'Bearer',
            },
        })
        mockedGet.mockResolvedValue({
            data: {
                id: 1,
                email: 'user@example.com',
                full_name: 'User Example',
                is_superuser: true,
                roles: ['admin'],
            },
        })

        const router = createTestRouter()
        router.push('/auth/callback?state=state-123&code=auth-code')
        await router.isReady()

        render(AuthCallbackView, {
            global: {
                plugins: [router],
            },
        })

        await waitFor(() => {
            expect(mockedPost).toHaveBeenCalledWith('/auth/oidc/callback', {
                state: 'state-123',
                code: 'auth-code',
            })
            expect(mockedGet).toHaveBeenCalledWith('/auth/me')
            expect(router.currentRoute.value.fullPath).toBe('/settings')
            const stored = window.localStorage.getItem('costcourter.tokens')
            expect(stored).not.toBeNull()
            expect(JSON.parse(stored as string)).toMatchObject({
                accessToken: token,
                tokenType: 'Bearer',
            })
            expect(
                window.localStorage.getItem('costcourter.postLoginRedirect'),
            ).toBeNull()
        })
    })

    it('shows an error when the callback is missing parameters', async () => {
        const router = createTestRouter()
        router.push('/auth/callback?state=only-state')
        await router.isReady()

        const { findByText, findByRole } = render(AuthCallbackView, {
            global: {
                plugins: [router],
            },
        })

        expect(await findByText(/Missing state or code/i)).toBeTruthy()
        expect(
            await findByRole('link', { name: /Return to sign-in/i }),
        ).toBeTruthy()
        expect(mockedPost).not.toHaveBeenCalled()
    })

    it('surfaces callback failures and displays the store error', async () => {
        const router = createTestRouter()
        router.push('/auth/callback?state=test-state&code=test-code')
        await router.isReady()

        mockedPost.mockRejectedValue(new Error('callback failed'))
        const consoleSpy = vi
            .spyOn(console, 'error')
            .mockImplementation(() => undefined)

        const { findByText, findByRole } = render(AuthCallbackView, {
            global: {
                plugins: [router],
            },
        })

        expect(await findByText(/Unable to complete sign-in/i)).toBeTruthy()
        expect(await findByText('callback failed')).toBeTruthy()
        expect(
            await findByRole('link', { name: /Return to sign-in/i }),
        ).toBeTruthy()
        expect(mockedGet).not.toHaveBeenCalled()

        consoleSpy.mockRestore()
    })
})
