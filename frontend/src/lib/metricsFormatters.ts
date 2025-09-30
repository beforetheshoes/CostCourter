export const formatPrice = (value: number | null, currency = 'USD') => {
    if (value === null || Number.isNaN(value)) return '—'
    return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency,
        maximumFractionDigits: 2,
    }).format(value)
}

export const formatDateTime = (value: string | Date | null) => {
    if (!value) return '—'
    const date = value instanceof Date ? value : new Date(value)
    if (Number.isNaN(date.getTime())) return '—'
    return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
    }).format(date)
}

export const formatChartLabel = (value: string) => {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    const thisYear = new Date().getFullYear()
    return new Intl.DateTimeFormat(undefined, {
        month: 'short',
        day: 'numeric',
        year: date.getFullYear() === thisYear ? undefined : '2-digit',
    }).format(date)
}

export const trendSeverity = (trend: string) => {
    const normalized = trend?.toLowerCase() ?? ''
    if (normalized.includes('up')) return 'success'
    if (normalized.includes('down')) return 'danger'
    if (normalized.includes('new')) return 'info'
    if (normalized.includes('steady')) return 'secondary'
    return 'contrast'
}

export const formatResultStatus = (success: boolean) =>
    success ? 'Success' : 'Failed'

export const formatResultPrice = (
    price: number | null,
    currency: string | null,
) => {
    if (typeof price !== 'number') return '—'
    const formatted = price.toFixed(2)
    return currency ? `${currency} ${formatted}` : formatted
}

export const formatResultReason = (reason: string | null, success: boolean) => {
    if (success) return '—'
    return reason ?? 'No reason provided'
}

export const formatScheduleValue = (value: unknown) => {
    if (value === null || value === undefined || value === '') return '—'
    if (typeof value === 'object') {
        try {
            return JSON.stringify(value)
        } catch {
            return String(value)
        }
    }
    return String(value)
}
