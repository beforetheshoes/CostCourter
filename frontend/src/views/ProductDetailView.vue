<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import type { MenuMethods } from 'primevue/menu'
import type { MenuItem } from 'primevue/menuitem'

import SparklineChart from '../components/SparklineChart.vue'
import ProductHistoryChart from '../components/ProductHistoryChart.vue'
import {
    useProductsStore,
    type Product,
    type ProductURL,
} from '../stores/useProductsStore'
import { usePriceHistoryStore } from '../stores/usePriceHistoryStore'
import { usePricingStore } from '../stores/usePricingStore'
import { useTagsStore } from '../stores/useTagsStore'

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
const refreshingMetadataId = ref<number | null>(null)
const metadataMessage = ref<string | null>(null)
const newUrlForm = ref({ url: '', setPrimary: false })
const addUrlError = ref<string | null>(null)
const addingUrl = ref(false)

const tagsStore = useTagsStore()
const {
    items: availableTags,
    loading: tagsLoading,
    error: tagsStoreError,
} = storeToRefs(tagsStore)

const editingTitle = ref(false)
const titleDraft = ref('')
const savingTitle = ref(false)
const titleError = ref<string | null>(null)

const selectedTagIds = ref<number[]>([])
const tagsDirty = ref(false)
const tagsSaving = ref(false)
const tagsUpdateError = ref<string | null>(null)

const newTagName = ref('')
const creatingTag = ref(false)
const newTagError = ref<string | null>(null)

const slugify = (value: string) =>
    value
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')

const resolveTagSlug = (name: string) => {
    const normalized = slugify(name)
    if (normalized) return normalized
    const fallback = slugify(`${name}-tag`)
    return fallback || `tag-${Date.now()}`
}

const resetTitleDraft = () => {
    titleDraft.value = product.value?.name ?? ''
}

const resetTagSelection = () => {
    if (product.value) {
        selectedTagIds.value = product.value.tags.map((tag) => tag.id)
    } else {
        selectedTagIds.value = []
    }
    tagsDirty.value = false
}

const startTitleEdit = () => {
    editingTitle.value = true
    titleError.value = null
    resetTitleDraft()
}

const cancelTitleEdit = () => {
    editingTitle.value = false
    titleError.value = null
    resetTitleDraft()
}

const saveTitle = async () => {
    if (!product.value || savingTitle.value) return
    const trimmed = titleDraft.value.trim()
    if (!trimmed) {
        titleError.value = 'Title is required.'
        return
    }
    if (trimmed === product.value.name) {
        editingTitle.value = false
        titleError.value = null
        return
    }

    savingTitle.value = true
    titleError.value = null
    try {
        const updated = await productsStore.update(product.value.id, {
            name: trimmed,
        })
        product.value = updated
        editingTitle.value = false
    } catch (err) {
        titleError.value =
            err instanceof Error
                ? err.message
                : 'Failed to update product title.'
    } finally {
        savingTitle.value = false
    }
}

const resolveTagSlugById = (id: number) => {
    const fromAvailable = availableTags.value.find((tag) => tag.id === id)
    if (fromAvailable?.slug) return fromAvailable.slug
    const fromProduct = product.value?.tags.find((tag) => tag.id === id)
    return fromProduct?.slug ?? null
}

const handleTagSelection = (value: number[]) => {
    selectedTagIds.value = value
    tagsDirty.value = true
    tagsUpdateError.value = null
}

const applySelectedTags = async () => {
    if (!product.value || tagsSaving.value || !tagsDirty.value) return

    const tagSlugs = selectedTagIds.value
        .map((id) => resolveTagSlugById(id))
        .filter((slug): slug is string => Boolean(slug))

    if (tagSlugs.length !== selectedTagIds.value.length) {
        tagsUpdateError.value =
            'Unable to determine slugs for one or more selected tags.'
        return
    }

    tagsSaving.value = true
    tagsUpdateError.value = null
    try {
        const updated = await productsStore.update(product.value.id, {
            tag_slugs: tagSlugs,
        })
        tagsDirty.value = false
        product.value = updated
    } catch (err) {
        tagsUpdateError.value =
            err instanceof Error ? err.message : 'Failed to update tags.'
    } finally {
        tagsSaving.value = false
    }
}

