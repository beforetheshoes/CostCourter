<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

import {
    useSearchStore,
    type BulkImportRequestItem,
    type BulkImportResponse,
    type QuickAddResult,
} from '../stores/useSearchStore'

const searchStore = useSearchStore()

const form = reactive({
    query: '',
    forceRefresh: false,
    pages: 1,
})

const hasSearched = ref(false)

type QuickAddStatus =
    | { state: 'idle' }
    | { state: 'loading' }
    | { state: 'success'; result: QuickAddResult }
    | { state: 'error'; message: string }

const quickAddStatuses = reactive<Record<string, QuickAddStatus>>({})

type BulkImportState = 'idle' | 'loading' | 'success' | 'error'

const selectedUrls = ref<string[]>([])
const primaryUrl = ref<string | null>(null)
const bulkForm = reactive({
    productId: '',
    enqueueRefresh: false,
})
const bulkStatus = reactive<{
    state: BulkImportState
    message: string
    summary: BulkImportResponse | null
}>({
    state: 'idle',
    message: '',
    summary: null,
})

const enginesSummary = computed(() => {
    const raw = searchStore.extra?.engines
    if (!raw || typeof raw !== 'object')
        return [] as Array<{ name: string; count: number }>
    return Object.entries(raw)
        .filter(
            (entry): entry is [string, number] => typeof entry[1] === 'number',
        )
        .map(([name, count]) => ({ name, count }))
})

const cacheDescription = computed(() => {
    if (searchStore.cacheHit === null) return null
    const expiresAt = searchStore.expiresAt
    if (expiresAt) {
        const value = new Date(expiresAt)
        if (!Number.isNaN(value.getTime())) {
            const formatted = new Intl.DateTimeFormat(undefined, {
                dateStyle: 'short',
                timeStyle: 'short',
            }).format(value)
            if (searchStore.cacheHit) {
                return `Served from cache — expires ${formatted}`
            }
            return `Fetched fresh — cached until ${formatted}`
        }
    }
    return searchStore.cacheHit
        ? 'Served from cache.'
        : 'Fetched fresh from SearXNG.'
})

const isSearchDisabled = computed(
    () => !form.query.trim() || searchStore.loading,
)

const clampPages = (value: number) =>
    Math.min(Math.max(Number.isFinite(value) ? value : 1, 1), 10)

const resetStatusesForResults = () => {
    const nextStatuses: Record<string, QuickAddStatus> = {}
    for (const result of searchStore.results) {
        const existing = quickAddStatuses[result.url]
        nextStatuses[result.url] =
            existing?.state === 'success' ? existing : { state: 'idle' }
    }
    for (const key of Object.keys(quickAddStatuses)) {
        if (!(key in nextStatuses)) {
            delete quickAddStatuses[key]
        }
    }
    Object.assign(quickAddStatuses, nextStatuses)
    syncSelectionWithResults()
}

const handleSearch = async () => {
    hasSearched.value = false
    const trimmed = form.query.trim()
    const pageCount = clampPages(form.pages)
    form.pages = pageCount
    await searchStore.search(trimmed, {
        forceRefresh: form.forceRefresh,
        pages: pageCount,
    })
    if (!trimmed) {
        form.forceRefresh = false
        hasSearched.value = false
        return
    }
    resetStatusesForResults()
    hasSearched.value = true
}

const quickAdd = async (url: string) => {
    quickAddStatuses[url] = { state: 'loading' }
    try {
        const result = await searchStore.quickAdd(url)
        quickAddStatuses[url] = { state: 'success', result }
    } catch (error) {
        const message =
            error instanceof Error ? error.message : 'Failed to quick-add URL'
        quickAddStatuses[url] = { state: 'error', message }
    }
}

const clearSearch = () => {
    form.query = ''
    form.forceRefresh = false
    form.pages = 1
    searchStore.reset()
    hasSearched.value = false
    Object.keys(quickAddStatuses).forEach((key) => delete quickAddStatuses[key])
    clearSelection()
    bulkStatus.state = 'idle'
    bulkStatus.message = ''
    bulkStatus.summary = null
    bulkForm.productId = ''
    bulkForm.enqueueRefresh = false
}

const isSelected = (url: string) => selectedUrls.value.includes(url)

