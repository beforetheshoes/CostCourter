import { defineStore } from 'pinia'

import { apiClient } from '../lib/http'

const DEFAULT_PAGE_SIZE = 10

type PriceTrend = 'up' | 'down' | 'lowest' | 'none'

type StoreSummary = {
    id: number
    name: string
    slug: string
    locale: string | null
    currency: string | null
}

type CatalogPriceCacheEntry = {
    currency: string | null
    aggregates?: {
        min?: number | null
        max?: number | null
        avg?: number | null
    } | null
    [key: string]: unknown
}

type HistoryPoint = {
    date: string
    price: number
}

type CatalogProductUrlRead = {
    id: number
    url: string
    is_primary: boolean
    active: boolean
    latest_price: number | null
    latest_price_currency: string | null
    latest_price_at: string | null
    store: StoreSummary | null
}

type CatalogProductRead = {
    id: number
    name: string
    slug: string
    description: string | null
    is_active: boolean
    tags: { name: string; slug: string }[]
    urls: CatalogProductUrlRead[]
    current_price: number | null
    latest_price: {
        price: number
        currency: string
        recorded_at: string
    } | null
    price_trend: PriceTrend
    last_refreshed_at: string | null
    history_points: HistoryPoint[]
    price_cache: CatalogPriceCacheEntry[]
    price_aggregates: {
        min?: number | null
        max?: number | null
        avg?: number | null
        currency?: string | null
        locale?: string | null
    } | null
}

export type CatalogProductUrl = {
    id: number
    url: string
    is_primary: boolean
    active: boolean
    latestPrice: number | null
    latestPriceCurrency: string | null
    latestPriceAt: string | null
    store: StoreSummary | null
}

export type CatalogProductSummary = {
    id: number
    name: string
    slug: string
    primaryUrl: string | null
    currentPrice: number | null
    latestPrice: number | null
    currency: string | null
    lastRefreshedAt: string | null
    priceTrend: PriceTrend
    historyPoints: HistoryPoint[]
    tags: string[]
    urls: CatalogProductUrl[]
    aggregates: {
        min: number | null
        max: number | null
        avg: number | null
        currency: string | null
    }
}

type CatalogFilters = {
    search: string
    tag: string
    isActive: boolean | null
}

type FetchOptions = {
    search?: string
    tag?: string
    isActive?: boolean | null
    page?: number
    pageSize?: number
}

export const useCatalogStore = defineStore('catalog', {
    state: () => ({
        items: [] as CatalogProductSummary[],
        loading: false,
        error: null as string | null,
        loaded: false,
        page: 1,
        pageSize: DEFAULT_PAGE_SIZE,
        hasMore: false,
        filters: { search: '', tag: '', isActive: null } as CatalogFilters,
    }),
    actions: {
        async fetchCatalog(options: FetchOptions = {}) {
            this.loading = true
            this.error = null

            const nextFilters: CatalogFilters = {
                search: options.search ?? this.filters.search,
                tag: options.tag ?? this.filters.tag,
                isActive:
                    options.isActive !== undefined
                        ? options.isActive
                        : this.filters.isActive,
            }

            const filtersChanged =
                options.search !== undefined ||
                options.tag !== undefined ||
                options.isActive !== undefined

            const nextPageSize = options.pageSize ?? this.pageSize
            const nextPage = filtersChanged
                ? (options.page ?? 1)
                : (options.page ?? this.page)

            this.pageSize = nextPageSize
            this.page = nextPage

            const params = new URLSearchParams()
            params.set('limit', String(nextPageSize))
            params.set('offset', String((nextPage - 1) * nextPageSize))

            const trimmedSearch = nextFilters.search.trim()
            const trimmedTag = nextFilters.tag.trim()
            this.filters = {
                search: trimmedSearch,
                tag: trimmedTag,
                isActive: nextFilters.isActive,
            }
            if (trimmedSearch) {
                params.set('search', trimmedSearch)
            }
            if (trimmedTag) {
                params.set('tag', trimmedTag)
            }
            if (nextFilters.isActive !== null) {
                params.set('is_active', String(nextFilters.isActive))
            }

            try {
                const response = await apiClient.get<CatalogProductRead[]>(
                    `/products?${params.toString()}`,
                )
                this.items = response.data.map((product) => {
                    const latest = product.latest_price
                    const urls: CatalogProductUrl[] = product.urls.map(
                        (url) => ({
                            id: url.id,
                            url: url.url,
                            is_primary: url.is_primary,
                            active: url.active,
                            latestPrice:
                                typeof url.latest_price === 'number'
                                    ? url.latest_price
                                    : null,
                            latestPriceCurrency:
                                url.latest_price_currency ?? null,
                            latestPriceAt: url.latest_price_at ?? null,
                            store: url.store,
                        }),
                    )

                    const currency =
                        latest?.currency ??
                        product.price_cache.find((entry) => entry.currency)
                            ?.currency ??
                        null

                    const aggregateSource =
                        product.price_aggregates ??
                        product.price_cache[0]?.aggregates ??
                        {}
                    const minAggregate =
                        typeof aggregateSource?.min === 'number'
                            ? aggregateSource.min
                            : null
                    const maxAggregate =
                        typeof aggregateSource?.max === 'number'
                            ? aggregateSource.max
                            : null
                    const avgAggregate =
                        typeof aggregateSource?.avg === 'number'
                            ? aggregateSource.avg
                            : null

                    return {
                        id: product.id,
                        name: product.name,
                        slug: product.slug,
                        primaryUrl:
                            product.urls.find((url) => url.is_primary)?.url ??
                            null,
                        currentPrice: product.current_price,
                        latestPrice: latest?.price ?? product.current_price,
                        currency,
                        lastRefreshedAt:
                            product.last_refreshed_at ??
                            latest?.recorded_at ??
                            null,
                        priceTrend: product.price_trend,
                        historyPoints: product.history_points.map((point) => ({
                            date: point.date,
                            price: point.price,
                        })),
                        tags: product.tags.map((tag) => tag.name),
                        urls,
                        aggregates: {
                            min: minAggregate,
                            max: maxAggregate,
                            avg: avgAggregate,
                            currency,
                        },
                    }
                })
                this.hasMore = response.data.length === nextPageSize
                this.loaded = true
            } catch (error) {
                this.error =
                    error instanceof Error
                        ? error.message
                        : 'Unable to load catalog'
            } finally {
                this.loading = false
            }
        },
        reset() {
            this.items = []
            this.loaded = false
            this.error = null
            this.page = 1
            this.pageSize = DEFAULT_PAGE_SIZE
            this.hasMore = false
            this.filters = { search: '', tag: '', isActive: null }
        },
    },
})
