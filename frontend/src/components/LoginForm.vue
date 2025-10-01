<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/useAuthStore'

const authStore = useAuthStore()
const { loading, error } = storeToRefs(authStore)
const redirecting = ref(false)
const route = useRoute()
const router = useRouter()

const passkeyEmail = ref('')
const passkeyFullName = ref('')
const passkeyMessage = ref<string | null>(null)
const showPasskeyRegistration = ref(false)

const POST_LOGIN_REDIRECT_KEY = 'costcourter.postLoginRedirect'

const ssoAvailable = computed(() => {
    const env = import.meta.env
    const flag = env.VITE_OIDC_ENABLED
    const normalize = (value: string) => value.trim().toLowerCase()
    if (typeof flag === 'string' && flag.trim().length > 0) {
        const normalized = normalize(flag)
        if (['false', '0', 'no', 'off', 'disabled'].includes(normalized)) {
            return false
        }
        if (['true', '1', 'yes', 'on', 'enabled'].includes(normalized)) {
            return true
        }
    }
    const hasValue = (value: unknown) => {
        if (typeof value !== 'string') return false
        const trimmed = value.trim()
        if (trimmed.length === 0) return false
        const lowered = trimmed.toLowerCase()
        return !['undefined', 'null', 'false', '0', 'off'].includes(lowered)
    }

    return (
        hasValue(env.VITE_OIDC_CLIENT_ID) &&
        (hasValue(env.VITE_OIDC_AUTHORITY) || hasValue(env.VITE_OIDC_ISSUER))
    )
})

const setRedirectPreference = () => {
    const target =
        typeof route.query.redirect === 'string'
            ? route.query.redirect
            : undefined
    if (target) {
        window.localStorage.setItem(POST_LOGIN_REDIRECT_KEY, target)
    } else {
        window.localStorage.removeItem(POST_LOGIN_REDIRECT_KEY)
    }
    return target
}

const navigateAfterAuth = async () => {
    const stored = window.localStorage.getItem(POST_LOGIN_REDIRECT_KEY)
    const queryTarget =
        typeof route.query.redirect === 'string'
            ? route.query.redirect
            : undefined
    const destination = stored ?? queryTarget ?? '/dashboard'
    window.localStorage.removeItem(POST_LOGIN_REDIRECT_KEY)
    try {
        await router.replace(destination)
    } catch {
        // navigation failures are non-fatal
    }
}

const submit = async () => {
    if (loading.value || redirecting.value) return
    try {
        redirecting.value = true
        const defaultRedirect = `${window.location.origin}/auth/callback`
        setRedirectPreference()
        const response = await authStore.beginOidcLogin(
            import.meta.env.VITE_OIDC_REDIRECT_URI ?? defaultRedirect,
        )
        window.location.href = response.authorization_url
    } catch (cause) {
        console.error('OIDC start failed', cause)
    } finally {
        redirecting.value = false
    }
}

const togglePasskeyRegistration = () => {
    showPasskeyRegistration.value = !showPasskeyRegistration.value
    if (!showPasskeyRegistration.value) {
        passkeyFullName.value = ''
        passkeyMessage.value = null
    }
}

const registerWithPasskey = async () => {
    passkeyMessage.value = null
    authStore.$patch({ error: null })
    const email = passkeyEmail.value.trim()
    if (!email) {
        passkeyMessage.value = 'Enter an email address to register a passkey.'
        return
    }
    try {
        setRedirectPreference()
        await authStore.registerPasskey({
            email,
            fullName: passkeyFullName.value.trim() || undefined,
        })
        await navigateAfterAuth()
        passkeyFullName.value = ''
        showPasskeyRegistration.value = false
    } catch (cause) {
        if (!error.value && cause instanceof Error) {
            passkeyMessage.value = cause.message
        }
    }
}

const authenticateWithPasskey = async () => {
    passkeyMessage.value = null
    authStore.$patch({ error: null })
    const email = passkeyEmail.value.trim()
    if (!email) {
        passkeyMessage.value =
            'Enter the email associated with your passkey before continuing.'
        return
    }
    try {
        setRedirectPreference()
        await authStore.authenticatePasskey(email)
        await navigateAfterAuth()
    } catch (cause) {
        if (!error.value && cause instanceof Error) {
            passkeyMessage.value = cause.message
        }
    }
}
</script>

