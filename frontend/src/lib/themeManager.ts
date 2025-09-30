import type { PrimeVueConfiguration } from 'primevue/config'

import {
    createPrimeVueThemeConfig,
    resolveBrandTheme,
    type BrandThemeDefinition,
    type BrandThemeId,
} from './theme'

export const BRAND_THEME_STORAGE_KEY = 'costcourter.theme.brand'
export const BRAND_THEME_EVENT = 'costcourter:brand-theme-changed'

const hasWindow = () => typeof window !== 'undefined'
const hasDocument = () => typeof document !== 'undefined'

const getStorage = () => {
    if (!hasWindow()) return null
    try {
        return window.localStorage
    } catch (error) {
        console.warn(
            'Unable to access localStorage for theme preferences.',
            error,
        )
        return null
    }
}

type PrimeVueInstance = {
    config: PrimeVueConfiguration
} | null

export const getStoredBrandThemeId = (): BrandThemeId => {
    const storage = getStorage()
    const stored = storage?.getItem(BRAND_THEME_STORAGE_KEY)
    return resolveBrandTheme(stored).id
}

export const setStoredBrandThemeId = (themeId: BrandThemeId) => {
    const storage = getStorage()
    storage?.setItem(BRAND_THEME_STORAGE_KEY, themeId)
}

export const setDocumentBrandTheme = (themeId: BrandThemeId) => {
    if (hasDocument()) {
        document.documentElement.dataset.brandTheme = themeId
    }
}

export const broadcastBrandThemeChange = (definition: BrandThemeDefinition) => {
    if (hasWindow()) {
        window.dispatchEvent(
            new CustomEvent(BRAND_THEME_EVENT, {
                detail: { id: definition.id },
            }),
        )
    }
}

export const applyBrandTheme = (
    primevue: PrimeVueInstance,
    targetThemeId: BrandThemeId,
): BrandThemeDefinition => {
    const definition = resolveBrandTheme(targetThemeId)

    if (primevue) {
        primevue.config.theme = createPrimeVueThemeConfig(definition.preset)
    }

    setDocumentBrandTheme(definition.id)
    setStoredBrandThemeId(definition.id)
    broadcastBrandThemeChange(definition)

    return definition
}

export const initializeBrandTheme = (primevue: PrimeVueInstance) => {
    const initialId = getStoredBrandThemeId()
    return applyBrandTheme(primevue, initialId)
}
