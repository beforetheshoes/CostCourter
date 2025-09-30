import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const axiosCreate = vi.fn()
const headersFrom = vi.fn()

vi.mock('axios', () => ({
    default: { create: axiosCreate },
    AxiosHeaders: { from: headersFrom },
}))

describe('http utilities', () => {
    beforeEach(() => {
        axiosCreate.mockReset()
        headersFrom.mockReset()
    })

    afterEach(() => {
        vi.unstubAllEnvs()
    })

    it('creates an API client with defaults', async () => {
        vi.unstubAllEnvs()
        const { createApiClient } = await import('../../src/lib/http')
        axiosCreate.mockReturnValue({ name: 'client' })

        const client = createApiClient()

        expect(client).toEqual({ name: 'client' })
        expect(axiosCreate).toHaveBeenCalledWith(
            expect.objectContaining({
                baseURL: '/api',
                headers: { 'Content-Type': 'application/json' },
                withCredentials: true,
            }),
        )
    })

    it('respects explicit baseURL when creating client', async () => {
        vi.stubEnv('VITE_API_BASE_URL', 'https://env.example')
        const { createApiClient } = await import('../../src/lib/http')
        axiosCreate.mockReturnValue({ name: 'client' })

        createApiClient({ baseURL: 'https://override.example' })

        expect(axiosCreate).toHaveBeenCalledWith(
            expect.objectContaining({ baseURL: 'https://override.example' }),
        )
    })

    it('attaches auth interceptor using header set shortcut', async () => {
        const { attachAuthInterceptor } = await import('../../src/lib/http')
        const setFn = vi.fn()
        const useFn = vi.fn((handler) => handler({ headers: { set: setFn } }))
        const tokenProvider = vi.fn(() => 'token-123')

        attachAuthInterceptor(
            { interceptors: { request: { use: useFn } } } as never,
            tokenProvider,
        )

        expect(useFn).toHaveBeenCalled()
        expect(setFn).toHaveBeenCalledWith('Authorization', 'Bearer token-123')
    })

    it('attaches auth interceptor by creating AxiosHeaders when needed', async () => {
        const customHeaders = {
            set: vi.fn(),
        }
        headersFrom.mockReturnValue(customHeaders)
        const { attachAuthInterceptor } = await import('../../src/lib/http')
        const useFn = vi.fn((handler) => handler({ headers: undefined }))

        attachAuthInterceptor(
            { interceptors: { request: { use: useFn } } } as never,
            () => 'token-xyz',
        )

        expect(headersFrom).toHaveBeenCalled()
        expect(customHeaders.set).toHaveBeenCalledWith(
            'Authorization',
            'Bearer token-xyz',
        )
    })

    it('ignores missing tokens when adding interceptor', async () => {
        const { attachAuthInterceptor } = await import('../../src/lib/http')
        headersFrom.mockReturnValue({ set: vi.fn() })
        const useFn = vi.fn((handler) => handler({ headers: {} }))

        attachAuthInterceptor(
            { interceptors: { request: { use: useFn } } } as never,
            () => null,
        )

        expect(headersFrom).not.toHaveBeenCalled()
    })
})
