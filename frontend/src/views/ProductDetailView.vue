<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import SparklineChart from '../components/SparklineChart.vue'
import ProductHistoryChart from '../components/ProductHistoryChart.vue'
import {
    useProductsStore,
    type Product,
    type ProductURL,
} from '../stores/useProductsStore'
import { usePriceHistoryStore } from '../stores/usePriceHistoryStore'
import { usePricingStore } from '../stores/usePricingStore'

const route = useRoute()
const router = useRouter()

const productsStore = useProductsStore()
const pricingStore = usePricingStore()
const historyStore = usePriceHistoryStore()

const product = ref<Product | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const refreshingProduct = ref(false)
const updatingUrlId = ref<number | null>(null)
const promotingUrlId = ref<number | null>(null)
const deletingUrlId = ref<number | null>(null)
const newUrlForm = ref({ url: '', setPrimary: false })
const addUrlError = ref<string | null>(null)
const addingUrl = ref(false)

const productId = computed(() => Number(route.params.id))

const mergeProductUrls = (urls: ProductURL[], updated: ProductURL) => {
    const others = urls.filter((entry) => entry.id !== updated.id)
    const demoted = updated.is_primary
        ? others.map((entry) => ({ ...entry, is_primary: false }))
        : others
    return [...demoted, updated]
}

const fetchProduct = async () => {
    const id = productId.value
    if (!Number.isFinite(id)) {
        error.value = 'Invalid product id'
        return
    }
    loading.value = true
    error.value = null
    try {
        const result = await productsStore.fetch(id)
        product.value = result
        if (result) {
            await historyStore.loadForProduct(result.id)
        }
    } catch (err) {
        error.value =
            err instanceof Error ? err.message : 'Unable to load product'
    } finally {
        loading.value = false
    }
}

onMounted(() => {
    void fetchProduct()
})

watch(
    () => route.params.id,
    () => {
        void fetchProduct()
    },
)

const priceHistoryEntries = computed(() => historyStore.entries)

const historyRows = computed(() => historyStore.entries.slice(0, 20))

const formatTimestamp = (value: string | null | undefined) => {
    if (!value) return '—'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) {
        return value
    }
    return date.toLocaleString()
}

const formatPrice = (
    value: number | null | undefined,
    currency: string | null,
) => {
    if (value == null) return '—'
    const formatted = value.toFixed(2)
    return currency ? `${currency} ${formatted}` : formatted
}

const selectedUrls = computed(() => product.value?.urls ?? [])

const currentTrend = computed(() => product.value?.price_trend ?? 'none')

const trendMeta = computed(() => {
    switch (currentTrend.value) {
        case 'up':
            return {
                icon: 'pi pi-arrow-up-right',
                label: 'Rising',
                tone: 'text-red-500',
            }
        case 'down':
            return {
                icon: 'pi pi-arrow-down-left',
                label: 'Falling',
                tone: 'text-green-500',
            }
        case 'lowest':
            return {
                icon: 'pi pi-star',
                label: 'Lowest',
                tone: 'text-green-600',
            }
        default:
            return {
                icon: 'pi pi-minus',
                label: 'Stable',
                tone: 'text-muted-color',
            }
    }
})

const refreshProduct = async () => {
    if (!product.value || refreshingProduct.value) return
    try {
        refreshingProduct.value = true
        await pricingStore.refreshProduct(product.value.id)
        await fetchProduct()
    } catch (err) {
        console.error(err)
    } finally {
        refreshingProduct.value = false
    }
}

const toggleUrlActive = async (entry: ProductURL) => {
    if (!product.value) return
    try {
        updatingUrlId.value = entry.id
        const updated = await productsStore.updateUrl(
            product.value.id,
            entry.id,
            {
                active: !entry.active,
            },
        )
        if (product.value) {
            product.value = {
                ...product.value,
                urls: mergeProductUrls(product.value.urls, updated),
            }
        }
    } catch (err) {
        console.error(err)
    } finally {
        updatingUrlId.value = null
    }
}

const setPrimaryUrl = async (entry: ProductURL) => {
    if (!product.value || entry.is_primary) return
    try {
        promotingUrlId.value = entry.id
        const updated = await productsStore.updateUrl(
            product.value.id,
            entry.id,
            {
                is_primary: true,
            },
        )
        if (product.value) {
            product.value = {
                ...product.value,
                urls: mergeProductUrls(product.value.urls, updated),
            }
        }
    } catch (err) {
        console.error(err)
    } finally {
        promotingUrlId.value = null
    }
}

