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
import { useTagsStore } from '../../src/stores/useTagsStore'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
    patch: ReturnType<typeof vi.fn>
    delete: ReturnType<typeof vi.fn>
}

describe('useTagsStore', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mocked.get.mockReset()
        mocked.post.mockReset()
        mocked.patch.mockReset()
        mocked.delete.mockReset()
    })

    it('loads tags via list', async () => {
        mocked.get.mockResolvedValue({
            data: [
                { id: 1, name: 'Flash Sales', slug: 'flash-sales' },
                { id: 2, name: 'Prime Day', slug: 'prime-day' },
            ],
        })

        const store = useTagsStore()
        await store.list()

        expect(mocked.get).toHaveBeenCalledWith('/tags')
        expect(store.items).toHaveLength(2)
        expect(store.items[0].slug).toBe('flash-sales')
    })

    it('creates a tag and prepends the response', async () => {
        const store = useTagsStore()
        mocked.post.mockResolvedValue({
            data: { id: 3, name: 'Holiday', slug: 'holiday' },
        })

        const payload = { name: 'Holiday', slug: 'holiday' }
        const created = await store.create(payload)

        expect(mocked.post).toHaveBeenCalledWith('/tags', payload)
        expect(created.id).toBe(3)
        expect(store.items[0].name).toBe('Holiday')
    })

    it('updates an existing record in place', async () => {
        const store = useTagsStore()
        store.items = [{ id: 4, name: 'Old', slug: 'old' }]

        mocked.patch.mockResolvedValue({
            data: { id: 4, name: 'New', slug: 'new' },
        })

        const updated = await store.update(4, { name: 'New', slug: 'new' })

        expect(mocked.patch).toHaveBeenCalledWith('/tags/4', {
            name: 'New',
            slug: 'new',
        })
        expect(updated.slug).toBe('new')
        expect(store.items[0].name).toBe('New')
    })

    it('removes a tag from the list after deletion', async () => {
        const store = useTagsStore()
        store.items = [{ id: 5, name: 'Delete Me', slug: 'delete-me' }]
        mocked.delete.mockResolvedValue({ status: 204 })

        await store.remove(5)

        expect(mocked.delete).toHaveBeenCalledWith('/tags/5')
        expect(store.items).toHaveLength(0)
    })

    it('merges tags and refreshes the list', async () => {
        const store = useTagsStore()
        mocked.post.mockResolvedValue({
            data: {
                source_tag_id: 1,
                target_tag_id: 2,
                moved_links: 3,
                removed_duplicate_links: 1,
                deleted_source: true,
            },
        })
        mocked.get.mockResolvedValue({ data: [] })

        const result = await store.merge({ source_tag_id: 1, target_tag_id: 2 })

        expect(mocked.post).toHaveBeenCalledWith('/tags/merge', {
            source_tag_id: 1,
            target_tag_id: 2,
            delete_source: true,
        })
        expect(mocked.get).toHaveBeenCalledWith('/tags')
        expect(result.deleted_source).toBe(true)
    })

    it('records errors from tag operations', async () => {
        const store = useTagsStore()

        mocked.get.mockRejectedValueOnce(new Error('load failed'))
        await store.list()
        expect(store.error).toBe('load failed')

        mocked.post.mockRejectedValueOnce(new Error('create failed'))
        await expect(store.create({ name: 'X', slug: 'x' })).rejects.toThrow(
            'create failed',
        )
        expect(store.error).toBe('create failed')

        mocked.patch.mockRejectedValueOnce(new Error('update failed'))
        await expect(store.update(1, { name: 'Y' })).rejects.toThrow(
            'update failed',
        )
        expect(store.error).toBe('update failed')

        mocked.delete.mockRejectedValueOnce(new Error('delete failed'))
        await expect(store.remove(1)).rejects.toThrow('delete failed')
        expect(store.error).toBe('delete failed')

        mocked.post.mockRejectedValueOnce(new Error('merge failed'))
        await expect(
            store.merge({ source_tag_id: 1, target_tag_id: 2 }),
        ).rejects.toThrow('merge failed')
        expect(store.error).toBe('merge failed')
    })
})
