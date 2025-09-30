import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const get = vi.fn()
    return {
        apiClient: { get },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { get },
    }
})

import { apiClient } from '../../src/lib/http'
import { useAdminMetricsStore } from '../../src/stores/useAdminMetricsStore'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
}

const mockedGet = mocked.get

describe('useAdminMetricsStore', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mockedGet.mockReset()
    })

    it('fetches metrics and stores them', async () => {
        mockedGet.mockResolvedValue({
            data: {
                totals: {
                    products: 10,
                    favourites: 6,
                    active_urls: 24,
                },
                spotlight: [
                    {
                        id: 1,
                        name: 'Noise Cancelling Headphones',
                        slug: 'noise-cancelling-headphones',
                        current_price: 199.99,
                        trend: 'down',
                        store_name: 'Example Store',
                        image_url: null,
                        last_refreshed_at: '2025-09-27T10:00:00Z',
                        history: [
                            { date: '2025-09-25', price: 219.99 },
                            { date: '2025-09-26', price: 199.99 },
                        ],
                    },
                ],
                tag_groups: [
                    {
                        label: 'Audio',
                        products: [
                            {
                                id: 1,
                                name: 'Noise Cancelling Headphones',
                                slug: 'noise-cancelling-headphones',
                                current_price: 199.99,
                                trend: 'down',
                                store_name: 'Example Store',
                                image_url: null,
                                last_refreshed_at: '2025-09-27T10:00:00Z',
                                history: [],
                            },
                        ],
                    },
                ],
                last_updated_at: '2025-09-27T10:00:00Z',
            },
        })

        const store = useAdminMetricsStore()
        await store.fetchMetrics()

        expect(mockedGet).toHaveBeenCalledWith('/admin/dashboard')
        expect(store.metrics?.totals.products).toBe(10)
        expect(store.metrics?.spotlight).toHaveLength(1)
        expect(store.error).toBeNull()
        expect(store.loading).toBe(false)
        expect(store.lastFetchedAt).not.toBeNull()
    })

    it('records errors when fetching fails', async () => {
        mockedGet.mockRejectedValue(new Error('network error'))

        const store = useAdminMetricsStore()
        await store.fetchMetrics()

        expect(store.metrics).toBeNull()
        expect(store.error).toBe('network error')
        expect(store.loading).toBe(false)
    })

    it('skips duplicate fetches while loading and supports reset', async () => {
        vi.useFakeTimers()
        mockedGet.mockImplementation(async () => {
            await new Promise((resolve) => setTimeout(resolve, 50))
            return {
                data: {
                    totals: { products: 0, favourites: 0, active_urls: 0 },
                    spotlight: [],
                    tag_groups: [],
                    last_updated_at: null,
                },
            }
        })

        const store = useAdminMetricsStore()
        const first = store.fetchMetrics()
        await store.fetchMetrics()
        expect(mockedGet).toHaveBeenCalledTimes(1)
        vi.advanceTimersByTime(50)
        await first
        store.reset()
        expect(store.metrics).toBeNull()
        expect(store.error).toBeNull()
        expect(store.lastFetchedAt).toBeNull()
        vi.useRealTimers()
    })
})
