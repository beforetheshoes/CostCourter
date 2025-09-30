export type ChartTokens = {
    accent1: string
    accent2: string
    accent3: string
    accent4: string
    accent5: string
    accent6: string
    accent7: string
    accent8: string
    gridStrong: string
    gridMuted: string
    gridSoft: string
}

const FALLBACKS: Record<keyof ChartTokens, string> = {
    accent1: '#6366f1',
    accent2: '#3b82f6',
    accent3: '#10b981',
    accent4: '#22d3ee',
    accent5: '#f97316',
    accent6: '#a855f7',
    accent7: '#f43f5e',
    accent8: '#0ea5e9',
    gridStrong: 'rgba(99, 102, 241, 0.08)',
    gridMuted: 'rgba(148, 163, 184, 0.12)',
    gridSoft: 'rgba(148, 163, 184, 0.1)',
}

/**
 * Reads a CSS custom property value, falling back to the provided default when
 * running in non-DOM environments (e.g., tests) or when the variable is unset.
 */
export const readCssVariable = (
    token: string,
    fallback: string,
    styleReader: typeof window.getComputedStyle = window.getComputedStyle,
): string => {
    if (typeof window === 'undefined' || typeof document === 'undefined') {
        return fallback
    }
    const style = styleReader(document.documentElement)
    const value = style?.getPropertyValue?.(token)
    return value?.trim() || fallback
}

const expandHex = (value: string) =>
    value
        .split('')
        .map((segment) => segment + segment)
        .join('')

/**
 * Converts any CSS color representation into RGBA with the supplied alpha
 * component. Supports `rgba`, `rgb`, shorthand and long-form hex values.
 */
export const toRgba = (color: string, alpha: number): string => {
    const value = color.trim()
    if (!value) return value

    if (value.startsWith('rgba(')) {
        const [, inner] = value.match(/^rgba\((.*)\)$/) ?? []
        if (!inner) return value
        const [r, g, b] = inner
            .split(',')
            .map((segment) => segment.trim())
            .slice(0, 3)
        return `rgba(${r}, ${g}, ${b}, ${alpha})`
    }

    if (value.startsWith('rgb(')) {
        const [, inner] = value.match(/^rgb\((.*)\)$/) ?? []
        if (!inner) return value
        return `rgba(${inner.trim()}, ${alpha})`
    }

    if (value.startsWith('#')) {
        let hex = value.slice(1)
        if (hex.length === 3) {
            hex = expandHex(hex)
        }
        const numeric = Number.parseInt(hex.slice(0, 6), 16)
        if (Number.isNaN(numeric)) return value
        const r = (numeric >> 16) & 255
        const g = (numeric >> 8) & 255
        const b = numeric & 255
        return `rgba(${r}, ${g}, ${b}, ${alpha})`
    }

    return value
}

export const withAlpha = (color: string, alpha: number) => toRgba(color, alpha)

export const resolveChartTokens = (
    reader: typeof window.getComputedStyle = window.getComputedStyle,
): ChartTokens => ({
    accent1: readCssVariable('--app-chart-accent-1', FALLBACKS.accent1, reader),
    accent2: readCssVariable('--app-chart-accent-2', FALLBACKS.accent2, reader),
    accent3: readCssVariable('--app-chart-accent-3', FALLBACKS.accent3, reader),
    accent4: readCssVariable('--app-chart-accent-4', FALLBACKS.accent4, reader),
    accent5: readCssVariable('--app-chart-accent-5', FALLBACKS.accent5, reader),
    accent6: readCssVariable('--app-chart-accent-6', FALLBACKS.accent6, reader),
    accent7: readCssVariable('--app-chart-accent-7', FALLBACKS.accent7, reader),
    accent8: readCssVariable('--app-chart-accent-8', FALLBACKS.accent8, reader),
    gridStrong: readCssVariable(
        '--app-chart-grid-strong',
        FALLBACKS.gridStrong,
        reader,
    ),
    gridMuted: readCssVariable(
        '--app-chart-grid-muted',
        FALLBACKS.gridMuted,
        reader,
    ),
    gridSoft: readCssVariable(
        '--app-chart-grid-soft',
        FALLBACKS.gridSoft,
        reader,
    ),
})

export { FALLBACKS }
