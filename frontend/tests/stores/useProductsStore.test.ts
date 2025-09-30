import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const get = vi.fn()
    const post = vi.fn()
    const patch = vi.fn()
    const del = vi.fn()
    return {
        apiClient: { get, post, patch, delete: del },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { get, post, patch, delete: del },
    }
})

import { apiClient } from '../../src/lib/http'
import { useProductsStore } from '../../src/stores/useProductsStore'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
    patch: ReturnType<typeof vi.fn>
    delete: ReturnType<typeof vi.fn>
}

describe('useProductsStore', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mocked.get.mockReset()
        mocked.post.mockReset()
        mocked.patch.mockReset()
        mocked.delete.mockReset()
    })

    it('loads products via list', async () => {
        mocked.get.mockResolvedValue({
            data: [
                {
                    id: 1,
                    name: 'Noise Cancelling Headphones',
                    slug: 'noise-cancelling-headphones',
                    description: 'Over-ear headphones',
                    is_active: true,
                    image_url: 'https://img.example.com/headphones.png',
                    current_price: 199.99,
                    price_cache: [
                        {
                            price: 199.99,
                            currency: 'USD',
                        },
                    ],
                    latest_price: {
                        price: 199.99,
                        currency: 'USD',
                        recorded_at: '2025-09-27T18:00:00Z',
                    },
                    tags: [],
                    urls: [
                        {
                            id: 10,
                            url: 'https://example.com/item',
                            is_primary: true,
                            active: true,
                            store: { name: 'Example', slug: 'example' },
                        },
                    ],
                },
            ],
        })

        const store = useProductsStore()
        await store.list()

        expect(mocked.get).toHaveBeenCalledWith('/products')
        expect(store.items).toHaveLength(1)
        expect(store.items[0].slug).toBe('noise-cancelling-headphones')
        expect(store.items[0].latest_price?.price).toBe(199.99)
    })

    it('creates a product and prepends it to the list', async () => {
        const store = useProductsStore()
        mocked.post.mockResolvedValue({
            data: {
                id: 2,
                name: 'Portable Charger',
                slug: 'portable-charger',
                description: null,
                is_active: true,
                image_url: 'https://img.example.com/charger.png',
                current_price: 49.99,
                price_cache: [],
                latest_price: null,
                tags: [],
                urls: [],
            },
        })

        const created = await store.create({
            name: 'Portable Charger',
            slug: 'portable-charger',
        })

        expect(mocked.post).toHaveBeenCalledWith('/products', {
            name: 'Portable Charger',
            slug: 'portable-charger',
        })
        expect(created.slug).toBe('portable-charger')
        expect(store.items[0].id).toBe(2)
    })

    it('quick-adds a product URL and refreshes the product entry', async () => {
        const store = useProductsStore()
        mocked.post.mockResolvedValueOnce({
            data: {
                product_id: 11,
                product_url_id: 42,
                store_id: 5,
                title: 'Example Widget',
                price: 129.99,
                currency: 'USD',
                image: 'https://img.example.com/widget.png',
                warnings: [],
            },
        })
        mocked.get.mockResolvedValueOnce({
            data: {
                id: 11,
                name: 'Example Widget',
                slug: 'example-widget',
                description: null,
                is_active: true,
                image_url: 'https://img.example.com/widget.png',
                current_price: 129.99,
                price_cache: [],
                latest_price: {
                    price: 129.99,
                    currency: 'USD',
                    recorded_at: '2025-01-01T00:00:00Z',
                },
                tags: [],
                urls: [],
            },
        })

        const { result, product: refreshed } = await store.quickAdd(
            'https://example.com/widget',
        )

        expect(mocked.post).toHaveBeenCalledWith('/product-urls/quick-add', {
            url: 'https://example.com/widget',
        })
        expect(mocked.get).toHaveBeenCalledWith('/products/11')
        expect(result.product_url_id).toBe(42)
        expect(refreshed?.id).toBe(11)
        expect(store.items[0].id).toBe(11)
    })

    it('quickly adds a URL to an existing product', async () => {
        const store = useProductsStore()
        mocked.post.mockResolvedValueOnce({
            data: {
                product_id: 7,
                product_name: 'Existing',
                product_slug: 'existing',
                created_product: false,
                created_urls: [
                    {
                        product_url_id: 501,
                        store_id: 12,
                        url: 'https://example.com/extra',
                        is_primary: true,
                        price: 49.99,
                        currency: 'USD',
                    },
                ],
                skipped: [],
            },
        })
        mocked.get.mockResolvedValueOnce({
            data: {
                id: 7,
                name: 'Existing',
                slug: 'existing',
                description: null,
                is_active: true,
                image_url: null,
                current_price: null,
                price_cache: [],
                latest_price: null,
                tags: [],
                urls: [],
            },
        })

        const response = await store.quickAddUrlForProduct(
            7,
            'https://example.com/extra',
            { setPrimary: true },
        )

        expect(mocked.post).toHaveBeenCalledWith('/product-urls/bulk-import', {
            items: [
                {
                    url: 'https://example.com/extra',
                    set_primary: true,
                },
            ],
            product_id: 7,
            enqueue_refresh: false,
        })
        expect(mocked.get).toHaveBeenCalledWith('/products/7')
        expect(response.created_urls[0].product_url_id).toBe(501)
    })

    it('updates an existing product in place', async () => {
        const store = useProductsStore()
        store.items = [
            {
                id: 3,
                name: 'Old Title',
                slug: 'old-title',
                description: null,
                is_active: true,
                image_url: null,
                current_price: null,
                price_cache: [],
                latest_price: null,
                tags: [],
                urls: [],
            },
        ]

        mocked.patch.mockResolvedValue({
            data: {
                ...store.items[0],
                name: 'Updated Title',
                description: 'Now with details',
            },
        })

        await store.update(3, {
            name: 'Updated Title',
            description: 'Now with details',
        })

        expect(mocked.patch).toHaveBeenCalledWith('/products/3', {
            name: 'Updated Title',
            description: 'Now with details',
        })
        expect(store.items[0].name).toBe('Updated Title')
        expect(store.items[0].description).toBe('Now with details')
    })

    it('removes a product after delete', async () => {
        const store = useProductsStore()
        store.items = [
            {
                id: 4,
                name: 'Removable',
                slug: 'removable',
                description: null,
                is_active: true,
                image_url: null,
                current_price: null,
                price_cache: [],
                latest_price: null,
                tags: [],
                urls: [],
            },
        ]

        mocked.delete.mockResolvedValue({ status: 204 })

        await store.remove(4)

        expect(mocked.delete).toHaveBeenCalledWith('/products/4')
        expect(store.items).toHaveLength(0)
    })

    it('bulk updates products and refreshes the list', async () => {
        const store = useProductsStore()
        mocked.post.mockResolvedValue({
            data: { updated_ids: [5], skipped_ids: [], missing_ids: [] },
        })
        mocked.get.mockResolvedValue({ data: [] })

        const result = await store.bulkUpdate({
            product_ids: [5],
            updates: { status: 'archived' },
        })

        expect(mocked.post).toHaveBeenCalledWith('/products/bulk-update', {
            product_ids: [5],
            updates: { status: 'archived' },
        })
        expect(mocked.get).toHaveBeenCalledWith('/products')
        expect(result.updated_ids).toEqual([5])
    })

    it('createUrl appends a new product URL and clears previous primary flag', async () => {
        const store = useProductsStore()
        store.items = [
            {
                id: 10,
                name: 'Primary Product',
                slug: 'primary-product',
                description: null,
                is_active: true,
                image_url: null,
                current_price: null,
                price_cache: [],
                latest_price: null,
                tags: [],
                urls: [
                    {
                        id: 1,
                        product_id: 10,
                        store_id: 100,
                        url: 'https://primary.example/item',
                        is_primary: true,
                        active: true,
                        created_by_id: null,
                        store: { id: 100, name: 'Primary', slug: 'primary' },
                    },
                ],
            },
        ]

        mocked.post.mockResolvedValueOnce({
            data: {
                id: 2,
                product_id: 10,
                store_id: 101,
                url: 'https://secondary.example/item',
                is_primary: true,
                active: true,
                created_by_id: null,
                store: { id: 101, name: 'Secondary', slug: 'secondary' },
            },
        })

        await store.createUrl({
            product_id: 10,
            store_id: 101,
            url: 'https://secondary.example/item',
            is_primary: true,
            active: true,
        })

        expect(mocked.post).toHaveBeenCalledWith('/product-urls', {
            product_id: 10,
            store_id: 101,
            url: 'https://secondary.example/item',
            is_primary: true,
            active: true,
        })

        const product = store.items[0]
        expect(product.urls).toHaveLength(2)
        const primary = product.urls.find((url) => url.id === 2)
        const demoted = product.urls.find((url) => url.id === 1)
        expect(primary?.is_primary).toBe(true)
        expect(demoted?.is_primary).toBe(false)
    })

    it('updateUrl refreshes URL data in place and demotes the previous primary', async () => {
        const store = useProductsStore()
        store.items = [
            {
                id: 20,
                name: 'Switchable Product',
                slug: 'switchable-product',
                description: null,
                is_active: true,
                image_url: null,
                current_price: null,
                price_cache: [],
                latest_price: null,
                tags: [],
                urls: [
                    {
                        id: 11,
                        product_id: 20,
                        store_id: 200,
                        url: 'https://first.example/item',
                        is_primary: true,
                        active: true,
                        created_by_id: null,
                        store: { id: 200, name: 'First', slug: 'first' },
                    },
                    {
                        id: 12,
                        product_id: 20,
                        store_id: 201,
                        url: 'https://second.example/item',
                        is_primary: false,
                        active: true,
                        created_by_id: null,
                        store: { id: 201, name: 'Second', slug: 'second' },
                    },
                ],
            },
        ]

        mocked.patch.mockResolvedValueOnce({
            data: {
                id: 12,
                product_id: 20,
                store_id: 201,
                url: 'https://second.example/item',
                is_primary: true,
                active: true,
                created_by_id: null,
                store: { id: 201, name: 'Second', slug: 'second' },
            },
        })

        await store.updateUrl(20, 12, { is_primary: true })

        expect(mocked.patch).toHaveBeenCalledWith('/product-urls/12', {
            is_primary: true,
        })
        const product = store.items[0]
        const first = product.urls.find((url) => url.id === 11)
        const second = product.urls.find((url) => url.id === 12)
        expect(first?.is_primary).toBe(false)
        expect(second?.is_primary).toBe(true)
    })

    it('deleteUrl removes an entry from the product', async () => {
        const store = useProductsStore()
        store.items = [
            {
                id: 30,
                name: 'Removable URLs',
                slug: 'removable-urls',
                description: null,
                is_active: true,
                image_url: null,
                current_price: null,
                price_cache: [],
                latest_price: null,
                tags: [],
                urls: [
                    {
                        id: 21,
                        product_id: 30,
                        store_id: 300,
                        url: 'https://remove.example/item',
                        is_primary: false,
                        active: true,
                        created_by_id: null,
                        store: {
                            id: 300,
                            name: 'Removable',
                            slug: 'removable',
                        },
                    },
                ],
            },
        ]

        mocked.delete.mockResolvedValueOnce({ status: 204 })

        await store.deleteUrl(30, 21)

        expect(mocked.delete).toHaveBeenCalledWith('/product-urls/21')
        expect(store.items[0].urls).toHaveLength(0)
    })

    it('validates quickAdd and quickAddUrlForProduct inputs', async () => {
        const store = useProductsStore()
        await expect(store.quickAdd('   ')).rejects.toThrow('URL is required')
        expect(store.error).toBe('URL is required')

        store.error = null
        await expect(store.quickAddUrlForProduct(1, '')).rejects.toThrow(
            'URL is required',
        )
        expect(store.error).toBe('URL is required')
    })

    it('captures API error details for quick add flows', async () => {
        const store = useProductsStore()
        mocked.post.mockRejectedValueOnce({
            response: { data: { detail: 'Duplicate URL' } },
        })

        await expect(store.quickAdd('https://dup.example')).rejects.toThrow(
            'Duplicate URL',
        )
        expect(store.error).toBe('Duplicate URL')

        mocked.post.mockRejectedValueOnce({
            response: { data: { detail: 'Already added' } },
        })

        await expect(
            store.quickAddUrlForProduct(9, 'https://dup.example'),
        ).rejects.toThrow('Already added')
        expect(store.error).toBe('Already added')
    })

    it('handles update, fetch, remove, and bulk update failures', async () => {
        const store = useProductsStore()
        mocked.patch.mockRejectedValueOnce(new Error('update failed'))
        await expect(store.update(1, { name: 'New' })).rejects.toThrow(
            'update failed',
        )
        expect(store.error).toBe('update failed')

        mocked.get.mockRejectedValueOnce(new Error('missing product'))
        await expect(store.fetch(42)).rejects.toThrow('missing product')
        expect(store.error).toBe('missing product')

        mocked.delete.mockRejectedValueOnce(new Error('cannot delete'))
        await expect(store.remove(5)).rejects.toThrow('cannot delete')
        expect(store.error).toBe('cannot delete')

        mocked.post.mockRejectedValueOnce(new Error('bulk oops'))
        await expect(
            store.bulkUpdate({
                product_ids: [1],
                updates: { favourite: true },
            }),
        ).rejects.toThrow('bulk oops')
        expect(store.error).toBe('bulk oops')
    })

    it('merges fetch results and keeps existing inventory in sync', async () => {
        const store = useProductsStore()
        store.items = [
            {
                id: 99,
                name: 'Old Name',
                slug: 'old-name',
                description: null,
                is_active: true,
                image_url: null,
                current_price: null,
                price_cache: [],
                latest_price: null,
                tags: [],
                urls: [],
            },
        ]

        mocked.get.mockResolvedValueOnce({
            data: {
                ...store.items[0],
                name: 'Fresh Name',
            },
        })

        const updated = await store.fetch(99)
        expect(updated.name).toBe('Fresh Name')
        expect(store.items[0].name).toBe('Fresh Name')

        mocked.get.mockResolvedValueOnce({
            data: {
                id: 100,
                name: 'New Arrival',
                slug: 'new-arrival',
                description: null,
                is_active: true,
                image_url: null,
                current_price: null,
                price_cache: [],
                latest_price: null,
                tags: [],
                urls: [],
            },
        })

        await store.fetch(100)
        expect(store.items.find((item) => item.id === 100)).toBeTruthy()
    })

    it('skips reloading list when bulk update changes nothing', async () => {
        const store = useProductsStore()
        mocked.post.mockResolvedValueOnce({
            data: { updated_ids: [], skipped_ids: [1], missing_ids: [] },
        })

        await store.bulkUpdate({
            product_ids: [1],
            updates: { favourite: true },
        })
        expect(mocked.get).not.toHaveBeenCalled()
    })

    it('propagates errors for URL mutations', async () => {
        const store = useProductsStore()
        mocked.post.mockRejectedValueOnce(new Error('create url fail'))
        await expect(
            store.createUrl({ product_id: 1, store_id: 2, url: 'https://x' }),
        ).rejects.toThrow('create url fail')
        expect(store.error).toBe('create url fail')

        mocked.patch.mockRejectedValueOnce(new Error('update url fail'))
        await expect(store.updateUrl(1, 2, { active: false })).rejects.toThrow(
            'update url fail',
        )
        expect(store.error).toBe('update url fail')

        mocked.delete.mockRejectedValueOnce(new Error('delete url fail'))
        await expect(store.deleteUrl(1, 2)).rejects.toThrow('delete url fail')
        expect(store.error).toBe('delete url fail')
    })
})