const deleteTrackedUrl = async (entry: ProductURL) => {
    if (!product.value) return
    const confirmed = window.confirm(
        'Deleting this URL removes its price history. Continue?',
    )
    if (!confirmed) {
        return
    }

    try {
        deletingUrlId.value = entry.id
        await productsStore.deleteUrl(product.value.id, entry.id)
        await fetchProduct()
    } catch (err) {
        console.error(err)
    } finally {
        deletingUrlId.value = null
    }
}

const addTrackedUrl = async () => {
    if (!product.value || addingUrl.value) return
    const trimmed = newUrlForm.value.url.trim()
    if (!trimmed) {
        addUrlError.value = 'URL is required to add a new entry.'
        return
    }

    addUrlError.value = null
    addingUrl.value = true
    try {
        await productsStore.quickAddUrlForProduct(product.value.id, trimmed, {
            setPrimary: newUrlForm.value.setPrimary,
        })
        newUrlForm.value = { url: '', setPrimary: false }
        await fetchProduct()
    } catch (err) {
        addUrlError.value =
            err instanceof Error ? err.message : 'Failed to add tracked URL.'
    } finally {
        addingUrl.value = false
    }
}

const close = () => {
    router.push({ name: 'products' }).catch(() => {})
}

const lastRefreshed = computed(() => product.value?.last_refreshed_at ?? null)

const summaryHistoryPoints = computed(() => {
    if (!product.value?.history_points) return []
    return product.value.history_points.map((point) => ({
        date: point.date,
        price: point.price,
    }))
})

const aggregates = computed(() => product.value?.price_aggregates ?? null)

const formatAggregate = (value: number | null | undefined) =>
    value == null ? '—' : value.toFixed(2)

const productInitial = computed(
    () => product.value?.name.trim().charAt(0).toUpperCase() ?? '#',
)
</script>

