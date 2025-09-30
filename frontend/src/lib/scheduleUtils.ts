import type { PricingScheduleEntry } from '../stores/usePricingStore'

type PrimitiveCronValue = string | number | null

export type ScheduleEditState = {
    schedule: string
    minute: string
    hour: string
    day_of_week: string
    day_of_month: string
    month_of_year: string
    enabled: boolean
}

const toInput = (value: PrimitiveCronValue | undefined) =>
    value === null || value === undefined ? '' : String(value)

export const createEditBuffer = (
    entry: PricingScheduleEntry,
): ScheduleEditState => {
    const scheduleValue = (() => {
        if (entry.schedule === null || entry.schedule === undefined) return ''
        if (typeof entry.schedule === 'object') {
            try {
                return JSON.stringify(entry.schedule)
            } catch (error) {
                console.error(error)
                return String(entry.schedule)
            }
        }
        return String(entry.schedule)
    })()

    return {
        schedule: scheduleValue,
        minute: toInput(entry.minute),
        hour: toInput(entry.hour),
        day_of_week: toInput(entry.day_of_week),
        day_of_month: toInput(entry.day_of_month),
        month_of_year: toInput(entry.month_of_year),
        enabled: entry.enabled !== false,
    }
}

export const parseCronField = (value: string) => {
    const trimmed = value.trim()
    if (!trimmed) return null
    const asNumber = Number(trimmed)
    return Number.isNaN(asNumber) ? trimmed : asNumber
}

export const parseScheduleValue = (value: string) => {
    const trimmed = value.trim()
    if (!trimmed) return null
    try {
        return JSON.parse(trimmed)
    } catch {
        const numeric = Number(trimmed)
        if (!Number.isNaN(numeric)) return numeric
        return trimmed
    }
}

export const applyBufferToEntry = (
    entry: PricingScheduleEntry,
    buffer: ScheduleEditState,
): PricingScheduleEntry => ({
    ...entry,
    schedule: parseScheduleValue(buffer.schedule),
    minute: parseCronField(buffer.minute),
    hour: parseCronField(buffer.hour),
    day_of_week: parseCronField(buffer.day_of_week),
    day_of_month: parseCronField(buffer.day_of_month),
    month_of_year: parseCronField(buffer.month_of_year),
    enabled: buffer.enabled,
})