const createAndAssignTag = async () => {
    if (!product.value || creatingTag.value || tagsSaving.value) return
    const name = newTagName.value.trim()
    if (!name) {
        newTagError.value = 'Tag name is required.'
        return
    }

    creatingTag.value = true
    newTagError.value = null
    try {
        const slug = resolveTagSlug(name)
        const created = await tagsStore.create({ name, slug })
        const nextSelection = Array.from(
            new Set([...selectedTagIds.value, created.id]),
        )
        handleTagSelection(nextSelection)
        await applySelectedTags()
        newTagName.value = ''
    } catch (err) {
        newTagError.value =
            err instanceof Error ? err.message : 'Failed to create tag.'
    } finally {
        creatingTag.value = false
    }
}

const urlActionMenuRefs = new Map<number, MenuMethods>()

const setUrlActionMenuRef = (entryId: number, instance: MenuMethods | null) => {
    if (instance) {
        urlActionMenuRefs.set(entryId, instance)
    } else {
        urlActionMenuRefs.delete(entryId)
    }
}

const isUrlActionBusy = (entry: ProductURL) =>
    refreshingMetadataId.value === entry.id ||
    updatingUrlId.value === entry.id ||
    promotingUrlId.value === entry.id ||
    deletingUrlId.value === entry.id

const openUrlActionMenu = (event: MouseEvent, entry: ProductURL) => {
    const menu = urlActionMenuRefs.get(entry.id)
    menu?.toggle(event)
}

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
        metadataMessage.value = null
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

onMounted(() => {
    if (availableTags.value.length === 0) {
        void tagsStore.list()
    }
})

watch(
    () => product.value,
    () => {
        if (!editingTitle.value) {
            resetTitleDraft()
        }
        resetTagSelection()
    },
    { immediate: true },
)

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
    if (currency) {
        try {
            return new Intl.NumberFormat(undefined, {
                style: 'currency',
                currency,
            }).format(value)
        } catch (err) {
            console.error('Failed to format price', err)
        }
    }
    return value.toFixed(2)
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

const refreshUrlMetadata = async (entry: ProductURL) => {
    if (!product.value || refreshingMetadataId.value === entry.id) {
        return
    }

    metadataMessage.value = null
    try {
        refreshingMetadataId.value = entry.id
        const result = await productsStore.refreshUrlMetadata(
            product.value.id,
            entry.id,
        )
        product.value = result.product

        const updatedFields: string[] = []
        if (result.name_updated) updatedFields.push('title')
        if (result.image_updated) updatedFields.push('image')

        let message =
            updatedFields.length > 0
                ? `Updated ${updatedFields.join(' and ')} from source metadata.`
                : 'Checked source metadata; no changes detected.'
        if (result.warnings.length) {
            message = `${message} ${result.warnings.join(' ')}`
        }
        metadataMessage.value = message.trim()
    } catch (err) {
        metadataMessage.value =
            err instanceof Error ? err.message : 'Failed to refresh metadata.'
    } finally {
        refreshingMetadataId.value = null
    }
}

