import { Buffer } from 'node:buffer'

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

import { createAuthGuard } from '../../src/router'
import { useAuthStore } from '../../src/stores/useAuthStore'

const createJwt = (payload: Record<string, unknown>) => {
    const header = {
        alg: 'none',
        typ: 'JWT',
    }
    const encode = (value: object) =>
        Buffer.from(JSON.stringify(value)).toString('base64url')
    return `${encode(header)}.${encode(payload)}.`
}

const createRoute = (
    overrides: Partial<RouteLocationNormalizedLoaded>,
): RouteLocationNormalizedLoaded =>
    ({
        path: '/',
        name: 'login',
        params: {},
        query: {},
        hash: '',
        fullPath: '/',
        matched: [],
        redirectedFrom: undefined,
        meta: {},
        ...overrides,
    }) as RouteLocationNormalizedLoaded

describe('router guards', () => {
    beforeEach(() => {
        window.localStorage.clear()
        setActivePinia(createPinia())
        useAuthStore().$reset()
    })

    it('redirects unauthenticated users attempting to access protected routes', () => {
        const authStore = useAuthStore()
        const guard = createAuthGuard(() => authStore)
        const next = vi.fn()

        guard(
            createRoute({
                name: 'settings',
                fullPath: '/settings',
                meta: { requiresAuth: true, requiredRole: 'admin' },
            }),
            createRoute({}),
            next,
        )

        expect(next).toHaveBeenCalledWith({
            name: 'login',
            query: { redirect: '/settings' },
        })
    })

    it('redirects non-admin users when accessing admin-only routes', () => {
        const authStore = useAuthStore()
        authStore.setTokens({
            accessToken: createJwt({
                sub: '1',
                exp: Math.floor(Date.now() / 1000) + 3600,
            }),
            tokenType: 'Bearer',
        })

        const guard = createAuthGuard(() => authStore)
        const next = vi.fn()

        guard(
            createRoute({
                name: 'products',
                fullPath: '/products',
                meta: { requiresAuth: true, requiredRole: 'admin' },
            }),
            createRoute({}),
            next,
        )

        expect(next).toHaveBeenCalledWith({
            name: 'login',
            query: { redirect: '/products' },
        })
    })

    it('allows access when user satisfies role requirements', () => {
        const authStore = useAuthStore()
        authStore.setTokens({
            accessToken: createJwt({
                sub: '1',
                scope: 'admin',
                exp: Math.floor(Date.now() / 1000) + 3600,
            }),
            tokenType: 'Bearer',
        })
        authStore.roles = ['admin']

        const guard = createAuthGuard(() => authStore)
        const next = vi.fn()

        guard(
            createRoute({
                name: 'settings',
                fullPath: '/settings',
                meta: { requiresAuth: true, requiredRole: 'admin' },
            }),
            createRoute({}),
            next,
        )

        expect(next).toHaveBeenCalledWith()
    })

    it('redirects authenticated users away from login', () => {
        const authStore = useAuthStore()
        authStore.setTokens({
            accessToken: createJwt({
                sub: '1',
                exp: Math.floor(Date.now() / 1000) + 3600,
            }),
            tokenType: 'Bearer',
        })

        const guard = createAuthGuard(() => authStore)
        const next = vi.fn()

        guard(createRoute({ name: 'login' }), createRoute({}), next)

        expect(next).toHaveBeenCalledWith({ name: 'dashboard' })
    })
})
