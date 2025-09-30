import { describe, expect, it, vi } from 'vitest'

import {
    FALLBACKS,
    readCssVariable,
    resolveChartTokens,
    toRgba,
    withAlpha,
} from '../../src/lib/chartTokens'

describe('chartTokens utilities', () => {
    it('reads css variables with fallbacks when unset', () => {
        const value = readCssVariable(
            '--missing',
            FALLBACKS.accent1,
            () => ({ getPropertyValue: () => '' }) as CSSStyleDeclaration,
        )
        expect(value).toBe(FALLBACKS.accent1)
    })

    it('returns fallbacks when the DOM APIs are unavailable', () => {
        const globals = globalThis as typeof globalThis & {
            window?: unknown
            document?: unknown
        }
        const originalWindow = globals.window
        const originalDocument = globals.document
        globals.window = undefined
        globals.document = undefined

        try {
            const value = readCssVariable(
                '--any',
                '#123456',
                () => ({ getPropertyValue: () => '' }) as CSSStyleDeclaration,
            )
            expect(value).toBe('#123456')
        } finally {
            globals.window = originalWindow
            globals.document = originalDocument
        }
    })

    it('converts colors to rgba across supported formats', () => {
        expect(toRgba('rgba(10, 20, 30, 0.4)', 0.8)).toBe(
            'rgba(10, 20, 30, 0.8)',
        )
        expect(toRgba('rgb(10, 20, 30)', 0.5)).toBe('rgba(10, 20, 30, 0.5)')
        expect(toRgba('#abc', 0.3)).toBe('rgba(170, 187, 204, 0.3)')
        expect(toRgba('#112233', 0.2)).toBe('rgba(17, 34, 51, 0.2)')
        expect(toRgba('transparent', 0.4)).toBe('transparent')
        expect(toRgba('rgba invalid', 0.4)).toBe('rgba invalid')
        expect(toRgba('rgb invalid', 0.4)).toBe('rgb invalid')
        expect(toRgba('#zzzzzz', 0.4)).toBe('#zzzzzz')
        expect(withAlpha('#ff0000', 0.1)).toBe('rgba(255, 0, 0, 0.1)')
    })

    it('resolves chart tokens using provided style reader', () => {
        const styleMap: Record<string, string> = {
            '--app-chart-accent-1': 'rgba(1, 2, 3, 0.5)',
            '--app-chart-accent-2': 'rgb(4, 5, 6)',
            '--app-chart-accent-3': '#789',
            '--app-chart-accent-4': '#123456',
            '--app-chart-accent-5': 'rgba(7, 8, 9, 1)',
            '--app-chart-accent-6': '',
            '--app-chart-accent-7': 'rgb(10, 11, 12)',
            '--app-chart-accent-8': '#fedcba',
            '--app-chart-grid-strong': 'rgba(13, 14, 15, 0.2)',
            '--app-chart-grid-muted': 'rgb(16, 17, 18)',
            '--app-chart-grid-soft': '#aaa',
        }

        const reader = vi.fn().mockReturnValue({
            getPropertyValue: (token: string) => styleMap[token] ?? '',
        })

        const tokens = resolveChartTokens(
            reader as unknown as typeof window.getComputedStyle,
        )
        expect(tokens.accent1).toBe('rgba(1, 2, 3, 0.5)')
        expect(tokens.accent2).toBe('rgb(4, 5, 6)')
        expect(tokens.accent3).toBe('#789')
        expect(tokens.accent4).toBe('#123456')
        expect(tokens.accent5).toBe('rgba(7, 8, 9, 1)')
        expect(tokens.accent6).toBe(FALLBACKS.accent6)
        expect(tokens.gridMuted).toBe('rgb(16, 17, 18)')
        expect(tokens.gridSoft).toBe('#aaa')
    })
})
