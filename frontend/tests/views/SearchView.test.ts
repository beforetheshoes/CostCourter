import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const get = vi.fn()
    const post = vi.fn()
    return {
        apiClient: { get, post },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { get, post },
    }
})

import SearchView from '../../src/views/SearchView.vue'
import { apiClient } from '../../src/lib/http'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
}

const mockedGet = mocked.get
const mockedPost = mocked.post

const CardStub = {
    template:
        '<section><slot name="header" /><slot name="content" /></section>',
}

const ButtonStub = {
    props: ['label', 'loading', 'disabled', 'type'],
    emits: ['click'],
    template:
        '<button :disabled="disabled || loading" :type="type" @click="$emit(\'click\')"><slot>{{ label }}</slot></button>',
}

const InputStub = {
    inheritAttrs: false,
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template:
        '<input v-bind="$attrs" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

describe('SearchView', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mockedGet.mockReset()
        mockedPost.mockReset()
    })

    it('renders search results after querying', async () => {
        mockedGet.mockResolvedValue({
            data: {
                query: 'headphones',
                cache_hit: false,
                expires_at: null,
                extra: { engines: { google: 1 } },
                results: [
                    {
                        title: 'Noise Cancelling Headphones',
                        url: 'https://example.com/product',
                        snippet: 'Premium sound',
                        thumbnail: null,
                        domain: 'example.com',
                        relevance: 0,
                        engine: 'google',
                        score: 12.5,
                        store_id: null,
                        store_name: null,
                    },
                ],
            },
        })

        const { getByPlaceholderText, getByRole, getByText, findByText } =
            render(SearchView, {
                global: {
                    stubs: {
                        PvCard: CardStub,
                        PvButton: ButtonStub,
                        PvInputText: InputStub,
                    },
                },
            })

        const input = getByPlaceholderText(
            'Search products…',
        ) as HTMLInputElement
        await fireEvent.update(input, 'headphones')
        await fireEvent.click(getByRole('button', { name: 'Search' }))

        await waitFor(() => expect(mockedGet).toHaveBeenCalled())
        expect(await findByText('Noise Cancelling Headphones')).toBeTruthy()
        expect(getByText('example.com')).toBeTruthy()
    })

    it('quick-adds a result from the list', async () => {
        mockedGet.mockResolvedValue({
            data: {
                query: 'laptop',
                cache_hit: true,
                expires_at: '2025-09-27T00:00:00Z',
                extra: {},
                results: [
                    {
                        title: 'Gaming Laptop',
                        url: 'https://example.com/laptop',
                        snippet: null,
                        thumbnail: null,
                        domain: 'example.com',
                        relevance: 0,
                        engine: 'bing',
                        score: null,
                        store_id: null,
                        store_name: null,
                    },
                ],
            },
        })
        mockedPost.mockResolvedValue({
            data: {
                product_id: 55,
                product_url_id: 88,
                store_id: 7,
                title: 'Gaming Laptop',
                price: null,
                currency: null,
                image: null,
                warnings: ['Metadata missing price'],
            },
        })

        const { getByRole, getByText, getByPlaceholderText, findByText } =
            render(SearchView, {
                global: {
                    stubs: {
                        PvCard: CardStub,
                        PvButton: ButtonStub,
                        PvInputText: InputStub,
                    },
                },
            })

        const input = getByPlaceholderText(
            'Search products…',
        ) as HTMLInputElement
        await fireEvent.update(input, 'laptop')
        await fireEvent.click(getByRole('button', { name: 'Search' }))
        await waitFor(() => expect(mockedGet).toHaveBeenCalled())

        const quickAddButton = getByText('Quick add')
        await fireEvent.click(quickAddButton)

        await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1))
        expect(mockedPost).toHaveBeenCalledWith('/product-urls/quick-add', {
            url: 'https://example.com/laptop',
        })
        expect(await findByText(/product #55/)).toBeTruthy()
        expect(await findByText(/Metadata missing price/)).toBeTruthy()
    })

    it('bulk imports selected URLs', async () => {
        mockedGet.mockResolvedValue({
            data: {
                query: 'headphones',
                cache_hit: false,
                expires_at: null,
                extra: {},
                results: [
                    {
                        title: 'Noise Cancelling Headphones',
                        url: 'https://example.com/product-a',
                        snippet: null,
                        thumbnail: null,
                        domain: 'example.com',
                        relevance: 0,
                        engine: 'google',
                        score: null,
                        store_id: null,
                        store_name: null,
                    },
                    {
                        title: 'Noise Cancelling Headphones Alt',
                        url: 'https://example.com/product-b',
                        snippet: null,
                        thumbnail: null,
                        domain: 'example.com',
                        relevance: 0,
                        engine: 'bing',
                        score: null,
                        store_id: null,
                        store_name: null,
                    },
                ],
            },
        })

        mockedPost.mockResolvedValue({
            data: {
                product_id: 9,
                product_name: 'Noise Cancelling Headphones',
                product_slug: 'noise-cancelling-headphones',
                created_product: true,
                created_urls: [
                    {
                        product_url_id: 101,
                        store_id: 5,
                        url: 'https://example.com/product-a',
                        is_primary: true,
                        price: 199.99,
                        currency: 'USD',
                    },
                ],
                skipped: [],
            },
        })

        const {
            getByRole,
            getByLabelText,
            getAllByLabelText,
            findByText,
            getByPlaceholderText,
        } = render(SearchView, {
            global: {
                stubs: {
                    PvCard: CardStub,
                    PvButton: ButtonStub,
                    PvInputText: InputStub,
                },
            },
        })

        const input = getByPlaceholderText(
            'Search products…',
        ) as HTMLInputElement
        await fireEvent.update(input, 'headphones')
        await fireEvent.click(getByRole('button', { name: 'Search' }))
        await waitFor(() => expect(mockedGet).toHaveBeenCalled())

        const selectionCheckboxes = getAllByLabelText(/^Select/)
        await fireEvent.click(selectionCheckboxes[0])
        await fireEvent.click(selectionCheckboxes[1])

        const primaryRadio = getByLabelText(
            'Mark Noise Cancelling Headphones as primary',
        ) as HTMLInputElement
        await fireEvent.click(primaryRadio)

        const productIdInput = getByLabelText(
            'Existing product ID',
        ) as HTMLInputElement
        await fireEvent.update(productIdInput, '9')

        const enqueueCheckbox = getByLabelText(
            'Queue refresh',
        ) as HTMLInputElement
        await fireEvent.click(enqueueCheckbox)

        await fireEvent.click(getByRole('button', { name: 'Bulk import' }))

        await waitFor(() => expect(mockedPost).toHaveBeenCalledTimes(1))
        expect(mockedPost).toHaveBeenCalledWith('/product-urls/bulk-import', {
            items: [
                { url: 'https://example.com/product-a', set_primary: true },
                { url: 'https://example.com/product-b', set_primary: false },
            ],
            enqueue_refresh: true,
            product_id: 9,
            search_query: 'headphones',
        })
        expect(await findByText(/Created product #9/)).toBeTruthy()
    })

    it('displays an error when the search request fails', async () => {
        mockedGet.mockRejectedValueOnce(new Error('search failed'))

        const { getByPlaceholderText, getByRole, findByText } = render(
            SearchView,
            {
                global: {
                    stubs: {
                        PvCard: CardStub,
                        PvButton: ButtonStub,
                        PvInputText: InputStub,
                    },
                },
            },
        )

        await fireEvent.update(
            getByPlaceholderText('Search products…'),
            'router',
        )
        await fireEvent.click(getByRole('button', { name: 'Search' }))

        expect(await findByText('search failed')).toBeTruthy()
    })

    it('shows quick add failures from the API', async () => {
        mockedGet.mockResolvedValue({
            data: {
                query: 'camera',
                cache_hit: false,
                expires_at: null,
                extra: {},
                results: [
                    {
                        title: 'Digital Camera',
                        url: 'https://example.com/camera',
                        snippet: null,
                        thumbnail: null,
                        domain: 'example.com',
                        relevance: 0,
                        engine: 'google',
                        score: null,
                        store_id: null,
                        store_name: null,
                    },
                ],
            },
        })
        mockedPost.mockRejectedValueOnce({
            response: { data: { detail: 'Already imported' } },
        })

        const { getByPlaceholderText, getByRole, findByText } = render(
            SearchView,
            {
                global: {
                    stubs: {
                        PvCard: CardStub,
                        PvButton: ButtonStub,
                        PvInputText: InputStub,
                    },
                },
            },
        )

        await fireEvent.update(
            getByPlaceholderText('Search products…'),
            'camera',
        )
        await fireEvent.click(getByRole('button', { name: 'Search' }))
        await waitFor(() => expect(mockedGet).toHaveBeenCalled())

        await fireEvent.click(getByRole('button', { name: 'Quick add' }))

        expect(await findByText('Already imported')).toBeTruthy()
    })

    it('surfaces errors when bulk import fails', async () => {
        mockedGet.mockResolvedValue({
            data: {
                query: 'headphones',
                cache_hit: false,
                expires_at: null,
                extra: {},
                results: [
                    {
                        title: 'Noise Cancelling Headphones',
                        url: 'https://example.com/product-a',
                        snippet: null,
                        thumbnail: null,
                        domain: 'example.com',
                        relevance: 0,
                        engine: 'google',
                        score: null,
                        store_id: null,
                        store_name: null,
                    },
                ],
            },
        })

        mockedPost.mockRejectedValueOnce(new Error('bulk failed'))

        const { getByRole, getByLabelText, getByPlaceholderText, findByText } =
            render(SearchView, {
                global: {
                    stubs: {
                        PvCard: CardStub,
                        PvButton: ButtonStub,
                        PvInputText: InputStub,
                    },
                },
            })

        await fireEvent.update(
            getByPlaceholderText('Search products…'),
            'headphones',
        )
        await fireEvent.click(getByRole('button', { name: 'Search' }))
        await waitFor(() => expect(mockedGet).toHaveBeenCalled())

        await fireEvent.click(getByLabelText(/^Select/))
        await fireEvent.click(getByRole('radio', { name: /mark/i }))
        await fireEvent.click(getByRole('button', { name: 'Bulk import' }))

        expect(await findByText('bulk failed')).toBeTruthy()
    })

    it('clears results and selections on demand', async () => {
        mockedGet.mockResolvedValue({
            data: {
                query: 'tablet',
                cache_hit: true,
                expires_at: null,
                extra: {},
                results: [
                    {
                        title: 'Android Tablet',
                        url: 'https://example.com/tablet',
                        snippet: null,
                        thumbnail: null,
                        domain: 'example.com',
                        relevance: 0,
                        engine: 'google',
                        score: null,
                        store_id: null,
                        store_name: null,
                    },
                ],
            },
        })

        const { getByPlaceholderText, getByRole, findByRole, queryByRole } =
            render(SearchView, {
                global: {
                    stubs: {
                        PvCard: CardStub,
                        PvButton: ButtonStub,
                        PvInputText: InputStub,
                    },
                },
            })

        const input = getByPlaceholderText(
            'Search products…',
        ) as HTMLInputElement
        await fireEvent.update(input, 'tablet')
        await fireEvent.click(getByRole('button', { name: 'Search' }))
        await findByRole('button', { name: 'Quick add' })

        await fireEvent.click(getByRole('button', { name: 'Clear' }))

        await waitFor(() => {
            expect(queryByRole('button', { name: 'Quick add' })).toBeNull()
        })
        expect(input.value).toBe('')
    })
})
