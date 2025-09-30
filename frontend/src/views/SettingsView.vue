<script setup lang="ts">
import {
    computed,
    getCurrentInstance,
    nextTick,
    onBeforeUnmount,
    onMounted,
    ref,
    watch,
} from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { usePrimeVue } from 'primevue/config'

import TagManagementPanel from '../components/TagManagementPanel.vue'
import NotificationPreferencesPanel from '../components/NotificationPreferencesPanel.vue'
import { useAuthStore } from '../stores/useAuthStore'
import {
    usePricingStore,
    type PricingScheduleEntry,
} from '../stores/usePricingStore'
import { apiClient } from '../lib/http'
import {
    brandThemeOptions,
    resolveBrandTheme,
    type BrandThemeId,
} from '../lib/theme'
import {
    applyBrandTheme,
    BRAND_THEME_EVENT,
    getStoredBrandThemeId,
} from '../lib/themeManager'
import {
    applyColorMode,
    COLOR_MODE_EVENT,
    getStoredColorMode,
    type ColorMode,
} from '../lib/colorMode'
import {
    formatDateTime as formatDateTimeDisplay,
    formatResultPrice as formatResultPriceDisplay,
    formatResultReason as formatResultReasonDisplay,
    formatResultStatus as formatResultStatusLabel,
    formatScheduleValue as formatScheduleValueDisplay,
} from '../lib/metricsFormatters'
import {
    applyBufferToEntry,
    createEditBuffer,
    type ScheduleEditState,
} from '../lib/scheduleUtils'

const refreshPending = ref(false)
const pricingStore = usePricingStore()
const authStore = useAuthStore()
const { summary, loading, error } = storeToRefs(pricingStore)
const scheduleEntries = ref<PricingScheduleEntry[]>([])
const scheduleJson = ref<string>('')
const editingEntry = ref<string | null>(null)
const editBuffers = ref<Record<string, ScheduleEditState>>({})
const showAdvancedEditor = ref(false)
const backupExporting = ref(false)
const backupExportMessage = ref<string | null>(null)
const backupExportError = ref<string | null>(null)
const backupImporting = ref(false)
const backupImportError = ref<string | null>(null)
const backupImportResult = ref<CatalogImportResponse | null>(null)
const selectedBackupPayload = ref<CatalogBackup | null>(null)
const selectedBackupFilename = ref<string | null>(null)
const backupFileInput = ref<HTMLInputElement | null>(null)

const instance = getCurrentInstance()
const hasRouter = Boolean(
    instance?.appContext.config.globalProperties &&
        '$router' in instance.appContext.config.globalProperties,
)
const route = hasRouter ? useRoute() : null

const sectionAnchors: Record<string, string> = {
    automation: 'settings-automation',
    appearance: 'settings-appearance',
    notifications: 'settings-notifications',
    tags: 'settings-tags',
    backups: 'settings-backups',
}

type BackupTag = {
    slug: string
    name: string
}

type BackupStore = {
    slug: string
    name: string
    website_url: string | null
    active: boolean
    locale: string | null
    currency: string | null
    domains: unknown[]
    scrape_strategy: Record<string, unknown>
    settings: Record<string, unknown>
    notes: string | null
}

type BackupProduct = {
    name: string
    slug: string
    description: string | null
    is_active: boolean
    status: string
    favourite: boolean
    only_official: boolean
    notify_price: number | null
    notify_percent: number | null
    ignored_urls: string[]
    image_url: string | null
    tag_slugs: string[]
    tags: BackupTag[]
}

type BackupProductURL = {
    url: string
    is_primary: boolean
    active: boolean
    store: BackupStore
}

type BackupPriceHistory = {
    price: number
    currency: string
    recorded_at: string
    url: string | null
}

type ProductBackupEntry = {
    product: BackupProduct
    urls: BackupProductURL[]
    price_history: BackupPriceHistory[]
}

type CatalogBackup = {
    version: number
    exported_at: string
    products: ProductBackupEntry[]
}

type CatalogImportResponse = {
    products_created: number
    products_updated: number
    product_urls_created: number
    product_urls_updated: number
    price_history_created: number
    price_history_skipped: number
    stores_created: number
    stores_updated: number
    tags_created: number
    tags_updated: number
}

const VIEW_PREFERENCE_STORAGE_KEY = 'costcourter.products.defaultView'
const VIEW_PREFERENCE_EVENT = 'costcourter:products:viewPreference'

const resolveStoredProductView = () => {
    const stored = localStorage.getItem(VIEW_PREFERENCE_STORAGE_KEY)
    return stored === 'table' ? 'table' : 'tiles'
}

