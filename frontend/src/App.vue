<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'

import { useAuthStore } from './stores/useAuthStore'

type NavItem = {
    key: string
    label: string
    icon: string
    to: RouteLocationRaw
}

const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()

const currentUser = computed(() => authStore.currentUser)
const isAuthenticated = computed(() => authStore.isAuthenticated)
const showAdminLinks = computed(() => authStore.hasRole('admin'))

const userInitials = computed(() => {
    const name = currentUser.value?.full_name ?? currentUser.value?.email ?? ''
    const segments = name.trim().split(/\s+/).filter(Boolean)
    if (segments.length === 0) return 'PB'
    if (segments.length === 1) return segments[0].slice(0, 2).toUpperCase()
    return `${segments[0][0] ?? ''}${segments[1][0] ?? ''}`.toUpperCase()
})

const navItems = computed<NavItem[]>(() => {
    const items: NavItem[] = [
        {
            key: 'home',
            label: 'Overview',
            icon: 'pi pi-compass',
            to: { name: 'home' },
        },
    ]

    if (showAdminLinks.value) {
        items.push(
            {
                key: 'products',
                label: 'Products',
                icon: 'pi pi-box',
                to: { name: 'products' },
            },
            {
                key: 'search',
                label: 'Search',
                icon: 'pi pi-search',
                to: { name: 'search' },
            },
            {
                key: 'stores',
                label: 'Stores',
                icon: 'pi pi-building',
                to: { name: 'stores' },
            },
            {
                key: 'settings',
                label: 'Settings',
                icon: 'pi pi-sliders-h',
                to: { name: 'settings' },
            },
        )
    }

    return items
})

const isActive = (item: NavItem) => {
    const destination = router.resolve(item.to)
    return destination.name === route.name
}

const isMobileMenuOpen = ref(false)

const toggleMobileMenu = () => {
    isMobileMenuOpen.value = !isMobileMenuOpen.value
}

const handleLogout = () => {
    authStore.logout(false)
    router.push({ name: 'home' }).catch(() => {})
}

const handleLogin = () => {
    const redirectTarget = route.fullPath === '/' ? undefined : route.fullPath
    router
        .push({
            name: 'home',
            query: redirectTarget ? { redirect: redirectTarget } : undefined,
        })
        .catch(() => {})
}

const currentYear = new Date().getFullYear()

watch(
    () => route.fullPath,
    () => {
        isMobileMenuOpen.value = false
    },
)
</script>

