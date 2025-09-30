<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import SparklineChart from '../components/SparklineChart.vue'
import { useProductsStore, type Product } from '../stores/useProductsStore'

const productsStore = useProductsStore()
const router = useRouter()

const VIEW_PREFERENCE_STORAGE_KEY = 'costcourter.products.defaultView'
const VIEW_PREFERENCE_EVENT = 'costcourter:products:viewPreference'

const resolveInitialViewMode = () => {
    const stored = localStorage.getItem(VIEW_PREFERENCE_STORAGE_KEY)
    return stored === 'table' ? 'table' : 'tiles'
}

const viewMode = ref<'tiles' | 'table'>(resolveInitialViewMode())
const searchTerm = ref('')

const createForm = reactive({
    url: '',
    name: '',
    slug: '',
    description: '',
    is_active: true,
    tags: '',
})
const creating = ref(false)
const createError = ref<string | null>(null)

const isQuickAddMode = computed(() => createForm.url.trim().length > 0)
const submitLabel = computed(() =>
    isQuickAddMode.value ? 'Quick add product' : 'Create product',
)
const submitIcon = computed(() =>
    isQuickAddMode.value ? 'pi pi-bolt' : 'pi pi-plus',
)

onMounted(() => {
    window.addEventListener(VIEW_PREFERENCE_EVENT, handleExternalViewPreference)
    if (!productsStore.items.length && !productsStore.loading) {
        void productsStore.list()
    }
})

onUnmounted(() => {
    window.removeEventListener(
        VIEW_PREFERENCE_EVENT,
        handleExternalViewPreference,
    )
})

const filteredProducts = computed(() => {
    const query = searchTerm.value.trim().toLowerCase()
    if (!query) {
        return productsStore.items
    }
    return productsStore.items.filter((product) =>
        [
            product.name,
            product.slug,
            ...(product.tags?.map((tag) => tag.name) ?? []),
        ]
            .join(' ')
            .toLowerCase()
            .includes(query),
    )
})

const broadcastViewPreference = (mode: 'tiles' | 'table') => {
    localStorage.setItem(VIEW_PREFERENCE_STORAGE_KEY, mode)
    window.dispatchEvent(
        new CustomEvent(VIEW_PREFERENCE_EVENT, { detail: mode }),
    )
}

const changeViewMode = (mode: 'tiles' | 'table') => {
    if (viewMode.value === mode) return
    viewMode.value = mode
    broadcastViewPreference(mode)
}

const handleExternalViewPreference: EventListener = (event) => {
    const detail = (event as CustomEvent<'tiles' | 'table'>).detail
    if (detail === 'tiles' || detail === 'table') {
        viewMode.value = detail
    }
}

const formatPrice = (product: Product) => {
    const latest = product.latest_price
    const price = latest?.price ?? product.current_price
    if (price == null) return '—'
    const currency = latest?.currency ?? product.price_aggregates?.currency
    const formatted = price.toFixed(2)
    return currency ? `${currency} ${formatted}` : formatted
}

const formatTimestamp = (value: string | null | undefined) => {
    if (!value) return '—'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) {
        return value
    }
    return date.toLocaleString()
}

const resolveHistoryPoints = (product: Product) =>
    product.history_points?.map((point) => ({
        date: point.date,
        price: point.price,
    })) ?? []

const navigateToDetail = (product: Product) => {
    router
        .push({ name: 'product-detail', params: { id: product.id } })
        .catch(() => {})
}

const productInitial = (product: Product) =>
    product.name.trim().charAt(0).toUpperCase() || '#'

const resetCreateForm = () => {
    createForm.url = ''
    createForm.name = ''
    createForm.slug = ''
    createForm.description = ''
    createForm.is_active = true
    createForm.tags = ''
    createError.value = null
}

const submitCreate = async () => {
    if (creating.value) return
    createError.value = null
    const url = createForm.url.trim()
    if (url) {
        creating.value = true
        try {
            const { product } = await productsStore.quickAdd(url)
            resetCreateForm()
            if (product) {
                navigateToDetail(product)
            }
        } catch (err) {
            createError.value =
                err instanceof Error
                    ? err.message
                    : 'Failed to quick add product.'
        } finally {
            creating.value = false
        }
        return
    }

    const name = createForm.name.trim()
    const slug = createForm.slug.trim()
    if (!name || !slug) {
        createError.value = 'Name and slug are required.'
        return
    }
    creating.value = true
    try {
        const tags = createForm.tags
            .split(',')
            .map((tag) => tag.trim())
            .filter(Boolean)
        const result = await productsStore.create({
            name,
            slug,
            description: createForm.description.trim() || null,
            is_active: createForm.is_active,
            tag_slugs: tags,
        })
        resetCreateForm()
        navigateToDetail(result)
    } catch (err) {
        createError.value =
            err instanceof Error ? err.message : 'Failed to create product.'
    } finally {
        creating.value = false
    }
}
</script>

