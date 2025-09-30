import { defineStore } from 'pinia'

import { apiClient } from '../lib/http'

type TagRecord = {
    id: number
    name: string
    slug: string
}

type TagCreatePayload = {
    name: string
    slug: string
}

type TagUpdatePayload = Partial<TagCreatePayload>

type TagMergePayload = {
    source_tag_id: number
    target_tag_id: number
    delete_source?: boolean
}

type TagMergeResult = {
    source_tag_id: number
    target_tag_id: number
    moved_links: number
    removed_duplicate_links: number
    deleted_source: boolean
}

export const useTagsStore = defineStore('tags', {
    state: () => ({
        items: [] as TagRecord[],
        loading: false,
        error: null as string | null,
    }),
    actions: {
        async list() {
            this.loading = true
            this.error = null
            try {
                const response = await apiClient.get<TagRecord[]>('/tags')
                this.items = response.data
            } catch (error) {
                this.error =
                    error instanceof Error
                        ? error.message
                        : 'Failed to load tags'
            } finally {
                this.loading = false
            }
        },
        async create(payload: TagCreatePayload) {
            this.error = null
            try {
                const response = await apiClient.post<TagRecord>(
                    '/tags',
                    payload,
                )
                this.items.unshift(response.data)
                return response.data
            } catch (error) {
                this.error =
                    error instanceof Error
                        ? error.message
                        : 'Failed to create tag'
                throw error
            }
        },
        async update(id: number, payload: TagUpdatePayload) {
            this.error = null
            try {
                const response = await apiClient.patch<TagRecord>(
                    `/tags/${id}`,
                    payload,
                )
                const index = this.items.findIndex((tag) => tag.id === id)
                if (index !== -1) {
                    this.items.splice(index, 1, response.data)
                }
                return response.data
            } catch (error) {
                this.error =
                    error instanceof Error
                        ? error.message
                        : 'Failed to update tag'
                throw error
            }
        },
        async remove(id: number) {
            this.error = null
            try {
                await apiClient.delete(`/tags/${id}`)
                this.items = this.items.filter((tag) => tag.id !== id)
            } catch (error) {
                this.error =
                    error instanceof Error
                        ? error.message
                        : 'Failed to delete tag'
                throw error
            }
        },
        async merge(payload: TagMergePayload) {
            this.error = null
            const body = {
                source_tag_id: payload.source_tag_id,
                target_tag_id: payload.target_tag_id,
                delete_source:
                    payload.delete_source === undefined
                        ? true
                        : payload.delete_source,
            }
            try {
                const response = await apiClient.post<TagMergeResult>(
                    '/tags/merge',
                    body,
                )
                await this.list()
                return response.data
            } catch (error) {
                this.error =
                    error instanceof Error
                        ? error.message
                        : 'Failed to merge tags'
                throw error
            }
        },
    },
})

export type {
    TagRecord,
    TagCreatePayload,
    TagUpdatePayload,
    TagMergePayload,
    TagMergeResult,
}
