import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const get = vi.fn()
    const put = vi.fn()
    const post = vi.fn()
    return {
        apiClient: { get, put, post },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { get, put, post },
    }
})

import NotificationsView from '../../src/views/NotificationsView.vue'
import { apiClient } from '../../src/lib/http'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    put: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
}

const mockedGet = mocked.get
const mockedPut = mocked.put
const mockedPost = mocked.post

describe('NotificationsView', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mockedGet.mockReset()
        mockedPut.mockReset()
        mockedPost.mockReset()
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
                        config: {
                            api_token: '__SECRET_PRESENT__',
                            user_key: '__SECRET_PRESENT__',
                        },
                        config_fields: [
                            {
                                key: 'api_token',
                                label: 'API token',
                                description: 'Pushover application token.',
                                required: true,
                                secret: true,
                                placeholder: 'abc123',
                            },
                            {
                                key: 'user_key',
                                label: 'User key',
                                description: 'Recipient key.',
                                required: true,
                                secret: true,
                                placeholder: 'def456',
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
                config: {
                    api_token: '__SECRET_PRESENT__',
                    user_key: '__SECRET_PRESENT__',
                },
                config_fields: [
                    {
                        key: 'api_token',
                        label: 'API token',
                        description: 'Pushover application token.',
                        required: true,
                        secret: true,
                        placeholder: 'abc123',
                    },
                    {
                        key: 'user_key',
                        label: 'User key',
                        description: 'Recipient key.',
                        required: true,
                        secret: true,
                        placeholder: 'def456',
                    },
                ],
            },
        })

        mockedPost.mockResolvedValue({})

        const { findByText, getByLabelText, getByRole } =
            render(NotificationsView)

        expect(await findByText('Pushover')).toBeTruthy()
        const tokenInput = getByLabelText('API token') as HTMLInputElement
        const userInput = getByLabelText('User key') as HTMLInputElement
        expect(tokenInput.value).toBe('••••••••')
        expect(tokenInput.disabled).toBe(true)
        expect(userInput.value).toBe('••••••••')
        expect(userInput.disabled).toBe(true)

        const testButton = getByRole('button', {
            name: 'Send test notification',
        })
        await fireEvent.click(testButton)
        await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1))
        expect(mockedPost).toHaveBeenCalledWith(
            '/notifications/channels/pushover/test',
        )
        mockedPost.mockClear()

        const modifyButton = getByRole('button', { name: 'Modify' })
        await fireEvent.click(modifyButton)

        expect(tokenInput.disabled).toBe(false)
        expect(userInput.disabled).toBe(false)

        await fireEvent.update(tokenInput, '  new-token  ')
        await fireEvent.update(userInput, '  new-key  ')
        const checkbox = getByRole('checkbox') as HTMLInputElement
        expect(checkbox.checked).toBe(true)

        await fireEvent.click(getByRole('button', { name: 'Save' }))

        await waitFor(() => expect(mockedPut).toHaveBeenCalledTimes(1))
        expect(mockedPut).toHaveBeenCalledWith(
            '/notifications/channels/pushover',
            {
                enabled: true,
                config: { api_token: 'new-token', user_key: 'new-key' },
            },
        )
    })
})