const toggleSelection = (url: string) => {
    if (isSelected(url)) {
        selectedUrls.value = selectedUrls.value.filter((entry) => entry !== url)
    } else {
        selectedUrls.value = [...selectedUrls.value, url]
    }
    if (primaryUrl.value && !selectedUrls.value.includes(primaryUrl.value)) {
        primaryUrl.value = selectedUrls.value[0] ?? null
    }
    if (!primaryUrl.value) {
        primaryUrl.value = selectedUrls.value[0] ?? null
    }
}

const setPrimary = (url: string) => {
    primaryUrl.value = url
    if (!isSelected(url)) {
        selectedUrls.value = [...selectedUrls.value, url]
    }
}

const clearSelection = () => {
    selectedUrls.value = []
    primaryUrl.value = null
}

const selectedCount = computed(() => selectedUrls.value.length)
const canBulkImport = computed(
    () => selectedCount.value > 0 && bulkStatus.state !== 'loading',
)

const syncSelectionWithResults = () => {
    if (!searchStore.results.length) {
        clearSelection()
        return
    }
    const available = new Set(searchStore.results.map((result) => result.url))
    selectedUrls.value = selectedUrls.value.filter((url) => available.has(url))
    if (primaryUrl.value && !available.has(primaryUrl.value)) {
        primaryUrl.value = selectedUrls.value[0] ?? null
    }
}

const handleBulkImport = async () => {
    if (!selectedUrls.value.length) return
    bulkStatus.state = 'loading'
    bulkStatus.message = ''
    bulkStatus.summary = null

    const items: BulkImportRequestItem[] = selectedUrls.value.map((url) => ({
        url,
        set_primary: primaryUrl.value === url,
    }))
    if (!items.some((item) => item.set_primary)) {
        items[0].set_primary = true
    }

    const options: {
        productId?: number
        searchQuery?: string
        enqueueRefresh?: boolean
    } = {
        searchQuery: form.query,
        enqueueRefresh: bulkForm.enqueueRefresh,
    }

    const productIdValue =
        typeof bulkForm.productId === 'string'
            ? bulkForm.productId
            : String(bulkForm.productId ?? '')
    if (productIdValue.trim()) {
        const parsed = Number.parseInt(productIdValue, 10)
        if (!Number.isNaN(parsed) && parsed > 0) {
            options.productId = parsed
        }
    }

    try {
        const summary = await searchStore.bulkImport(items, options)
        bulkStatus.state = 'success'
        bulkStatus.summary = summary
        bulkStatus.message = summary.created_product
            ? `Created product #${summary.product_id}`
            : `Updated product #${summary.product_id}`
        if (summary.created_product) {
            bulkForm.productId = ''
        } else {
            bulkForm.productId = String(summary.product_id)
        }
        clearSelection()
    } catch (error) {
        const message =
            error instanceof Error
                ? error.message
                : 'Failed to bulk import selected URLs'
        bulkStatus.state = 'error'
        bulkStatus.message = message
    } finally {
        if (bulkStatus.state !== 'loading' && !selectedUrls.value.length) {
            primaryUrl.value = null
        }
    }
}

watch(selectedUrls, (urls) => {
    if (primaryUrl.value && !urls.includes(primaryUrl.value)) {
        primaryUrl.value = urls[0] ?? null
    }
})
</script>

