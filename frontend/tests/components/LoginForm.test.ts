import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, fireEvent, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import { reactive } from 'vue'

import LoginForm from '../../src/components/LoginForm.vue'
import { useAuthStore } from '../../src/stores/useAuthStore'

const routeMock = reactive({
    query: {} as Record<string, unknown>,
    fullPath: '/',
})

const routerReplace = vi.fn()

vi.mock('vue-router', () => ({
    useRoute: () => routeMock,
    useRouter: () => ({ replace: routerReplace }),
}))

const createButtonStub = () => ({
    inheritAttrs: false,
    props: { label: { type: String, default: '' } },
    emits: ['click'],
    template:
        '<button type="button" v-bind="$attrs" @click="$emit(\'click\')"><slot>{{ label }}</slot></button>',
})

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

const CardStub = {
    template:
        '<section><slot name="header" /><slot name="content" /><slot /></section>',
}

describe('LoginForm', () => {
    const originalLocation = window.location
    let pinia: ReturnType<typeof createPinia>

    beforeEach(() => {
        pinia = createPinia()
        setActivePinia(pinia)
        window.localStorage.clear()
        vi.stubEnv('VITE_OIDC_ENABLED', 'true')
        routeMock.query = {}
        routeMock.fullPath = '/'
        routerReplace.mockReset()
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: {
                ...originalLocation,
                href: 'http://localhost:5173/login',
                origin: 'http://localhost:5173',
                assign: vi.fn(),
            },
        })
    })

    afterEach(() => {
        vi.unstubAllEnvs()
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: originalLocation,
        })
        vi.restoreAllMocks()
    })

    const renderForm = (routeQuery: Record<string, unknown> = {}) => {
        routeMock.query = routeQuery
        routeMock.fullPath = routeQuery.redirect
            ? String(routeQuery.redirect)
            : '/'

        return render(LoginForm, {
            global: {
                plugins: [pinia],
                stubs: {
                    PvButton: createButtonStub(),
                    PvInputText: InputTextStub,
                    PvCheckbox: CheckboxStub,
                    PvCard: CardStub,
                },
            },
        })
    }

    it('starts OIDC login and stores redirect preference', async () => {
        const store = useAuthStore()
        const beginSpy = vi.spyOn(store, 'beginOidcLogin').mockResolvedValue({
            authorization_url: 'https://auth.example.com/authorize',
        })

        const { getByRole } = renderForm({ redirect: '/settings' })

        await fireEvent.click(
            getByRole('button', { name: /continue with sso/i }),
        )

        await waitFor(() => expect(beginSpy).toHaveBeenCalled())
        expect(
            window.localStorage.getItem('costcourter.postLoginRedirect'),
        ).toBe('/settings')
        expect(window.location.href).toBe('https://auth.example.com/authorize')
    })

    it('shows message when registering passkey without email', async () => {
        const store = useAuthStore()
        vi.spyOn(store, 'registerPasskey').mockResolvedValue()

        const { getByRole, findByText } = renderForm()

        await fireEvent.click(
            getByRole('button', { name: /register a passkey/i }),
        )
        await fireEvent.click(
            getByRole('button', { name: /complete passkey registration/i }),
        )

        await findByText(/enter an email address to register a passkey/i)
        expect(store.registerPasskey).not.toHaveBeenCalled()
    })

    it('registers a passkey and navigates to stored redirect', async () => {
        const store = useAuthStore()
        const registerSpy = vi
            .spyOn(store, 'registerPasskey')
            .mockResolvedValue()
        const { getByRole, getAllByLabelText } = renderForm({
            redirect: '/products',
        })

        await fireEvent.click(
            getByRole('button', { name: /register a passkey/i }),
        )
        const [, registrationEmailField] = getAllByLabelText(/email address/i)
        await fireEvent.update(registrationEmailField, 'user@example.com')
        const nameField = getAllByLabelText(/full name/i)[0]
        await fireEvent.update(nameField, 'User Example')
        await fireEvent.click(
            getByRole('button', { name: /complete passkey registration/i }),
        )

        await waitFor(() => expect(registerSpy).toHaveBeenCalled())
        expect(registerSpy).toHaveBeenCalledWith({
            email: 'user@example.com',
            fullName: 'User Example',
        })
        expect(routerReplace).toHaveBeenCalledWith('/products')
        expect(
            window.localStorage.getItem('costcourter.postLoginRedirect'),
        ).toBeNull()
    })

    it('authenticates with a passkey when email is provided', async () => {
        const store = useAuthStore()
        const authSpy = vi
            .spyOn(store, 'authenticatePasskey')
            .mockResolvedValue()
        const { getByRole, getAllByLabelText } = renderForm({
            redirect: '/reports',
        })

        const emailField = getAllByLabelText(/email address/i)[0]
        await fireEvent.update(emailField, 'admin@example.com')

        await fireEvent.click(
            getByRole('button', { name: /sign in with a passkey/i }),
        )

        await waitFor(() =>
            expect(authSpy).toHaveBeenCalledWith('admin@example.com'),
        )
        expect(routerReplace).toHaveBeenCalledWith('/reports')
        expect(
            window.localStorage.getItem('costcourter.postLoginRedirect'),
        ).toBeNull()
    })

    it('hides SSO controls when the feature flag is disabled', () => {
        vi.stubEnv('VITE_OIDC_ENABLED', 'false')
        vi.stubEnv('VITE_OIDC_CLIENT_ID', '')
        const { queryByRole } = renderForm()
        expect(queryByRole('button', { name: /continue with sso/i })).toBeNull()
    })

    it('resets passkey registration fields when panel is closed', async () => {
        const { getByRole, getAllByLabelText } = renderForm()

        await fireEvent.click(
            getByRole('button', { name: /register a passkey/i }),
        )
        const registrationEmailField = getAllByLabelText(/email address/i)[1]
        await fireEvent.update(registrationEmailField, 'temp@example.com')

        await fireEvent.click(getByRole('button', { name: /cancel/i }))

        await fireEvent.click(
            getByRole('button', { name: /register a passkey/i }),
        )

        expect(getAllByLabelText(/full name/i)[0]).toHaveValue('')
    })
})
