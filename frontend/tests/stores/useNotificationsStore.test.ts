import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const get = vi.fn()
    const put = vi.fn()
    return {
        apiClient: { get, put },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { get, put },
    }
})

import { apiClient } from '../../src/lib/http'
import { useNotificationsStore } from '../../src/stores/useNotificationsStore'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    put: ReturnType<typeof vi.fn>
}

const mockedGet = mocked.get
const mockedPut = mocked.put

describe('useNotificationsStore', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mockedGet.mockReset()
        mockedPut.mockReset()
    })

    it('loads channels from the API', async () => {
        mockedGet.mockResolvedValue({
            data: {
                channels: [
                    {
                        channel: 'email',
                        display_name: 'Email',
                        description: 'SMTP alerts',
                        available: true,
                        unavailable_reason: null,
                        enabled: true,
                        config: {},
                        config_fields: [],
                    },
                ],
            },
        })

        const store = useNotificationsStore()
        await store.fetchChannels()

        expect(mockedGet).toHaveBeenCalledWith('/notifications/channels')
        expect(store.channels).toHaveLength(1)
        expect(store.channels[0].channel).toBe('email')
        expect(store.error).toBeNull()
        expect(store.loading).toBe(false)
    })

    it('captures errors when loading channels fails', async () => {
        mockedGet.mockRejectedValue(new Error('network failure'))
        const store = useNotificationsStore()

        await expect(store.fetchChannels()).rejects.toThrowError(
            'network failure',
        )
        expect(store.channels).toEqual([])
        expect(store.error).toBe('network failure')
        expect(store.loading).toBe(false)
    })

    it('updates a channel and merges it into state', async () => {
        const store = useNotificationsStore()
        store.channels = [
            {
                channel: 'email',
                display_name: 'Email',
                description: null,
                available: true,
                unavailable_reason: null,
                enabled: true,
                config: {},
                config_fields: [],
            },
        ]

        mockedPut.mockResolvedValue({
            data: {
                channel: 'email',
                display_name: 'Email',
                description: null,
                available: true,
                unavailable_reason: null,
                enabled: false,
                config: {},
                config_fields: [],
            },
        })

        await store.updateChannel('email', { enabled: false })

        expect(mockedPut).toHaveBeenCalledWith(
            '/notifications/channels/email',
            {
                enabled: false,
            },
        )
        expect(store.channels[0].enabled).toBe(false)
        expect(store.updating.email).toBe(false)
    })
})
