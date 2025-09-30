<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { useAdminMetricsStore } from '../stores/useAdminMetricsStore'
import { BRAND_THEME_EVENT } from '../lib/themeManager'
import { COLOR_MODE_EVENT } from '../lib/colorMode'
import {
    type ChartTokens,
    resolveChartTokens,
    withAlpha,
} from '../lib/chartTokens'
import {
    formatChartLabel,
    formatDateTime,
    formatPrice,
    trendSeverity,
} from '../lib/metricsFormatters'

const metricsStore = useAdminMetricsStore()

const metrics = computed(() => metricsStore.metrics)
const totals = computed(() => metrics.value?.totals)
const spotlight = computed(() => metrics.value?.spotlight ?? [])
const tagGroups = computed(() => metrics.value?.tag_groups ?? [])
const loading = computed(() => metricsStore.loading)
const error = computed(() => metricsStore.error)

type ChartTokens = {
    accent1: string
    accent2: string
    accent3: string
    accent4: string
    accent5: string
    accent6: string
    accent7: string
    accent8: string
    gridStrong: string
    gridMuted: string
    gridSoft: string
}

const chartTokens = ref<ChartTokens>(resolveChartTokens())

const refreshChartTokens = () => {
    chartTokens.value = resolveChartTokens()
}

const totalsChartData = computed(() => {
    if (!totals.value) return null
    const colors = chartTokens.value
    return {
        labels: ['Products', 'Favourites', 'Active URLs'],
        datasets: [
            {
                data: [
                    totals.value.products,
                    totals.value.favourites,
                    totals.value.active_urls,
                ],
                backgroundColor: [
                    withAlpha(colors.accent1, 0.35),
                    withAlpha(colors.accent2, 0.35),
                    withAlpha(colors.accent3, 0.35),
                ],
                borderColor: [colors.accent1, colors.accent2, colors.accent3],
                borderWidth: 2,
                borderRadius: 12,
                hoverBorderWidth: 3,
            },
        ],
    }
})

const totalsChartOptions = computed(() => ({
    maintainAspectRatio: false,
    plugins: {
        legend: {
            display: false,
        },
    },
    scales: {
        x: {
            ticks: {
                color: '#475569',
                font: {
                    family: 'var(--p-font-family)',
                    weight: '600',
                },
            },
            grid: {
                display: false,
            },
            border: {
                display: false,
            },
        },
        y: {
            beginAtZero: true,
            ticks: {
                precision: 0,
                color: '#94a3b8',
                font: {
                    family: 'var(--p-font-family)',
                },
            },
            grid: {
                color: chartTokens.value.gridStrong,
                borderDash: [6, 6],
            },
            border: {
                display: false,
            },
        },
    },
}))

const spotlightChartData = computed(() => {
    if (!spotlight.value.length) return null

    const colors = chartTokens.value
    const palette = [
        colors.accent1,
        colors.accent4,
        colors.accent5,
        colors.accent6,
    ]
    const dateSet = new Set<string>()

    spotlight.value.forEach((product) => {
        product.history?.forEach((point) => {
            if (point.date) dateSet.add(point.date)
        })
    })

    if (dateSet.size === 0) {
        return null
    }

    const sortedDates = Array.from(dateSet).sort(
        (a, b) => new Date(a).getTime() - new Date(b).getTime(),
    )

    const labels = sortedDates.map((date) => formatChartLabel(date))

    return {
        labels,
        datasets: spotlight.value.slice(0, 3).map((product, index) => {
            const color = palette[index % palette.length]
            return {
                label: product.name,
                data: sortedDates.map((date) => {
                    const matching = product.history?.find(
                        (point) => point.date === date,
                    )
                    return matching?.price ?? null
                }),
                fill: false,
                borderColor: color,
                backgroundColor: color,
                pointBackgroundColor: color,
                pointBorderColor: '#ffffff',
                tension: 0.35,
                pointRadius: 3,
                pointHoverRadius: 4,
                spanGaps: true,
            }
        }),
    }
})

const spotlightChartOptions = computed(() => ({
    maintainAspectRatio: false,
    plugins: {
        legend: {
            position: 'bottom',
            labels: {
                boxWidth: 12,
                color: '#475569',
                font: {
                    family: 'var(--p-font-family)',
                },
            },
        },
    },
    scales: {
        x: {
            ticks: {
                color: '#64748b',
                font: {
                    family: 'var(--p-font-family)',
                },
            },
            grid: {
                color: chartTokens.value.gridMuted,
            },
        },
        y: {
            ticks: {
                color: '#94a3b8',
                font: {
                    family: 'var(--p-font-family)',
                },
            },
            grid: {
                color: chartTokens.value.gridSoft,
            },
        },
    },
}))

