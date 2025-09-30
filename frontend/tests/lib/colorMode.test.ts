import { beforeEach, describe, expect, it, vi } from 'vitest'

const createMockMatchMedia = (matches: boolean, withModernListeners = true) => {
    const listeners: Array<(event: MediaQueryListEvent) => void> = []
    const modernAdd = vi.fn(
        (event: string, handler: (event: MediaQueryListEvent) => void) => {
            if (event === 'change') listeners.push(handler)
        },
    )
    const modernRemove = vi.fn(
        (event: string, handler: (event: MediaQueryListEvent) => void) => {
            const index = listeners.indexOf(handler)
            if (index !== -1) listeners.splice(index, 1)
        },
    )
    const legacyAdd = vi.fn((handler: (event: MediaQueryListEvent) => void) => {
        listeners.push(handler)
    })
    const legacyRemove = vi.fn(
        (handler: (event: MediaQueryListEvent) => void) => {
            const index = listeners.indexOf(handler)
            if (index !== -1) listeners.splice(index, 1)
        },
    )
    const base: Partial<MediaQueryList> & {
        matches: boolean
        media: string
        listeners: Array<(event: MediaQueryListEvent) => void>
        dispatch(event: MediaQueryListEvent): void
    } = {
        matches,
        media: '(prefers-color-scheme: dark)',
        listeners,
        dispatch(event: MediaQueryListEvent) {
            listeners.forEach((handler) => handler(event))
        },
    }
    if (withModernListeners) {
        base.addEventListener =
            modernAdd as unknown as typeof base.addEventListener
        base.removeEventListener =
            modernRemove as unknown as typeof base.removeEventListener
    } else {
        base.addListener = legacyAdd as unknown as typeof base.addListener
        base.removeListener =
            legacyRemove as unknown as typeof base.removeListener
    }
    return base as MediaQueryList & {
        listeners: typeof listeners
        dispatch(event: MediaQueryListEvent): void
    }
}

const resetDomState = () => {
    document.documentElement.dataset.theme = ''
    document.documentElement.dataset.colorMode = ''
    document.documentElement.style.colorScheme = ''
    window.localStorage.clear()
}

beforeEach(() => {
    vi.resetModules()
    resetDomState()
})

describe('colorMode utilities', () => {
    it('reads stored color mode with fallback', async () => {
        window.localStorage.setItem('costcourter.theme', 'light')
        const { getStoredColorMode } = await import('../../src/lib/colorMode')
        expect(getStoredColorMode()).toBe('light')

        window.localStorage.setItem('costcourter.theme', 'unknown')
        expect(getStoredColorMode()).toBe('system')
    })

    it('falls back gracefully when storage access is blocked', async () => {
        const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
        const getter = vi
            .spyOn(window, 'localStorage', 'get')
            .mockImplementation(() => {
                throw new Error('denied')
            })

        const { getStoredColorMode, applyColorMode } = await import(
            '../../src/lib/colorMode'
        )

        expect(getStoredColorMode()).toBe('system')
        expect(() => applyColorMode('light')).not.toThrow()
        expect(warnSpy).toHaveBeenCalled()

        getter.mockRestore()
        warnSpy.mockRestore()
    })

    it('applies explicit color mode and persists selection', async () => {
        const mockMedia = createMockMatchMedia(false)
        const matchMediaSpy = vi
            .spyOn(window, 'matchMedia')
            .mockImplementation(() => mockMedia as unknown as MediaQueryList)
        const dispatchSpy = vi.spyOn(window, 'dispatchEvent')

        const { applyColorMode, COLOR_MODE_STORAGE_KEY } = await import(
            '../../src/lib/colorMode'
        )
        const effective = applyColorMode('dark')

        expect(effective).toBe('dark')
        expect(document.documentElement.dataset.theme).toBe('dark')
        expect(document.documentElement.dataset.colorMode).toBe('dark')
        expect(window.localStorage.getItem(COLOR_MODE_STORAGE_KEY)).toBe('dark')
        expect(dispatchSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                type: 'costcourter:color-mode-changed',
                detail: { mode: 'dark', effective: 'dark' },
            }),
        )
        expect(matchMediaSpy).toHaveBeenCalledTimes(1)
    })

    it('handles system mode with legacy media listener APIs', async () => {
        const mockMedia = createMockMatchMedia(true, false)
        vi.spyOn(window, 'matchMedia').mockImplementation(
            () => mockMedia as unknown as MediaQueryList,
        )
        const dispatchSpy = vi.spyOn(window, 'dispatchEvent')

        const { applyColorMode } = await import('../../src/lib/colorMode')
        const effective = applyColorMode('system')

        expect(effective).toBe('dark')
        expect(mockMedia.addListener).toHaveBeenCalled()
        expect(dispatchSpy).toHaveBeenCalledTimes(1)
        const initialDispatchCount = dispatchSpy.mock.calls.length
        mockMedia.dispatch(
            new Event('change') as unknown as MediaQueryListEvent,
        )
        expect(dispatchSpy.mock.calls.length).toBeGreaterThan(
            initialDispatchCount,
        )
        dispatchSpy.mockClear()

        // switching away from system should remove legacy listeners
        applyColorMode('light')
        expect(mockMedia.removeListener).toHaveBeenCalled()
        expect(dispatchSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                detail: { mode: 'light', effective: 'light' },
            }),
        )
    })

    it('removes modern media listeners when leaving system mode', async () => {
        const mockMedia = createMockMatchMedia(true)
        vi.spyOn(window, 'matchMedia').mockImplementation(
            () => mockMedia as unknown as MediaQueryList,
        )
        const dispatchSpy = vi.spyOn(window, 'dispatchEvent')

        const { applyColorMode } = await import('../../src/lib/colorMode')
        applyColorMode('system')
        expect(mockMedia.addEventListener).toHaveBeenCalled()

        dispatchSpy.mockClear()
        applyColorMode('light')
        expect(mockMedia.removeEventListener).toHaveBeenCalled()
        expect(dispatchSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                detail: { mode: 'light', effective: 'light' },
            }),
        )

        dispatchSpy.mockRestore()
    })

    it('initialises color mode without emitting events', async () => {
        const mockMedia = createMockMatchMedia(false)
        vi.spyOn(window, 'matchMedia').mockImplementation(
            () => mockMedia as unknown as MediaQueryList,
        )
        window.localStorage.setItem('costcourter.theme', 'system')
        const dispatchSpy = vi.spyOn(window, 'dispatchEvent')

        const { initializeColorMode } = await import('../../src/lib/colorMode')

        initializeColorMode()

        expect(document.documentElement.dataset.colorMode).toBe('system')
        expect(document.documentElement.dataset.theme).toBe('light')
        expect(dispatchSpy).not.toHaveBeenCalled()
        expect(
            mockMedia.addEventListener ?? mockMedia.addListener,
        ).toHaveBeenCalled()
    })
})
