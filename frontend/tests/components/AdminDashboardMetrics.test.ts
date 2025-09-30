import { h, defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const get = vi.fn()
    return {
        apiClient: { get },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { get },
    }
})

import { apiClient } from '../../src/lib/http'
import AdminDashboardMetrics from '../../src/components/AdminDashboardMetrics.vue'
import { useAdminMetricsStore } from '../../src/stores/useAdminMetricsStore'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
}

const mockedGet = mocked.get

const createButtonStub = () =>
    defineComponent({
        name: 'PvButtonStub',
        props: {
            label: { type: String, default: '' },
        },
        emits: ['click'],
        setup(props, { emit, slots, attrs }) {
            return () =>
                h(
                    'button',
                    {
                        type: 'button',
                        ...attrs,
                        onClick: () => emit('click'),
                    },
                    slots.default ? slots.default() : props.label,
                )
        },
    })

const createCardStub = () =>
    defineComponent({
        name: 'PvCardStub',
        setup(_, { slots, attrs }) {
            return () =>
                h('section', attrs, [
                    slots.header ? h('header', slots.header()) : null,
                    h(
                        'div',
                        {},
                        slots.content ? slots.content() : slots.default?.(),
                    ),
                    slots.footer ? h('footer', slots.footer()) : null,
                ])
        },
    })

const createPlainStub = (tag: string, name: string) =>
    defineComponent({
        name,
        setup(_, { slots, attrs }) {
            return () => h(tag, attrs, slots.default?.())
        },
    })

const createTagStub = (name: string) =>
    defineComponent({
        name,
        props: {
            value: { type: [String, Number], default: '' },
        },
        setup(props, { slots, attrs }) {
            return () =>
                h(
                    'span',
                    attrs,
                    slots.default ? slots.default() : String(props.value),
                )
        },
    })

