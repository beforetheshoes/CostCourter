import { defineStore } from 'pinia'

import { apiClient } from '../lib/http'

export type DashboardTotals = {
    products: number
    favourites: number
    active_urls: number
}

export type DashboardProductSummary = {
    id: number
    name: string
    slug: string
    current_price: number | null
    trend: string
    store_name: string | null
    image_url: string | null
    last_refreshed_at: string | null
    history: Array<{ date: string; price: number }>
}

export type DashboardTagGroup = {
    label: string
    products: DashboardProductSummary[]
}

export type DashboardMetrics = {
    totals: DashboardTotals
    spotlight: DashboardProductSummary[]
    tag_groups: DashboardTagGroup[]
    last_updated_at: string | null
}

type MetricsState = {
    metrics: DashboardMetrics | null
    loading: boolean
    error: string | null
    lastFetchedAt: string | null
}

export const useAdminMetricsStore = defineStore('adminMetrics', {
    state: (): MetricsState => ({
        metrics: null,
        loading: false,
        error: null,
        lastFetchedAt: null,
    }),
    actions: {
        async fetchMetrics(): Promise<void> {
            if (this.loading) return
            this.loading = true
            this.error = null
            try {
                const response =
                    await apiClient.get<DashboardMetrics>('/admin/dashboard')
                this.metrics = response.data
                this.lastFetchedAt = new Date().toISOString()
            } catch (error) {
                const message =
                    error instanceof Error
                        ? error.message
                        : 'Failed to load dashboard metrics'
                this.error = message
                this.metrics = null
            } finally {
                this.loading = false
            }
        },
        reset(): void {
            this.metrics = null
            this.error = null
            this.lastFetchedAt = null
        },
    },
})