const tagDistributionChartData = computed(() => {
    if (!tagGroups.value.length) return null
    const labels = tagGroups.value.map((group) => group.label)
    const values = tagGroups.value.map((group) => group.products.length)
    const colors = chartTokens.value
    const palette = [
        colors.accent1,
        colors.accent6,
        colors.accent4,
        colors.accent3,
        colors.accent5,
        colors.accent7,
        colors.accent8,
        colors.accent2,
    ]
    return {
        labels,
        datasets: [
            {
                data: values,
                backgroundColor: labels.map(
                    (_, index) => palette[index % palette.length],
                ),
                borderColor: '#ffffff',
                borderWidth: 2,
            },
        ],
    }
})

const tagDistributionOptions = computed(() => ({
    maintainAspectRatio: false,
    plugins: {
        legend: {
            position: 'bottom',
            labels: {
                color: '#475569',
                font: {
                    family: 'var(--p-font-family)',
                },
            },
        },
    },
}))

onMounted(() => {
    refreshChartTokens()
    if (!metrics.value && !metricsStore.loading) {
        metricsStore.fetchMetrics()
    }
})

if (typeof window !== 'undefined') {
    window.addEventListener(BRAND_THEME_EVENT, refreshChartTokens)
    window.addEventListener(COLOR_MODE_EVENT, refreshChartTokens)
}

onBeforeUnmount(() => {
    if (typeof window !== 'undefined') {
        window.removeEventListener(BRAND_THEME_EVENT, refreshChartTokens)
        window.removeEventListener(COLOR_MODE_EVENT, refreshChartTokens)
    }
})
</script>

