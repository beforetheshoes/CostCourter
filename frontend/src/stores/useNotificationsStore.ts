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
        testing: {} as Record<string, boolean>,
        testStatus: {} as Record<
            string,
            { success: boolean; message: string } | null
        >,
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
                const knownChannels = new Set(
                    response.data.channels.map((entry) => entry.channel),
                )
                const retainedStatus: typeof this.testStatus = {}
                Object.entries(this.testStatus).forEach(([key, value]) => {
                    if (knownChannels.has(key)) {
                        retainedStatus[key] = value
                    }
                })
                this.testStatus = retainedStatus
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
                this.testStatus = { ...this.testStatus, [channel]: null }
                return response.data
            } finally {
                this.updating = { ...this.updating, [channel]: false }
            }
        },
        async testChannel(channel: string) {
            this.testing = { ...this.testing, [channel]: true }
            this.testStatus = { ...this.testStatus, [channel]: null }
            try {
                await apiClient.post(`/notifications/channels/${channel}/test`)
                this.testStatus = {
                    ...this.testStatus,
                    [channel]: {
                        success: true,
                        message: 'Test notification sent successfully.',
                    },
                }
            } catch (error) {
                let message = 'Failed to send test notification'
                if (
                    typeof error === 'object' &&
                    error !== null &&
                    'response' in error &&
                    error.response &&
                    typeof error.response === 'object' &&
                    'data' in error.response &&
                    error.response.data &&
                    typeof error.response.data === 'object' &&
                    'detail' in error.response.data
                ) {
                    message = String(error.response.data.detail)
                } else if (error instanceof Error) {
                    message = error.message
                }
                this.testStatus = {
                    ...this.testStatus,
                    [channel]: { success: false, message },
                }
                throw error
            } finally {
                this.testing = { ...this.testing, [channel]: false }
            }
        },
    },
})
