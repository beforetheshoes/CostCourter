<script setup lang="ts">
import { computed, onMounted, reactive, watch } from 'vue'

import {
    type NotificationChannel,
    useNotificationsStore,
} from '../stores/useNotificationsStore'

const SECRET_PLACEHOLDER = '__SECRET_PRESENT__'

const notificationsStore = useNotificationsStore()
const channelList = computed(() =>
    Array.isArray(notificationsStore.channels)
        ? notificationsStore.channels
        : [],
)
const formState = reactive<
    Record<string, { enabled: boolean; config: Record<string, string> }>
>({})
const saveErrors = reactive<Record<string, string | null>>({})
const editMode = reactive<Record<string, boolean>>({})

const isEditingChannel = (channelId: string) => editMode[channelId] !== false
const isTestingChannel = (channelId: string) =>
    Boolean(notificationsStore.testing[channelId])
const getTestStatus = (channelId: string) =>
    notificationsStore.testStatus[channelId] ?? null

const syncFormState = (channels: NotificationChannel[] | undefined) => {
    const list = Array.isArray(channels) ? channels : []
    const nextState: Record<
        string,
        { enabled: boolean; config: Record<string, string> }
    > = {}
    list.forEach((channel) => {
        const config: Record<string, string> = {}
        if (channel.config_fields.length > 0) {
            channel.config_fields.forEach((field) => {
                const value = channel.config[field.key]
                if (field.secret && value === SECRET_PLACEHOLDER) {
                    config[field.key] = SECRET_PLACEHOLDER
                } else {
                    config[field.key] = value ?? ''
                }
            })
        } else {
            Object.entries(channel.config).forEach(([key, value]) => {
                config[key] = value ?? ''
            })
        }
        nextState[channel.channel] = {
            enabled: channel.enabled,
            config,
        }
        saveErrors[channel.channel] = null
        const hasSecretFields = channel.config_fields.some(
            (field) => field.secret,
        )
        const allSecretsLocked = channel.config_fields
            .filter((field) => field.secret)
            .every((field) => channel.config[field.key] === SECRET_PLACEHOLDER)
        const shouldLock =
            channel.enabled && hasSecretFields && allSecretsLocked
        editMode[channel.channel] = shouldLock ? false : true
    })

    Object.keys(formState).forEach((key) => {
        if (!nextState[key]) {
            delete formState[key]
        }
    })

    Object.entries(nextState).forEach(([key, value]) => {
        formState[key] = value
    })
}

watch(
    channelList,
    (channels) => {
        syncFormState(channels)
    },
    { immediate: true, deep: true },
)

onMounted(async () => {
    try {
        await notificationsStore.fetchChannels()
    } catch {
        // errors are surfaced via store state
    }
})

const updatingState = computed(() => notificationsStore.updating)

const sanitizeConfig = (channel: NotificationChannel) => {
    const state = formState[channel.channel]
    if (!state) {
        return undefined
    }
    const sanitized: Record<string, string | null> = {}
    if (channel.config_fields.length === 0) {
        return undefined
    }
    channel.config_fields.forEach((field) => {
        const rawValue = state.config[field.key]
        if (field.secret && rawValue === SECRET_PLACEHOLDER) {
            return
        }
        const value = typeof rawValue === 'string' ? rawValue : ''
        const trimmed = value.trim()
        sanitized[field.key] = trimmed === '' ? null : trimmed
    })
    return sanitized
}

const saveChannel = async (channel: NotificationChannel) => {
    const state = formState[channel.channel]
    if (!state) {
        return
    }
    saveErrors[channel.channel] = null
    const configPayload = sanitizeConfig(channel)
    try {
        await notificationsStore.updateChannel(channel.channel, {
            enabled: state.enabled,
            config:
                configPayload && Object.keys(configPayload).length > 0
                    ? configPayload
                    : channel.config_fields.length > 0
                      ? (configPayload ?? {})
                      : undefined,
        })
    } catch (error) {
        const message =
            error instanceof Error
                ? error.message
                : 'Failed to update notification channel'
        saveErrors[channel.channel] = message
    }
}

const isUpdating = (channel: string) => Boolean(updatingState.value[channel])

const getFieldDisplayValue = (
    channelId: string,
    fieldKey: string,
    secret: boolean,
) => {
    const state = formState[channelId]
    if (!state) {
        return ''
    }
    const rawValue = state.config[fieldKey]
    if (
        secret &&
        rawValue === SECRET_PLACEHOLDER &&
        !isEditingChannel(channelId)
    ) {
        return '••••••••'
    }
    return typeof rawValue === 'string' ? rawValue : ''
}

const onFieldInput = (
    channelId: string,
    fieldKey: string,
    secret: boolean,
    nextValue: string,
) => {
    const state = formState[channelId]
    if (!state) {
        return
    }
    if (secret && state.config[fieldKey] === SECRET_PLACEHOLDER) {
        state.config[fieldKey] = nextValue
        return
    }
    state.config[fieldKey] = nextValue
}

const beginEditing = (channel: NotificationChannel) => {
    editMode[channel.channel] = true
    const state = formState[channel.channel]
    if (!state) {
        return
    }
    channel.config_fields.forEach((field) => {
        if (field.secret && state.config[field.key] === SECRET_PLACEHOLDER) {
            state.config[field.key] = ''
        }
    })
    notificationsStore.testStatus = {
        ...notificationsStore.testStatus,
        [channel.channel]: null,
    }
}

const handlePrimaryAction = async (channel: NotificationChannel) => {
    if (!isEditingChannel(channel.channel)) {
        beginEditing(channel)
        return
    }
    await saveChannel(channel)
}

