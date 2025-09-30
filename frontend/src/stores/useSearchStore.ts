import type { AxiosError } from 'axios'
import { defineStore } from 'pinia'

import { apiClient } from '../lib/http'

export type SearchHit = {
    title: string | null
    url: string
    snippet: string | null
    thumbnail: string | null
    domain: string | null
    relevance: number
    engine: string | null
    score: number | null
    store_id: number | null
    store_name: string | null
}

export type BulkImportRequestItem = {
    url: string
    set_primary?: boolean
}

export type BulkImportCreatedUrl = {
    product_url_id: number
    store_id: number
    url: string
    is_primary: boolean
    price: number | null
    currency: string | null
}

export type BulkImportResponse = {
    product_id: number
    product_name: string
    product_slug: string
    created_product: boolean
    created_urls: BulkImportCreatedUrl[]
    skipped: Array<{ url: string; reason: string }>
}

type SearchResponse = {
    query: string
    cache_hit: boolean
    expires_at: string | null
    results: SearchHit[]
    extra: Record<string, unknown>
}

export type QuickAddResult = {
    product_id: number
    product_url_id: number
    store_id: number
    title: string
    price: unknown
    currency: string | null
    image: string | null
    warnings: string[]
}

type SearchOptions = {
    forceRefresh?: boolean
    pages?: number
}

export const useSearchStore = defineStore('search', {
    state: () => ({
        results: [] as SearchHit[],
        cacheHit: null as boolean | null,
        expiresAt: null as string | null,
        extra: {} as Record<string, unknown>,
        loading: false,
        error: null as string | null,
        lastQuery: '',
        lastFetchedAt: null as string | null,
    }),
    actions: {
        async search(query: string, options: SearchOptions = {}) {
            const trimmed = query.trim()
            if (!trimmed) {
                this.results = []
                this.cacheHit = null
                this.expiresAt = null
                this.error = 'Enter a search query to begin.'
                return
            }

            const pages = Math.min(Math.max(options.pages ?? 1, 1), 10)

            this.loading = true
            this.error = null
            try {
                const params: Record<string, unknown> = { query: trimmed }
                if (options.forceRefresh) {
                    params.force_refresh = true
                }
                if (pages > 1) {
                    params.pages = pages
                }
                const response = await apiClient.get<SearchResponse>(
                    '/search',
                    {
                        params,
                    },
                )
                const data = response.data
                this.results = data.results ?? []
                this.cacheHit = data.cache_hit
                this.expiresAt = data.expires_at ?? null
                this.extra = data.extra ?? {}
                this.lastQuery = trimmed
                this.lastFetchedAt = new Date().toISOString()
            } catch (error) {
                const message =
                    error instanceof Error ? error.message : 'Search failed'
                this.error = message
                this.results = []
                this.cacheHit = null
                this.expiresAt = null
            } finally {
                this.loading = false
            }
        },
        async quickAdd(url: string): Promise<QuickAddResult> {
            try {
                const response = await apiClient.post<QuickAddResult>(
                    '/product-urls/quick-add',
                    { url },
                )
                return response.data
            } catch (error) {
                const axiosError = error as AxiosError<{ detail?: string }>
                const detail = axiosError.response?.data?.detail
                const message =
                    detail ??
                    (error instanceof Error
                        ? error.message
                        : 'Failed to quick-add URL')
                throw new Error(message)
            }
        },
        async bulkImport(
            items: BulkImportRequestItem[],
            options: {
                productId?: number
                searchQuery?: string
                enqueueRefresh?: boolean
            } = {},
        ): Promise<BulkImportResponse> {
            if (!items.length) {
                throw new Error('Select at least one URL to import')
            }
            try {
                const normalizedItems = items.map((item) => ({
                    url: item.url,
                    set_primary: item.set_primary ?? false,
                }))
                const payload: Record<string, unknown> = {
                    items: normalizedItems,
                    enqueue_refresh: Boolean(options.enqueueRefresh),
                }
                if (options.productId) {
                    payload.product_id = options.productId
                }
                if (options.searchQuery && options.searchQuery.trim()) {
                    payload.search_query = options.searchQuery.trim()
                }
                const response = await apiClient.post<BulkImportResponse>(
                    '/product-urls/bulk-import',
                    payload,
                )
                return response.data
            } catch (error) {
                const axiosError = error as AxiosError<{ detail?: string }>
                const detail = axiosError.response?.data?.detail
                const message =
                    detail ??
                    (error instanceof Error
                        ? error.message
                        : 'Failed to bulk import URLs')
                throw new Error(message)
            }
        },
        reset() {
            this.results = []
            this.cacheHit = null
            this.expiresAt = null
            this.extra = {}
            this.error = null
            this.lastQuery = ''
            this.lastFetchedAt = null
        },
    },
})
