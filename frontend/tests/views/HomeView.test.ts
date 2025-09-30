import { h, defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

vi.mock('../../src/lib/http', () => {
    const post = vi.fn()
    return {
        apiClient: { post },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { post },
    }
})

import HomeView from '../../src/views/HomeView.vue'
import { apiClient } from '../../src/lib/http'

const mockedPost = (apiClient as unknown as { post: ReturnType<typeof vi.fn> })
    .post

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
                        slots.content
                            ? slots.content()
                            : slots.default
                              ? slots.default()
                              : null,
                    ),
                    slots.footer ? h('footer', slots.footer()) : null,
                ])
        },
    })

const createPlainStub = (name: string) =>
    defineComponent({
        name,
        setup(_, { slots, attrs }) {
            return () => h('div', attrs, slots.default?.())
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

const RouterLinkStub = defineComponent({
    props: {
        to: { type: [String, Object], required: true },
    },
    setup(props, { slots }) {
        return () => h('a', { href: String(props.to) }, slots.default?.())
    },
})

describe('HomeView', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        window.localStorage.clear()
        mockedPost.mockReset()
        const hrefRef = { current: 'http://localhost/' }
        Object.defineProperty(window, 'location', {
            value: {
                get href() {
                    return hrefRef.current
                },
                set href(value: string) {
                    hrefRef.current = value
                },
                origin: 'http://localhost',
            },
            configurable: true,
        })
    })

    const createTestRouter = () =>
        createRouter({
            history: createMemoryHistory(),
            routes: [
                {
                    path: '/',
                    name: 'home',
                    component: { template: '<div />' },
                },
            ],
        })

    const renderView = async (path = '/') => {
        const router = createTestRouter()
        router.push(path)
        await router.isReady()
        return render(HomeView, {
            global: {
                plugins: [router],
                stubs: {
                    RouterLink: RouterLinkStub,
                    PvButton: createButtonStub(),
                    PvCard: createCardStub(),
                    PvSkeleton: createPlainStub('PvSkeletonStub'),
                    PvInlineMessage: createPlainStub('PvInlineMessageStub'),
                    PvChart: createPlainStub('PvChartStub'),
                    PvTag: createTagStub('PvTagStub'),
                    PvBadge: createTagStub('PvBadgeStub'),
                },
            },
        })
    }

    it('starts OIDC flow when sign-in button clicked', async () => {
        mockedPost.mockResolvedValue({
            data: {
                state: 'state-123',
                authorization_url: 'https://auth.example.com/authorize',
            },
        })

        const { getByRole } = await renderView('/?redirect=/settings')

        const button = getByRole('button', { name: /continue with sso/i })
        button.click()

        await waitFor(() => {
            expect(mockedPost).toHaveBeenCalledWith('/auth/oidc/start', {
                redirect_uri: 'http://localhost:5173/auth/callback',
            })
            expect(window.location.href).toBe(
                'https://auth.example.com/authorize',
            )
        })
        expect(
            window.localStorage.getItem('costcourter.postLoginRedirect'),
        ).toBe('/settings')
    })

    it('shows shortcuts when authenticated', async () => {
        window.localStorage.setItem(
            'costcourter.tokens',
            JSON.stringify({ accessToken: 'token', tokenType: 'Bearer' }),
        )

        const { getByText } = await renderView()
        expect(getByText(/settings hub/i)).toBeTruthy()
        expect(getByText(/product workspace/i)).toBeTruthy()
    })
})
