import { Buffer } from 'node:buffer'

import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'

import { createAppRouter } from '../../src/router'
import { useAuthStore } from '../../src/stores/useAuthStore'

const cloneRouter = () => createAppRouter(createMemoryHistory())

const createJwt = (payload: Record<string, unknown>) => {
    const header = {
        alg: 'none',
        typ: 'JWT',
    }
    const encode = (value: object) =>
        Buffer.from(JSON.stringify(value)).toString('base64url')
    return `${encode(header)}.${encode(payload)}.`
}

describe('router guards', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
    })

    it('redirects unauthenticated users attempting to access protected route', async () => {
        const router = cloneRouter()
        await router.push('/')
        await router.isReady()

        await router.push('/settings').catch(() => {})
        expect(router.currentRoute.value.name).toBe('home')
        expect(router.currentRoute.value.fullPath).toBe('/?redirect=/settings')
    })

    it('blocks products access without admin role', async () => {
        const router = cloneRouter()
        await router.push('/')
        await router.isReady()

        const authStore = useAuthStore()
        authStore.setTokens({
            accessToken: createJwt({
                sub: '1',
                exp: Math.floor(Date.now() / 1000) + 3600,
            }),
            tokenType: 'Bearer',
        })

        await router.push('/products').catch(() => {})
        expect(router.currentRoute.value.name).toBe('home')
    })

    it('allows settings access with admin role', async () => {
        const router = cloneRouter()
        await router.push('/')
        await router.isReady()

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

        await router.push('/settings')
        expect(router.currentRoute.value.name).toBe('settings')
    })
})