const defaultProductView = ref<'tiles' | 'table'>(resolveStoredProductView())
const productViewOptions = [
    { label: 'Tile view', value: 'tiles' as const },
    { label: 'Table view', value: 'table' as const },
]

const updateDefaultProductView = (value: 'tiles' | 'table') => {
    defaultProductView.value = value
    localStorage.setItem(VIEW_PREFERENCE_STORAGE_KEY, value)
    window.dispatchEvent(
        new CustomEvent(VIEW_PREFERENCE_EVENT, { detail: value }),
    )
}

const scrollToSettingsSection = (rawSection: unknown) => {
    const candidate = Array.isArray(rawSection) ? rawSection[0] : rawSection
    if (typeof candidate !== 'string') return
    const normalized = candidate.toLowerCase()
    const anchor = sectionAnchors[normalized]
    if (!anchor) return
    void nextTick(() => {
        document.getElementById(anchor)?.scrollIntoView({
            behavior: 'smooth',
            block: 'start',
        })
    })
}

const resolveSectionQuery = () => (route ? route.query.section : null)

onMounted(() => {
    scrollToSettingsSection(resolveSectionQuery())
})

watch(resolveSectionQuery, (section) => {
    scrollToSettingsSection(section)
})

const displayMode = ref<ColorMode>(getStoredColorMode())
applyColorMode(displayMode.value, { persist: false, emit: false })

const primevue = usePrimeVue()
const brandTheme = ref<BrandThemeId>(getStoredBrandThemeId())
const accentThemes = brandThemeOptions

const selectBrandTheme = (next: BrandThemeId) => {
    brandTheme.value = next
    applyBrandTheme(primevue, next)
}

selectBrandTheme(brandTheme.value)

const selectDisplayMode = (mode: ColorMode | null | undefined) => {
    if (!mode) return
    displayMode.value = mode
    applyColorMode(mode)
}

const handleBrandThemeBroadcast = (event: Event) => {
    const detail = (event as CustomEvent<{ id?: string }>).detail
    const resolved = resolveBrandTheme(detail?.id)
    brandTheme.value = resolved.id
}

const handleColorModeBroadcast = (event: Event) => {
    const detail = (event as CustomEvent<{ mode?: ColorMode }>).detail
    if (detail?.mode) {
        displayMode.value = detail.mode
    } else {
        displayMode.value = getStoredColorMode()
    }
}

if (typeof window !== 'undefined') {
    window.addEventListener(BRAND_THEME_EVENT, handleBrandThemeBroadcast)
    window.addEventListener(COLOR_MODE_EVENT, handleColorModeBroadcast)
}

onBeforeUnmount(() => {
    if (typeof window !== 'undefined') {
        window.removeEventListener(BRAND_THEME_EVENT, handleBrandThemeBroadcast)
        window.removeEventListener(COLOR_MODE_EVENT, handleColorModeBroadcast)
    }
})

const loadSchedule = async () => {
    const entries = await pricingStore.loadSchedule()
    scheduleEntries.value = entries
    scheduleJson.value = JSON.stringify(entries, null, 2)
    editingEntry.value = null
    editBuffers.value = {}
}

void loadSchedule()

const resultRows = computed(() => summary.value?.results ?? [])
const hasResults = computed(() => resultRows.value.length > 0)
const isAuthenticated = computed(() => authStore.isAuthenticated)
const backupImportSummary = computed(() => {
    const result = backupImportResult.value
    if (!result) return null
    const parts = [
        `${result.products_created} product${result.products_created === 1 ? '' : 's'} created`,
        `${result.product_urls_created} URL${result.product_urls_created === 1 ? '' : 's'} created`,
        `${result.price_history_created} price record${result.price_history_created === 1 ? '' : 's'} imported`,
    ]
    return parts.join(', ')
})

const triggerRefresh = async () => {
    if (!isAuthenticated.value) return
    try {
        refreshPending.value = true
        await pricingStore.refreshAll(true)
    } finally {
        refreshPending.value = false
    }
}

const resetImportState = () => {
    backupImportError.value = null
    backupImportResult.value = null
    selectedBackupPayload.value = null
    selectedBackupFilename.value = null
    if (backupFileInput.value) {
        backupFileInput.value.value = ''
    }
}

