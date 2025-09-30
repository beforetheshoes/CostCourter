import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const get = vi.fn()
    const post = vi.fn()
    return {
        apiClient: { get, post },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { get, post },
    }
})

import { apiClient } from '../../src/lib/http'
import { useSearchStore } from '../../src/stores/useSearchStore'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
}

const mockedGet = mocked.get
const mockedPost = mocked.post

describe('useSearchStore', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mockedGet.mockReset()
        mockedPost.mockReset()
    })

    it('performs a search and stores results', async () => {
        mockedGet.mockResolvedValue({
            data: {
                query: 'headphones',
                cache_hit: false,
                expires_at: '2025-09-27T00:00:00Z',
                extra: { engines: { google: 1 } },
                results: [
                    {
                        title: 'Noise Cancelling Headphones',
                        url: 'https://example.com/product',
                        snippet: 'Premium sound',
                        thumbnail: null,
                        domain: 'example.com',
                        relevance: 0,
                        engine: 'google',
                        score: 12.5,
                        store_id: 5,
                        store_name: 'Example Store',
                    },
                ],
            },
        })

        const store = useSearchStore()
        await store.search('  headphones  ')

        expect(mockedGet).toHaveBeenCalledWith('/search', {
            params: { query: 'headphones' },
        })
        expect(store.results).toHaveLength(1)
        expect(store.cacheHit).toBe(false)
        expect(store.expiresAt).toBe('2025-09-27T00:00:00Z')
        expect(store.extra).toEqual({ engines: { google: 1 } })
        expect(store.error).toBeNull()
        expect(store.lastQuery).toBe('headphones')
        expect(store.lastFetchedAt).not.toBeNull()
    })

    it('handles blank queries gracefully', async () => {
        const store = useSearchStore()
        await store.search('    ')
        expect(store.results).toEqual([])
        expect(store.error).toBe('Enter a search query to begin.')
        expect(store.cacheHit).toBeNull()
        expect(store.expiresAt).toBeNull()
    })

    it('passes force refresh and page options', async () => {
        mockedGet.mockResolvedValue({
            data: {
                query: 'laptop',
                cache_hit: true,
                expires_at: null,
                extra: {},
                results: [],
            },
        })

        const store = useSearchStore()
        await store.search('laptop', { forceRefresh: true, pages: 3 })

        expect(mockedGet).toHaveBeenCalledWith('/search', {
            params: { query: 'laptop', force_refresh: true, pages: 3 },
        })
        expect(store.cacheHit).toBe(true)
    })

    it('handles search failures gracefully', async () => {
        mockedGet.mockRejectedValue(new Error('upstream unavailable'))

        const store = useSearchStore()
        await store.search('tablet')

        expect(store.error).toBe('upstream unavailable')
        expect(store.results).toEqual([])
        expect(store.cacheHit).toBeNull()
        expect(store.expiresAt).toBeNull()
    })

    it('quick-adds a URL', async () => {
        mockedPost.mockResolvedValue({
            data: {
                product_id: 42,
                product_url_id: 101,
                store_id: 7,
                title: 'Noise Cancelling Headphones',
                price: 199.99,
                currency: 'USD',
                image: null,
                warnings: [],
            },
        })

        const store = useSearchStore()
        const result = await store.quickAdd('https://example.com/product')

        expect(mockedPost).toHaveBeenCalledWith('/product-urls/quick-add', {
            url: 'https://example.com/product',
        })
        expect(result.product_id).toBe(42)
    })

    it('propagates quick-add errors with detail message', async () => {
        mockedPost.mockRejectedValue({
            response: { data: { detail: 'Already tracked' } },
        })

        const store = useSearchStore()
        await expect(
            store.quickAdd('https://example.com/product'),
        ).rejects.toThrow('Already tracked')
    })

    it('propagates quick-add errors without response detail', async () => {
        mockedPost.mockRejectedValue(new Error('service offline'))

        const store = useSearchStore()
        await expect(
            store.quickAdd('https://example.com/product'),
        ).rejects.toThrow('service offline')
    })

    it('bulk imports selected URLs', async () => {
        mockedPost.mockResolvedValue({
            data: {
                product_id: 7,
                product_name: 'Noise Cancelling Headphones',
                product_slug: 'noise-cancelling-headphones',
                created_product: false,
                created_urls: [
                    {
                        product_url_id: 101,
                        store_id: 5,
                        url: 'https://example.com/a',
                        is_primary: true,
                        price: 199.99,
                        currency: 'USD',
                    },
                ],
                skipped: [],
            },
        })

        const store = useSearchStore()
        const result = await store.bulkImport(
            [
                { url: 'https://example.com/a', set_primary: true },
                { url: 'https://example.com/b' },
            ],
            {
                productId: 7,
                searchQuery: 'headphones',
                enqueueRefresh: true,
            },
        )

        expect(mockedPost).toHaveBeenCalledWith('/product-urls/bulk-import', {
            items: [
                { url: 'https://example.com/a', set_primary: true },
                { url: 'https://example.com/b', set_primary: false },
            ],
            enqueue_refresh: true,
            product_id: 7,
            search_query: 'headphones',
        })
        expect(result.product_id).toBe(7)
        expect(result.created_urls).toHaveLength(1)
    })

    it('raises an error when bulk import fails', async () => {
        mockedPost.mockRejectedValue(new Error('bulk import failed'))

        const store = useSearchStore()
        await expect(
            store.bulkImport([{ url: 'https://example.com/a' }], {
                searchQuery: 'headphones',
            }),
        ).rejects.toThrow('bulk import failed')
    })

    it('requires at least one item to bulk import', async () => {
        const store = useSearchStore()
        await expect(store.bulkImport([])).rejects.toThrow(
            'Select at least one URL to import',
        )
    })
})
