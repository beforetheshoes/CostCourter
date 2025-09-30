<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { useStoresStore, type StoreRecord } from '../stores/useStoresStore'

const storesStore = useStoresStore()
const { items, loading, error } = storeToRefs(storesStore)

const createSubmitting = ref(false)
const editSubmitting = ref(false)
const deleteSubmitting = ref(false)
const createError = ref<string | null>(null)
const editError = ref<string | null>(null)
const deleteError = ref<string | null>(null)
const selectedStoreId = ref<number | null>(null)

const defaultSelector = () => ({ type: 'css', value: '' })

const createForm = reactive({
    name: '',
    slug: '',
    website_url: '',
    locale: '',
    currency: '',
    notes: '',
    domains: '',
    title: defaultSelector(),
    price: defaultSelector(),
    image: defaultSelector(),
})

const editForm = reactive({
    name: '',
    slug: '',
    website_url: '',
    locale: '',
    currency: '',
    notes: '',
    domains: '',
    active: true,
    title: defaultSelector(),
    price: defaultSelector(),
    image: defaultSelector(),
})

const selectedStore = computed<StoreRecord | null>(
    () =>
        items.value.find((store) => store.id === selectedStoreId.value) ?? null,
)

const parseDomains = (input: string) =>
    input
        .split(/[\n,]+/)
        .map((value) => value.trim())
        .filter(Boolean)

const normalizeLocale = (value: string) => value.trim() || null
const normalizeCurrency = (value: string) =>
    value.trim() ? value.trim().toUpperCase() : null

const buildStrategy = (source: {
    title: { type: string; value: string }
    price: { type: string; value: string }
    image: { type: string; value: string }
}) => {
    const strategy: Record<
        string,
        { type: string; value: string; data: null }
    > = {}
    Object.entries(source).forEach(([key, data]) => {
        const selectorValue = data.value.trim()
        if (!selectorValue) return
        const selectorType = data.type.trim() || 'css'
        strategy[key] = {
            type: selectorType,
            value: selectorValue,
            data: null,
        }
    })
    return strategy
}

const resetCreateForm = () => {
    createForm.name = ''
    createForm.slug = ''
    createForm.website_url = ''
    createForm.locale = ''
    createForm.currency = ''
    createForm.notes = ''
    createForm.domains = ''
    createForm.title = { ...defaultSelector() }
    createForm.price = { ...defaultSelector() }
    createForm.image = { ...defaultSelector() }
}

const resetEditForm = () => {
    editForm.name = ''
    editForm.slug = ''
    editForm.website_url = ''
    editForm.locale = ''
    editForm.currency = ''
    editForm.notes = ''
    editForm.domains = ''
    editForm.active = true
    editForm.title = { ...defaultSelector() }
    editForm.price = { ...defaultSelector() }
    editForm.image = { ...defaultSelector() }
}

watch(
    selectedStore,
    (store) => {
        deleteError.value = null
        if (!store) {
            resetEditForm()
            return
        }
        editForm.name = store.name
        editForm.slug = store.slug
        editForm.website_url = store.website_url ?? ''
        editForm.locale = store.locale ?? ''
        editForm.currency = store.currency ?? ''
        editForm.notes = store.notes ?? ''
        editForm.domains = store.domains.map((entry) => entry.domain).join('\n')
        editForm.active = store.active
        const strategy = store.scrape_strategy ?? {}
        editForm.title = {
            type: strategy.title?.type ?? 'css',
            value: strategy.title?.value ?? '',
        }
        editForm.price = {
            type: strategy.price?.type ?? 'css',
            value: strategy.price?.value ?? '',
        }
        editForm.image = {
            type: strategy.image?.type ?? 'css',
            value: strategy.image?.value ?? '',
        }
    },
    { immediate: true },
)

const submitCreate = async () => {
    if (createSubmitting.value) return
    createError.value = null
    const domainList = parseDomains(createForm.domains)
    if (domainList.length === 0) {
        createError.value = 'Add at least one domain'
        return
    }
    const strategy = buildStrategy({
        title: createForm.title,
        price: createForm.price,
        image: createForm.image,
    })

    createSubmitting.value = true
    try {
        await storesStore.create({
            name: createForm.name.trim(),
            slug: createForm.slug.trim(),
            website_url: createForm.website_url.trim() || null,
            active: true,
            domains: domainList.map((domain) => ({ domain })),
            scrape_strategy: strategy,
            locale: normalizeLocale(createForm.locale) || undefined,
            currency: normalizeCurrency(createForm.currency) || undefined,
            notes: createForm.notes.trim() || undefined,
        })
        resetCreateForm()
        if (!items.value.length) {
            await storesStore.list()
        }
    } catch (error) {
        if (error instanceof Error) {
            createError.value = error.message
        }
    } finally {
        createSubmitting.value = false
    }
}

