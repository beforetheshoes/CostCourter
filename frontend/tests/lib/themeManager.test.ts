import type { PrimeVueConfiguration } from 'primevue/config'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const resetDomState = () => {
    document.documentElement.dataset.brandTheme = ''
    window.localStorage.clear()
}

beforeEach(() => {
    vi.resetModules()
    resetDomState()
})

describe('theme manager utilities', () => {
    it('applies brand themes and broadcasts changes', async () => {
        const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
        const { applyBrandTheme, BRAND_THEME_STORAGE_KEY } = await import(
            '../../src/lib/themeManager'
        )

        const primevue = {
            config: {} as PrimeVueConfiguration,
        }

        const definition = applyBrandTheme(primevue, 'lagoon')

        expect(definition.id).toBe('lagoon')
        expect(primevue.config.theme).toBeTruthy()
        expect(document.documentElement.dataset.brandTheme).toBe('lagoon')
        expect(window.localStorage.getItem(BRAND_THEME_STORAGE_KEY)).toBe(
            'lagoon',
        )
        expect(dispatchSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                type: 'costcourter:brand-theme-changed',
                detail: { id: 'lagoon' },
            }),
        )

        dispatchSpy.mockRestore()
    })

    it('falls back when storage access is blocked', async () => {
        const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
        const getter = vi
            .spyOn(window, 'localStorage', 'get')
            .mockImplementation(() => {
                throw new Error('denied')
            })

        const { getStoredBrandThemeId, setStoredBrandThemeId } = await import(
            '../../src/lib/themeManager'
        )

        expect(getStoredBrandThemeId()).toBe('aurora')
        expect(() => setStoredBrandThemeId('lagoon')).not.toThrow()
        expect(warnSpy).toHaveBeenCalled()

        getter.mockRestore()
        warnSpy.mockRestore()
    })

    it('initialises the stored brand theme on load', async () => {
        const dispatchSpy = vi.spyOn(window, 'dispatchEvent')

        const { initializeBrandTheme, BRAND_THEME_STORAGE_KEY } = await import(
            '../../src/lib/themeManager'
        )

        window.localStorage.setItem(BRAND_THEME_STORAGE_KEY, 'ember')

        const primevue = {
            config: {} as PrimeVueConfiguration,
        }

        const definition = initializeBrandTheme(primevue)

        expect(definition.id).toBe('ember')
        expect(primevue.config.theme).toBeTruthy()
        expect(document.documentElement.dataset.brandTheme).toBe('ember')
        expect(dispatchSpy).toHaveBeenCalled()

        dispatchSpy.mockRestore()
    })
})
