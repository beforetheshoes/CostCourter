import { defineStore } from 'pinia'

import { apiClient } from '../lib/http'

export type NotificationConfigField = {
    key: string
    label: string
    description: string | null
    required: boolean
    secret: boolean
    placeholder: string | null
}

export type NotificationChannel = {
    channel: string
    display_name: string
    description: string | null
    available: boolean
    unavailable_reason: string | null
    enabled: boolean
    config: Record<string, string | null>
    config_fields: NotificationConfigField[]
}

type NotificationChannelListResponse = {
    channels: NotificationChannel[]
}

type UpdatePayload = {
    enabled: boolean
    config?: Record<string, string | null>
}

export const useNotificationsStore = defineStore('notifications', {
    state: () => ({
        channels: [] as NotificationChannel[],
        loading: false,
        error: null as string | null,
        updating: {} as Record<string, boolean>,
    }),
    actions: {
        async fetchChannels() {
            this.loading = true
            this.error = null
            try {
                const response =
                    await apiClient.get<NotificationChannelListResponse>(
                        '/notifications/channels',
                    )
                this.channels = response.data.channels
            } catch (error) {
                const message =
                    error instanceof Error
                        ? error.message
                        : 'Failed to load notification channels'
                this.error = message
                this.channels = []
                throw error
            } finally {
                this.loading = false
            }
        },
        async updateChannel(channel: string, payload: UpdatePayload) {
            this.updating = { ...this.updating, [channel]: true }
            const body: UpdatePayload = { enabled: payload.enabled }
            if (payload.config !== undefined) {
                body.config = payload.config
            }
            try {
                const response = await apiClient.put<NotificationChannel>(
                    `/notifications/channels/${channel}`,
                    body,
                )
                const index = this.channels.findIndex(
                    (entry) => entry.channel === channel,
                )
                if (index >= 0) {
                    this.channels.splice(index, 1, response.data)
                } else {
                    this.channels.push(response.data)
                }
                return response.data
            } finally {
                this.updating = { ...this.updating, [channel]: false }
            }
        },
    },
})