<template>
    <section class="page-section flex flex-col gap-6 max-w-5xl w-full mx-auto">
        <header class="flex flex-col gap-2 text-center">
            <h1 class="text-3xl font-semibold text-color">
                Search &amp; Import
            </h1>
            <p class="text-muted-color">
                Query your SearXNG instance, review results, and quick-add
                promising product URLs with one click.
            </p>
        </header>

        <PvCard class="border border-surface-200 bg-surface-50">
            <template #header>
                <div class="flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <h2 class="text-xl font-semibold text-color">Search</h2>
                        <p class="text-sm text-muted-color">
                            Searches go through FastAPI which caches responses
                            for quicker lookups.
                        </p>
                    </div>
                    <i class="pi pi-search text-2xl text-primary"></i>
                </div>
            </template>
            <template #content>
                <form
                    class="flex flex-col gap-4"
                    @submit.prevent="handleSearch"
                >
                    <div
                        class="grid gap-3 md:grid-cols-[1fr_auto_auto] items-center"
                    >
                        <PvInputText
                            v-model="form.query"
                            class="w-full"
                            placeholder="Search products…"
                        />
                        <label class="flex items-center gap-2 text-sm">
                            <input
                                v-model="form.forceRefresh"
                                type="checkbox"
                                class="accent-primary"
                            />
                            <span>Force refresh</span>
                        </label>
                        <label class="flex items-center gap-2 text-sm">
                            <span>Pages</span>
                            <input
                                v-model.number="form.pages"
                                type="number"
                                min="1"
                                max="10"
                                class="w-20 border rounded-border px-2 py-1"
                            />
                        </label>
                    </div>
                    <div class="flex gap-3">
                        <PvButton
                            type="submit"
                            :disabled="isSearchDisabled"
                            :loading="searchStore.loading"
                            label="Search"
                            icon="pi pi-arrow-right"
                        />
                        <PvButton
                            type="button"
                            text
                            label="Clear"
                            icon="pi pi-undo"
                            @click="clearSearch"
                        />
                    </div>
                    <p v-if="searchStore.error" class="text-sm text-red-500">
                        {{ searchStore.error }}
                    </p>
                    <p
                        v-else-if="cacheDescription"
                        class="text-sm text-muted-color"
                    >
                        {{ cacheDescription }}
                    </p>
                    <div
                        v-if="enginesSummary.length"
                        class="flex flex-wrap gap-2 text-xs text-muted-color"
                    >
                        <span
                            v-for="engine in enginesSummary"
                            :key="engine.name"
                            class="px-2 py-1 bg-surface-100 rounded-border"
                        >
                            {{ engine.name }} • {{ engine.count }}
                        </span>
                    </div>
                </form>
            </template>
        </PvCard>

        <PvCard class="border border-surface-200 bg-surface-50">
            <template #header>
                <div class="flex items-center justify-between">
                    <div>
                        <h2 class="text-xl font-semibold text-color">
                            Results
                        </h2>
                        <p class="text-sm text-muted-color">
                            Quick-add any result to create the product, store,
                            and URL records automatically.
                        </p>
                    </div>
                    <i class="pi pi-list text-2xl text-primary"></i>
                </div>
            </template>
            <template #content>
                <div
                    v-if="searchStore.loading"
                    class="py-6 text-center text-muted-color"
                >
                    <i class="pi pi-spin pi-spinner mr-2"></i>
                    Searching…
                </div>
                <div
                    v-else-if="hasSearched && searchStore.results.length === 0"
                    class="py-6 text-center text-muted-color"
                >
                    No results yet. Try adjusting your keywords or forcing a
                    refresh.
                </div>
                <ul v-else class="flex flex-col gap-4">
                    <li
                        v-if="selectedCount"
                        class="border border-surface-200 rounded-border p-4 bg-surface-100 flex flex-col gap-3"
                    >
                        <div
                            class="flex flex-wrap items-center justify-between gap-3"
                        >
                            <div class="text-sm text-muted-color">
                                {{ selectedCount }} URL(s) selected
                            </div>
                            <div class="flex flex-wrap gap-3 items-center">
                                <label
                                    class="flex items-center gap-2 text-xs md:text-sm"
                                >
                                    <span>Existing product ID</span>
                                    <input
                                        v-model="bulkForm.productId"
                                        type="number"
                                        min="1"
                                        class="w-28 border rounded-border px-2 py-1"
                                    />
                                </label>
                                <label
                                    class="flex items-center gap-2 text-xs md:text-sm"
                                >
                                    <input
                                        v-model="bulkForm.enqueueRefresh"
                                        type="checkbox"
                                        class="accent-primary"
                                    />
                                    <span>Queue refresh</span>
                                </label>
                                <PvButton
                                    label="Bulk import"
                                    icon="pi pi-cloud-upload"
                                    :disabled="!canBulkImport"
                                    :loading="bulkStatus.state === 'loading'"
                                    @click="handleBulkImport"
                                />
                                <PvButton
                                    type="button"
                                    text
                                    label="Clear selection"
                                    icon="pi pi-times"
                                    @click="clearSelection"
                                />
                            </div>
                        </div>
                    </li>
                    <li
                        v-if="bulkStatus.state !== 'idle'"
                        class="border border-surface-200 rounded-border p-4 bg-surface-50 text-xs md:text-sm"
                        :class="{
                            'text-emerald-600 border-emerald-200':
                                bulkStatus.state === 'success',
                            'text-red-500 border-red-200':
                                bulkStatus.state === 'error',
                        }"
                    >
                        <template
                            v-if="
                                bulkStatus.state === 'success' &&
                                bulkStatus.summary
                            "
                        >
                            {{ bulkStatus.message }} — added
                            {{ bulkStatus.summary.created_urls.length }} URL(s)
                            <template v-if="bulkStatus.summary.skipped.length">
                                (skipped
                                {{ bulkStatus.summary.skipped.length }}
                                due to
                                {{
                                    bulkStatus.summary.skipped
                                        .map((item) => item.reason)
                                        .join(', ')
                                }})
                            </template>
                        </template>
                        <template v-else>
                            {{ bulkStatus.message }}
                        </template>
                    </li>
                    <li
                        v-for="result in searchStore.results"
                        :key="result.url"
                        class="border border-surface-200 rounded-border p-4 flex flex-col gap-3"
                    >
                        <div class="flex flex-col gap-1">
                            <div class="flex items-start justify-between gap-3">
                                <div class="flex items-start gap-3">
                                    <label class="mt-1">
                                        <input
                                            type="checkbox"
                                            class="accent-primary"
                                            :checked="isSelected(result.url)"
                                            :aria-label="`Select ${result.title || result.url}`"
                                            @change="
                                                toggleSelection(result.url)
                                            "
                                        />
                                    </label>
                                    <div>
                                        <a
                                            :href="result.url"
                                            target="_blank"
                                            rel="noreferrer"
                                            class="text-lg font-semibold text-primary hover:underline"
                                        >
                                            {{ result.title || result.url }}
                                        </a>
                                        <div class="text-xs text-muted-color">
                                            {{ result.domain || 'unknown' }}
                                            <span v-if="result.engine">
                                                • {{ result.engine }}
                                            </span>
                                            <span
                                                v-if="
                                                    typeof result.score ===
                                                    'number'
                                                "
                                            >
                                                • score
                                                {{ result.score.toFixed(2) }}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                                <PvButton
                                    label="Quick add"
                                    icon="pi pi-plus"
                                    :loading="
                                        quickAddStatuses[result.url]?.state ===
                                        'loading'
                                    "
                                    :disabled="
                                        quickAddStatuses[result.url]?.state ===
                                        'loading'
                                    "
                                    @click="quickAdd(result.url)"
                                />
                            </div>
                            <p
                                v-if="result.snippet"
                                class="text-sm text-muted-color"
                            >
                                {{ result.snippet }}
                            </p>
                            <p
                                v-if="result.store_name"
                                class="text-xs text-emerald-600 font-medium"
                            >
                                Matches existing store: {{ result.store_name }}
                            </p>
                            <label
                                v-if="isSelected(result.url)"
                                class="flex items-center gap-2 text-xs text-muted-color"
                            >
                                <input
                                    type="radio"
                                    name="primary-selection"
                                    class="accent-primary"
                                    :value="result.url"
                                    :checked="primaryUrl === result.url"
                                    :aria-label="`Mark ${result.title || result.url} as primary`"
                                    @change="setPrimary(result.url)"
                                />
                                <span>Mark as primary</span>
                            </label>
                        </div>
                        <div v-if="result.thumbnail" class="w-full">
                            <img
                                :src="result.thumbnail"
                                alt="thumbnail"
                                class="w-32 h-32 object-cover rounded-border border"
                            />
                        </div>
                        <div
                            v-if="
                                quickAddStatuses[result.url]?.state ===
                                'success'
                            "
                            class="text-sm text-emerald-600"
                        >
                            Added product #{{
                                quickAddStatuses[result.url]?.result?.product_id
                            }}
                            (URL #{{
                                quickAddStatuses[result.url]?.result
                                    ?.product_url_id
                            }}) for store #{{
                                quickAddStatuses[result.url]?.result?.store_id
                            }}.
                            <ul
                                v-if="
                                    quickAddStatuses[result.url]?.result
                                        ?.warnings?.length
                                "
                                class="mt-1 text-xs text-amber-600 list-disc list-inside"
                            >
                                <li
                                    v-for="warning in quickAddStatuses[
                                        result.url
                                    ]?.result?.warnings"
                                    :key="warning"
                                >
                                    {{ warning }}
                                </li>
                            </ul>
                        </div>
                        <div
                            v-else-if="
                                quickAddStatuses[result.url]?.state === 'error'
                            "
                            class="text-sm text-red-500"
                        >
                            {{ quickAddStatuses[result.url]?.message }}
                        </div>
                    </li>
                </ul>
            </template>
        </PvCard>
    </section>
</template>
