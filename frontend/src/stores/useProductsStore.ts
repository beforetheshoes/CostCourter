import type { AxiosError } from 'axios'
import { defineStore } from 'pinia'

import { apiClient } from '../lib/http'
import type { BulkImportResponse } from './useSearchStore'

export type ProductTag = {
    id: number
    name: string
    slug: string
}

export type ProductURLStore = {
    id: number
    name: string | null
    slug: string | null
}

export type ProductURL = {
    id: number
    product_id: number
    store_id: number
    url: string
    is_primary: boolean
    active: boolean
    created_by_id: number | null
    store: ProductURLStore | null
    latest_price?: number | null
    latest_price_currency?: string | null
    latest_price_at?: string | null
}

export type ProductPriceCache = {
    store_id?: number | null
    store_name?: string | null
    price?: number | null
    currency?: string | null
    last_scrape?: string | null
    aggregates?: {
        min?: number | null
        max?: number | null
        avg?: number | null
    } | null
}

export type ProductLatestPrice = {
    price: number
    currency: string | null
    recorded_at: string
}

export type Product = {
    id: number
    name: string
    slug: string
    description: string | null
    is_active: boolean
    image_url: string | null
    current_price: number | null
    price_cache: ProductPriceCache[]
    latest_price: ProductLatestPrice | null
    last_refreshed_at?: string | null
    price_aggregates?: {
        min?: number | null
        max?: number | null
        avg?: number | null
        currency?: string | null
        locale?: string | null
    } | null
    tags: ProductTag[]
    urls: ProductURL[]
    price_trend?: 'up' | 'down' | 'lowest' | 'none'
    history_points?: { date: string; price: number }[]
}

export type ProductCreate = {
    name: string
    slug: string
    description?: string | null
    is_active?: boolean
    tag_slugs?: string[]
}

export type ProductUpdatePayload = {
    name?: string
    slug?: string
    description?: string | null
    is_active?: boolean
    tag_slugs?: string[]
}

export type ProductBulkUpdatePayload = {
    product_ids: number[]
    updates: {
        status?: 'published' | 'archived'
        is_active?: boolean
        favourite?: boolean
        only_official?: boolean
    }
}

export type ProductBulkUpdateResponse = {
    updated_ids: number[]
    skipped_ids: number[]
    missing_ids: number[]
}

export type ProductURLCreatePayload = {
    product_id: number
    store_id: number
    url: string
    is_primary?: boolean
    active?: boolean
    created_by_id?: number | null
}

export type ProductURLUpdatePayload = {
    store_id?: number
    url?: string
    is_primary?: boolean
    active?: boolean
    created_by_id?: number | null
}

export type ProductQuickAddResponse = {
    product_id: number
    product_url_id: number
    store_id: number
    title: string
    price: unknown
    currency: string | null
    image: string | null
    warnings: string[]
}

const mergeProductUrls = (urls: ProductURL[], updated: ProductURL) => {
    const others = urls.filter((entry) => entry.id !== updated.id)
    const demoted = updated.is_primary
        ? others.map((entry) => ({ ...entry, is_primary: false }))
        : others
    return [...demoted, updated]
}