const submitUpdate = async () => {
    if (!selectedStore.value || editSubmitting.value) return
    editError.value = null
    const domainList = parseDomains(editForm.domains)
    if (domainList.length === 0) {
        editError.value = 'Add at least one domain'
        return
    }
    const strategy = buildStrategy({
        title: editForm.title,
        price: editForm.price,
        image: editForm.image,
    })

    editSubmitting.value = true
    try {
        await storesStore.update(selectedStore.value.id, {
            name: editForm.name.trim() || undefined,
            slug: editForm.slug.trim() || undefined,
            website_url: editForm.website_url.trim() || null,
            active: editForm.active,
            domains: domainList.map((domain) => ({ domain })),
            scrape_strategy: strategy,
            locale: normalizeLocale(editForm.locale) || undefined,
            currency: normalizeCurrency(editForm.currency) || undefined,
            notes: editForm.notes.trim() || undefined,
        })
    } catch (error) {
        if (error instanceof Error) {
            editError.value = error.message
        }
    } finally {
        editSubmitting.value = false
    }
}

const selectStore = (id: number) => {
    selectedStoreId.value = id
}

const cancelEdit = () => {
    selectedStoreId.value = null
}

const removeStore = async () => {
    if (!selectedStore.value || deleteSubmitting.value) return
    if (
        !window.confirm(
            'Delete this store? All associated metadata will be removed.',
        )
    ) {
        return
    }
    deleteError.value = null
    deleteSubmitting.value = true
    try {
        await storesStore.remove(selectedStore.value.id)
        selectedStoreId.value = null
    } catch (error) {
        if (error instanceof Error) {
            deleteError.value = error.message
        } else {
            deleteError.value = 'Failed to delete store'
        }
    } finally {
        deleteSubmitting.value = false
    }
}

onMounted(() => {
    if (!items.value.length) {
        void storesStore.list()
    }
})
</script>

