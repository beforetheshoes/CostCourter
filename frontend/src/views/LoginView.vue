<script setup lang="ts">
import LoginForm from '../components/LoginForm.vue'
</script>

<template>
    <section
        class="login-view mx-auto flex min-h-[70vh] w-full max-w-4xl flex-col items-center gap-8 text-center"
    >
        <div
            class="relative overflow-hidden rounded-3xl border border-surface-200/60 bg-surface-0/80 px-8 py-12 shadow-[0_30px_60px_-35px_rgba(79,70,229,0.55)] backdrop-blur"
        >
            <div class="pointer-events-none absolute inset-0 -z-10">
                <div
                    class="absolute inset-0 scale-[1.1] bg-gradient-to-br from-primary-500/15 via-primary-500/5 to-surface-0 opacity-90"
                ></div>
                <div
                    class="absolute left-1/2 top-12 h-72 w-72 -translate-x-1/2 rounded-full bg-primary-400/20 blur-3xl"
                ></div>
            </div>
            <div class="mx-auto flex max-w-2xl flex-col gap-6">
                <span
                    class="mx-auto inline-flex items-center gap-2 rounded-full border border-primary-400/40 bg-primary-500/10 px-4 py-1 text-sm font-medium text-primary-700"
                >
                    <i class="pi pi-sparkles text-sm"></i>
                    Welcome to CostCourter
                </span>
                <h1
                    class="text-3xl font-semibold leading-snug text-color sm:text-4xl"
                >
                    Sign in to manage pricing operations
                </h1>
                <p class="text-base text-muted-color sm:text-lg">
                    Access administrative tools, monitor price retrieval, and
                    keep catalog data current.
                </p>
            </div>
        </div>

        <PvCard
            class="w-full max-w-2xl border border-surface-200/70 bg-surface-0/95"
        >
            <template #header>
                <h2 class="text-left text-xl font-semibold text-color">
                    CostCourter Admin Sign In
                </h2>
            </template>
            <template #content>
                <LoginForm />
            </template>
        </PvCard>
    </section>
</template>