export const useProductsStore = defineStore('products', {
    state: () => ({
        items: [] as Product[],
        loading: false,
        error: null as string | null,
    }),
    actions: {
        async list() {
            this.loading = true
            this.error = null
            try {
                const res = await apiClient.get<Product[]>('/products')
                this.items = res.data
            } catch (err) {
                this.error =
                    err instanceof Error
                        ? err.message
                        : 'Failed to load products'
            } finally {
                this.loading = false
            }
        },
        async create(payload: ProductCreate) {
            this.error = null
            try {
                const res = await apiClient.post<Product>('/products', payload)
                this.items.unshift(res.data)
                return res.data
            } catch (err) {
                this.error =
                    err instanceof Error
                        ? err.message
                        : 'Failed to create product'
                throw err
            }
        },
        async quickAdd(url: string) {
            const trimmed = url.trim()
            if (!trimmed) {
                const error = new Error('URL is required')
                this.error = error.message
                throw error
            }

            this.error = null
            try {
                const response = await apiClient.post<ProductQuickAddResponse>(
                    '/product-urls/quick-add',
                    { url: trimmed },
                )
                const result = response.data
                let product: Product | null = null
                try {
                    product = await this.fetch(result.product_id)
                } catch {
                    product = null
                }
                return { result, product }
            } catch (error) {
                const axiosError = error as AxiosError<{ detail?: string }>
                const detail = axiosError.response?.data?.detail
                const message =
                    detail ??
                    (error instanceof Error
                        ? error.message
                        : 'Failed to quick-add product URL')
                this.error = message
                throw new Error(message)
            }
        },
        async quickAddUrlForProduct(
            productId: number,
            url: string,
            options: { setPrimary?: boolean } = {},
        ) {
            const trimmed = url.trim()
            if (!trimmed) {
                const error = new Error('URL is required')
                this.error = error.message
                throw error
            }

            this.error = null
            try {
                const response = await apiClient.post<BulkImportResponse>(
                    '/product-urls/bulk-import',
                    {
                        items: [
                            {
                                url: trimmed,
                                set_primary: Boolean(options.setPrimary),
                            },
                        ],
                        product_id: productId,
                        enqueue_refresh: false,
                    },
                )
                await this.fetch(productId)
                return response.data
            } catch (error) {
                const axiosError = error as AxiosError<{ detail?: string }>
                const detail = axiosError.response?.data?.detail
                const message =
                    detail ??
                    (error instanceof Error
                        ? error.message
                        : 'Failed to add product URL')
                this.error = message
                throw new Error(message)
            }
        },
        async update(productId: number, payload: ProductUpdatePayload) {
            this.error = null
            try {
                const res = await apiClient.patch<Product>(
                    `/products/${productId}`,
                    payload,
                )
                const index = this.items.findIndex(
                    (item) => item.id === productId,
                )
                if (index >= 0) {
                    this.items.splice(index, 1, res.data)
                }
                return res.data
            } catch (err) {
                this.error =
                    err instanceof Error
                        ? err.message
                        : 'Failed to update product'
                throw err
            }
        },
        async fetch(productId: number) {
            this.error = null
            try {
                const res = await apiClient.get<Product>(
                    `/products/${productId}`,
                )
                const index = this.items.findIndex(
                    (item) => item.id === productId,
                )
                if (index >= 0) {
                    this.items.splice(index, 1, res.data)
                } else {
                    this.items.push(res.data)
                }
                return res.data
            } catch (err) {
                this.error =
                    err instanceof Error
                        ? err.message
                        : 'Failed to load product'
                throw err
            }
        },
        async remove(productId: number) {
            this.error = null
            try {
                await apiClient.delete(`/products/${productId}`)
                this.items = this.items.filter((item) => item.id !== productId)
            } catch (err) {
                this.error =
                    err instanceof Error
                        ? err.message
                        : 'Failed to delete product'
                throw err
            }
        },
        async bulkUpdate(payload: ProductBulkUpdatePayload) {
            this.error = null
            try {
                const res = await apiClient.post<ProductBulkUpdateResponse>(
                    '/products/bulk-update',
                    payload,
                )
                if (res.data.updated_ids.length) {
                    await this.list()
                }
                return res.data
            } catch (err) {
                this.error =
                    err instanceof Error
                        ? err.message
                        : 'Failed to bulk update products'
                throw err
            }
        },
        async createUrl(payload: ProductURLCreatePayload) {
            this.error = null
            try {
                const res = await apiClient.post<ProductURL>(
                    '/product-urls',
                    payload,
                )
                const product = this.items.find(
                    (item) => item.id === payload.product_id,
                )
                if (product) {
                    product.urls = mergeProductUrls(product.urls, res.data)
                }
                return res.data
            } catch (err) {
                this.error =
                    err instanceof Error
                        ? err.message
                        : 'Failed to create product URL'
                throw err
            }
        },
        async updateUrl(
            productId: number,
            productUrlId: number,
            payload: ProductURLUpdatePayload,
        ) {
            this.error = null
            try {
                const res = await apiClient.patch<ProductURL>(
                    `/product-urls/${productUrlId}`,
                    payload,
                )
                const product = this.items.find((item) => item.id === productId)
                if (product) {
                    product.urls = mergeProductUrls(product.urls, res.data)
                }
                return res.data
            } catch (err) {
                this.error =
                    err instanceof Error
                        ? err.message
                        : 'Failed to update product URL'
                throw err
            }
        },
        async deleteUrl(productId: number, productUrlId: number) {
            this.error = null
            try {
                await apiClient.delete(`/product-urls/${productUrlId}`)
                const product = this.items.find((item) => item.id === productId)
                if (product) {
                    product.urls = product.urls.filter(
                        (url) => url.id !== productUrlId,
                    )
                }
            } catch (err) {
                this.error =
                    err instanceof Error
                        ? err.message
                        : 'Failed to delete product URL'
                throw err
            }
        },
    },
})
