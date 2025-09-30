import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// Ensure tests exercise authenticated flows without bypassing auth checks.
import.meta.env.VITE_AUTH_BYPASS = 'false'

if (typeof window !== 'undefined' && !window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: vi.fn().mockImplementation((query: string) => ({
            matches: false,
            media: query,
            onchange: null,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
            addListener: vi.fn(),
            removeListener: vi.fn(),
            dispatchEvent: vi.fn(),
        })),
    })
}
