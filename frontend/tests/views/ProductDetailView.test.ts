import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { fireEvent, render, waitFor, within } from '@testing-library/vue'
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
        useRoute: () => ({ params: { id: '101' } }),
        useRouter: () => ({ push: pushMock }),
    }
})

import ProductDetailView from '../../src/views/ProductDetailView.vue'
import { apiClient } from '../../src/lib/http'
import { usePricingStore } from '../../src/stores/usePricingStore'
import { useProductsStore } from '../../src/stores/useProductsStore'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
    patch: ReturnType<typeof vi.fn>
    delete: ReturnType<typeof vi.fn>
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

const InputTextStub = {
    inheritAttrs: false,
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template:
        '<input v-bind="$attrs" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
}

const CheckboxStub = {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template:
        '<input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" />',
}

type MenuStubItem = {
    label: string
    command?: () => void
    disabled?: boolean
}

const MultiSelectStub = defineComponent({
    name: 'PvMultiSelectStub',
    props: {
        modelValue: { type: Array, default: () => [] },
        options: { type: Array, default: () => [] },
        optionLabel: { type: String, default: 'label' },
        optionValue: { type: String, default: 'value' },
    },
    emits: ['update:modelValue'],
    setup(props, { emit }) {
        return () =>
            h(
                'select',
                {
                    multiple: true,
                    value: props.modelValue.map((value) => String(value)),
                    onChange: (event: Event) => {
                        const target = event.target as HTMLSelectElement
                        const values = Array.from(target.selectedOptions).map(
                            (option) => {
                                const parsed = Number(option.value)
                                return Number.isNaN(parsed)
                                    ? option.value
                                    : parsed
                            },
                        )
                        emit('update:modelValue', values)
                    },
                },
                props.options.map((option: Record<string, unknown>, index) =>
                    h(
                        'option',
                        {
                            key: index,
                            value: String(option[props.optionValue] ?? ''),
                        },
                        String(option[props.optionLabel] ?? option),
                    ),
                ),
            )
    },
})

const MenuStub = defineComponent({
    name: 'PvMenuStub',
    props: {
        model: { type: Array, default: () => [] },
        popup: { type: Boolean, default: false },
    },
    setup(props) {
        return () =>
            h(
                'div',
                { class: 'pv-menu' },
                props.model.map((item: MenuStubItem, index: number) =>
                    h(
                        'button',
                        {
                            type: 'button',
                            onClick: () => item.command && item.command(),
                            disabled: item.disabled,
                            'data-index': index,
                        },
                        item.label,
                    ),
                ),
            )
    },
})

