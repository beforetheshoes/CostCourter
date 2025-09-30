import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const get = vi.fn()
    const post = vi.fn()
    const patch = vi.fn()
    const del = vi.fn()
    return {
        apiClient: { get, post, patch, delete: del },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { get, post, patch, delete: del },
    }
})

const pushMock = vi.fn()

vi.mock('vue-router', async (importOriginal) => {
    const actual = (await importOriginal()) as typeof import('vue-router')
    return {
        ...actual,
        useRouter: () => ({
            push: pushMock,
        }),
    }
})

import ProductsView from '../../src/views/ProductsView.vue'
import { apiClient } from '../../src/lib/http'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
}

const CardStub = {
    template:
        '<section><slot name="header" /><slot name="content" /><slot /></section>',
}

const ButtonStub = {
    inheritAttrs: false,
    props: {
        label: { type: String, default: '' },
        loading: { type: Boolean, default: false },
        disabled: { type: Boolean, default: false },
    },
    emits: ['click'],
    template:
        '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot>{{ label }}</slot></button>',
}

const InputStub = {
    inheritAttrs: false,
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template:
        '<input v-bind="$attrs" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const TextareaStub = {
    inheritAttrs: false,
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template:
        '<textarea v-bind="$attrs" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)"></textarea>',
}

const CheckboxStub = {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template:
        '<input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" />',
}

describe('ProductsView', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mocked.get.mockReset()
        mocked.post.mockReset()
        pushMock.mockReset()
    })

    const product = {
        id: 101,
        name: 'Test Product',
        slug: 'test-product',
        description: 'Test description',
        is_active: true,
        image_url: 'https://example.com/test-product.jpg',
        current_price: 129.99,
        price_cache: [],
        latest_price: {
            price: 129.99,
            currency: 'USD',
            recorded_at: '2024-01-01T00:00:00Z',
        },
        last_refreshed_at: '2024-01-01T00:00:00Z',
        price_aggregates: {
            min: 99.99,
            max: 149.99,
            avg: 123.45,
            currency: 'USD',
            locale: 'en_US',
        },
        tags: [{ id: 1, name: 'Electronics', slug: 'electronics' }],
        urls: [],
        price_trend: 'down' as const,
        history_points: [
            { date: '2024-01-01', price: 149.99 },
            { date: '2024-01-02', price: 129.99 },
        ],
    }

    it('renders products and toggles between tile and table view', async () => {
        mocked.get.mockResolvedValueOnce({ data: [product] })

        const { findByText, findByRole, getByRole, queryByText } = render(
            ProductsView,
            {
                global: {
                    stubs: {
                        RouterLink: {
                            props: ['to'],
                            template: '<a><slot /></a>',
                        },
                        PvCard: CardStub,
                        PvButton: ButtonStub,
                        PvInputText: InputStub,
                        PvInputTextarea: TextareaStub,
                        PvCheckbox: CheckboxStub,
                    },
                },
            },
        )

        expect(await findByText('Test Product')).toBeTruthy()
        expect(
            await findByRole('img', { name: /Test Product cover art/i }),
        ).toBeTruthy()
        const tableButton = getByRole('button', { name: /table view/i })
        await fireEvent.click(tableButton)
        expect(
            await findByRole('img', { name: /Test Product thumbnail/i }),
        ).toBeTruthy()
        expect(queryByText('test-product')).toBeNull()
    })

    it('creates a product and navigates to detail', async () => {
        mocked.get.mockResolvedValueOnce({ data: [] })
        mocked.post.mockResolvedValueOnce({ data: product })

        const { getByPlaceholderText, getByRole } = render(ProductsView, {
            global: {
                stubs: {
                    RouterLink: {
                        props: ['to'],
                        template: '<a><slot /></a>',
                    },
                    PvCard: CardStub,
                    PvButton: ButtonStub,
                    PvInputText: InputStub,
                    PvInputTextarea: TextareaStub,
                    PvCheckbox: CheckboxStub,
                },
            },
        })

        await fireEvent.update(
            getByPlaceholderText('Nintendo Switch'),
            'Steam Deck',
        )
        await fireEvent.update(
            getByPlaceholderText('nintendo-switch'),
            'steam-deck',
        )
        await fireEvent.update(
            getByPlaceholderText(/Optional summary/i),
            'Portable PC',
        )
        await fireEvent.update(
            getByPlaceholderText('consoles, gaming'),
            'gaming, portable',
        )

        const submitButton = getByRole('button', { name: /create product/i })
        await fireEvent.click(submitButton)

        await waitFor(() => {
            expect(mocked.post).toHaveBeenCalledWith(
                '/products',
                expect.any(Object),
            )
        })
        await waitFor(() => {
            expect(pushMock).toHaveBeenCalledWith({
                name: 'product-detail',
                params: { id: 101 },
            })
        })
    })

    it('quick adds a product URL and navigates to detail', async () => {
        const quickAddResponse = {
            product_id: 202,
            product_url_id: 404,
            store_id: 12,
            title: 'Quick Added Item',
            price: 59.99,
            currency: 'USD',
            image: 'https://example.com/quick-add.jpg',
            warnings: [],
        }
        const fetchedProduct = {
            id: 202,
            name: 'Quick Added Item',
            slug: 'quick-added-item',
            description: null,
            is_active: true,
            image_url: quickAddResponse.image,
            current_price: 59.99,
            price_cache: [],
            latest_price: {
                price: 59.99,
                currency: 'USD',
                recorded_at: '2024-02-01T00:00:00Z',
            },
            tags: [],
            urls: [],
        }

        mocked.get.mockResolvedValueOnce({ data: [] })
        mocked.post.mockResolvedValueOnce({ data: quickAddResponse })
        mocked.get.mockResolvedValueOnce({ data: fetchedProduct })

        const { getByPlaceholderText, getByRole } = render(ProductsView, {
            global: {
                stubs: {
                    RouterLink: {
                        props: ['to'],
                        template: '<a><slot /></a>',
                    },
                    PvCard: CardStub,
                    PvButton: ButtonStub,
                    PvInputText: InputStub,
                    PvInputTextarea: TextareaStub,
                    PvCheckbox: CheckboxStub,
                },
            },
        })

        await fireEvent.update(
            getByPlaceholderText('https://example.com/product'),
            'https://example.com/new-item',
        )

        const submitButton = getByRole('button', { name: /quick add product/i })
        await fireEvent.click(submitButton)

        await waitFor(() => {
            expect(mocked.post).toHaveBeenCalledWith(
                '/product-urls/quick-add',
                {
                    url: 'https://example.com/new-item',
                },
            )
        })
        await waitFor(() => {
            expect(mocked.get).toHaveBeenCalledWith('/products/202')
        })
        await waitFor(() => {
            expect(pushMock).toHaveBeenCalledWith({
                name: 'product-detail',
                params: { id: 202 },
            })
        })
    })
})
