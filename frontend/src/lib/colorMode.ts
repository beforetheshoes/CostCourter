export const COLOR_MODE_STORAGE_KEY = 'costcourter.theme'
export const COLOR_MODE_EVENT = 'costcourter:color-mode-changed'

type ColorMode = 'system' | 'light' | 'dark'
type EffectiveColorMode = 'light' | 'dark'

type ColorModeDetail = {
    mode: ColorMode
    effective: EffectiveColorMode
}

const hasWindow = () => typeof window !== 'undefined'
const hasDocument = () => typeof document !== 'undefined'

const getStorage = () => {
    if (!hasWindow()) return null
    try {
        return window.localStorage
    } catch (error) {
        console.warn(
            'Unable to access localStorage for color mode preferences.',
            error,
        )
        return null
    }
}

let currentMode: ColorMode = 'system'
let mediaQuery: MediaQueryList | null = null
let mediaQueryHandler: ((event: MediaQueryListEvent) => void) | null = null

const ensureMediaQuery = () => {
    if (!hasWindow()) return null
    if (!mediaQuery) {
        mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    }
    return mediaQuery
}

const attachMediaQueryListener = () => {
    const media = ensureMediaQuery()
    if (!media) return
    if (!mediaQueryHandler) {
        mediaQueryHandler = () => {
            if (currentMode === 'system') {
                applyColorMode('system', { persist: false, emit: true })
            }
        }
    }
    if ('addEventListener' in media) {
        media.addEventListener('change', mediaQueryHandler)
    } else if ('addListener' in media) {
        // @ts-expect-error Legacy browsers
        media.addListener(mediaQueryHandler)
    }
}

const detachMediaQueryListener = () => {
    const media = ensureMediaQuery()
    if (!media || !mediaQueryHandler) return
    if ('removeEventListener' in media) {
        media.removeEventListener('change', mediaQueryHandler)
    } else if ('removeListener' in media) {
        // @ts-expect-error Legacy browsers
        media.removeListener(mediaQueryHandler)
    }
}

const resolveEffectiveMode = (mode: ColorMode): EffectiveColorMode => {
    if (mode === 'system') {
        const media = ensureMediaQuery()
        return media?.matches ? 'dark' : 'light'
    }
    return mode
}

const applyDataset = (mode: ColorMode, effective: EffectiveColorMode) => {
    if (!hasDocument()) return
    const root = document.documentElement
    root.dataset.theme = effective
    root.dataset.colorMode = mode
    root.style.colorScheme = effective
}

const broadcastColorMode = (detail: ColorModeDetail) => {
    if (!hasWindow()) return
    window.dispatchEvent(
        new CustomEvent<ColorModeDetail>(COLOR_MODE_EVENT, { detail }),
    )
}

export const getStoredColorMode = (): ColorMode => {
    const storage = getStorage()
    const stored = storage?.getItem(COLOR_MODE_STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') {
        return stored
    }
    return 'system'
}

type ApplyOptions = {
    persist?: boolean
    emit?: boolean
}

export const applyColorMode = (
    mode: ColorMode,
    options: ApplyOptions = {},
): EffectiveColorMode => {
    const { persist = true, emit = true } = options
    currentMode = mode
    const effective = resolveEffectiveMode(mode)
    applyDataset(mode, effective)

    if (persist) {
        const storage = getStorage()
        storage?.setItem(COLOR_MODE_STORAGE_KEY, mode)
    }

    if (mode === 'system') {
        attachMediaQueryListener()
    } else {
        detachMediaQueryListener()
    }

    if (emit) {
        broadcastColorMode({ mode, effective })
    }

    return effective
}

export const initializeColorMode = () => {
    const stored = getStoredColorMode()
    applyColorMode(stored, { persist: false, emit: false })
    currentMode = stored
    if (stored === 'system') {
        attachMediaQueryListener()
    }
}

export type { ColorMode, EffectiveColorMode }