<template>
    <section class="flex flex-col gap-6 w-full">
        <header
            class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
        >
            <div class="flex flex-col gap-1">
                <h3 class="text-lg font-semibold text-color">
                    Operations pulse
                </h3>
                <p class="text-sm text-muted-color">
                    Snapshot of catalog health, spotlight movers, and curated
                    tag performance.
                </p>
            </div>
            <div class="flex gap-2">
                <PvButton
                    icon="pi pi-refresh"
                    label="Refresh"
                    :loading="loading"
                    severity="secondary"
                    outlined
                    @click="metricsStore.fetchMetrics()"
                />
            </div>
        </header>

        <div v-if="loading" class="space-y-4">
            <div class="grid gap-4 md:grid-cols-3">
                <PvSkeleton height="6.75rem" style="border-radius: 1.25rem" />
                <PvSkeleton height="6.75rem" style="border-radius: 1.25rem" />
                <PvSkeleton height="6.75rem" style="border-radius: 1.25rem" />
            </div>
            <PvSkeleton height="20rem" style="border-radius: 1.25rem" />
        </div>

        <PvInlineMessage v-else-if="error" severity="error" :closable="false">
            {{ error }}
        </PvInlineMessage>

        <div v-else-if="metrics" class="flex flex-col gap-6">
            <div class="grid gap-4 md:grid-cols-3">
                <PvCard
                    v-for="entry in [
                        {
                            key: 'products',
                            label: 'Products',
                            value: totals?.products ?? 0,
                            icon: 'pi pi-box',
                        },
                        {
                            key: 'favourites',
                            label: 'Favourites',
                            value: totals?.favourites ?? 0,
                            icon: 'pi pi-heart',
                        },
                        {
                            key: 'active_urls',
                            label: 'Active URLs',
                            value: totals?.active_urls ?? 0,
                            icon: 'pi pi-link',
                        },
                    ]"
                    :key="entry.key"
                    class="dashboard-card"
                >
                    <template #content>
                        <div class="flex items-start justify-between gap-3">
                            <div class="flex flex-col gap-2">
                                <span class="text-sm text-muted-color">{{
                                    entry.label
                                }}</span>
                                <span class="text-3xl font-semibold text-color">
                                    {{ entry.value.toLocaleString() }}
                                </span>
                            </div>
                            <span
                                class="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-primary-400/30 bg-primary-500/10 text-primary"
                            >
                                <i :class="[entry.icon, 'text-base']"></i>
                            </span>
                        </div>
                    </template>
                </PvCard>
            </div>

            <div class="grid gap-4 xl:grid-cols-[2fr,1fr]">
                <PvCard v-if="spotlightChartData" class="dashboard-card">
                    <template #header>
                        <div class="flex items-center justify-between">
                            <div>
                                <h4 class="text-base font-semibold text-color">
                                    Spotlight price trends
                                </h4>
                                <p class="text-xs text-muted-color">
                                    Track the last refresh windows for standout
                                    products.
                                </p>
                            </div>
                        </div>
                    </template>
                    <template #content>
                        <div class="h-64">
                            <PvChart
                                type="line"
                                :data="spotlightChartData"
                                :options="spotlightChartOptions"
                            />
                        </div>
                    </template>
                </PvCard>

                <PvCard class="dashboard-card">
                    <template #header>
                        <div class="flex items-center justify-between">
                            <h4 class="text-base font-semibold text-color">
                                Volume overview
                            </h4>
                            <PvTag value="Today" severity="secondary" rounded />
                        </div>
                    </template>
                    <template #content>
                        <div class="h-64">
                            <PvChart
                                v-if="totalsChartData"
                                type="bar"
                                :data="totalsChartData"
                                :options="totalsChartOptions"
                            />
                            <div
                                v-else
                                class="flex h-full items-center justify-center text-sm text-muted-color"
                            >
                                Totals unavailable
                            </div>
                        </div>
                    </template>
                </PvCard>
            </div>

            <div class="grid gap-4 xl:grid-cols-[1.4fr,1fr]">
                <PvCard class="dashboard-card">
                    <template #header>
                        <div class="flex items-center justify-between">
                            <h4 class="text-base font-semibold text-color">
                                Spotlight movers
                            </h4>
                            <PvTag
                                :value="`${spotlight.length} highlighted`"
                                severity="contrast"
                                rounded
                            />
                        </div>
                    </template>
                    <template #content>
                        <ul class="flex flex-col gap-4">
                            <li
                                v-for="product in spotlight"
                                :key="product.id"
                                class="flex flex-col gap-3 rounded-2xl border border-surface-200/60 bg-surface-0/60 p-4"
                            >
                                <div
                                    class="flex items-start justify-between gap-3"
                                >
                                    <div class="flex items-center gap-3">
                                        <span
                                            class="flex h-10 w-10 items-center justify-center rounded-full border border-primary-200/60 bg-primary-50 text-sm font-semibold text-primary-700"
                                        >
                                            {{
                                                product.name
                                                    .trim()
                                                    .charAt(0)
                                                    .toUpperCase() || '#'
                                            }}
                                        </span>
                                        <div class="flex flex-col">
                                            <span
                                                class="truncate-2 text-sm font-semibold text-color"
                                            >
                                                {{ product.name }}
                                            </span>
                                            <span
                                                class="text-xs text-muted-color"
                                            >
                                                {{
                                                    product.store_name ||
                                                    'Unknown store'
                                                }}
                                            </span>
                                        </div>
                                    </div>
                                    <PvBadge
                                        v-if="product.trend"
                                        :value="product.trend"
                                        :severity="trendSeverity(product.trend)"
                                    />
                                </div>
                                <div
                                    class="flex items-center justify-between text-sm"
                                >
                                    <span class="text-muted-color"
                                        >Current price</span
                                    >
                                    <span
                                        class="text-lg font-semibold text-color"
                                    >
                                        {{ formatPrice(product.current_price) }}
                                    </span>
                                </div>
                                <span class="text-xs text-muted-color">
                                    Last refreshed:
                                    {{
                                        formatDateTime(
                                            product.last_refreshed_at,
                                        )
                                    }}
                                </span>
                            </li>
                        </ul>
                        <p
                            v-if="spotlight.length === 0"
                            class="text-sm text-muted-color"
                        >
                            No spotlight products yet. They'll appear here after
                            the next refresh cycle.
                        </p>
                    </template>
                </PvCard>

                <PvCard class="dashboard-card">
                    <template #header>
                        <div class="flex items-center justify-between">
                            <h4 class="text-base font-semibold text-color">
                                Tag reach
                            </h4>
                            <PvTag
                                v-if="tagGroups.length"
                                :value="`${tagGroups.length} groups`"
                                severity="secondary"
                                rounded
                            />
                        </div>
                    </template>
                    <template #content>
                        <div v-if="tagDistributionChartData" class="h-64">
                            <PvChart
                                type="doughnut"
                                :data="tagDistributionChartData"
                                :options="tagDistributionOptions"
                            />
                        </div>
                        <div
                            v-else
                            class="flex h-64 items-center justify-center text-sm text-muted-color"
                        >
                            Tag grouping insights will appear after the next
                            refresh.
                        </div>
                    </template>
                </PvCard>
            </div>

            <div v-if="tagGroups.length" class="grid gap-4 xl:grid-cols-2">
                <PvCard
                    v-for="group in tagGroups"
                    :key="group.label"
                    class="dashboard-card"
                >
                    <template #header>
                        <div class="flex items-center justify-between">
                            <h5 class="text-base font-semibold text-color">
                                {{ group.label }}
                            </h5>
                            <PvTag
                                :value="`${group.products.length}`"
                                severity="contrast"
                                rounded
                            />
                        </div>
                    </template>
                    <template #content>
                        <div class="flex flex-col gap-3">
                            <div class="flex flex-wrap gap-2">
                                <PvTag
                                    v-for="product in group.products"
                                    :key="product.id"
                                    size="small"
                                    rounded
                                    severity="secondary"
                                    :value="product.name"
                                />
                            </div>
                        </div>
                    </template>
                </PvCard>
            </div>

            <span class="text-xs text-muted-color">
                Last updated: {{ formatDateTime(metrics.last_updated_at) }}
            </span>
        </div>
        <div
            v-else
            class="rounded-border border border-dashed border-surface-200/80 bg-surface-0/60 p-6 text-sm text-muted-color"
        >
            Metrics will populate once the first backend refresh completes.
        </div>
    </section>
</template>