<template>
    <section class="page-section max-w-6xl mx-auto space-y-8">
        <header class="flex flex-wrap items-center justify-between gap-4">
            <div>
                <h1 class="text-3xl font-semibold text-color">Products</h1>
                <p class="text-muted-color">
                    Browse every tracked product, switch layouts, and drill into
                    detailed pricing history.
                </p>
            </div>
            <div class="flex items-center gap-2">
                <PvInputText
                    v-model="searchTerm"
                    placeholder="Search products…"
                    class="w-64"
                />
                <PvButton
                    :severity="viewMode === 'tiles' ? 'primary' : 'secondary'"
                    icon="pi pi-th-large"
                    label="Tile view"
                    outlined
                    @click="changeViewMode('tiles')"
                />
                <PvButton
                    :severity="viewMode === 'table' ? 'primary' : 'secondary'"
                    icon="pi pi-table"
                    label="Table view"
                    outlined
                    @click="changeViewMode('table')"
                />
            </div>
        </header>

        <section
            class="rounded-border border border-surface-200 bg-surface-0 p-6 space-y-4"
        >
            <header class="space-y-1">
                <h2 class="text-xl font-semibold text-color">
                    Add a new product
                </h2>
                <p class="text-sm text-muted-color">
                    Provide a product URL to quick add it instantly, or leave
                    the URL blank and fill in the details to create a product
                    manually.
                </p>
            </header>
            <div
                v-if="createError"
                class="rounded-border border border-red-200 bg-red-50 p-3 text-sm text-red-600"
            >
                {{ createError }}
            </div>
            <div class="grid gap-4 md:grid-cols-2">
                <label class="flex flex-col gap-1 text-sm md:col-span-2">
                    <span class="text-muted-color"
                        >Product URL (quick add)</span
                    >
                    <PvInputText
                        v-model="createForm.url"
                        placeholder="https://example.com/product"
                        type="url"
                        inputmode="url"
                    />
                    <span class="text-xs text-muted-color">
                        When supplied, the system will scrape the product and
                        attach it automatically.
                    </span>
                </label>
                <label class="flex flex-col gap-1 text-sm">
                    <span class="text-muted-color">Name</span>
                    <PvInputText
                        v-model="createForm.name"
                        placeholder="Nintendo Switch"
                        :disabled="isQuickAddMode"
                    />
                </label>
                <label class="flex flex-col gap-1 text-sm">
                    <span class="text-muted-color">Slug</span>
                    <PvInputText
                        v-model="createForm.slug"
                        placeholder="nintendo-switch"
                        :disabled="isQuickAddMode"
                    />
                </label>
                <label class="flex flex-col gap-1 text-sm md:col-span-2">
                    <span class="text-muted-color">Description</span>
                    <PvInputTextarea
                        v-model="createForm.description"
                        rows="3"
                        auto-resize
                        placeholder="Optional summary to help team members"
                        :disabled="isQuickAddMode"
                    />
                </label>
                <label class="flex flex-col gap-1 text-sm">
                    <span class="text-muted-color">Tags (comma separated)</span>
                    <PvInputText
                        v-model="createForm.tags"
                        placeholder="consoles, gaming"
                        :disabled="isQuickAddMode"
                    />
                </label>
                <label class="flex items-center gap-2 text-sm">
                    <PvCheckbox
                        v-model="createForm.is_active"
                        binary
                        :disabled="isQuickAddMode"
                    />
                    <span class="text-muted-color"
                        >Active (manual create only)</span
                    >
                </label>
            </div>
            <div class="flex gap-3">
                <PvButton
                    :label="submitLabel"
                    :icon="submitIcon"
                    :loading="creating"
                    @click="submitCreate"
                />
                <PvButton
                    label="Reset"
                    severity="secondary"
                    outlined
                    @click="resetCreateForm"
                />
            </div>
        </section>

        <section
            v-if="productsStore.error"
            class="rounded-border border border-red-200 bg-red-50 p-4 text-red-600"
        >
            {{ productsStore.error }}
        </section>

        <section
            v-if="productsStore.loading"
            class="text-center text-muted-color py-10"
        >
            <i class="pi pi-spin pi-spinner mr-2"></i>
            Loading products…
        </section>

        <section v-else>
            <div
                v-if="filteredProducts.length === 0"
                class="py-10 text-center text-muted-color"
            >
                No products found. Use the form above to add one.
            </div>
            <div
                v-else-if="viewMode === 'tiles'"
                class="grid gap-3 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5"
            >
                <PvCard
                    v-for="product in filteredProducts"
                    :key="product.id"
                    class="product-card product-card--compact cursor-pointer transition-shadow hover:shadow-lg"
                    @click="navigateToDetail(product)"
                >
                    <template #header>
                        <div class="flex items-start justify-between">
                            <div class="min-w-0">
                                <h2
                                    class="truncate-2 text-base font-semibold text-color"
                                >
                                    {{ product.name }}
                                </h2>
                            </div>
                            <span
                                class="rounded-full px-2.5 py-0.5 text-[11px]"
                                :class="
                                    product.is_active
                                        ? 'bg-green-100 text-green-700'
                                        : 'bg-surface-200 text-muted-color'
                                "
                            >
                                {{ product.is_active ? 'Active' : 'Inactive' }}
                            </span>
                        </div>
                    </template>
                    <template #content>
                        <div class="space-y-2">
                            <div
                                class="h-20 w-full overflow-hidden rounded-border bg-surface-100 flex items-center justify-center"
                            >
                                <img
                                    v-if="product.image_url"
                                    :src="product.image_url"
                                    class="h-full w-full object-cover"
                                    :alt="`${product.name} cover art`"
                                />
                                <div
                                    v-else
                                    class="flex h-full w-full items-center justify-center bg-surface-200 text-xl font-semibold text-muted-color"
                                    aria-hidden="true"
                                >
                                    {{ productInitial(product) }}
                                </div>
                            </div>
                            <div class="text-lg font-semibold text-color">
                                {{ formatPrice(product) }}
                            </div>
                            <SparklineChart
                                :points="resolveHistoryPoints(product)"
                                class="h-12"
                            />
                            <div class="text-[11px] text-muted-color">
                                Last refresh:
                                {{
                                    formatTimestamp(
                                        product.last_refreshed_at ?? null,
                                    )
                                }}
                            </div>
                            <div class="flex flex-wrap gap-1.5 text-[11px]">
                                <span
                                    v-for="tag in product.tags"
                                    :key="tag.id"
                                    class="rounded-full bg-surface-200 px-2 py-0.5 text-muted-color"
                                >
                                    {{ tag.name }}
                                </span>
                            </div>
                        </div>
                    </template>
                </PvCard>
            </div>
            <div v-else class="overflow-x-auto">
                <table
                    class="min-w-full divide-y divide-surface-200 text-left text-sm"
                >
                    <thead class="bg-surface-100 text-muted-color uppercase">
                        <tr>
                            <th class="px-4 py-3">Product</th>
                            <th class="px-4 py-3">Price</th>
                            <th class="px-4 py-3">Last refreshed</th>
                            <th class="px-4 py-3">Tags</th>
                            <th class="px-4 py-3">Status</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-surface-200">
                        <tr
                            v-for="product in filteredProducts"
                            :key="product.id"
                            class="hover:bg-surface-50 cursor-pointer"
                            @click="navigateToDetail(product)"
                        >
                            <td class="px-4 py-3 text-color">
                                <div class="flex items-center gap-3">
                                    <div
                                        class="h-12 w-12 overflow-hidden rounded-border bg-surface-100 flex items-center justify-center"
                                    >
                                        <img
                                            v-if="product.image_url"
                                            :src="product.image_url"
                                            class="h-full w-full object-cover"
                                            :alt="`${product.name} thumbnail`"
                                        />
                                        <div
                                            v-else
                                            class="flex h-full w-full items-center justify-center bg-surface-200 text-lg font-semibold text-muted-color"
                                            aria-hidden="true"
                                        >
                                            {{ productInitial(product) }}
                                        </div>
                                    </div>
                                    <div class="min-w-0 flex-1">
                                        <span
                                            class="block truncate-2 font-semibold text-color"
                                        >
                                            {{ product.name }}
                                        </span>
                                    </div>
                                </div>
                            </td>
                            <td class="px-4 py-3 text-muted-color">
                                {{ formatPrice(product) }}
                            </td>
                            <td class="px-4 py-3 text-muted-color">
                                {{
                                    formatTimestamp(
                                        product.last_refreshed_at ?? null,
                                    )
                                }}
                            </td>
                            <td class="px-4 py-3 text-muted-color">
                                <span v-if="product.tags.length === 0">—</span>
                                <span v-else>
                                    {{
                                        product.tags
                                            .map((tag) => tag.name)
                                            .join(', ')
                                    }}
                                </span>
                            </td>
                            <td class="px-4 py-3">
                                <span
                                    class="rounded-full px-3 py-1 text-xs"
                                    :class="
                                        product.is_active
                                            ? 'bg-green-100 text-green-700'
                                            : 'bg-surface-200 text-muted-color'
                                    "
                                >
                                    {{
                                        product.is_active
                                            ? 'Active'
                                            : 'Inactive'
                                    }}
                                </span>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </section>
    </section>
</template>
