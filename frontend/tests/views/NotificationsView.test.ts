import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, waitFor } from '@testing-library/vue'
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

import NotificationsView from '../../src/views/NotificationsView.vue'
import { apiClient } from '../../src/lib/http'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    put: ReturnType<typeof vi.fn>
}

const mockedGet = mocked.get
const mockedPut = mocked.put

describe('NotificationsView', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mockedGet.mockReset()
        mockedPut.mockReset()
    })

    it('renders channels and allows updating configuration', async () => {
        mockedGet.mockResolvedValue({
            data: {
                channels: [
                    {
                        channel: 'pushover',
                        display_name: 'Pushover',
                        description: 'Send push alerts',
                        available: true,
                        unavailable_reason: null,
                        enabled: true,
                        config: { user_key: 'existing-key' },
                        config_fields: [
                            {
                                key: 'user_key',
                                label: 'User key',
                                description: 'Override the default key.',
                                required: false,
                                secret: false,
                                placeholder: 'abc123',
                            },
                        ],
                    },
                ],
            },
        })

        mockedPut.mockResolvedValue({
            data: {
                channel: 'pushover',
                display_name: 'Pushover',
                description: 'Send push alerts',
                available: true,
                unavailable_reason: null,
                enabled: false,
                config: { user_key: 'new-key' },
                config_fields: [
                    {
                        key: 'user_key',
                        label: 'User key',
                        description: 'Override the default key.',
                        required: false,
                        secret: false,
                        placeholder: 'abc123',
                    },
                ],
            },
        })

        const { findByText, getByLabelText, getByRole } =
            render(NotificationsView)

        expect(await findByText('Pushover')).toBeTruthy()
        const input = getByLabelText('User key') as HTMLInputElement
        expect(input.value).toBe('existing-key')

        await fireEvent.update(input, '  new-key  ')
        const checkbox = getByRole('checkbox') as HTMLInputElement
        expect(checkbox.checked).toBe(true)

        await fireEvent.click(getByRole('button', { name: 'Save' }))

        await waitFor(() => expect(mockedPut).toHaveBeenCalledTimes(1))
        expect(mockedPut).toHaveBeenCalledWith(
            '/notifications/channels/pushover',
            {
                enabled: true,
                config: { user_key: 'new-key' },
            },
        )
    })
})