<template>
    <section class="page-section flex flex-col gap-6 max-w-5xl w-full mx-auto">
        <header class="flex flex-col gap-2 text-center">
            <h1 class="text-3xl font-semibold text-color">Stores</h1>
            <p class="text-muted-color">
                Manage store metadata, domains, and scrape selectors across the
                catalog.
            </p>
        </header>

        <PvCard class="border border-surface-200 bg-surface-50">
            <template #header>
                <div class="flex items-center justify-between">
                    <div>
                        <h2 class="text-xl font-semibold text-color">
                            New Store
                        </h2>
                        <p class="text-sm text-muted-color">
                            Configure domains, locale, and selectors before
                            tracking URLs.
                        </p>
                    </div>
                    <i class="pi pi-store text-2xl text-primary"></i>
                </div>
            </template>
            <template #content>
                <form
                    class="flex flex-col gap-4"
                    @submit.prevent="submitCreate"
                >
                    <div class="grid md:grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm mb-2">Name</label>
                            <PvInputText v-model="createForm.name" required />
                        </div>
                        <div>
                            <label class="block text-sm mb-2">Slug</label>
                            <PvInputText v-model="createForm.slug" required />
                        </div>
                    </div>
                    <div class="grid md:grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm mb-2"
                                >Website URL</label
                            >
                            <PvInputText v-model="createForm.website_url" />
                        </div>
                        <div class="grid grid-cols-2 gap-4">
                            <div>
                                <label class="block text-sm mb-2">Locale</label>
                                <PvInputText
                                    v-model="createForm.locale"
                                    placeholder="en_US"
                                />
                            </div>
                            <div>
                                <label class="block text-sm mb-2"
                                    >Currency</label
                                >
                                <PvInputText
                                    v-model="createForm.currency"
                                    placeholder="USD"
                                />
                            </div>
                        </div>
                    </div>
                    <div>
                        <label class="block text-sm mb-2"
                            >Domains (one per line)</label
                        >
                        <textarea
                            v-model="createForm.domains"
                            rows="3"
                            class="w-full p-3 border rounded-border"
                            placeholder="example.com\nwww.example.com"
                        />
                    </div>
                    <div class="grid md:grid-cols-3 gap-4">
                        <div>
                            <label class="block text-sm mb-2"
                                >Title Selector</label
                            >
                            <div class="flex gap-2">
                                <PvInputText
                                    v-model="createForm.title.type"
                                    class="w-24"
                                    placeholder="css"
                                />
                                <PvInputText
                                    v-model="createForm.title.value"
                                    class="flex-1"
                                    placeholder=".product-title"
                                />
                            </div>
                        </div>
                        <div>
                            <label class="block text-sm mb-2"
                                >Price Selector</label
                            >
                            <div class="flex gap-2">
                                <PvInputText
                                    v-model="createForm.price.type"
                                    class="w-24"
                                    placeholder="json"
                                />
                                <PvInputText
                                    v-model="createForm.price.value"
                                    class="flex-1"
                                    placeholder="$.price"
                                />
                            </div>
                        </div>
                        <div>
                            <label class="block text-sm mb-2"
                                >Image Selector</label
                            >
                            <div class="flex gap-2">
                                <PvInputText
                                    v-model="createForm.image.type"
                                    class="w-24"
                                    placeholder="attr"
                                />
                                <PvInputText
                                    v-model="createForm.image.value"
                                    class="flex-1"
                                    placeholder="img::src"
                                />
                            </div>
                        </div>
                    </div>
                    <div>
                        <label class="block text-sm mb-2">Notes</label>
                        <textarea
                            v-model="createForm.notes"
                            rows="2"
                            class="w-full p-3 border rounded-border"
                            placeholder="Optional operator notes"
                        />
                    </div>
                    <div class="flex gap-3 items-center">
                        <PvButton
                            type="submit"
                            label="Create Store"
                            icon="pi pi-save"
                            :loading="createSubmitting"
                        />
                        <PvButton
                            type="button"
                            text
                            label="Reset"
                            icon="pi pi-undo"
                            @click="resetCreateForm"
                        />
                        <span v-if="createError" class="text-sm text-red-500">
                            {{ createError }}
                        </span>
                    </div>
                    <p v-if="error" class="text-sm text-red-500">
                        {{ error }}
                    </p>
                </form>
            </template>
        </PvCard>

        <PvCard class="border border-surface-200 bg-surface-50">
            <template #header>
                <div class="flex items-center justify-between">
                    <div>
                        <h2 class="text-xl font-semibold text-color">
                            Existing Stores
                        </h2>
                        <p class="text-sm text-muted-color">
                            Click edit to adjust selectors, domains, or status.
                        </p>
                    </div>
                    <i class="pi pi-list text-2xl text-primary"></i>
                </div>
            </template>
            <template #content>
                <div v-if="loading" class="py-6 text-center text-muted-color">
                    <i class="pi pi-spin pi-spinner mr-2"></i>
                    Loading stores…
                </div>
                <div
                    v-else-if="items.length === 0"
                    class="py-6 text-center text-muted-color"
                >
                    No stores created yet.
                </div>
                <div v-else class="overflow-x-auto">
                    <table
                        class="min-w-full divide-y divide-surface-200 text-left text-sm"
                    >
                        <thead
                            class="bg-surface-100 text-muted-color uppercase"
                        >
                            <tr>
                                <th class="px-4 py-3">Name</th>
                                <th class="px-4 py-3">Domains</th>
                                <th class="px-4 py-3">Locale</th>
                                <th class="px-4 py-3">Currency</th>
                                <th class="px-4 py-3">Active</th>
                                <th class="px-4 py-3">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-surface-200">
                            <tr
                                v-for="store in items"
                                :key="store.id"
                                :class="{
                                    'bg-primary-50':
                                        store.id === selectedStoreId,
                                }"
                            >
                                <td class="px-4 py-3">
                                    <div class="font-medium text-color">
                                        {{ store.name }}
                                    </div>
                                    <div class="text-xs text-muted-color">
                                        {{ store.slug }}
                                    </div>
                                </td>
                                <td class="px-4 py-3 text-muted-color">
                                    {{
                                        store.domains
                                            .map((entry) => entry.domain)
                                            .join(', ')
                                    }}
                                </td>
                                <td class="px-4 py-3 text-muted-color">
                                    {{ store.locale ?? '—' }}
                                </td>
                                <td class="px-4 py-3 text-muted-color">
                                    {{ store.currency ?? '—' }}
                                </td>
                                <td class="px-4 py-3 text-muted-color">
                                    {{ store.active ? 'Yes' : 'No' }}
                                </td>
                                <td class="px-4 py-3">
                                    <PvButton
                                        size="small"
                                        icon="pi pi-pencil"
                                        label="Edit"
                                        outlined
                                        @click="selectStore(store.id)"
                                    />
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </template>
        </PvCard>

        <PvCard
            v-if="selectedStore"
            class="border border-surface-200 bg-surface-50"
        >
            <template #header>
                <div class="flex items-center justify-between">
                    <div>
                        <h2 class="text-xl font-semibold text-color">
                            Edit Store
                        </h2>
                        <p class="text-sm text-muted-color">
                            Update selectors, locale, or deactivate the store.
                        </p>
                    </div>
                    <i class="pi pi-pencil text-2xl text-primary"></i>
                </div>
            </template>
            <template #content>
                <form
                    class="flex flex-col gap-4"
                    @submit.prevent="submitUpdate"
                >
                    <div class="grid md:grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm mb-2">Name</label>
                            <PvInputText v-model="editForm.name" required />
                        </div>
                        <div>
                            <label class="block text-sm mb-2">Slug</label>
                            <PvInputText v-model="editForm.slug" required />
                        </div>
                    </div>
                    <div class="grid md:grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm mb-2"
                                >Website URL</label
                            >
                            <PvInputText v-model="editForm.website_url" />
                        </div>
                        <div class="grid grid-cols-2 gap-4 items-center">
                            <div>
                                <label class="block text-sm mb-2">Locale</label>
                                <PvInputText v-model="editForm.locale" />
                            </div>
                            <div>
                                <label class="block text-sm mb-2"
                                    >Currency</label
                                >
                                <PvInputText v-model="editForm.currency" />
                            </div>
                        </div>
                    </div>
                    <div>
                        <label class="block text-sm mb-2"
                            >Domains (one per line)</label
                        >
                        <textarea
                            v-model="editForm.domains"
                            rows="3"
                            class="w-full p-3 border rounded-border"
                        />
                    </div>
                    <div class="grid md:grid-cols-3 gap-4">
                        <div>
                            <label class="block text-sm mb-2"
                                >Title Selector</label
                            >
                            <div class="flex gap-2">
                                <PvInputText
                                    v-model="editForm.title.type"
                                    class="w-24"
                                />
                                <PvInputText
                                    v-model="editForm.title.value"
                                    class="flex-1"
                                />
                            </div>
                        </div>
                        <div>
                            <label class="block text-sm mb-2"
                                >Price Selector</label
                            >
                            <div class="flex gap-2">
                                <PvInputText
                                    v-model="editForm.price.type"
                                    class="w-24"
                                />
                                <PvInputText
                                    v-model="editForm.price.value"
                                    class="flex-1"
                                />
                            </div>
                        </div>
                        <div>
                            <label class="block text-sm mb-2"
                                >Image Selector</label
                            >
                            <div class="flex gap-2">
                                <PvInputText
                                    v-model="editForm.image.type"
                                    class="w-24"
                                />
                                <PvInputText
                                    v-model="editForm.image.value"
                                    class="flex-1"
                                />
                            </div>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <input v-model="editForm.active" type="checkbox" />
                        <span class="text-sm text-muted-color">Active</span>
                    </div>
                    <div>
                        <label class="block text-sm mb-2">Notes</label>
                        <textarea
                            v-model="editForm.notes"
                            rows="2"
                            class="w-full p-3 border rounded-border"
                        />
                    </div>
                    <div class="flex gap-3 items-center">
                        <PvButton
                            type="submit"
                            label="Save Changes"
                            icon="pi pi-save"
                            :loading="editSubmitting"
                        />
                        <PvButton
                            type="button"
                            severity="danger"
                            icon="pi pi-trash"
                            label="Delete"
                            :loading="deleteSubmitting"
                            outlined
                            @click="removeStore"
                        />
                        <PvButton
                            type="button"
                            text
                            label="Close"
                            icon="pi pi-times"
                            @click="cancelEdit"
                        />
                        <span v-if="editError" class="text-sm text-red-500">
                            {{ editError }}
                        </span>
                        <span v-if="deleteError" class="text-sm text-red-500">
                            {{ deleteError }}
                        </span>
                    </div>
                </form>
            </template>
        </PvCard>
    </section>
</template>
