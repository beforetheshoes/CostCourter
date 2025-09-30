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
import { useStoresStore } from '../../src/stores/useStoresStore'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
    patch: ReturnType<typeof vi.fn>
    delete: ReturnType<typeof vi.fn>
}

describe('useStoresStore', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mocked.get.mockReset()
        mocked.post.mockReset()
        mocked.patch.mockReset()
        mocked.delete.mockReset()
    })

    it('loads stores via list', async () => {
        mocked.get.mockResolvedValue({
            data: [
                {
                    id: 1,
                    name: 'Example',
                    slug: 'example',
                    website_url: 'https://example.com',
                    active: true,
                    domains: [{ domain: 'example.com' }],
                    scrape_strategy: {
                        title: { type: 'css', value: '.title' },
                    },
                    settings: {},
                    notes: null,
                    locale: 'en_US',
                    currency: 'USD',
                },
            ],
        })

        const store = useStoresStore()
        await store.list()

        expect(mocked.get).toHaveBeenCalledWith('/stores')
        expect(store.items).toHaveLength(1)
        expect(store.items[0].slug).toBe('example')
        expect(store.items[0].locale).toBe('en_US')
    })

    it('creates a store and updates state', async () => {
        const store = useStoresStore()
        mocked.post.mockResolvedValue({
            data: {
                id: 2,
                name: 'New Store',
                slug: 'new-store',
                website_url: null,
                active: true,
                domains: [{ domain: 'new.example.com' }],
                scrape_strategy: {},
                settings: {},
                notes: null,
                locale: 'en_US',
                currency: 'USD',
            },
        })

        const payload = {
            name: 'New Store',
            slug: 'new-store',
            domains: [{ domain: 'new.example.com' }],
            locale: 'en_US',
            currency: 'USD',
        }

        const created = await store.create(payload)

        expect(mocked.post).toHaveBeenCalledWith('/stores', payload)
        expect(created.slug).toBe('new-store')
        expect(store.items[0].id).toBe(2)
    })

    it('updates a store in place', async () => {
        const store = useStoresStore()
        store.items = [
            {
                id: 3,
                name: 'Keep Store',
                slug: 'keep-store',
                website_url: null,
                active: true,
                domains: [{ domain: 'keep.example.com' }],
                scrape_strategy: {},
                settings: {},
                notes: null,
                locale: 'en_US',
                currency: 'USD',
            },
        ]

        mocked.patch.mockResolvedValue({
            data: {
                ...store.items[0],
                name: 'Updated Store',
                locale: 'fr_FR',
            },
        })

        await store.update(3, { name: 'Updated Store', locale: 'fr_FR' })

        expect(mocked.patch).toHaveBeenCalledWith('/stores/3', {
            name: 'Updated Store',
            locale: 'fr_FR',
        })
        expect(store.items[0].name).toBe('Updated Store')
        expect(store.items[0].locale).toBe('fr_FR')
    })

    it('removes a store and handles success path', async () => {
        const store = useStoresStore()
        store.items = [
            {
                id: 4,
                name: 'Delete Me',
                slug: 'delete-me',
                website_url: null,
                active: true,
                domains: [],
                scrape_strategy: {},
                settings: {},
                notes: null,
                locale: null,
                currency: null,
            },
        ]

        mocked.delete.mockResolvedValue({ status: 204 })

        await store.remove(4)

        expect(mocked.delete).toHaveBeenCalledWith('/stores/4')
        expect(store.items).toHaveLength(0)
        expect(store.error).toBeNull()
    })

    it('propagates delete failures with detail message', async () => {
        const store = useStoresStore()
        store.items = [
            {
                id: 9,
                name: 'Existing',
                slug: 'existing',
                website_url: null,
                active: true,
                domains: [],
                scrape_strategy: {},
                settings: {},
                notes: null,
                locale: null,
                currency: null,
            },
        ]

        mocked.delete.mockRejectedValue({
            response: { data: { detail: 'Cannot delete store with products' } },
        })

        await expect(store.remove(9)).rejects.toThrow(
            'Cannot delete store with products',
        )
        expect(store.error).toBe('Cannot delete store with products')
        expect(store.items).toHaveLength(1)
    })

    it('records error when list fails', async () => {
        mocked.get.mockRejectedValue(new Error('network down'))
        const store = useStoresStore()

        await store.list()

        expect(store.error).toBe('network down')
        expect(store.loading).toBe(false)
    })

    it('surfaced errors from create and update paths', async () => {
        const store = useStoresStore()
        mocked.post.mockRejectedValue(new Error('nope'))

        await expect(store.create({ name: 'A', slug: 'a' })).rejects.toThrow(
            'nope',
        )
        expect(store.error).toBe('nope')

        mocked.patch.mockRejectedValue(new Error('update failed'))
        await expect(store.update(1, { name: 'B' })).rejects.toThrow(
            'update failed',
        )
        expect(store.error).toBe('update failed')
    })
})