<template>
    <section
        v-if="product && !loading"
        class="page-section max-w-5xl mx-auto space-y-6"
    >
        <header class="flex flex-wrap items-start justify-between gap-6">
            <div class="flex flex-wrap items-start gap-6">
                <div
                    class="h-32 w-32 overflow-hidden rounded-border bg-surface-100 flex items-center justify-center"
                >
                    <img
                        v-if="product.image_url"
                        :src="product.image_url"
                        class="h-full w-full object-cover"
                        :alt="`${product.name} cover art`"
                    />
                    <div
                        v-else
                        class="flex h-full w-full items-center justify-center bg-surface-200 text-3xl font-semibold text-muted-color"
                        aria-hidden="true"
                    >
                        {{ productInitial }}
                    </div>
                </div>
                <div class="space-y-3">
                    <button
                        type="button"
                        class="text-sm text-muted-color hover:text-primary flex items-center gap-2"
                        @click="close"
                    >
                        <i class="pi pi-arrow-left"></i>
                        Back to products
                    </button>
                    <h1 class="text-3xl font-semibold text-color">
                        {{ product.name }}
                    </h1>
                    <div class="flex flex-wrap gap-2 text-xs">
                        <span
                            v-for="tag in product.tags"
                            :key="tag.id"
                            class="rounded-full bg-surface-200 px-3 py-1 text-muted-color"
                        >
                            {{ tag.name }}
                        </span>
                    </div>
                </div>
            </div>
            <div class="flex flex-col gap-3 text-right">
                <div
                    class="flex items-center gap-2 text-sm"
                    :class="trendMeta.tone"
                >
                    <i :class="trendMeta.icon"></i>
                    <span>{{ trendMeta.label }}</span>
                </div>
                <div class="text-sm text-muted-color">
                    Last refresh:
                    <strong class="text-color">{{
                        formatTimestamp(lastRefreshed)
                    }}</strong>
                </div>
                <div class="flex gap-2 justify-end">
                    <PvButton
                        icon="pi pi-refresh"
                        label="Refresh prices"
                        :loading="refreshingProduct"
                        @click="refreshProduct"
                    />
                </div>
            </div>
        </header>

        <section class="grid gap-4 md:grid-cols-2">
            <PvCard class="border border-surface-200 bg-surface-0">
                <template #header>
                    <div class="flex items-center justify-between">
                        <h2 class="text-lg font-semibold text-color">
                            Summary trend
                        </h2>
                        <span class="text-xs text-muted-color"
                            >Cached history overview</span
                        >
                    </div>
                </template>
                <template #content>
                    <div class="space-y-4">
                        <SparklineChart
                            :points="summaryHistoryPoints"
                            class="h-24"
                        />
                        <div
                            class="grid grid-cols-3 gap-2 text-sm text-muted-color"
                        >
                            <div>
                                <div class="text-xs uppercase">Min</div>
                                <div class="text-color">
                                    {{ formatAggregate(aggregates?.min) }}
                                </div>
                            </div>
                            <div>
                                <div class="text-xs uppercase">Avg</div>
                                <div class="text-color">
                                    {{ formatAggregate(aggregates?.avg) }}
                                </div>
                            </div>
                            <div>
                                <div class="text-xs uppercase">Max</div>
                                <div class="text-color">
                                    {{ formatAggregate(aggregates?.max) }}
                                </div>
                            </div>
                        </div>
                    </div>
                </template>
            </PvCard>
            <PvCard class="border border-surface-200 bg-surface-0">
                <template #header>
                    <h2 class="text-lg font-semibold text-color">
                        Historical trend
                    </h2>
                </template>
                <template #content>
                    <ProductHistoryChart
                        :entries="priceHistoryEntries"
                        :urls="selectedUrls"
                    />
                </template>
            </PvCard>
        </section>

        <PvCard class="border border-surface-200 bg-surface-0">
            <template #header>
                <div class="flex items-center justify-between">
                    <h2 class="text-lg font-semibold text-color">
                        Tracked URLs
                    </h2>
                    <span class="text-xs text-muted-color">
                        {{ selectedUrls.length }}
                        {{ selectedUrls.length === 1 ? 'entry' : 'entries' }}
                    </span>
                </div>
            </template>
            <template #content>
                <div class="mb-4 space-y-2">
                    <div class="flex flex-wrap items-center gap-3">
                        <PvInputText
                            v-model="newUrlForm.url"
                            placeholder="https://example.com/product"
                            class="flex-1 min-w-[16rem]"
                            :disabled="addingUrl"
                        />
                        <label
                            class="flex items-center gap-2 text-sm text-muted-color"
                        >
                            <PvCheckbox
                                v-model="newUrlForm.setPrimary"
                                :disabled="addingUrl"
                                binary
                            />
                            Make primary
                        </label>
                        <PvButton
                            label="Add URL"
                            icon="pi pi-link"
                            :loading="addingUrl"
                            @click="addTrackedUrl"
                        />
                    </div>
                    <p v-if="addUrlError" class="text-sm text-red-600">
                        {{ addUrlError }}
                    </p>
                </div>
                <div
                    v-if="selectedUrls.length === 0"
                    class="py-6 text-center text-muted-color"
                >
                    No tracked URLs yet.
                </div>
                <div v-else class="overflow-x-auto">
                    <table
                        class="min-w-full divide-y divide-surface-200 text-left text-sm"
                    >
                        <thead
                            class="bg-surface-100 text-muted-color uppercase"
                        >
                            <tr>
                                <th class="px-4 py-3">Store</th>
                                <th class="px-4 py-3">URL</th>
                                <th class="px-4 py-3">Latest price</th>
                                <th class="px-4 py-3">Last checked</th>
                                <th class="px-4 py-3">Primary</th>
                                <th class="px-4 py-3">Active</th>
                                <th class="px-4 py-3">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-surface-200">
                            <tr v-for="entry in selectedUrls" :key="entry.id">
                                <td class="px-4 py-3 text-color">
                                    <div>{{ entry.store?.name ?? '—' }}</div>
                                    <div class="text-xs text-muted-color">
                                        {{ entry.store?.slug ?? '—' }}
                                    </div>
                                </td>
                                <td class="px-4 py-3 align-top">
                                    <a
                                        :href="entry.url"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        class="text-primary hover:underline break-words whitespace-break-spaces block max-w-[20rem]"
                                    >
                                        {{ entry.url }}
                                    </a>
                                </td>
                                <td class="px-4 py-3 text-muted-color">
                                    {{
                                        formatPrice(
                                            entry.latest_price ?? null,
                                            entry.store?.currency ?? null,
                                        )
                                    }}
                                </td>
                                <td class="px-4 py-3 text-muted-color">
                                    {{
                                        formatTimestamp(
                                            entry.latest_price_at ?? null,
                                        )
                                    }}
                                </td>
                                <td class="px-4 py-3 text-muted-color">
                                    {{ entry.is_primary ? 'Yes' : 'No' }}
                                </td>
                                <td class="px-4 py-3 text-muted-color">
                                    {{ entry.active ? 'Yes' : 'No' }}
                                </td>
                                <td class="px-4 py-3">
                                    <div class="flex flex-wrap gap-2">
                                        <PvButton
                                            size="small"
                                            :severity="
                                                entry.active
                                                    ? 'secondary'
                                                    : 'success'
                                            "
                                            :loading="
                                                updatingUrlId === entry.id
                                            "
                                            :label="
                                                entry.active
                                                    ? 'Deactivate'
                                                    : 'Activate'
                                            "
                                            :icon="
                                                entry.active
                                                    ? 'pi pi-stop'
                                                    : 'pi pi-play'
                                            "
                                            @click="toggleUrlActive(entry)"
                                        />
                                        <PvButton
                                            size="small"
                                            severity="info"
                                            :disabled="entry.is_primary"
                                            :loading="
                                                promotingUrlId === entry.id
                                            "
                                            label="Make primary"
                                            icon="pi pi-star"
                                            @click="setPrimaryUrl(entry)"
                                        />
                                        <PvButton
                                            size="small"
                                            severity="danger"
                                            :loading="
                                                deletingUrlId === entry.id
                                            "
                                            label="Delete"
                                            icon="pi pi-trash"
                                            @click="deleteTrackedUrl(entry)"
                                        />
                                    </div>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </template>
        </PvCard>

        <PvCard class="border border-surface-200 bg-surface-0">
            <template #header>
                <h2 class="text-lg font-semibold text-color">
                    Price history entries
                </h2>
            </template>
            <template #content>
                <div
                    v-if="historyStore.loading"
                    class="py-6 text-center text-muted-color"
                >
                    <i class="pi pi-spin pi-spinner mr-2"></i>
                    Loading history…
                </div>
                <div
                    v-else-if="historyStore.error"
                    class="py-6 text-center text-red-500"
                >
                    {{ historyStore.error }}
                </div>
                <div
                    v-else-if="historyRows.length === 0"
                    class="py-6 text-center text-muted-color"
                >
                    No price history recorded yet.
                </div>
                <div v-else class="overflow-x-auto">
                    <table
                        class="min-w-full divide-y divide-surface-200 text-left text-sm"
                    >
                        <thead
                            class="bg-surface-100 text-muted-color uppercase"
                        >
                            <tr>
                                <th class="px-4 py-3">Recorded at</th>
                                <th class="px-4 py-3">Price</th>
                                <th class="px-4 py-3">Store</th>
                                <th class="px-4 py-3">URL</th>
                                <th class="px-4 py-3">Status</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-surface-200">
                            <tr v-for="entry in historyRows" :key="entry.id">
                                <td class="px-4 py-3 text-muted-color">
                                    {{ formatTimestamp(entry.recorded_at) }}
                                </td>
                                <td class="px-4 py-3 text-color">
                                    {{ entry.currency }}
                                    {{ entry.price.toFixed(2) }}
                                </td>
                                <td class="px-4 py-3 text-muted-color">
                                    {{ entry.product_url?.store?.name ?? '—' }}
                                </td>
                                <td class="px-4 py-3">
                                    <a
                                        v-if="entry.product_url?.url"
                                        :href="entry.product_url.url"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        class="text-primary hover:underline"
                                    >
                                        {{ entry.product_url.url }}
                                    </a>
                                    <span v-else class="text-muted-color"
                                        >—</span
                                    >
                                </td>
                                <td class="px-4 py-3 text-muted-color">
                                    {{
                                        entry.product_url_id
                                            ? 'Tracked URL'
                                            : 'Manual entry'
                                    }}
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </template>
        </PvCard>
    </section>
    <section v-else class="page-section max-w-3xl mx-auto">
        <PvCard class="bg-surface-0 border border-surface-200">
            <template #content>
                <div class="py-12 text-center space-y-3">
                    <div v-if="loading" class="text-muted-color">
                        <i class="pi pi-spin pi-spinner mr-2"></i>
                        Loading product…
                    </div>
                    <div v-else-if="error" class="text-red-500">
                        {{ error }}
                    </div>
                    <div v-else class="text-muted-color">
                        Product not found.
                    </div>
                    <PvButton
                        label="Back to products"
                        icon="pi pi-arrow-left"
                        @click="close"
                    />
                </div>
            </template>
        </PvCard>
    </section>
</template>