describe('ProductDetailView', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mocked.get.mockReset()
        mocked.post.mockReset()
        mocked.patch.mockReset()
        mocked.delete.mockReset()
        pushMock.mockReset()
        pushMock.mockResolvedValue(undefined)
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
        urls: [
            {
                id: 1,
                product_id: 101,
                store_id: 55,
                url: 'https://example.com/test-product',
                is_primary: true,
                active: true,
                created_by_id: null,
                store: {
                    id: 55,
                    name: 'Example Store',
                    slug: 'example-store',
                    currency: 'USD',
                },
                latest_price: 129.99,
                latest_price_currency: 'USD',
                latest_price_at: '2024-01-01T00:00:00Z',
            },
        ],
        price_trend: 'down' as const,
        history_points: [
            { date: '2024-01-01', price: 149.99 },
            { date: '2024-01-02', price: 129.99 },
        ],
    }

    const historyEntries = [
        {
            id: 1,
            product_id: 101,
            product_url_id: 1,
            price: 129.99,
            currency: 'USD',
            recorded_at: '2024-01-01T00:00:00Z',
            product_url: {
                url: 'https://example.com/test-product',
                store: { name: 'Example Store', slug: 'example-store' },
            },
        },
    ]

    it('renders detail view with tracked URLs and history', async () => {
        const productFixture = structuredClone(product)

        mocked.get.mockImplementation((url: string) => {
            if (url === '/products/101') {
                return Promise.resolve({ data: productFixture })
            }
            if (url.startsWith('/price-history')) {
                return Promise.resolve({ data: historyEntries })
            }
            return Promise.resolve({ data: [] })
        })

        const { findByText, findAllByText, findByRole, queryByText } = render(
            ProductDetailView,
            {
                global: {
                    stubs: {
                        RouterLink: {
                            props: ['to'],
                            template: '<a><slot /></a>',
                        },
                        PvCard: CardStub,
                        PvButton: ButtonStub,
                        PvInputText: InputTextStub,
                        PvCheckbox: CheckboxStub,
                        ProductHistoryChart: {
                            template: '<div data-testid="history-chart" />',
                        },
                        PvInputTextarea: {
                            template: '<textarea />',
                        },
                    },
                },
            },
        )

        expect(await findByText('Test Product')).toBeTruthy()
        expect(
            await findByRole('img', { name: /Test Product cover art/i }),
        ).toBeTruthy()
        const links = await findAllByText('https://example.com/test-product')
        expect(links.length).toBeGreaterThan(0)
        expect(await findByText('Tracked URL')).toBeTruthy()
        expect(queryByText(/slug/i)).toBeNull()
    })

    it('toggles a tracked URL active status', async () => {
        const productFixture = structuredClone(product)

        mocked.get.mockImplementation((url: string) => {
            if (url === '/products/101') {
                return Promise.resolve({ data: productFixture })
            }
            if (url.startsWith('/price-history')) {
                return Promise.resolve({ data: historyEntries })
            }
            return Promise.resolve({ data: [] })
        })
        mocked.patch.mockResolvedValueOnce({
            data: {
                ...product.urls[0],
                active: false,
            },
        })

        const { findByRole } = render(ProductDetailView, {
            global: {
                stubs: {
                    RouterLink: {
                        props: ['to'],
                        template: '<a><slot /></a>',
                    },
                    PvCard: CardStub,
                    PvButton: ButtonStub,
                    PvInputText: InputTextStub,
                    PvCheckbox: CheckboxStub,
                    PvMultiSelect: MultiSelectStub,
                    PvMenu: MenuStub,
                    ProductHistoryChart: {
                        template: '<div />',
                    },
                    PvInputTextarea: {
                        template: '<textarea />',
                    },
                },
            },
        })

        const toggleButton = await findByRole('button', { name: /deactivate/i })
        await fireEvent.click(toggleButton)

        await waitFor(() => {
            expect(mocked.patch).toHaveBeenCalledWith('/product-urls/1', {
                active: false,
            })
        })
    })

    it('adds a new tracked URL via quick add form', async () => {
        mocked.get.mockImplementation((url: string) => {
            if (url === '/products/101') {
                return Promise.resolve({ data: product })
            }
            if (url.startsWith('/price-history')) {
                return Promise.resolve({ data: historyEntries })
            }
            return Promise.resolve({ data: [] })
        })

        mocked.post.mockResolvedValueOnce({
            data: {
                product_id: 101,
                product_name: 'Test Product',
                product_slug: 'test-product',
                created_product: false,
                created_urls: [
                    {
                        product_url_id: 55,
                        store_id: 20,
                        url: 'https://example.com/secondary',
                        is_primary: true,
                        price: 119.99,
                        currency: 'USD',
                    },
                ],
                skipped: [],
            },
        })

        const { findByPlaceholderText, findByRole } = render(
            ProductDetailView,
            {
                global: {
                    stubs: {
                        RouterLink: {
                            props: ['to'],
                            template: '<a><slot /></a>',
                        },
                        PvCard: CardStub,
                        PvButton: ButtonStub,
                        PvInputText: InputTextStub,
                        PvCheckbox: CheckboxStub,
                        ProductHistoryChart: {
                            template: '<div />',
                        },
                        PvInputTextarea: {
                            template: '<textarea />',
                        },
                    },
                },
            },
        )

        const urlInput = await findByPlaceholderText(
            'https://example.com/product',
        )
        await fireEvent.update(urlInput, 'https://example.com/secondary')
        const makePrimaryCheckbox = await findByRole('checkbox', {
            name: /make primary/i,
        })
        await fireEvent.click(makePrimaryCheckbox)
        await fireEvent.click(await findByRole('button', { name: /add url/i }))

        await waitFor(() => {
            expect(mocked.post).toHaveBeenCalledWith(
                '/product-urls/bulk-import',
                {
                    items: [
                        {
                            url: 'https://example.com/secondary',
                            set_primary: true,
                        },
                    ],
                    product_id: 101,
                    enqueue_refresh: false,
                },
            )
        })

        await waitFor(() => {
            const calls = mocked.get.mock.calls.filter(
                ([url]) => url === '/products/101',
            )
            expect(calls.length).toBeGreaterThan(1)
        })
    })

    it('deletes a tracked URL', async () => {
        mocked.get.mockImplementation((url: string) => {
            if (url === '/products/101') {
                return Promise.resolve({ data: product })
            }
            if (url.startsWith('/price-history')) {
                return Promise.resolve({ data: historyEntries })
            }
            return Promise.resolve({ data: [] })
        })

        mocked.delete.mockResolvedValueOnce({})
        const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

        const { findByRole } = render(ProductDetailView, {
            global: {
                stubs: {
                    RouterLink: {
                        props: ['to'],
                        template: '<a><slot /></a>',
                    },
                    PvCard: CardStub,
                    PvButton: ButtonStub,
                    PvInputText: InputTextStub,
                    PvCheckbox: CheckboxStub,
                    PvMultiSelect: MultiSelectStub,
                    PvMenu: MenuStub,
                    ProductHistoryChart: {
                        template: '<div />',
                    },
                    PvInputTextarea: {
                        template: '<textarea />',
                    },
                },
            },
        })

        const deleteButton = await findByRole('button', { name: /delete/i })
        await fireEvent.click(deleteButton)

        await waitFor(() => {
            expect(mocked.delete).toHaveBeenCalledWith('/product-urls/1')
        })

        confirmSpy.mockRestore()
    })

    it('refreshes product data on demand', async () => {
        mocked.get.mockImplementation((url: string) => {
            if (url === '/products/101') {
                return Promise.resolve({ data: product })
            }
            if (url.startsWith('/price-history')) {
                return Promise.resolve({ data: historyEntries })
            }
            return Promise.resolve({ data: [] })
        })

        const pricingStore = usePricingStore()
        const refreshSpy = vi
            .spyOn(pricingStore, 'refreshProduct')
            .mockResolvedValue()

        const { findByRole } = render(ProductDetailView, {
            global: {
                stubs: {
                    RouterLink: {
                        props: ['to'],
                        template: '<a><slot /></a>',
                    },
                    PvCard: CardStub,
                    PvButton: ButtonStub,
                    PvInputText: InputTextStub,
                    PvCheckbox: CheckboxStub,
                    PvMultiSelect: MultiSelectStub,
                    PvMenu: MenuStub,
                    ProductHistoryChart: { template: '<div />' },
                    PvInputTextarea: { template: '<textarea />' },
                },
            },
        })

        await fireEvent.click(
            await findByRole('button', { name: /refresh prices/i }),
        )

        await waitFor(() => {
            expect(refreshSpy).toHaveBeenCalledWith(101)
        })

        refreshSpy.mockRestore()
    })

    it('promotes a secondary URL to primary', async () => {
        const productWithSecondary = structuredClone({
            ...product,
            urls: [
                { ...product.urls[0] },
                {
                    id: 2,
                    product_id: 101,
                    store_id: 99,
                    url: 'https://example.com/secondary',
                    is_primary: false,
                    active: true,
                    created_by_id: null,
                    store: {
                        id: 99,
                        name: 'Spare Store',
                        slug: 'spare-store',
                        currency: 'USD',
                    },
                    latest_price: 129.99,
                    latest_price_currency: 'USD',
                    latest_price_at: '2024-01-01T00:00:00Z',
                },
            ],
        })

        mocked.get.mockImplementation((url: string) => {
            if (url === '/products/101') {
                return Promise.resolve({ data: productWithSecondary })
            }
            if (url.startsWith('/price-history')) {
                return Promise.resolve({ data: historyEntries })
            }
            return Promise.resolve({ data: [] })
        })

        const productsStore = useProductsStore()
        const updatedEntry = {
            ...productWithSecondary.urls[1],
            is_primary: true,
        }
        const updateSpy = vi
            .spyOn(productsStore, 'updateUrl')
            .mockResolvedValue(updatedEntry)

        const { findAllByRole } = render(ProductDetailView, {
            global: {
                stubs: {
                    RouterLink: {
                        props: ['to'],
                        template: '<a><slot /></a>',
                    },
                    PvCard: CardStub,
                    PvButton: ButtonStub,
                    PvInputText: InputTextStub,
                    PvCheckbox: CheckboxStub,
                    PvMultiSelect: MultiSelectStub,
                    PvMenu: MenuStub,
                    ProductHistoryChart: { template: '<div />' },
                    PvInputTextarea: { template: '<textarea />' },
                },
            },
        })

        const rows = await findAllByRole('row')
        const secondaryRow = rows.find((row) =>
            row.textContent?.includes('Spare Store'),
        )
        expect(secondaryRow).toBeTruthy()
        const promoteButton = within(secondaryRow as HTMLElement).getByRole(
            'button',
            { name: /set primary url/i },
        ) as HTMLButtonElement
        await fireEvent.click(promoteButton)

        await waitFor(() => {
            expect(updateSpy).toHaveBeenCalledWith(101, 2, { is_primary: true })
            expect(promoteButton).toBeDisabled()
        })

        updateSpy.mockRestore()
    })

    it('navigates back to the products list when closing', async () => {
        const productFixture = structuredClone(product)

        mocked.get.mockImplementation((url: string) => {
            if (url === '/products/101') {
                return Promise.resolve({ data: productFixture })
            }
            if (url.startsWith('/price-history')) {
                return Promise.resolve({ data: historyEntries })
            }
            return Promise.resolve({ data: [] })
        })

        const { findByRole } = render(ProductDetailView, {
            global: {
                stubs: {
                    RouterLink: {
                        props: ['to'],
                        template: '<a><slot /></a>',
                    },
                    PvCard: CardStub,
                    PvButton: ButtonStub,
                    PvInputText: InputTextStub,
                    PvCheckbox: CheckboxStub,
                    PvMultiSelect: MultiSelectStub,
                    PvMenu: MenuStub,
                    ProductHistoryChart: { template: '<div />' },
                    PvInputTextarea: { template: '<textarea />' },
                },
            },
        })

        await fireEvent.click(
            await findByRole('button', { name: /back to products/i }),
        )

        expect(pushMock).toHaveBeenCalledWith({ name: 'products' })
    })
})