const canSendTest = (channel: NotificationChannel) =>
    channel.available && channel.enabled && !isEditingChannel(channel.channel)

const triggerTest = async (channel: NotificationChannel) => {
    if (!canSendTest(channel) || isTestingChannel(channel.channel)) {
        return
    }
    try {
        await notificationsStore.testChannel(channel.channel)
    } catch {
        // errors surface via store state
    }
}
</script>

<template>
    <div class="flex flex-col gap-4">
        <div
            v-if="notificationsStore.loading"
            class="text-muted-color"
            data-testid="loading"
        >
            Loading notification channels…
        </div>
        <div
            v-else-if="notificationsStore.error"
            class="text-danger-color"
            role="alert"
        >
            {{ notificationsStore.error }}
        </div>
        <div v-else class="flex flex-col gap-4">
            <template v-for="channel in channelList" :key="channel.channel">
                <article
                    v-if="formState[channel.channel]"
                    class="border border-surface-200 rounded-border bg-surface-0/60 p-4 flex flex-col gap-3"
                >
                    <div
                        class="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between"
                    >
                        <div>
                            <h3 class="text-lg font-semibold text-color">
                                {{ channel.display_name }}
                            </h3>
                            <p
                                v-if="channel.description"
                                class="text-sm text-muted-color"
                            >
                                {{ channel.description }}
                            </p>
                        </div>
                        <label
                            class="flex items-center gap-2 text-sm text-muted-color"
                        >
                            <input
                                v-model="formState[channel.channel].enabled"
                                type="checkbox"
                                :disabled="
                                    !channel.available ||
                                    isUpdating(channel.channel)
                                "
                            />
                            <span>
                                {{
                                    formState[channel.channel]?.enabled
                                        ? 'Enabled'
                                        : 'Disabled'
                                }}
                            </span>
                        </label>
                    </div>

                    <p
                        v-if="!channel.available"
                        class="text-sm text-warning-color"
                    >
                        {{
                            channel.unavailable_reason ||
                            'Channel disabled in server configuration.'
                        }}
                    </p>

                    <div
                        v-if="channel.config_fields.length > 0"
                        class="flex flex-col gap-3"
                    >
                        <div
                            v-for="field in channel.config_fields"
                            :key="field.key"
                            class="flex flex-col gap-1"
                        >
                            <label
                                :for="`${channel.channel}-${field.key}`"
                                class="text-sm font-medium"
                            >
                                {{ field.label }}
                            </label>
                            <input
                                v-if="field.secret"
                                :id="`${channel.channel}-${field.key}`"
                                :value="
                                    getFieldDisplayValue(
                                        channel.channel,
                                        field.key,
                                        true,
                                    )
                                "
                                type="password"
                                autocomplete="new-password"
                                class="border border-surface-200 rounded px-3 py-2 disabled:opacity-60"
                                :placeholder="field.placeholder || ''"
                                :disabled="
                                    !channel.available ||
                                    isUpdating(channel.channel) ||
                                    !isEditingChannel(channel.channel)
                                "
                                @input="
                                    onFieldInput(
                                        channel.channel,
                                        field.key,
                                        true,
                                        ($event.target as HTMLInputElement)
                                            .value,
                                    )
                                "
                            />
                            <input
                                v-else
                                :id="`${channel.channel}-${field.key}`"
                                v-model="
                                    formState[channel.channel].config[field.key]
                                "
                                type="text"
                                class="border border-surface-200 rounded px-3 py-2"
                                :placeholder="field.placeholder || ''"
                                :disabled="
                                    !channel.available ||
                                    isUpdating(channel.channel)
                                "
                            />
                            <p
                                v-if="field.description"
                                class="text-xs text-muted-color"
                            >
                                {{ field.description }}
                            </p>
                        </div>
                    </div>

                    <div class="flex items-center gap-3">
                        <button
                            class="px-4 py-2 rounded bg-primary text-white disabled:opacity-40"
                            type="button"
                            :disabled="
                                (isEditingChannel(channel.channel) &&
                                    (!channel.available ||
                                        isUpdating(channel.channel))) ||
                                (!isEditingChannel(channel.channel) &&
                                    isUpdating(channel.channel))
                            "
                            @click="handlePrimaryAction(channel)"
                        >
                            {{
                                isEditingChannel(channel.channel)
                                    ? isUpdating(channel.channel)
                                        ? 'Saving…'
                                        : 'Save'
                                    : 'Modify'
                            }}
                        </button>
                        <button
                            class="px-4 py-2 rounded border border-primary text-primary disabled:opacity-40"
                            type="button"
                            :disabled="
                                !canSendTest(channel) ||
                                isTestingChannel(channel.channel)
                            "
                            @click="triggerTest(channel)"
                        >
                            {{
                                isTestingChannel(channel.channel)
                                    ? 'Sending…'
                                    : 'Send test notification'
                            }}
                        </button>
                        <p
                            v-if="saveErrors[channel.channel]"
                            class="text-sm text-danger-color"
                        >
                            {{ saveErrors[channel.channel] }}
                        </p>
                        <p
                            v-else-if="getTestStatus(channel.channel)"
                            class="text-sm"
                            :class="
                                getTestStatus(channel.channel)?.success
                                    ? 'text-color'
                                    : 'text-danger-color'
                            "
                        >
                            {{ getTestStatus(channel.channel)?.message }}
                        </p>
                    </div>
                </article>
            </template>

            <p v-if="channelList.length === 0" class="text-sm text-muted-color">
                No notification channels available yet.
            </p>
        </div>
    </div>
</template>
