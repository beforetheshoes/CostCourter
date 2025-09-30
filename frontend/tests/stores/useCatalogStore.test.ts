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
import { useCatalogStore } from '../../src/stores/useCatalogStore'

const mockedGet = (apiClient as unknown as { get: ReturnType<typeof vi.fn> })
    .get

describe('useCatalogStore', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mockedGet.mockReset()
    })

    it('populates items on fetch with summary data', async () => {
        mockedGet.mockResolvedValue({
            data: [
                {
                    id: 1,
                    name: 'Widget',
                    slug: 'widget',
                    description: null,
                    is_active: true,
                    tags: [{ name: 'Electronics', slug: 'electronics' }],
                    urls: [
                        {
                            id: 11,
                            url: 'https://example.com/widget',
                            is_primary: true,
                            active: true,
                            latest_price: 129.99,
                            latest_price_currency: 'USD',
                            latest_price_at: '2024-01-02T00:00:00Z',
                            store: {
                                id: 5,
                                name: 'Example Store',
                                slug: 'example-store',
                                locale: 'en_US',
                                currency: 'USD',
                            },
                        },
                    ],
                    current_price: 127.25,
                    latest_price: {
                        price: 129.99,
                        currency: 'USD',
                        recorded_at: '2024-01-01T00:00:00Z',
                    },
                    price_trend: 'down',
                    last_refreshed_at: '2024-01-02T00:00:00Z',
                    history_points: [
                        { date: '2024-01-01', price: 129.99 },
                        { date: '2024-01-02', price: 127.25 },
                    ],
                    price_aggregates: {
                        min: 120,
                        max: 140,
                        avg: 130,
                        currency: 'USD',
                    },
                    price_cache: [
                        {
                            currency: 'USD',
                            aggregates: { min: 120, max: 140, avg: 130 },
                        },
                    ],
                },
            ],
        })

        const store = useCatalogStore()
        await store.fetchCatalog()

        expect(mockedGet).toHaveBeenCalledWith('/products?limit=10&offset=0')
        expect(store.items).toEqual([
            {
                id: 1,
                name: 'Widget',
                slug: 'widget',
                primaryUrl: 'https://example.com/widget',
                currentPrice: 127.25,
                latestPrice: 129.99,
                currency: 'USD',
                lastRefreshedAt: '2024-01-02T00:00:00Z',
                priceTrend: 'down',
                historyPoints: [
                    { date: '2024-01-01', price: 129.99 },
                    { date: '2024-01-02', price: 127.25 },
                ],
                tags: ['Electronics'],
                urls: [
                    {
                        id: 11,
                        url: 'https://example.com/widget',
                        is_primary: true,
                        active: true,
                        latestPrice: 129.99,
                        latestPriceCurrency: 'USD',
                        latestPriceAt: '2024-01-02T00:00:00Z',
                        store: {
                            id: 5,
                            name: 'Example Store',
                            slug: 'example-store',
                            locale: 'en_US',
                            currency: 'USD',
                        },
                    },
                ],
                aggregates: {
                    min: 120,
                    max: 140,
                    avg: 130,
                    currency: 'USD',
                },
            },
        ])
        expect(store.hasMore).toBe(false)
        expect(store.page).toBe(1)
        expect(store.pageSize).toBe(10)
        expect(store.loaded).toBe(true)
    })

    it('applies filters and pagination to request parameters', async () => {
        mockedGet.mockResolvedValue({ data: [] })
        const store = useCatalogStore()

        await store.fetchCatalog({
            search: 'Widget',
            tag: 'electronics',
            isActive: false,
            page: 2,
            pageSize: 5,
        })

        expect(mockedGet).toHaveBeenCalledWith(
            '/products?limit=5&offset=5&search=Widget&tag=electronics&is_active=false',
        )
        expect(store.page).toBe(2)
        expect(store.pageSize).toBe(5)
        expect(store.filters).toEqual({
            search: 'Widget',
            tag: 'electronics',
            isActive: false,
        })
    })

    it('marks hasMore when the page is full', async () => {
        mockedGet.mockResolvedValue({
            data: Array.from({ length: 10 }).map((_, index) => ({
                id: index + 1,
                name: `Product ${index + 1}`,
                slug: `product-${index + 1}`,
                description: null,
                is_active: true,
                tags: [],
                urls: [],
                current_price: null,
                latest_price: null,
                price_trend: 'none',
                last_refreshed_at: null,
                history_points: [],
                price_cache: [],
            })),
        })

        const store = useCatalogStore()
        await store.fetchCatalog()

        expect(store.hasMore).toBe(true)
    })

    it('handles failures gracefully', async () => {
        mockedGet.mockRejectedValue(new Error('network'))
        const store = useCatalogStore()
        await store.fetchCatalog()
        expect(store.error).toBe('network')
        expect(store.items).toEqual([])
        expect(store.loading).toBe(false)
    })

    it('resets to defaults', async () => {
        mockedGet.mockResolvedValue({ data: [] })
        const store = useCatalogStore()
        await store.fetchCatalog({
            search: 'Reset',
            tag: 'reset-tag',
            isActive: true,
            page: 3,
            pageSize: 5,
        })

        store.reset()
        expect(store.items).toEqual([])
        expect(store.page).toBe(1)
        expect(store.pageSize).toBe(10)
        expect(store.hasMore).toBe(false)
        expect(store.filters).toEqual({ search: '', tag: '', isActive: null })
        expect(store.error).toBeNull()
    })
})
