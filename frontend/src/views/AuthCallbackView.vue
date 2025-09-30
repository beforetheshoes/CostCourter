<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/useAuthStore'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { error } = storeToRefs(authStore)
const processing = ref(true)
const message = ref('Finalising sign-in…')
const POST_LOGIN_REDIRECT_KEY = 'costcourter.postLoginRedirect'

onMounted(async () => {
    const state = route.query.state
    const code = route.query.code
    const storedRedirect = window.localStorage.getItem(POST_LOGIN_REDIRECT_KEY)
    const redirect =
        (route.query.redirect as string | undefined) ??
        storedRedirect ??
        undefined

    if (typeof state !== 'string' || typeof code !== 'string') {
        message.value = 'Missing state or code in callback response.'
        processing.value = false
        return
    }

    try {
        await authStore.completeOidcLogin({ state, code })
        message.value = 'Authenticated successfully. Redirecting…'
        window.localStorage.removeItem(POST_LOGIN_REDIRECT_KEY)
        await router.replace(redirect || '/settings')
    } catch (cause) {
        console.error('OIDC callback failed', cause)
        message.value = 'Unable to complete sign-in. Please try again.'
        processing.value = false
    }
})
</script>

<template>
    <section
        class="page-section flex flex-col items-center gap-4 text-center max-w-lg mx-auto"
    >
        <i
            :class="[
                'pi text-4xl',
                processing
                    ? 'pi-spin pi-spinner text-primary'
                    : 'pi-exclamation-triangle text-red-500',
            ]"
        ></i>
        <p class="text-sm text-muted-color">{{ message }}</p>
        <p v-if="error" class="text-sm text-red-500">{{ error }}</p>
        <RouterLink v-if="!processing" to="/" class="text-primary">
            Return to sign-in
        </RouterLink>
    </section>
</template>