describe('AdminDashboardMetrics', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        mockedGet.mockReset()
    })

    const chartProps: Array<{ type: string | undefined; data: unknown }> = []

    const renderWithStubs = () => {
        chartProps.length = 0
        return render(AdminDashboardMetrics, {
            global: {
                stubs: {
                    PvButton: createButtonStub(),
                    PvCard: createCardStub(),
                    PvSkeleton: createPlainStub('div', 'PvSkeletonStub'),
                    PvInlineMessage: createPlainStub(
                        'div',
                        'PvInlineMessageStub',
                    ),
                    PvChart: defineComponent({
                        name: 'PvChartStub',
                        props: {
                            type: { type: String, default: 'line' },
                            data: { type: Object, default: () => ({}) },
                            options: { type: Object, default: () => ({}) },
                        },
                        setup(props) {
                            return () => {
                                chartProps.push({
                                    type: props.type,
                                    data: JSON.parse(
                                        JSON.stringify(props.data),
                                    ),
                                })
                                return h('div')
                            }
                        },
                    }),
                    PvTag: createTagStub('PvTagStub'),
                    PvBadge: createTagStub('PvBadgeStub'),
                },
            },
        })
    }

    it('shows an empty state when metrics are unavailable', async () => {
        const store = useAdminMetricsStore()
        store.metrics = null
        store.loading = false
        store.error = null
        store.fetchMetrics = vi.fn().mockResolvedValue(undefined)

        const { findByText } = renderWithStubs()

        expect(store.fetchMetrics).toHaveBeenCalled()
        expect(
            await findByText(
                'Metrics will populate once the first backend refresh completes.',
            ),
        ).toBeTruthy()
    })

    it('renders totals and spotlight after fetch', async () => {
        const styleMap: Record<string, string> = {
            '--app-chart-accent-1': 'rgba(1, 2, 3, 0.5)',
            '--app-chart-accent-2': 'rgb(4, 5, 6)',
            '--app-chart-accent-3': '#789',
            '--app-chart-accent-4': '#123456',
            '--app-chart-accent-5': 'rgba(7, 8, 9, 1)',
            '--app-chart-accent-6': '#abc',
            '--app-chart-accent-7': '#def',
            '--app-chart-accent-8': '#fedcba',
            '--app-chart-grid-strong': 'rgba(13, 14, 15, 0.2)',
            '--app-chart-grid-muted': 'rgb(16, 17, 18)',
            '--app-chart-grid-soft': '#aaa',
        }
        const styleSpy = vi
            .spyOn(window, 'getComputedStyle')
            .mockImplementation(
                () =>
                    ({
                        getPropertyValue: (token: string) =>
                            styleMap[token] ?? '',
                    }) as CSSStyleDeclaration,
            )

        mockedGet.mockResolvedValue({
            data: {
                totals: { products: 5, favourites: 2, active_urls: 12 },
                spotlight: [
                    {
                        id: 1,
                        name: 'Noise Cancelling Headphones',
                        slug: 'noise-cancelling-headphones',
                        current_price: 199.99,
                        trend: 'down',
                        store_name: 'Example Store',
                        image_url: null,
                        last_refreshed_at: '2025-09-27T10:00:00Z',
                        history: [
                            { date: '2024-01-01', price: 200 },
                            { date: '2024-01-02', price: 190 },
                        ],
                    },
                    {
                        id: 2,
                        name: 'Gaming Console',
                        slug: 'gaming-console',
                        current_price: 299.99,
                        trend: 'steady',
                        store_name: 'Market',
                        image_url: null,
                        last_refreshed_at: '2025-09-26T12:00:00Z',
                        history: [
                            { date: '2024-01-01', price: 320 },
                            { date: '2024-01-03', price: 310 },
                        ],
                    },
                ],
                tag_groups: [
                    {
                        label: 'Audio',
                        products: [
                            { id: 1, name: 'Noise Cancelling Headphones' },
                        ],
                    },
                    {
                        label: 'Gaming',
                        products: [
                            { id: 2, name: 'Gaming Console' },
                            { id: 3, name: 'Gaming Chair' },
                        ],
                    },
                ],
                last_updated_at: '2025-09-27T10:00:00Z',
            },
        })

        const { findByText, findAllByText } = renderWithStubs()

        await waitFor(() => expect(mockedGet).toHaveBeenCalled())
        expect(await findByText('Products')).toBeTruthy()
        expect(await findByText('5')).toBeTruthy()
        const spotlightLabels = await findAllByText(
            'Noise Cancelling Headphones',
        )
        expect(spotlightLabels.length).toBeGreaterThan(0)
        expect(chartProps.some((entry) => entry.type === 'line')).toBe(true)
        expect(chartProps.some((entry) => entry.type === 'bar')).toBe(true)
        expect(styleSpy).toHaveBeenCalled()

        const initialCallCount = styleSpy.mock.calls.length
        window.dispatchEvent(new Event('costcourter:brand-theme-changed'))
        window.dispatchEvent(new Event('costcourter:color-mode-changed'))
        await waitFor(() => {
            expect(styleSpy.mock.calls.length).toBeGreaterThan(initialCallCount)
        })

        styleSpy.mockRestore()
    })

    it('shows errors when the request fails', async () => {
        mockedGet.mockRejectedValue(new Error('network error'))

        const { findByText } = renderWithStubs()

        expect(await findByText('network error')).toBeTruthy()
    })

    it('renders placeholder messaging when spotlight and tag data are empty', async () => {
        mockedGet.mockResolvedValue({
            data: {
                totals: { products: 0, favourites: 0, active_urls: 0 },
                spotlight: [],
                tag_groups: [],
                last_updated_at: '2025-09-27T10:00:00Z',
            },
        })

        const { findByText } = renderWithStubs()

        await waitFor(() => expect(mockedGet).toHaveBeenCalled())
        expect(await findByText(/No spotlight products yet/i)).toBeTruthy()
        expect(
            await findByText(/Tag grouping insights will appear/i),
        ).toBeTruthy()
        expect(chartProps.some((entry) => entry.type === 'line')).toBe(false)
    })
})
