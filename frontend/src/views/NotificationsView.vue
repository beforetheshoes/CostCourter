<script setup lang="ts">
import NotificationPreferencesPanel from '../components/NotificationPreferencesPanel.vue'
</script>

<template>
    <section class="page-section max-w-3xl mx-auto flex flex-col gap-4">
        <header class="flex flex-col gap-2">
            <h1 class="text-3xl font-semibold text-color">
                Notification preferences
            </h1>
            <p class="text-muted-color">
                Choose how CostCourter alerts you about price drops and scrape
                issues.
            </p>
        </header>
        <NotificationPreferencesPanel />
    </section>
</template>
