<script setup lang="ts">
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'

import { useAuthStore } from '../stores/useAuthStore'

const authStore = useAuthStore()
const { loading, error } = storeToRefs(authStore)
const redirecting = ref(false)
const route = useRoute()

const POST_LOGIN_REDIRECT_KEY = 'costcourter.postLoginRedirect'

const submit = async () => {
    if (loading.value || redirecting.value) return
    try {
        redirecting.value = true
        const defaultRedirect = `${window.location.origin}/auth/callback`
        const targetAfterLogin =
            typeof route.query.redirect === 'string'
                ? route.query.redirect
                : undefined
        if (targetAfterLogin) {
            window.localStorage.setItem(
                POST_LOGIN_REDIRECT_KEY,
                targetAfterLogin,
            )
        } else {
            window.localStorage.removeItem(POST_LOGIN_REDIRECT_KEY)
        }
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
</script>

<template>
    <div class="flex flex-col gap-4">
        <p class="text-sm text-muted-color">
            CostCourter uses single sign-on. Click below to continue via your
            organisation's identity provider.
        </p>
        <PvButton
            type="button"
            severity="primary"
            :loading="loading || redirecting"
            icon="pi pi-sign-in"
            label="Continue with SSO"
            @click="submit"
        />
        <p v-if="error" class="text-sm text-red-500">{{ error }}</p>
    </div>
</template>
