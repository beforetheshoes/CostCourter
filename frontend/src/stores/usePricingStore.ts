import { defineStore } from 'pinia'

import { apiClient } from '../lib/http'

type PriceFetchResult = {
    product_url_id: number
    success: boolean
    price: number | null
    currency: string | null
    reason: string | null
}

type PriceFetchSummary = {
    total_urls: number
    successful_urls: number
    failed_urls: number
    results: PriceFetchResult[]
}

export type PricingScheduleEntry = {
    name: string
    task: string
    schedule?: unknown
    enabled?: boolean | null
    args?: unknown[]
    kwargs?: Record<string, unknown>
    minute?: string | number | null
    hour?: string | number | null
    day_of_week?: string | number | null
    day_of_month?: string | number | null
    month_of_year?: string | number | null
    last_run_at?: string | null
    next_run_at?: string | null
}

type PricingScheduleResponse = {
    entries: PricingScheduleEntry[]
}

export const usePricingStore = defineStore('pricing', {
    state: () => ({
        summary: null as PriceFetchSummary | null,
        loading: false,
        error: null as string | null,
    }),
    actions: {
        async loadSchedule() {
            this.error = null
            try {
                const response =
                    await apiClient.get<PricingScheduleResponse>(
                        '/pricing/schedule',
                    )
                return response.data.entries
            } catch (error) {
                if (error instanceof Error) return []
                return []
            }
        },
        async updateSchedule(entries: PricingScheduleEntry[]) {
            this.error = null
            try {
                const sanitised = entries.map((entry) => {
                    const { last_run_at, next_run_at, ...rest } = entry
                    void last_run_at
                    void next_run_at
                    return rest
                })
                const response = await apiClient.put<PricingScheduleResponse>(
                    '/pricing/schedule',
                    { entries: sanitised },
                )
                return response.data.entries
            } catch (error) {
                if (error instanceof Error) {
                    this.error = error.message
                } else {
                    this.error = 'Unexpected error saving schedule'
                }
                throw error
            }
        },
        async refreshAll(logging = false) {
            this.loading = true
            this.error = null
            try {
                const response = await apiClient.post<PriceFetchSummary>(
                    '/pricing/products/fetch-all',
                    undefined,
                    {
                        params: logging ? { logging } : undefined,
                    },
                )
                this.summary = response.data
            } catch (error) {
                if (error instanceof Error) {
                    this.error = error.message
                } else {
                    this.error = 'Unexpected error triggering refresh'
                }
            } finally {
                this.loading = false
            }
        },
        async refreshProduct(productId: number, logging = false) {
            this.error = null
            try {
                const response = await apiClient.post<PriceFetchSummary>(
                    `/pricing/products/${productId}/fetch`,
                    undefined,
                    {
                        params: logging ? { logging } : undefined,
                    },
                )
                this.summary = response.data
                return response.data
            } catch (error) {
                if (error instanceof Error) {
                    this.error = error.message
                } else {
                    this.error = 'Unexpected error triggering refresh'
                }
                throw error
            }
        },
    },
})
