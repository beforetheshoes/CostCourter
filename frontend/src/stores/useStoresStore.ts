import type { AxiosError } from 'axios'
import { defineStore } from 'pinia'

import { apiClient } from '../lib/http'

type StoreDomain = {
    domain: string
}

type StoreStrategyField = {
    type: string
    value: string
    data?: unknown
}

type StoreRecord = {
    id: number
    name: string
    slug: string
    website_url: string | null
    active: boolean
    domains: StoreDomain[]
    scrape_strategy: Record<string, StoreStrategyField>
    settings: Record<string, unknown>
    notes: string | null
    locale: string | null
    currency: string | null
}

type StoreCreatePayload = {
    name: string
    slug: string
    website_url?: string | null
    active?: boolean
    domains?: StoreDomain[]
    scrape_strategy?: Record<string, StoreStrategyField>
    settings?: Record<string, unknown>
    notes?: string | null
    locale?: string | null
    currency?: string | null
}

type StoreUpdatePayload = Partial<StoreCreatePayload> & {
    domains?: StoreDomain[]
    scrape_strategy?: Record<string, StoreStrategyField>
}

export const useStoresStore = defineStore('stores', {
    state: () => ({
        items: [] as StoreRecord[],
        loading: false,
        error: null as string | null,
    }),
    actions: {
        async list() {
            this.loading = true
            this.error = null
            try {
                const response = await apiClient.get<StoreRecord[]>('/stores')
                this.items = response.data
            } catch (error) {
                this.error =
                    error instanceof Error
                        ? error.message
                        : 'Failed to load stores'
            } finally {
                this.loading = false
            }
        },
        async create(payload: StoreCreatePayload) {
            this.error = null
            try {
                const response = await apiClient.post<StoreRecord>(
                    '/stores',
                    payload,
                )
                this.items.unshift(response.data)
                return response.data
            } catch (error) {
                this.error =
                    error instanceof Error
                        ? error.message
                        : 'Failed to create store'
                throw error
            }
        },
        async update(id: number, payload: StoreUpdatePayload) {
            this.error = null
            try {
                const response = await apiClient.patch<StoreRecord>(
                    `/stores/${id}`,
                    payload,
                )
                const index = this.items.findIndex((store) => store.id === id)
                if (index !== -1) {
                    this.items[index] = response.data
                }
                return response.data
            } catch (error) {
                this.error =
                    error instanceof Error
                        ? error.message
                        : 'Failed to update store'
                throw error
            }
        },
        async remove(id: number) {
            this.error = null
            try {
                await apiClient.delete(`/stores/${id}`)
                this.items = this.items.filter((store) => store.id !== id)
            } catch (error) {
                const axiosError = error as AxiosError<{ detail?: string }>
                const detail = axiosError.response?.data?.detail
                const message =
                    detail ??
                    (error instanceof Error
                        ? error.message
                        : 'Failed to delete store')
                this.error = message
                throw new Error(message)
            }
        },
    },
})

export type { StoreCreatePayload, StoreUpdatePayload, StoreRecord }
