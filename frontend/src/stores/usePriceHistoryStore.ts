import { defineStore } from 'pinia'

import { apiClient } from '../lib/http'

type PriceHistoryEntry = {
    id: number
    product_id: number
    product_url_id: number | null
    price: number
    currency: string
    recorded_at: string
    product_url?: {
        url: string
        store?: {
            name: string
            slug: string
        }
    } | null
}

export const usePriceHistoryStore = defineStore('priceHistory', {
    state: () => ({
        entries: [] as PriceHistoryEntry[],
        loading: false,
        error: null as string | null,
    }),
    actions: {
        async loadForProduct(productId: number) {
            this.loading = true
            this.error = null
            try {
                const response = await apiClient.get<PriceHistoryEntry[]>(
                    '/price-history',
                    {
                        params: { product_id: productId },
                    },
                )
                this.entries = response.data
            } catch (error) {
                if (error instanceof Error) {
                    this.error = error.message
                } else {
                    this.error = 'Unable to load price history'
                }
                this.entries = []
                throw error
            } finally {
                this.loading = false
            }
        },
        reset() {
            this.entries = []
            this.error = null
            this.loading = false
        },
    },
})
