import { describe, expect, it, vi } from 'vitest'

import {
    applyBufferToEntry,
    createEditBuffer,
    parseCronField,
    parseScheduleValue,
    type ScheduleEditState,
} from '../../src/lib/scheduleUtils'
import type { PricingScheduleEntry } from '../../src/stores/usePricingStore'

describe('schedule utilities', () => {
    const baseEntry: PricingScheduleEntry = {
        name: 'pricing.update_all_products',
        task: 'pricing.update_all_products',
        schedule: 3600,
        enabled: true,
        args: [],
        kwargs: {},
        minute: null,
        hour: null,
        day_of_week: '*',
        day_of_month: '*',
        month_of_year: '*',
    }

    it('creates edit buffers and tolerates circular schedule objects', () => {
        const circular: Record<string, unknown> = {}
        circular.self = circular
        const entry: PricingScheduleEntry = {
            ...baseEntry,
            schedule: circular,
        }
        const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
        const buffer = createEditBuffer(entry)
        expect(buffer.schedule).toContain('[object Object]')
        expect(buffer.enabled).toBe(true)
        expect(buffer.day_of_week).toBe('*')
        expect(errorSpy).toHaveBeenCalled()
        errorSpy.mockRestore()
    })

    it('stringifies serialisable schedule objects', () => {
        const entry: PricingScheduleEntry = {
            ...baseEntry,
            schedule: { cron: '@hourly' },
        }
        const buffer = createEditBuffer(entry)
        expect(buffer.schedule).toBe('{"cron":"@hourly"}')
    })

    it('parses cron fields and schedule values', () => {
        expect(parseCronField('')).toBeNull()
        expect(parseCronField('15')).toBe(15)
        expect(parseCronField('*/5')).toBe('*/5')

        expect(parseScheduleValue('')).toBeNull()
        expect(parseScheduleValue('42')).toBe(42)
        expect(parseScheduleValue('"cron"')).toBe('cron')
        expect(parseScheduleValue('{"foo":true}')).toEqual({ foo: true })
        expect(parseScheduleValue('{invalid')).toBe('{invalid')
    })

    it('applies buffers to entries', () => {
        const buffer: ScheduleEditState = {
            schedule: '{"cron":"@hourly"}',
            minute: '15',
            hour: '*/3',
            day_of_week: '*',
            day_of_month: '1',
            month_of_year: 'Jan',
            enabled: false,
        }
        const updated = applyBufferToEntry(baseEntry, buffer)
        expect(updated.schedule).toEqual({ cron: '@hourly' })
        expect(updated.minute).toBe(15)
        expect(updated.month_of_year).toBe('Jan')
        expect(updated.enabled).toBe(false)
    })
})