const validateBackupPayload = (payload: unknown): CatalogBackup => {
    if (!payload || typeof payload !== 'object') {
        throw new Error('Backup file is not a valid JSON object')
    }
    const candidate = payload as Partial<CatalogBackup>
    if (!Array.isArray(candidate.products)) {
        throw new Error('Backup is missing product entries')
    }
    if (typeof candidate.version !== 'number') {
        throw new Error('Backup version is missing')
    }
    return candidate as CatalogBackup
}

const handleBackupFileChange = async (event: Event) => {
    const target = event.target as HTMLInputElement | null
    const file = target?.files?.[0]
    if (!file) {
        resetImportState()
        return
    }
    try {
        const contents = await file.text()
        const parsed = JSON.parse(contents)
        const backup = validateBackupPayload(parsed)
        selectedBackupPayload.value = backup
        selectedBackupFilename.value = file.name
        backupImportError.value = null
        backupImportResult.value = null
    } catch (error) {
        selectedBackupPayload.value = null
        selectedBackupFilename.value = file.name
        backupImportResult.value = null
        backupImportError.value =
            error instanceof Error
                ? error.message
                : 'Unable to read backup file'
    }
}

const exportProductBackup = async () => {
    if (backupExporting.value) return
    backupExporting.value = true
    backupExportMessage.value = null
    backupExportError.value = null
    try {
        const response = await apiClient.get<CatalogBackup>('/backups/products')
        const backup = response.data
        const blob = new Blob([JSON.stringify(backup, null, 2)], {
            type: 'application/json',
        })
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
        const objectUrl = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = objectUrl
        link.download = `costcourter-backup-${timestamp}.json`
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        URL.revokeObjectURL(objectUrl)
        const count = backup.products.length
        backupExportMessage.value = `Exported ${count} product${count === 1 ? '' : 's'}.`
    } catch (error) {
        backupExportError.value =
            error instanceof Error ? error.message : 'Failed to export backup'
    } finally {
        backupExporting.value = false
    }
}

const importProductBackup = async () => {
    if (backupImporting.value) return
    if (!selectedBackupPayload.value) {
        backupImportError.value = 'Select a valid backup file before importing'
        return
    }
    backupImporting.value = true
    backupImportError.value = null
    backupImportResult.value = null
    try {
        const response = await apiClient.post<CatalogImportResponse>(
            '/backups/products',
            selectedBackupPayload.value,
        )
        backupImportResult.value = response.data
    } catch (error) {
        backupImportError.value =
            error instanceof Error ? error.message : 'Failed to import backup'
    } finally {
        backupImporting.value = false
    }
}

const beginEditing = (entry: PricingScheduleEntry) => {
    editingEntry.value = entry.name
    editBuffers.value[entry.name] = createEditBuffer(entry)
}

const cancelEditing = (name: string) => {
    if (editingEntry.value === name) {
        editingEntry.value = null
    }
    const existing = scheduleEntries.value.find((entry) => entry.name === name)
    if (existing) {
        editBuffers.value[name] = createEditBuffer(existing)
    } else {
        delete editBuffers.value[name]
    }
}

const toggleEntry = async (name: string) => {
    const updated = scheduleEntries.value.map((entry) =>
        entry.name === name
            ? { ...entry, enabled: entry.enabled === false ? true : false }
            : entry,
    )
    const saved = await pricingStore.updateSchedule(updated)
    scheduleEntries.value = saved
    scheduleJson.value = JSON.stringify(saved, null, 2)
    const refreshed = saved.find((entry) => entry.name === name)
    if (refreshed && editingEntry.value === name) {
        editBuffers.value[name] = createEditBuffer(refreshed)
    }
}

const saveScheduleEntry = async (name: string) => {
    const buffer = editBuffers.value[name]
    if (!buffer) return
    const updatedEntries = scheduleEntries.value.map((entry) =>
        entry.name === name ? applyBufferToEntry(entry, buffer) : entry,
    )
    const saved = await pricingStore.updateSchedule(updatedEntries)
    scheduleEntries.value = saved
    scheduleJson.value = JSON.stringify(saved, null, 2)
    editingEntry.value = null
    delete editBuffers.value[name]
}

const saveSchedule = async () => {
    try {
        const parsed = JSON.parse(scheduleJson.value || '[]')
        const updated = await pricingStore.updateSchedule(
            Array.isArray(parsed) ? (parsed as PricingScheduleEntry[]) : [],
        )
        scheduleEntries.value = updated
        scheduleJson.value = JSON.stringify(updated, null, 2)
        editingEntry.value = null
        editBuffers.value = {}
    } catch (err) {
        console.error(err)
    }
}