const getUrlActionItems = (entry: ProductURL): MenuItem[] => [
    {
        label:
            refreshingMetadataId.value === entry.id
                ? 'Refreshing metadata…'
                : 'Refresh metadata',
        icon: 'pi pi-image',
        disabled: refreshingMetadataId.value === entry.id,
        command: () => {
            void refreshUrlMetadata(entry)
        },
    },
    {
        label: 'Set Primary URL',
        icon: 'pi pi-star',
        disabled: entry.is_primary || promotingUrlId.value === entry.id,
        command: () => {
            void setPrimaryUrl(entry)
        },
    },
    {
        label:
            updatingUrlId.value === entry.id
                ? 'Updating status…'
                : entry.active
                  ? 'Deactivate'
                  : 'Activate',
        icon: entry.active ? 'pi pi-stop' : 'pi pi-play',
        disabled: updatingUrlId.value === entry.id,
        command: () => {
            void toggleUrlActive(entry)
        },
    },
    {
        label: deletingUrlId.value === entry.id ? 'Deleting…' : 'Delete',
        icon: 'pi pi-trash',
        disabled: deletingUrlId.value === entry.id,
        command: () => {
            void deleteTrackedUrl(entry)
        },
        class: 'text-red-500',
    },
]

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
        <header class="space-y-4">
            <button
                type="button"
                class="text-sm text-muted-color hover:text-primary flex items-center gap-2"
                @click="close"
            >
                <i class="pi pi-arrow-left"></i>
                Back to products
            </button>
            <div
                class="flex flex-col gap-6 rounded-border border border-surface-200 bg-surface-0 p-6 md:flex-row md:items-start md:gap-8"
            >
                <div
                    class="h-32 w-32 flex-shrink-0 overflow-hidden rounded-border bg-surface-100 flex items-center justify-center"
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
                <div class="flex-1 space-y-6">
                    <div class="space-y-3">
                        <div class="flex flex-wrap items-start gap-3">
                            <div class="flex-1 min-w-[16rem]">
                                <template v-if="editingTitle">
                                    <PvInputText
                                        v-model="titleDraft"
                                        class="w-full"
                                        placeholder="Product title"
                                        :disabled="savingTitle"
                                        @keyup.enter.prevent="saveTitle"
                                    />
                                </template>
                                <template v-else>
                                    <h1
                                        class="text-3xl font-semibold text-color break-words"
                                    >
                                        {{ product.name }}
                                    </h1>
                                </template>
                                <p
                                    v-if="titleError"
                                    class="mt-2 text-sm text-red-600"
                                >
                                    {{ titleError }}
                                </p>
                            </div>
                            <div class="flex flex-wrap items-center gap-2">
                                <template v-if="editingTitle">
                                    <PvButton
                                        size="small"
                                        icon="pi pi-check"
                                        label="Save title"
                                        :loading="savingTitle"
                                        @click="saveTitle"
                                    />
                                    <PvButton
                                        size="small"
                                        severity="secondary"
                                        icon="pi pi-times"
                                        label="Cancel"
                                        :disabled="savingTitle"
                                        @click="cancelTitleEdit"
                                    />
                                </template>
                                <template v-else>
                                    <PvButton
                                        size="small"
                                        severity="secondary"
                                        icon="pi pi-pencil"
                                        label="Edit title"
                                        @click="startTitleEdit"
                                    />
                                </template>
                            </div>
                        </div>
                    </div>
                    <div class="space-y-3">
                        <div class="flex items-center justify-between">
                            <span
                                class="text-xs font-semibold uppercase tracking-wide text-muted-color"
                            >
                                Tags
                            </span>
                            <span v-if="tagsDirty" class="text-xs text-primary">
                                Unsaved changes
                            </span>
                        </div>
                        <div class="flex flex-col gap-3">
                            <div
                                class="flex flex-col gap-2 md:flex-row md:items-center md:gap-3"
                            >
                                <PvMultiSelect
                                    :model-value="selectedTagIds"
                                    :options="availableTags"
                                    option-label="name"
                                    option-value="id"
                                    display="chip"
                                    filter
                                    placeholder="Select tags"
                                    class="w-full md:max-w-sm"
                                    :loading="tagsLoading"
                                    :disabled="tagsLoading"
                                    @update:model-value="handleTagSelection"
                                />
                                <div class="flex items-center gap-2">
                                    <PvButton
                                        size="small"
                                        icon="pi pi-check"
                                        label="Apply tags"
                                        :loading="tagsSaving"
                                        :disabled="!tagsDirty || tagsSaving"
                                        @click="applySelectedTags"
                                    />
                                    <PvButton
                                        v-if="tagsDirty"
                                        size="small"
                                        icon="pi pi-undo"
                                        label="Reset"
                                        severity="secondary"
                                        :disabled="tagsSaving"
                                        @click="resetTagSelection"
                                    />
                                </div>
                            </div>
                            <div
                                class="flex flex-col gap-2 md:flex-row md:items-center md:gap-3"
                            >
                                <PvInputText
                                    v-model="newTagName"
                                    class="w-full md:max-w-sm"
                                    placeholder="Create and assign new tag"
                                    :disabled="creatingTag"
                                    @keyup.enter.prevent="createAndAssignTag"
                                />
                                <PvButton
                                    size="small"
                                    icon="pi pi-plus"
                                    label="Add tag"
                                    :loading="creatingTag"
                                    :disabled="creatingTag || tagsSaving"
                                    @click="createAndAssignTag"
                                />
                            </div>
                        </div>
                        <p v-if="tagsStoreError" class="text-sm text-red-600">
                            {{ tagsStoreError }}
                        </p>
                        <p v-if="tagsUpdateError" class="text-sm text-red-600">
                            {{ tagsUpdateError }}
                        </p>
                        <p v-if="newTagError" class="text-sm text-red-600">
                            {{ newTagError }}
                        </p>
                    </div>
                </div>
                <div
                    class="flex flex-col items-end justify-between gap-4 md:w-52"
                >
                    <div
                        class="flex flex-col items-end gap-2 text-right text-sm"
                    >
                        <div
                            class="flex items-center gap-2"
                            :class="trendMeta.tone"
                        >
                            <i :class="trendMeta.icon"></i>
                            <span>{{ trendMeta.label }}</span>
                        </div>
                        <div class="text-muted-color">
                            Last refresh:
                            <strong class="text-color">{{
                                formatTimestamp(lastRefreshed)
                            }}</strong>
                        </div>
                    </div>
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
                    <p v-if="metadataMessage" class="text-sm text-muted-color">
                        {{ metadataMessage }}
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
                                <td class="px-4 py-3 text-color align-middle">
                                    {{ entry.store?.name ?? '—' }}
                                </td>
                                <td class="px-4 py-3 align-middle">
                                    <a
                                        :href="entry.url"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        class="text-primary hover:underline break-words whitespace-break-spaces block max-w-[20rem]"
                                    >
                                        {{ entry.url }}
                                    </a>
                                </td>
                                <td
                                    class="px-4 py-3 text-muted-color align-middle"
                                >
                                    {{
                                        formatPrice(
                                            entry.latest_price ?? null,
                                            entry.store?.currency ?? null,
                                        )
                                    }}
                                </td>
                                <td
                                    class="px-4 py-3 text-muted-color align-middle"
                                >
                                    {{
                                        formatTimestamp(
                                            entry.latest_price_at ?? null,
                                        )
                                    }}
                                </td>
                                <td
                                    class="px-4 py-3 text-muted-color align-middle"
                                >
                                    {{ entry.is_primary ? 'Yes' : 'No' }}
                                </td>
                                <td
                                    class="px-4 py-3 text-muted-color align-middle"
                                >
                                    {{ entry.active ? 'Yes' : 'No' }}
                                </td>
                                <td class="px-4 py-3 align-middle">
                                    <div class="flex justify-end">
                                        <PvMenu
                                            :ref="
                                                (instance) =>
                                                    setUrlActionMenuRef(
                                                        entry.id,
                                                        instance,
                                                    )
                                            "
                                            popup
                                            :model="getUrlActionItems(entry)"
                                        />
                                        <PvButton
                                            size="small"
                                            severity="secondary"
                                            label="Actions"
                                            icon="pi pi-ellipsis-v"
                                            :loading="isUrlActionBusy(entry)"
                                            class="ml-2"
                                            @click="
                                                (event) =>
                                                    openUrlActionMenu(
                                                        event,
                                                        entry,
                                                    )
                                            "
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