<template>
    <div class="flex flex-col gap-6">
        <section
            v-if="ssoAvailable"
            class="rounded-2xl border border-surface-200/80 bg-surface-0/80 p-4"
        >
            <h3 class="text-sm font-semibold text-color">Single Sign-On</h3>
            <p class="mt-2 text-xs text-muted-color">
                Continue with your organisation's identity provider. We'll
                remember where you intended to go once signed in.
            </p>
            <PvButton
                type="button"
                severity="primary"
                :loading="loading || redirecting"
                icon="pi pi-sign-in"
                label="Continue with SSO"
                class="mt-4"
                @click="submit"
            />
        </section>

        <div
            v-if="ssoAvailable"
            class="flex items-center gap-3 text-xs text-muted-color"
        >
            <span
                class="h-px flex-1 bg-surface-200/80"
                aria-hidden="true"
            ></span>
            <span>Or</span>
            <span
                class="h-px flex-1 bg-surface-200/80"
                aria-hidden="true"
            ></span>
        </div>

        <section
            class="rounded-2xl border border-surface-200/80 bg-surface-0/80 p-4"
        >
            <h3 class="text-sm font-semibold text-color">Passkey Access</h3>
            <p class="mt-2 text-xs text-muted-color">
                Enter your email to locate the correct passkey, then continue to
                authenticate. If you need to create a new passkey, open the
                registration panel.
            </p>

            <div class="mt-4 flex flex-col gap-3">
                <label
                    class="text-xs font-medium text-muted-color"
                    for="login-passkey-email"
                >
                    Email address
                </label>
                <PvInputText
                    id="login-passkey-email"
                    v-model="passkeyEmail"
                    type="email"
                    autocomplete="username"
                    placeholder="you@example.com"
                />
            </div>

            <div class="mt-4 flex flex-wrap gap-2">
                <PvButton
                    type="button"
                    severity="primary"
                    :loading="loading"
                    icon="pi pi-unlock"
                    label="Sign in with a Passkey"
                    @click="authenticateWithPasskey"
                />
                <PvButton
                    type="button"
                    severity="secondary"
                    :loading="loading"
                    icon="pi pi-plus"
                    :label="
                        showPasskeyRegistration
                            ? 'Hide passkey registration'
                            : 'Register a Passkey'
                    "
                    outlined
                    @click="togglePasskeyRegistration"
                />
            </div>

            <Transition name="fade-scale">
                <div
                    v-if="showPasskeyRegistration"
                    class="mt-4 rounded-border border border-dashed border-surface-300 bg-surface-0/60 p-4 text-left"
                >
                    <div class="flex flex-col gap-3">
                        <label
                            class="text-xs font-medium text-muted-color"
                            for="register-passkey-email"
                        >
                            Email address
                        </label>
                        <PvInputText
                            id="register-passkey-email"
                            v-model="passkeyEmail"
                            type="email"
                            autocomplete="username"
                            placeholder="you@example.com"
                        />
                        <label
                            class="text-xs font-medium text-muted-color"
                            for="login-passkey-name"
                        >
                            Full name (optional; helps personalise new accounts)
                        </label>
                        <PvInputText
                            id="login-passkey-name"
                            v-model="passkeyFullName"
                            autocomplete="name"
                            placeholder="Ada Lovelace"
                        />
                    </div>
                    <div class="mt-3 flex flex-wrap gap-2">
                        <PvButton
                            type="button"
                            severity="secondary"
                            :loading="loading"
                            icon="pi pi-check"
                            label="Complete Passkey Registration"
                            outlined
                            @click="registerWithPasskey"
                        />
                        <PvButton
                            type="button"
                            text
                            severity="secondary"
                            icon="pi pi-times"
                            label="Cancel"
                            :disabled="loading"
                            @click="togglePasskeyRegistration"
                        />
                    </div>
                    <p class="mt-2 text-xs text-muted-color">
                        We'll remember your redirect after registration so you
                        land back where you intended.
                    </p>
                </div>
            </Transition>

            <p v-if="passkeyMessage" class="mt-2 text-xs text-red-500">
                {{ passkeyMessage }}
            </p>
        </section>

        <p v-if="error" class="text-sm text-red-500">{{ error }}</p>
    </div>
</template>