const scheduleMeta = computed(() => {
    const enabledEntries = scheduleEntries.value.filter(
        (entry) => entry.enabled !== false,
    )
    const nextRuns = enabledEntries
        .map((entry) =>
            entry.next_run_at ? new Date(entry.next_run_at) : null,
        )
        .filter(
            (date): date is Date =>
                date instanceof Date && !Number.isNaN(date.getTime()),
        )
    const lastRuns = scheduleEntries.value
        .map((entry) =>
            entry.last_run_at ? new Date(entry.last_run_at) : null,
        )
        .filter(
            (date): date is Date =>
                date instanceof Date && !Number.isNaN(date.getTime()),
        )

    const nextRun =
        nextRuns.sort((a, b) => a.getTime() - b.getTime())[0] ?? null
    const lastRun =
        lastRuns.sort((a, b) => b.getTime() - a.getTime())[0] ?? null

    return { nextRun, lastRun }
})
</script>

<template>
    <section class="page-section max-w-6xl mx-auto space-y-10">
        <header class="space-y-2">
            <h1 class="text-3xl font-semibold text-color">
                Workspace settings
            </h1>
            <p class="text-muted-color">
                Configure automation schedules, tagging, and appearance
                preferences for the admin console.
            </p>
        </header>

        <section
            v-if="scheduleMeta.nextRun || scheduleMeta.lastRun"
            class="rounded-border border border-primary/20 bg-primary/5 px-4 py-3 text-sm text-left"
            role="status"
        >
            <p class="text-color">
                <strong>Next scheduled run:</strong>
                {{ formatDateTimeDisplay(scheduleMeta.nextRun) }}
            </p>
            <p class="text-muted-color mt-1">
                <strong>Last completed run:</strong>
                {{ formatDateTimeDisplay(scheduleMeta.lastRun) }}
            </p>
        </section>

        <PvCard
            id="settings-backups"
            class="border border-surface-200 bg-surface-0"
        >
            <template #header>
                <div class="flex items-center justify-between">
                    <div>
                        <h2 class="text-xl font-semibold text-color">
                            Data backups
                        </h2>
                        <p class="text-sm text-muted-color">
                            Export your tracked products and price history, or
                            import an existing backup into this workspace.
                        </p>
                    </div>
                    <i class="pi pi-database text-2xl text-primary"></i>
                </div>
            </template>
            <template #content>
                <div class="grid gap-6 lg:grid-cols-2">
                    <section class="space-y-3">
                        <header class="space-y-1">
                            <h3 class="text-lg font-semibold text-color">
                                Export
                            </h3>
                            <p class="text-sm text-muted-color">
                                Download a JSON backup containing all products,
                                URLs, and price history for the current user.
                            </p>
                        </header>
                        <PvButton
                            severity="primary"
                            icon="pi pi-download"
                            label="Export products JSON"
                            :loading="backupExporting"
                            @click="exportProductBackup"
                        />
                        <p
                            v-if="backupExportMessage"
                            class="text-xs text-green-600"
                        >
                            {{ backupExportMessage }}
                        </p>
                        <p
                            v-if="backupExportError"
                            class="text-xs text-red-500"
                        >
                            {{ backupExportError }}
                        </p>
                    </section>
                    <section class="space-y-3">
                        <header class="space-y-1">
                            <h3 class="text-lg font-semibold text-color">
                                Import
                            </h3>
                            <p class="text-sm text-muted-color">
                                Select a backup JSON exported from CostCourter
                                to recreate products, URLs, and historical
                                prices under your account.
                            </p>
                        </header>
                        <label
                            class="flex flex-col gap-2 text-sm text-muted-color"
                        >
                            <span>Backup file (JSON)</span>
                            <input
                                ref="backupFileInput"
                                type="file"
                                accept="application/json"
                                class="rounded-border border border-dashed border-surface-300 bg-surface-0 px-3 py-2 text-color"
                                @change="handleBackupFileChange"
                            />
                        </label>
                        <p
                            v-if="selectedBackupFilename"
                            class="text-xs text-muted-color"
                        >
                            Selected: {{ selectedBackupFilename }}
                        </p>
                        <div class="flex flex-wrap gap-2">
                            <PvButton
                                severity="primary"
                                icon="pi pi-upload"
                                label="Import backup"
                                :loading="backupImporting"
                                :disabled="!selectedBackupPayload"
                                @click="importProductBackup"
                            />
                            <PvButton
                                severity="secondary"
                                label="Clear selection"
                                outlined
                                :disabled="backupImporting"
                                @click="resetImportState"
                            />
                        </div>
                        <p
                            v-if="backupImportError"
                            class="text-xs text-red-500"
                        >
                            {{ backupImportError }}
                        </p>
                        <p
                            v-else-if="backupImportSummary"
                            class="text-xs text-green-600"
                        >
                            {{ backupImportSummary }}
                        </p>
                        <ul
                            v-if="backupImportResult"
                            class="text-xs text-muted-color space-y-1 border border-surface-200 bg-surface-50 p-3 rounded-border"
                        >
                            <li>
                                Products updated:
                                {{ backupImportResult.products_updated }}
                            </li>
                            <li>
                                URLs updated:
                                {{ backupImportResult.product_urls_updated }}
                            </li>
                            <li>
                                Price records skipped (duplicates):
                                {{ backupImportResult.price_history_skipped }}
                            </li>
                            <li>
                                Stores created:
                                {{ backupImportResult.stores_created }} ·
                                updated: {{ backupImportResult.stores_updated }}
                            </li>
                            <li>
                                Tags created:
                                {{ backupImportResult.tags_created }} · updated:
                                {{ backupImportResult.tags_updated }}
                            </li>
                        </ul>
                    </section>
                </div>
            </template>
        </PvCard>

        <PvCard
            id="settings-automation"
            class="border border-surface-200 bg-surface-0"
        >
            <template #header>
                <div class="flex items-center justify-between">
                    <div>
                        <h2 class="text-xl font-semibold text-color">
                            Pricing automation
                        </h2>
                        <p class="text-sm text-muted-color">
                            Manage the Celery schedule and trigger manual
                            refreshes when you need results quickly.
                        </p>
                    </div>
                    <i class="pi pi-chart-line text-2xl text-primary"></i>
                </div>
            </template>
            <template #content>
                <div class="space-y-5">
                    <div class="flex flex-wrap gap-3">
                        <PvButton
                            severity="primary"
                            :loading="refreshPending || loading"
                            icon="pi pi-refresh"
                            label="Refresh all prices"
                            @click="triggerRefresh"
                        />
                        <PvButton
                            severity="secondary"
                            icon="pi pi-sync"
                            label="Reload schedule"
                            outlined
                            @click="loadSchedule"
                        />
                        <PvButton
                            severity="secondary"
                            icon="pi pi-code"
                            label="Toggle JSON editor"
                            outlined
                            @click="showAdvancedEditor = !showAdvancedEditor"
                        />
                    </div>

                    <footer class="space-y-3">
                        <p v-if="error" class="text-sm text-red-500">
                            {{ error }}
                        </p>
                        <ul
                            v-else-if="summary"
                            class="text-sm text-muted-color space-y-1"
                        >
                            <li>
                                <strong>URLs Processed:</strong>
                                {{ summary.total_urls }}
                            </li>
                            <li>
                                <strong>Success:</strong>
                                {{ summary.successful_urls }}
                            </li>
                            <li>
                                <strong>Failures:</strong>
                                {{ summary.failed_urls }}
                            </li>
                        </ul>
                        <div v-if="hasResults" class="mt-4 overflow-x-auto">
                            <table
                                class="min-w-full divide-y divide-surface-200 text-left text-sm"
                                aria-label="Price fetch results"
                            >
                                <thead
                                    class="bg-surface-100 text-muted-color uppercase"
                                >
                                    <tr>
                                        <th class="px-4 py-3">
                                            Product URL ID
                                        </th>
                                        <th class="px-4 py-3">Status</th>
                                        <th class="px-4 py-3">Price</th>
                                        <th class="px-4 py-3">Currency</th>
                                        <th class="px-4 py-3">Reason</th>
                                    </tr>
                                </thead>
                                <tbody class="divide-y divide-surface-200">
                                    <tr
                                        v-for="entry in resultRows"
                                        :key="entry.product_url_id"
                                    >
                                        <td class="px-4 py-3 text-color">
                                            {{ entry.product_url_id }}
                                        </td>
                                        <td
                                            class="px-4 py-3 font-medium"
                                            :class="
                                                entry.success
                                                    ? 'text-green-600'
                                                    : 'text-red-500'
                                            "
                                        >
                                            {{
                                                formatResultStatusLabel(
                                                    entry.success,
                                                )
                                            }}
                                        </td>
                                        <td class="px-4 py-3 text-muted-color">
                                            {{
                                                formatResultPriceDisplay(
                                                    entry.price,
                                                    entry.currency,
                                                )
                                            }}
                                        </td>
                                        <td class="px-4 py-3 text-muted-color">
                                            {{ entry.currency ?? '—' }}
                                        </td>
                                        <td class="px-4 py-3 text-muted-color">
                                            {{
                                                formatResultReasonDisplay(
                                                    entry.reason,
                                                    entry.success,
                                                )
                                            }}
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </footer>

                    <div v-if="scheduleEntries.length" class="space-y-3">
                        <h3 class="font-semibold text-color">
                            Schedule entries
                        </h3>
                        <p class="text-xs text-muted-color">
                            Edit interval and cron fields inline; leave blank to
                            clear a specific cron field.
                        </p>
                        <ul class="space-y-3">
                            <li
                                v-for="entry in scheduleEntries"
                                :key="entry.name"
                                class="border border-surface rounded-border bg-surface-0 p-3"
                            >
                                <div class="flex flex-col gap-3">
                                    <div
                                        class="flex flex-wrap items-start justify-between gap-3"
                                    >
                                        <div class="flex items-start gap-3">
                                            <span
                                                class="mt-1 inline-block h-2 w-2 rounded-full"
                                                :class="
                                                    entry.enabled !== false
                                                        ? 'bg-green-500'
                                                        : 'bg-surface-400'
                                                "
                                                aria-hidden="true"
                                            ></span>
                                            <div class="flex flex-col gap-1">
                                                <span
                                                    class="font-mono text-sm text-color"
                                                    >{{ entry.name }}</span
                                                >
                                                <span
                                                    class="text-xs text-muted-color"
                                                >
                                                    Task:
                                                    <code>{{
                                                        entry.task
                                                    }}</code>
                                                </span>
                                                <div
                                                    class="flex flex-wrap gap-2 text-xs text-muted-color"
                                                >
                                                    <span>
                                                        Schedule:
                                                        <code>{{
                                                            formatScheduleValueDisplay(
                                                                entry.schedule,
                                                            )
                                                        }}</code>
                                                    </span>
                                                    <span
                                                        >Minute:
                                                        {{
                                                            formatScheduleValueDisplay(
                                                                entry.minute,
                                                            )
                                                        }}</span
                                                    >
                                                    <span
                                                        >Hour:
                                                        {{
                                                            formatScheduleValueDisplay(
                                                                entry.hour,
                                                            )
                                                        }}</span
                                                    >
                                                    <span
                                                        >Day of week:
                                                        {{
                                                            formatScheduleValueDisplay(
                                                                entry.day_of_week,
                                                            )
                                                        }}</span
                                                    >
                                                    <span
                                                        >Day of month:
                                                        {{
                                                            formatScheduleValueDisplay(
                                                                entry.day_of_month,
                                                            )
                                                        }}</span
                                                    >
                                                    <span
                                                        >Month:
                                                        {{
                                                            formatScheduleValueDisplay(
                                                                entry.month_of_year,
                                                            )
                                                        }}</span
                                                    >
                                                </div>
                                            </div>
                                        </div>
                                        <div class="flex flex-wrap gap-2">
                                            <PvButton
                                                v-if="
                                                    editingEntry !== entry.name
                                                "
                                                size="small"
                                                label="Edit"
                                                icon="pi pi-pencil"
                                                type="button"
                                                @click="beginEditing(entry)"
                                            />
                                            <PvButton
                                                v-else
                                                size="small"
                                                label="Cancel"
                                                icon="pi pi-times"
                                                severity="secondary"
                                                outlined
                                                type="button"
                                                @click="
                                                    cancelEditing(entry.name)
                                                "
                                            />
                                            <PvButton
                                                size="small"
                                                :label="
                                                    entry.enabled !== false
                                                        ? 'Disable'
                                                        : 'Enable'
                                                "
                                                :icon="
                                                    entry.enabled !== false
                                                        ? 'pi pi-pause'
                                                        : 'pi pi-play'
                                                "
                                                :severity="
                                                    entry.enabled !== false
                                                        ? 'secondary'
                                                        : 'success'
                                                "
                                                type="button"
                                                @click="toggleEntry(entry.name)"
                                            />
                                        </div>
                                    </div>
                                    <div
                                        v-if="
                                            editingEntry === entry.name &&
                                            editBuffers[entry.name]
                                        "
                                        class="rounded-border border border-dashed border-surface-300 bg-surface p-3 space-y-3"
                                    >
                                        <p class="text-xs text-muted-color">
                                            Update the interval or cron fields.
                                            Numeric values are parsed when
                                            possible.
                                        </p>
                                        <div class="grid gap-3 md:grid-cols-2">
                                            <div class="flex flex-col gap-1">
                                                <label
                                                    class="text-xs font-medium uppercase text-muted-color"
                                                    :for="`schedule-${entry.name}`"
                                                >
                                                    Interval / schedule
                                                </label>
                                                <PvInputText
                                                    :id="`schedule-${entry.name}`"
                                                    v-model="
                                                        editBuffers[entry.name]
                                                            .schedule
                                                    "
                                                    placeholder="e.g. 3600"
                                                />
                                            </div>
                                            <div class="flex flex-col gap-1">
                                                <label
                                                    class="text-xs font-medium uppercase text-muted-color"
                                                    :for="`minute-${entry.name}`"
                                                >
                                                    Minute
                                                </label>
                                                <PvInputText
                                                    :id="`minute-${entry.name}`"
                                                    v-model="
                                                        editBuffers[entry.name]
                                                            .minute
                                                    "
                                                    placeholder="*"
                                                />
                                            </div>
                                            <div class="flex flex-col gap-1">
                                                <label
                                                    class="text-xs font-medium uppercase text-muted-color"
                                                    :for="`hour-${entry.name}`"
                                                >
                                                    Hour
                                                </label>
                                                <PvInputText
                                                    :id="`hour-${entry.name}`"
                                                    v-model="
                                                        editBuffers[entry.name]
                                                            .hour
                                                    "
                                                    placeholder="*/6"
                                                />
                                            </div>
                                            <div class="flex flex-col gap-1">
                                                <label
                                                    class="text-xs font-medium uppercase text-muted-color"
                                                    :for="`dow-${entry.name}`"
                                                >
                                                    Day of week
                                                </label>
                                                <PvInputText
                                                    :id="`dow-${entry.name}`"
                                                    v-model="
                                                        editBuffers[entry.name]
                                                            .day_of_week
                                                    "
                                                    placeholder="*"
                                                />
                                            </div>
                                            <div class="flex flex-col gap-1">
                                                <label
                                                    class="text-xs font-medium uppercase text-muted-color"
                                                    :for="`dom-${entry.name}`"
                                                >
                                                    Day of month
                                                </label>
                                                <PvInputText
                                                    :id="`dom-${entry.name}`"
                                                    v-model="
                                                        editBuffers[entry.name]
                                                            .day_of_month
                                                    "
                                                    placeholder="*"
                                                />
                                            </div>
                                            <div class="flex flex-col gap-1">
                                                <label
                                                    class="text-xs font-medium uppercase text-muted-color"
                                                    :for="`moy-${entry.name}`"
                                                >
                                                    Month of year
                                                </label>
                                                <PvInputText
                                                    :id="`moy-${entry.name}`"
                                                    v-model="
                                                        editBuffers[entry.name]
                                                            .month_of_year
                                                    "
                                                    placeholder="*"
                                                />
                                            </div>
                                            <label
                                                class="flex items-center gap-2 text-sm md:col-span-2"
                                            >
                                                <PvCheckbox
                                                    v-model="
                                                        editBuffers[entry.name]
                                                            .enabled
                                                    "
                                                    binary
                                                />
                                                <span class="text-muted-color"
                                                    >Enabled</span
                                                >
                                            </label>
                                        </div>
                                        <div class="flex gap-2">
                                            <PvButton
                                                label="Save changes"
                                                icon="pi pi-check"
                                                size="small"
                                                @click="
                                                    saveScheduleEntry(
                                                        entry.name,
                                                    )
                                                "
                                            />
                                        </div>
                                    </div>
                                </div>
                            </li>
                        </ul>
                    </div>

                    <section v-if="showAdvancedEditor" class="space-y-2">
                        <h3 class="font-semibold text-color">
                            Advanced JSON editor
                        </h3>
                        <PvInputTextarea
                            v-model="scheduleJson"
                            auto-resize
                            rows="10"
                            class="font-mono"
                        />
                        <div class="flex gap-2">
                            <PvButton
                                label="Save schedule"
                                icon="pi pi-save"
                                :loading="loading"
                                @click="saveSchedule"
                            />
                        </div>
                    </section>
                </div>
            </template>
        </PvCard>

        <PvCard
            id="settings-appearance"
            class="border border-surface-200 bg-surface-0"
        >
            <template #header>
                <div class="flex items-center justify-between">
                    <div>
                        <h2 class="text-xl font-semibold text-color">
                            Theme & appearance
                        </h2>
                        <p class="text-sm text-muted-color">
                            Choose how the admin interface should look across
                            sessions.
                        </p>
                    </div>
                    <i class="pi pi-palette text-2xl text-primary"></i>
                </div>
            </template>
            <template #content>
                <div class="flex flex-col gap-6">
                    <div
                        class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
                    >
                        <label
                            class="text-sm flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3"
                        >
                            <span class="text-muted-color">Display mode</span>
                            <PvDropdown
                                :model-value="displayMode"
                                :options="[
                                    { label: 'Match system', value: 'system' },
                                    { label: 'Light', value: 'light' },
                                    { label: 'Dark', value: 'dark' },
                                ]"
                                option-label="label"
                                option-value="value"
                                placeholder="Select theme"
                                @update:model-value="selectDisplayMode"
                            />
                        </label>
                        <p class="text-xs text-muted-color sm:text-right">
                            Changes apply immediately and persist for your
                            browser.
                        </p>
                    </div>

                    <div
                        class="flex flex-col gap-3 border-t border-surface-100 pt-4"
                    >
                        <div
                            class="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between"
                        >
                            <span class="text-sm text-muted-color"
                                >Accent theme</span
                            >
                            <p class="text-xs text-muted-color sm:text-right">
                                Pick a palette to recolor PrimeVue tokens and
                                ambient visuals.
                            </p>
                        </div>
                        <div
                            class="grid gap-3 md:grid-cols-3"
                            role="group"
                            aria-label="Accent theme"
                        >
                            <button
                                v-for="option in accentThemes"
                                :key="option.value"
                                type="button"
                                class="group flex flex-col overflow-hidden rounded-2xl border transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-primary-400/70"
                                :class="[
                                    brandTheme === option.value
                                        ? 'border-primary-400 bg-primary-500/10 shadow-[0_24px_40px_-28px_color-mix(in_srgb,var(--p-primary-600)_45%,transparent)]'
                                        : 'border-surface-200 bg-surface-0 hover:border-primary-300/60 hover:bg-primary-500/5',
                                ]"
                                :aria-pressed="brandTheme === option.value"
                                @click="selectBrandTheme(option.value)"
                            >
                                <span
                                    class="h-12 w-full"
                                    :style="{
                                        background: `linear-gradient(135deg, ${option.preview.primary}, ${option.preview.secondary})`,
                                    }"
                                ></span>
                                <div
                                    class="flex flex-col gap-1 px-3 pb-3 pt-2 text-left"
                                >
                                    <span
                                        class="text-sm font-semibold text-color"
                                    >
                                        {{ option.label }}
                                    </span>
                                    <span class="text-xs text-muted-color">
                                        {{ option.description }}
                                    </span>
                                </div>
                            </button>
                        </div>
                    </div>

                    <div
                        class="flex flex-col gap-2 border-t border-surface-100 pt-4"
                    >
                        <div
                            class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between"
                        >
                            <span class="text-sm text-muted-color"
                                >Products default layout</span
                            >
                            <PvSelectButton
                                :model-value="defaultProductView"
                                :options="productViewOptions"
                                option-label="label"
                                option-value="value"
                                aria-label="Select default products layout"
                                @update:model-value="updateDefaultProductView"
                            />
                        </div>
                        <p class="text-xs text-muted-color">
                            Your choice controls how the products page opens
                            until you change it again.
                        </p>
                    </div>
                </div>
            </template>
        </PvCard>

        <PvCard
            id="settings-notifications"
            class="border border-surface-200 bg-surface-0"
        >
            <template #header>
                <div class="flex items-center justify-between">
                    <div>
                        <h2 class="text-xl font-semibold text-color">
                            Notification routing
                        </h2>
                        <p class="text-sm text-muted-color">
                            Tune alert channels that keep your team informed
                            about pricing activity.
                        </p>
                    </div>
                    <i class="pi pi-bell text-2xl text-primary"></i>
                </div>
            </template>
            <template #content>
                <NotificationPreferencesPanel />
            </template>
        </PvCard>

        <PvCard
            id="settings-tags"
            class="border border-surface-200 bg-surface-0"
        >
            <template #header>
                <div class="flex items-center justify-between">
                    <div>
                        <h2 class="text-xl font-semibold text-color">
                            Tag governance
                        </h2>
                        <p class="text-sm text-muted-color">
                            Keep your catalog tidy by managing tag names,
                            merges, and cleanup workflows.
                        </p>
                    </div>
                    <i class="pi pi-tags text-2xl text-primary"></i>
                </div>
            </template>
            <template #content>
                <TagManagementPanel />
            </template>
        </PvCard>
    </section>
</template>
