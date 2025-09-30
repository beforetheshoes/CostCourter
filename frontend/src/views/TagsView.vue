<script setup lang="ts">
import TagManagementPanel from '../components/TagManagementPanel.vue'
</script>

<template>
    <section class="page-section max-w-5xl mx-auto space-y-6">
        <header class="space-y-2">
            <h1 class="text-3xl font-semibold text-color">Tag settings</h1>
            <p class="text-sm text-muted-color">
                Manage the taxonomy that powers filtering, notifications, and
                reports.
            </p>
        </header>
        <TagManagementPanel />
    </section>
</template>
