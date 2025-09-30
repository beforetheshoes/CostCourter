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
import { usePriceHistoryStore } from '../../src/stores/usePriceHistoryStore'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
}

describe('usePriceHistoryStore', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mocked.get.mockReset()
    })

    it('loads price history entries for a product', async () => {
        mocked.get.mockResolvedValue({
            data: [
                {
                    id: 1,
                    product_id: 7,
                    product_url_id: 3,
                    price: 199.99,
                    currency: 'USD',
                    recorded_at: '2025-01-01T00:00:00Z',
                    product_url: {
                        url: 'https://example.com/item',
                        store: { name: 'Example', slug: 'example' },
                    },
                },
            ],
        })

        const store = usePriceHistoryStore()
        await store.loadForProduct(7)

        expect(mocked.get).toHaveBeenCalledWith('/price-history', {
            params: { product_id: 7 },
        })
        expect(store.entries).toHaveLength(1)
        expect(store.entries[0].price).toBe(199.99)
        expect(store.error).toBeNull()
        expect(store.loading).toBe(false)
    })

    it('captures errors when loading price history', async () => {
        const error = new Error('network issue')
        mocked.get.mockRejectedValue(error)

        const store = usePriceHistoryStore()
        await expect(store.loadForProduct(9)).rejects.toThrow('network issue')
        expect(store.entries).toHaveLength(0)
        expect(store.error).toBe('network issue')
        expect(store.loading).toBe(false)
    })

    it('resets state to initial values', () => {
        const store = usePriceHistoryStore()
        store.entries = [
            {
                id: 1,
                product_id: 2,
                product_url_id: null,
                price: 99,
                currency: 'USD',
                recorded_at: '2025-01-01T00:00:00Z',
            },
        ]
        store.error = 'error'
        store.loading = true

        store.reset()
        expect(store.entries).toEqual([])
        expect(store.error).toBeNull()
        expect(store.loading).toBe(false)
    })
})
