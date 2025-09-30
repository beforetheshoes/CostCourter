import { describe, expect, it } from 'vitest'

import {
    formatChartLabel,
    formatDateTime,
    formatPrice,
    formatResultPrice,
    formatResultReason,
    formatResultStatus,
    formatScheduleValue,
    trendSeverity,
} from '../../src/lib/metricsFormatters'

describe('metrics formatters', () => {
    it('formats prices with currency', () => {
        const formatted = formatPrice(199.5, 'EUR')
        expect(formatted).not.toBe('—')
        expect(formatted).toMatch(/199/)
        expect(formatPrice(null)).toBe('—')
        expect(formatResultPrice(49.123, 'USD')).toBe('USD 49.12')
        expect(formatResultPrice(null, 'USD')).toBe('—')
    })

    it('formats dates and chart labels', () => {
        const iso = '2024-01-01T10:00:00Z'
        expect(formatDateTime(iso)).not.toBe('—')
        expect(formatDateTime(new Date(iso))).not.toBe('—')
        expect(formatDateTime('invalid')).toBe('—')
        expect(formatChartLabel('2024-01-02')).toMatch(/Jan/)
        expect(formatChartLabel('invalid')).toBe('invalid')
    })

    it('describes trends and result status', () => {
        expect(trendSeverity('Going Up')).toBe('success')
        expect(trendSeverity('trend-down')).toBe('danger')
        expect(trendSeverity('brand new')).toBe('info')
        expect(trendSeverity('steady-state')).toBe('secondary')
        expect(trendSeverity('unknown')).toBe('contrast')
        expect(formatResultStatus(true)).toBe('Success')
        expect(formatResultStatus(false)).toBe('Failed')
    })

    it('represents result reasons and schedule values', () => {
        expect(formatResultReason('timeout', false)).toBe('timeout')
        expect(formatResultReason(null, false)).toBe('No reason provided')
        expect(formatResultReason('ignored', true)).toBe('—')

        expect(formatScheduleValue(null)).toBe('—')
        expect(formatScheduleValue({ foo: 'bar' })).toBe('{"foo":"bar"}')
        const circular: Record<string, unknown> = {}
        circular.self = circular
        expect(formatScheduleValue(circular)).toBe('[object Object]')
        expect(formatScheduleValue(Symbol('x'))).toBe('Symbol(x)')
    })
})