<template>
    <div class="app-shell min-h-screen flex flex-col text-color">
        <div class="app-ambient-bg" aria-hidden="true">
            <div class="app-ambient-blob app-ambient-blob--left"></div>
            <div class="app-ambient-blob app-ambient-blob--right"></div>
        </div>

        <header class="px-4 pt-6 sm:px-6">
            <nav
                class="app-nav relative mx-auto flex max-w-6xl items-center gap-3 rounded-3xl border border-surface-200/70 bg-surface-0/80 px-4 py-3 shadow-[0_18px_45px_-28px_rgba(79,70,229,0.45)] backdrop-blur"
            >
                <RouterLink
                    to="/"
                    class="flex min-w-0 shrink-0 items-center gap-3 no-underline text-inherit"
                >
                    <span
                        class="flex h-11 w-11 items-center justify-center rounded-2xl border border-primary-400/40 bg-primary-500/10 text-primary-600 shadow-[0_15px_40px_-25px_rgba(79,70,229,0.75)]"
                    >
                        <i class="pi pi-chart-line text-lg"></i>
                    </span>
                    <span class="flex min-w-0 flex-col">
                        <span
                            class="truncate text-lg font-semibold tracking-tight text-color"
                        >
                            CostCourter
                        </span>
                    </span>
                </RouterLink>

                <div class="hidden flex-1 items-center justify-center md:flex">
                    <div
                        class="flex min-w-0 flex-nowrap items-center justify-center gap-1.5"
                    >
                        <RouterLink
                            v-for="item in navItems"
                            :key="item.key"
                            :to="item.to"
                            class="nav-link"
                            :class="[
                                isActive(item)
                                    ? 'nav-link--active'
                                    : 'nav-link--idle',
                            ]"
                        >
                            <i :class="[item.icon, 'text-xs']"></i>
                            <span>{{ item.label }}</span>
                        </RouterLink>
                    </div>
                </div>

                <div
                    class="ml-auto flex shrink-0 items-center gap-1.5 md:ml-0 md:gap-2"
                >
                    <PvButton
                        icon="pi pi-bars"
                        severity="secondary"
                        text
                        size="small"
                        class="inline-flex md:hidden"
                        :aria-expanded="isMobileMenuOpen"
                        aria-label="Toggle navigation menu"
                        @click="toggleMobileMenu"
                    />
                    <PvTag
                        v-if="showAdminLinks"
                        value="Admin"
                        rounded
                        severity="primary"
                        class="hidden lg:inline-flex px-2 py-0.5 text-xs font-medium"
                    />
                    <div
                        v-if="isAuthenticated && currentUser"
                        class="hidden min-w-0 flex-col items-end leading-tight md:flex"
                    >
                        <span class="truncate text-sm font-semibold text-color">
                            {{ currentUser.full_name ?? currentUser.email }}
                        </span>
                        <span class="truncate text-xs text-muted-color">
                            {{ currentUser.email }}
                        </span>
                    </div>
                    <PvAvatar
                        v-if="isAuthenticated"
                        :label="userInitials"
                        class="app-nav-avatar border border-primary-200 bg-primary-50 text-primary-700"
                        size="small"
                        shape="circle"
                    />
                    <template v-if="isAuthenticated">
                        <PvButton
                            icon="pi pi-sign-out"
                            rounded
                            text
                            severity="secondary"
                            size="small"
                            class="sm:hidden"
                            aria-label="Sign out"
                            @click="handleLogout"
                        />
                        <PvButton
                            label="Sign out"
                            icon="pi pi-sign-out"
                            severity="secondary"
                            text
                            size="small"
                            class="hidden sm:inline-flex"
                            @click="handleLogout"
                        />
                    </template>
                    <PvButton
                        v-else
                        label="Sign in"
                        icon="pi pi-sign-in"
                        severity="primary"
                        size="small"
                        @click="handleLogin"
                    />
                </div>

                <Transition name="fade-scale">
                    <div
                        v-if="isMobileMenuOpen"
                        class="absolute left-3 right-3 top-full z-10 mt-3 flex flex-col gap-2 rounded-2xl border border-surface-200/70 bg-surface-0/95 p-3 shadow-lg backdrop-blur md:hidden"
                    >
                        <RouterLink
                            v-for="item in navItems"
                            :key="item.key"
                            :to="item.to"
                            class="nav-link nav-link--mobile"
                            :class="[
                                isActive(item)
                                    ? 'nav-link--active'
                                    : 'nav-link--idle',
                            ]"
                        >
                            <i :class="[item.icon, 'text-xs']"></i>
                            <span>{{ item.label }}</span>
                        </RouterLink>
                    </div>
                </Transition>
            </nav>
        </header>

        <main class="flex-1 px-4 pb-16 pt-10 sm:px-6">
            <div class="mx-auto flex w-full max-w-6xl flex-col gap-6">
                <RouterView />
            </div>
        </main>

        <footer class="px-4 pb-10 sm:px-6">
            <div
                class="mx-auto flex w-full max-w-6xl flex-col gap-3 border-t border-surface-200/70 pt-6 sm:flex-row sm:items-center sm:justify-between"
            >
                <span class="text-xs text-muted-color">
                    © {{ currentYear }} CostCourter · Beautifully themed with
                    PrimeVue
                </span>
                <span class="flex items-center gap-2 text-xs text-muted-color">
                    <i class="pi pi-sparkles text-primary"></i>
                    <span>Crafted for focused pricing workflows</span>
                </span>
            </div>
        </footer>
    </div>
</template>
