<script setup lang="ts">
import { storeToRefs } from 'pinia'

import AdminDashboardMetrics from '../components/AdminDashboardMetrics.vue'
import { useAuthStore } from '../stores/useAuthStore'

const authStore = useAuthStore()
const { currentUser } = storeToRefs(authStore)
</script>

<template>
    <section class="page-section mx-auto flex w-full max-w-5xl flex-col gap-8">
        <header
            class="relative overflow-hidden rounded-3xl border border-surface-200/60 bg-surface-0/80 px-8 py-12 text-center shadow-[0_30px_60px_-35px_rgba(79,70,229,0.55)] backdrop-blur"
        >
            <div class="pointer-events-none absolute inset-0 -z-10">
                <div
                    class="absolute inset-0 scale-[1.1] bg-gradient-to-br from-primary-500/15 via-primary-500/5 to-surface-0 opacity-90"
                ></div>
                <div
                    class="absolute left-1/2 top-12 h-72 w-72 -translate-x-1/2 rounded-full bg-primary-400/15 blur-3xl"
                ></div>
            </div>
            <div class="mx-auto flex max-w-2xl flex-col gap-6">
                <span
                    class="mx-auto inline-flex items-center gap-2 rounded-full border border-primary-400/40 bg-primary-500/10 px-4 py-1 text-sm font-medium text-primary-700"
                >
                    <i class="pi pi-sparkles text-sm"></i>
                    A refreshed PrimeVue-powered workspace
                </span>
                <h1
                    class="text-3xl font-semibold leading-snug text-color sm:text-4xl"
                >
                    Welcome back,
                    <span class="text-primary-600">
                        {{ currentUser?.full_name ?? currentUser?.email }}
                    </span>
                </h1>
                <p class="text-base text-muted-color sm:text-lg">
                    Manage catalog data, trigger price refreshes, and monitor
                    the health of the new Python backend—all from a calm,
                    focused interface.
                </p>
                <div class="grid gap-3 sm:grid-cols-3">
                    <div
                        class="rounded-2xl border border-white/40 bg-white/40 px-4 py-3 text-sm text-surface-600 shadow-sm"
                    >
                        <i class="pi pi-chart-line mr-2 text-primary"></i>
                        Real-time dashboard snapshots
                    </div>
                    <div
                        class="rounded-2xl border border-white/40 bg-white/40 px-4 py-3 text-sm text-surface-600 shadow-sm"
                    >
                        <i class="pi pi-compass mr-2 text-primary"></i>
                        Guided admin navigation
                    </div>
                    <div
                        class="rounded-2xl border border-white/40 bg-white/40 px-4 py-3 text-sm text-surface-600 shadow-sm"
                    >
                        <i class="pi pi-bell mr-2 text-primary"></i>
                        Configurable notifications
                    </div>
                </div>
            </div>
        </header>

        <PvCard class="dashboard-card">
            <template #header>
                <div
                    class="flex flex-col gap-1 text-left sm:flex-row sm:items-center sm:justify-between"
                >
                    <div>
                        <h2 class="text-xl font-semibold text-color">
                            Your administrative workspace
                        </h2>
                        <p class="text-sm text-muted-color">
                            Explore maintenance tasks, run refreshes, and keep
                            an eye on key metrics across the platform.
                        </p>
                    </div>
                    <i
                        :class="[
                            'pi text-3xl sm:text-4xl',
                            authStore.isAuthenticated
                                ? 'pi-check-circle text-primary'
                                : 'pi-lock text-muted-color',
                        ]"
                    ></i>
                </div>
            </template>
            <template #content>
                <div class="flex flex-col gap-6">
                    <div class="grid gap-3 text-left sm:grid-cols-3">
                        <div
                            class="rounded-2xl border border-surface-200/80 bg-surface-0/80 p-4"
                        >
                            <h3 class="text-sm font-semibold text-color">
                                Quick next steps
                            </h3>
                            <p class="mt-2 text-xs text-muted-color">
                                Head over to the
                                <RouterLink to="/settings" class="text-primary"
                                    >settings hub</RouterLink
                                >
                                to trigger refreshes or explore the
                                <RouterLink to="/products" class="text-primary"
                                    >product workspace</RouterLink
                                >
                                .
                            </p>
                        </div>
                        <div
                            class="rounded-2xl border border-surface-200/80 bg-surface-0/80 p-4"
                        >
                            <h3 class="text-sm font-semibold text-color">
                                Stay informed
                            </h3>
                            <p class="mt-2 text-xs text-muted-color">
                                Manage your
                                <RouterLink
                                    to="/notifications"
                                    class="text-primary"
                                    >notification preferences</RouterLink
                                >
                                to control alert noise.
                            </p>
                        </div>
                        <div
                            class="rounded-2xl border border-surface-200/80 bg-surface-0/80 p-4"
                        >
                            <h3 class="text-sm font-semibold text-color">
                                Discover trends
                            </h3>
                            <p class="mt-2 text-xs text-muted-color">
                                Inspect spotlight movers and tag health from the
                                snapshot below.
                            </p>
                        </div>
                    </div>
                    <AdminDashboardMetrics />
                </div>
            </template>
        </PvCard>
    </section>
</template>
