import { beforeEach, describe, expect, it, vi } from 'vitest'

const appUse = vi.fn().mockReturnThis()
const appComponent = vi.fn().mockReturnThis()
const appMount = vi.fn()
const createAppMock = vi.fn(() => ({
    use: appUse,
    component: appComponent,
    mount: appMount,
}))

vi.mock('vue', () => ({
    createApp: createAppMock,
}))

const createPiniaMock = vi.fn(() => ({ id: 'pinia' }))
vi.mock('pinia', () => ({
    createPinia: createPiniaMock,
}))

const primeUseMock = vi.fn()
vi.mock('primevue/config', () => ({
    default: primeUseMock,
}))

vi.mock('primevue/button', () => ({ default: 'Button' }))
vi.mock('primevue/card', () => ({ default: 'Card' }))
vi.mock('primevue/dialog', () => ({ default: 'Dialog' }))
vi.mock('primevue/inputtext', () => ({ default: 'InputText' }))
vi.mock('primevue/password', () => ({ default: 'Password' }))
vi.mock('primevue/avatar', () => ({ default: 'Avatar' }))
vi.mock('primevue/dropdown', () => ({ default: 'Dropdown' }))
vi.mock('primevue/textarea', () => ({ default: 'Textarea' }))
vi.mock('primevue/checkbox', () => ({ default: 'Checkbox' }))
vi.mock('primevue/chart', () => ({ default: 'Chart' }))
vi.mock('primevue/inlinemessage', () => ({ default: 'InlineMessage' }))
vi.mock('primevue/tag', () => ({ default: 'Tag' }))
vi.mock('primevue/badge', () => ({ default: 'Badge' }))
vi.mock('primevue/divider', () => ({ default: 'Divider' }))
vi.mock('primevue/skeleton', () => ({ default: 'Skeleton' }))
vi.mock('primevue/selectbutton', () => ({ default: 'SelectButton' }))

const initializeColorMode = vi.fn()
vi.mock('../src/lib/colorMode', () => ({
    initializeColorMode,
}))

const registerAuthInterceptor = vi.fn()
const fetchCurrentUser = vi.fn().mockResolvedValue(undefined)
const useAuthStoreMock = vi.fn(() => ({
    isAuthenticated: true,
    currentUser: null,
    fetchCurrentUser,
}))

vi.mock('../src/stores/useAuthStore', () => ({
    registerAuthInterceptor,
    useAuthStore: useAuthStoreMock,
}))

const setDocumentBrandTheme = vi.fn()
const getStoredBrandThemeId = vi.fn(() => 'midnight')
const resolveBrandTheme = vi.fn(() => ({ id: 'midnight', preset: 'dark' }))
const createPrimeVueThemeConfig = vi.fn(() => ({ theme: 'config' }))

vi.mock('../src/lib/theme', () => ({
    setDocumentBrandTheme,
    getStoredBrandThemeId,
    resolveBrandTheme,
    createPrimeVueThemeConfig,
}))

vi.mock('../src/lib/themeManager', () => ({
    getStoredBrandThemeId,
    setDocumentBrandTheme,
}))

const routerMock = { install: vi.fn() }
vi.mock('../src/router', () => ({
    default: routerMock,
}))

vi.mock('../src/App.vue', () => ({ default: { name: 'App' } }))

beforeEach(() => {
    vi.resetModules()
    createAppMock.mockClear()
    appUse.mockClear()
    appComponent.mockClear()
    appMount.mockClear()
    createPiniaMock.mockClear()
    primeUseMock.mockClear()
    initializeColorMode.mockClear()
    registerAuthInterceptor.mockClear()
    fetchCurrentUser.mockClear()
    useAuthStoreMock.mockClear()
    setDocumentBrandTheme.mockClear()
    getStoredBrandThemeId.mockClear()
    resolveBrandTheme.mockClear()
    createPrimeVueThemeConfig.mockClear()
})

describe('main bootstrap', () => {
    it('wires the application bootstrap sequence', async () => {
        await import('../src/main')

        expect(initializeColorMode).toHaveBeenCalled()
        expect(createAppMock).toHaveBeenCalledWith(
            expect.objectContaining({ name: 'App' }),
        )
        expect(createPiniaMock).toHaveBeenCalled()
        expect(appUse).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'pinia' }),
        )
        expect(appUse).toHaveBeenCalledWith(routerMock)
        expect(appUse).toHaveBeenCalledWith(primeUseMock, {
            theme: { theme: 'config' },
        })
        expect(registerAuthInterceptor).toHaveBeenCalled()
        expect(useAuthStoreMock).toHaveBeenCalledWith({ id: 'pinia' })
        expect(fetchCurrentUser).toHaveBeenCalled()
        expect(setDocumentBrandTheme).toHaveBeenCalledWith('midnight')
        expect(createPrimeVueThemeConfig).toHaveBeenCalledWith('dark')
        expect(resolveBrandTheme).toHaveBeenCalledWith('midnight')
        expect(appComponent).toHaveBeenCalledWith('PvButton', 'Button')
        expect(appMount).toHaveBeenCalledWith('#app')
    })

    it('skips fetching current user when already populated', async () => {
        useAuthStoreMock.mockReturnValueOnce({
            isAuthenticated: true,
            currentUser: { id: 1 },
            fetchCurrentUser,
        })

        await import('../src/main')

        expect(fetchCurrentUser).not.toHaveBeenCalled()
    })
})
