import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { render, fireEvent, screen, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { defineComponent, h } from 'vue'

import App from '../src/App.vue'
import { useAuthStore } from '../src/stores/useAuthStore'

const routes = [
    { path: '/', name: 'login', component: { template: '<div>Login</div>' } },
    {
        path: '/dashboard',
        name: 'dashboard',
        component: { template: '<div>Dashboard</div>' },
    },
    {
        path: '/products',
        name: 'products',
        component: { template: '<div>Products</div>' },
    },
    { path: '/search', name: 'search', component: { template: '<div />' } },
    { path: '/stores', name: 'stores', component: { template: '<div />' } },
    { path: '/settings', name: 'settings', component: { template: '<div />' } },
]

const createTestRouter = () =>
    createRouter({ history: createMemoryHistory(), routes })

const createPrimeButtonStub = () =>
    defineComponent({
        inheritAttrs: false,
        props: {
            label: { type: String, default: '' },
            icon: { type: String, default: '' },
        },
        emits: ['click'],
        setup(props, { emit, slots, attrs }) {
            return () =>
                h(
                    'button',
                    {
                        ...attrs,
                        'data-icon': props.icon,
                        onClick: (event: Event) => emit('click', event),
                    },
                    slots.default?.() ?? props.label ?? '',
                )
        },
    })

const AvatarStub = defineComponent({
    props: { label: { type: String, default: '' } },
    setup(props) {
        return () => h('div', { 'data-avatar': props.label }, props.label)
    },
})

const TagStub = defineComponent({
    props: { value: { type: String, default: '' } },
    setup(props, { attrs }) {
        return () => h('span', attrs, props.value)
    },
})

const renderWithProviders = async (
    router: Router,
    configureStore: (store: ReturnType<typeof useAuthStore>) => void,
) => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const authStore = useAuthStore()
    configureStore(authStore)

    await router.push(router.currentRoute.value.fullPath)
    await router.isReady()

    return render(App, {
        global: {
            plugins: [pinia, router],
            stubs: {
                PvButton: createPrimeButtonStub(),
                PvAvatar: AvatarStub,
                PvTag: TagStub,
            },
        },
    })
}

beforeEach(() => {
    vi.unstubAllEnvs()
})

describe('App shell behaviour', () => {
    it('renders admin navigation and handles logout flow', async () => {
        const router = createTestRouter()
        await router.push('/dashboard')
        await router.isReady()

        const logoutSpy = vi.fn()

        await renderWithProviders(router, (store) => {
            store.tokens = { accessToken: 'token', tokenType: 'Bearer' }
            store.currentUser = {
                id: 1,
                email: 'admin@example.com',
                full_name: 'Ada Lovelace',
                is_superuser: true,
                roles: ['admin'],
            }
            store.roles = ['admin']
            store.logout = logoutSpy as typeof store.logout
        })

        expect(screen.getByText('Overview')).toBeTruthy()
        expect(screen.getByText('Products')).toBeTruthy()
        expect(screen.getByText('Settings')).toBeTruthy()
        expect(screen.getByText('Ada Lovelace')).toBeTruthy()
        expect(screen.getByText('admin@example.com')).toBeTruthy()

        const pushSpy = vi.spyOn(router, 'push')

        const signOutButtons = screen.getAllByRole('button', {
            name: /sign out/i,
        })
        const desktopSignOut =
            signOutButtons.find((button) =>
                button.textContent?.includes('Sign out'),
            ) ?? signOutButtons[0]

        await fireEvent.click(desktopSignOut)

        expect(logoutSpy).toHaveBeenCalledWith(false)
        expect(pushSpy).toHaveBeenCalledWith({ name: 'login' })

        pushSpy.mockRestore()
    })

    it('shows login CTA, toggles mobile menu, and closes on navigation', async () => {
        const router = createTestRouter()
        await router.push('/search?utm=test')
        await router.isReady()

        const view = await renderWithProviders(router, (store) => {
            store.tokens = null
            store.currentUser = null
            store.roles = []
        })

        const pushSpy = vi.spyOn(router, 'push')

        await fireEvent.click(
            screen.getByRole('button', { name: /toggle navigation menu/i }),
        )
        expect(view.container.querySelector('.nav-link--mobile')).not.toBeNull()

        await router.push('/products')
        await router.isReady()
        await nextTick()
        const toggleButton = screen.getByRole('button', {
            name: /toggle navigation menu/i,
        })
        await waitFor(() =>
            expect(toggleButton).toHaveAttribute('aria-expanded', 'false'),
        )
        expect(view.container.querySelector('.nav-link--mobile')).toBeNull()

        await fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
        await waitFor(() =>
            expect(pushSpy).toHaveBeenCalledWith({
                name: 'login',
                query: { redirect: '/products' },
            }),
        )

        pushSpy.mockRestore()
    })
})
