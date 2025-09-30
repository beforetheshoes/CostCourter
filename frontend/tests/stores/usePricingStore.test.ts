import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const post = vi.fn()
    const get = vi.fn()
    const put = vi.fn()
    return {
        apiClient: { post, get, put },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { post, get, put },
    }
})

import { apiClient } from '../../src/lib/http'
import { usePricingStore } from '../../src/stores/usePricingStore'

const mockedHttp = apiClient as unknown as {
    post: ReturnType<typeof vi.fn>
    get: ReturnType<typeof vi.fn>
    put: ReturnType<typeof vi.fn>
}
const { post: mockedPost, get: mockedGet, put: mockedPut } = mockedHttp

describe('usePricingStore', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mockedPost.mockReset()
        mockedGet.mockReset()
        mockedPut.mockReset()
    })

    afterEach(() => {
        mockedPost.mockReset()
        mockedGet.mockReset()
        mockedPut.mockReset()
    })

    it('stores summary on success', async () => {
        mockedPost.mockResolvedValue({
            data: {
                total_urls: 2,
                successful_urls: 2,
                failed_urls: 0,
                results: [],
            },
        })

        const store = usePricingStore()
        await store.refreshAll()

        expect(store.summary?.total_urls).toBe(2)
        expect(store.error).toBeNull()
        expect(mockedPost).toHaveBeenCalledWith(
            '/pricing/products/fetch-all',
            undefined,
            { params: undefined },
        )
    })

    it('captures error state on failure', async () => {
        mockedPost.mockRejectedValue(new Error('boom'))

        const store = usePricingStore()
        await expect(store.refreshAll()).resolves.toBeUndefined()

        expect(store.summary).toBeNull()
        expect(store.error).toBe('boom')
    })

    it('loads scheduling metadata', async () => {
        mockedGet.mockResolvedValue({
            data: {
                entries: [
                    {
                        name: 'pricing.update_all_products',
                        task: 'pricing.update_all_products',
                        schedule: 3600,
                        next_run_at: '2025-09-27T10:00:00Z',
                        last_run_at: '2025-09-27T09:00:00Z',
                    },
                ],
            },
        })

        const store = usePricingStore()
        const entries = await store.loadSchedule()

        expect(entries).toHaveLength(1)
        expect(entries[0]?.next_run_at).toBe('2025-09-27T10:00:00Z')
        expect(mockedGet).toHaveBeenCalledWith('/pricing/schedule')
    })

    it('sanitises computed fields before updating schedule', async () => {
        mockedPut.mockResolvedValue({
            data: {
                entries: [
                    {
                        name: 'pricing.update_all_products',
                        task: 'pricing.update_all_products',
                        schedule: 7200,
                        enabled: true,
                    },
                ],
            },
        })

        const store = usePricingStore()
        const entries = await store.updateSchedule([
            {
                name: 'pricing.update_all_products',
                task: 'pricing.update_all_products',
                schedule: 7200,
                next_run_at: '2025-09-27T10:00:00Z',
                last_run_at: '2025-09-27T09:00:00Z',
            },
        ])

        expect(entries).toHaveLength(1)
        expect(mockedPut).toHaveBeenCalledWith('/pricing/schedule', {
            entries: [
                {
                    name: 'pricing.update_all_products',
                    task: 'pricing.update_all_products',
                    schedule: 7200,
                },
            ],
        })
    })

    it('returns empty schedule when load fails', async () => {
        mockedGet.mockRejectedValue(new Error('timeout'))
        const store = usePricingStore()

        const entries = await store.loadSchedule()

        expect(entries).toEqual([])
        expect(store.error).toBeNull()
    })

    it('propagates update errors and records message', async () => {
        mockedPut.mockRejectedValue(new Error('save failed'))
        const store = usePricingStore()

        await expect(
            store.updateSchedule([
                {
                    name: 'job',
                    task: 'job',
                },
            ]),
        ).rejects.toThrow('save failed')
        expect(store.error).toBe('save failed')
    })

    it('refreshes individual products and propagates summary', async () => {
        mockedPost.mockResolvedValue({
            data: {
                total_urls: 1,
                successful_urls: 1,
                failed_urls: 0,
                results: [],
            },
        })

        const store = usePricingStore()
        const summary = await store.refreshProduct(123, true)

        expect(mockedPost).toHaveBeenCalledWith(
            '/pricing/products/123/fetch',
            undefined,
            { params: { logging: true } },
        )
        expect(summary?.total_urls).toBe(1)
        expect(store.summary?.failed_urls).toBe(0)
    })

    it('captures errors when refreshing individual products', async () => {
        mockedPost.mockRejectedValue(new Error('bad request'))

        const store = usePricingStore()
        await expect(store.refreshProduct(87)).rejects.toThrow('bad request')
        expect(store.error).toBe('bad request')
    })
})
