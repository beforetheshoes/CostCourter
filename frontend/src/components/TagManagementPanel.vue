<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { storeToRefs } from 'pinia'

import { useTagsStore, type TagRecord } from '../stores/useTagsStore'

const tagsStore = useTagsStore()
const { items, loading, error } = storeToRefs(tagsStore)

const createForm = reactive({
    name: '',
    slug: '',
})
const createSubmitting = ref(false)
const createError = ref<string | null>(null)

const editingId = ref<number | null>(null)
const editForm = reactive({
    name: '',
    slug: '',
})
const editSubmitting = ref(false)
const editError = ref<string | null>(null)
const deletingId = ref<number | null>(null)

const mergeForm = reactive({
    source: null as number | null,
    target: null as number | null,
    deleteSource: true,
})
const mergeSubmitting = ref(false)
const mergeError = ref<string | null>(null)
const mergeFeedback = ref<string | null>(null)
let mergeFeedbackTimeout: number | undefined

const slugify = (value: string) =>
    value
        .normalize('NFKD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '')

const resolveSlug = (name: string, slug: string) => {
    const normalized = slug.trim() || slugify(name)
    return normalized || slugify(`${name}-tag`)
}

const sortedTags = computed(() =>
    [...items.value].sort((a, b) => a.name.localeCompare(b.name)),
)

const hasTags = computed(() => sortedTags.value.length > 0)
const mergeTargets = computed(() =>
    mergeForm.source === null
        ? sortedTags.value
        : sortedTags.value.filter((tag) => tag.id !== mergeForm.source),
)
const canSubmitMerge = computed(
    () =>
        mergeForm.source !== null &&
        mergeForm.target !== null &&
        mergeForm.source !== mergeForm.target,
)

const resetCreateForm = () => {
    createForm.name = ''
    createForm.slug = ''
    createError.value = null
}

const startEdit = (tag: TagRecord) => {
    editingId.value = tag.id
    editForm.name = tag.name
    editForm.slug = tag.slug
    editError.value = null
}

const cancelEdit = () => {
    editingId.value = null
    editForm.name = ''
    editForm.slug = ''
    editError.value = null
}

const submitCreate = async () => {
    if (createSubmitting.value) return
    const name = createForm.name.trim()
    const slug = resolveSlug(name, createForm.slug)
    if (!name) {
        createError.value = 'Name is required'
        return
    }
    if (!slug) {
        createError.value = 'Slug is required'
        return
    }

    createSubmitting.value = true
    createError.value = null
    try {
        await tagsStore.create({ name, slug })
        resetCreateForm()
    } catch (err) {
        createError.value =
            err instanceof Error ? err.message : 'Failed to create tag'
    } finally {
        createSubmitting.value = false
    }
}

const submitEdit = async () => {
    if (editingId.value === null || editSubmitting.value) return
    const name = editForm.name.trim()
    const slug = resolveSlug(name, editForm.slug)
    if (!name) {
        editError.value = 'Name is required'
        return
    }
    if (!slug) {
        editError.value = 'Slug is required'
        return
    }

    editSubmitting.value = true
    editError.value = null
    try {
        await tagsStore.update(editingId.value, { name, slug })
        cancelEdit()
    } catch (err) {
        editError.value =
            err instanceof Error ? err.message : 'Failed to update tag'
    } finally {
        editSubmitting.value = false
    }
}

const removeTag = async (tag: TagRecord) => {
    if (deletingId.value !== null) return
    if (!window.confirm(`Delete “${tag.name}” tag? This cannot be undone.`)) {
        return
    }
    deletingId.value = tag.id
    try {
        await tagsStore.remove(tag.id)
    } catch (err) {
        tagsStore.error =
            err instanceof Error ? err.message : 'Failed to delete tag'
    } finally {
        deletingId.value = null
    }
}

const submitMerge = async () => {
    if (mergeSubmitting.value || !canSubmitMerge.value) return
    mergeSubmitting.value = true
    mergeError.value = null
    try {
        const result = await tagsStore.merge({
            source_tag_id: mergeForm.source as number,
            target_tag_id: mergeForm.target as number,
            delete_source: mergeForm.deleteSource,
        })
        mergeFeedback.value = result.deleted_source
            ? 'Merged tags and removed the source tag.'
            : 'Merged tags successfully.'
        if (mergeFeedbackTimeout) {
            window.clearTimeout(mergeFeedbackTimeout)
        }
        mergeFeedbackTimeout = window.setTimeout(() => {
            mergeFeedback.value = null
        }, 4000)
        mergeForm.source = null
        mergeForm.target = null
    } catch (err) {
        mergeError.value =
            err instanceof Error ? err.message : 'Failed to merge tags'
    } finally {
        mergeSubmitting.value = false
    }
}

onMounted(() => {
    void tagsStore.list()
})
</script>

<template>
    <section class="space-y-8">
        <header class="space-y-1">
            <h2 class="text-xl font-semibold text-color">Tag management</h2>
            <p class="text-sm text-muted-color">
                Create, rename, merge, or remove tags used across product
                tracking.
            </p>
        </header>

        <form
            class="rounded-border border border-surface-200 bg-surface-0 p-4 space-y-3 shadow-sm"
        >
            <div class="grid gap-3 md:grid-cols-3">
                <label class="text-sm flex flex-col gap-1">
                    <span class="text-muted-color">Name</span>
                    <PvInputText
                        v-model="createForm.name"
                        placeholder="Black Friday"
                    />
                </label>
                <label class="text-sm flex flex-col gap-1">
                    <span class="text-muted-color">Slug</span>
                    <PvInputText
                        v-model="createForm.slug"
                        placeholder="black-friday"
                    />
                </label>
                <div class="flex items-end">
                    <PvButton
                        label="Create tag"
                        icon="pi pi-plus"
                        :loading="createSubmitting"
                        @click.prevent="submitCreate"
                    />
                </div>
            </div>
            <p v-if="createError" class="text-sm text-red-500">
                {{ createError }}
            </p>
        </form>

        <section
            class="rounded-border border border-surface-200 bg-surface-0 shadow-sm"
        >
            <header
                class="flex items-center justify-between border-b border-surface-200 px-4 py-3"
            >
                <div>
                    <h3
                        class="text-sm font-semibold text-color uppercase tracking-wide"
                    >
                        Existing tags
                    </h3>
                    <p class="text-xs text-muted-color">
                        {{ sortedTags.length }} total
                    </p>
                </div>
            </header>
            <div v-if="loading" class="p-6 text-center text-muted-color">
                <i class="pi pi-spin pi-spinner mr-2"></i>
                Loading tags…
            </div>
            <div v-else-if="error" class="p-6 text-center text-red-500">
                {{ error }}
            </div>
            <div v-else-if="!hasTags" class="p-6 text-center text-muted-color">
                No tags yet. Create your first tag above.
            </div>
            <ul v-else class="divide-y divide-surface-200">
                <li v-for="tag in sortedTags" :key="tag.id" class="px-4 py-3">
                    <div class="flex flex-wrap items-center gap-3">
                        <div class="flex-1">
                            <div class="font-semibold text-color">
                                {{ tag.name }}
                            </div>
                            <div class="text-xs text-muted-color">
                                {{ tag.slug }}
                            </div>
                        </div>
                        <div class="flex gap-2">
                            <PvButton
                                v-if="editingId !== tag.id"
                                label="Edit"
                                size="small"
                                icon="pi pi-pencil"
                                severity="secondary"
                                outlined
                                @click="startEdit(tag)"
                            />
                            <PvButton
                                v-else
                                label="Cancel"
                                size="small"
                                icon="pi pi-times"
                                severity="secondary"
                                outlined
                                @click="cancelEdit"
                            />
                            <PvButton
                                label="Delete"
                                size="small"
                                icon="pi pi-trash"
                                severity="danger"
                                :loading="deletingId === tag.id"
                                @click="removeTag(tag)"
                            />
                        </div>
                    </div>
                    <div
                        v-if="editingId === tag.id"
                        class="mt-3 grid gap-3 md:grid-cols-3"
                    >
                        <label class="text-xs flex flex-col gap-1">
                            <span class="text-muted-color uppercase">Name</span>
                            <PvInputText v-model="editForm.name" />
                        </label>
                        <label class="text-xs flex flex-col gap-1">
                            <span class="text-muted-color uppercase">Slug</span>
                            <PvInputText v-model="editForm.slug" />
                        </label>
                        <div class="flex items-end">
                            <PvButton
                                label="Save"
                                icon="pi pi-check"
                                size="small"
                                :loading="editSubmitting"
                                @click="submitEdit"
                            />
                        </div>
                        <p
                            v-if="editError"
                            class="text-xs text-red-500 md:col-span-3"
                        >
                            {{ editError }}
                        </p>
                    </div>
                </li>
            </ul>
        </section>

        <section
            class="rounded-border border border-surface-200 bg-surface-0 p-4 shadow-sm space-y-3"
        >
            <header class="space-y-1">
                <h3
                    class="text-sm font-semibold text-color uppercase tracking-wide"
                >
                    Merge tags
                </h3>
                <p class="text-xs text-muted-color">
                    Combine duplicate tags by selecting a source and a
                    destination.
                </p>
            </header>
            <div class="grid gap-3 md:grid-cols-3">
                <label class="text-xs flex flex-col gap-1">
                    <span class="text-muted-color uppercase">Source</span>
                    <PvDropdown
                        v-model="mergeForm.source"
                        :options="sortedTags"
                        option-label="name"
                        option-value="id"
                        placeholder="Select source"
                    />
                </label>
                <label class="text-xs flex flex-col gap-1">
                    <span class="text-muted-color uppercase">Target</span>
                    <PvDropdown
                        v-model="mergeForm.target"
                        :options="mergeTargets"
                        option-label="name"
                        option-value="id"
                        placeholder="Select target"
                    />
                </label>
                <label class="flex items-center gap-2 text-sm">
                    <PvCheckbox v-model="mergeForm.deleteSource" binary />
                    <span class="text-muted-color"
                        >Delete source after merge</span
                    >
                </label>
            </div>
            <div class="flex gap-2">
                <PvButton
                    label="Merge tags"
                    icon="pi pi-object-group"
                    :disabled="!canSubmitMerge"
                    :loading="mergeSubmitting"
                    @click="submitMerge"
                />
                <PvButton
                    label="Reset"
                    outlined
                    severity="secondary"
                    @click="
                        () => (
                            (mergeForm.source = null),
                            (mergeForm.target = null),
                            (mergeForm.deleteSource = true)
                        )
                    "
                />
            </div>
            <p v-if="mergeError" class="text-sm text-red-500">
                {{ mergeError }}
            </p>
            <p v-if="mergeFeedback" class="text-sm text-green-600">
                {{ mergeFeedback }}
            </p>
        </section>
    </section>
</template>
