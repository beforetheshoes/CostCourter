<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
    Chart,
    Filler,
    Legend,
    LineController,
    LineElement,
    LinearScale,
    PointElement,
    TimeScale,
    Tooltip,
    type ChartDataset,
    type ChartOptions,
    type ChartData,
} from 'chart.js'
import 'chartjs-adapter-date-fns'

import type { ProductURL } from '../stores/useProductsStore'

Chart.register(
    LineController,
    LineElement,
    PointElement,
    LinearScale,
    TimeScale,
    Tooltip,
    Legend,
    Filler,
)

type HistoryEntry = {
    id: number
    product_url_id: number | null
    price: number
    currency: string
    recorded_at: string
}

const props = defineProps<{
    entries: HistoryEntry[]
    urls: ProductURL[]
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
let chart: Chart<'line'> | null = null

const colorPalette = computed(() => {
    const base = [
        '#2563eb',
        '#16a34a',
        '#dc2626',
        '#9333ea',
        '#f97316',
        '#0891b2',
        '#d946ef',
        '#10b981',
    ]
    return base
})

const datasets = computed<ChartDataset<'line'>[]>(() => {
    if (!props.entries.length) {
        return []
    }

    const grouped = new Map<number | 'manual', HistoryEntry[]>()
    for (const entry of props.entries) {
        const key = entry.product_url_id ?? 'manual'
        const existing = grouped.get(key) ?? []
        existing.push(entry)
        grouped.set(key, existing)
    }

    const items: ChartDataset<'line'>[] = []
    let index = 0
    for (const [key, entries] of grouped.entries()) {
        const color = colorPalette.value[index % colorPalette.value.length]
        index += 1
        const urlName =
            key === 'manual'
                ? 'Manual updates'
                : (props.urls.find((url) => url.id === key)?.store?.name ??
                  'Tracked URL')
        const sorted = [...entries].sort(
            (a, b) =>
                new Date(a.recorded_at).getTime() -
                new Date(b.recorded_at).getTime(),
        )
        const sampleCurrency =
            sorted.find((entry) => entry.currency)?.currency ?? null
        items.push({
            label: urlName,
            data: sorted.map((entry) => ({
                x: entry.recorded_at,
                y: entry.price,
            })),
            borderColor: color,
            backgroundColor: `${color}33`,
            fill: false,
            tension: 0.3,
            pointRadius: 3,
            // @ts-expect-error - custom field for tooltip formatting
            currency: sampleCurrency,
        })
    }
    return items
})

const chartData = computed<ChartData<'line'>>(() => ({
    datasets: datasets.value,
}))

const options = computed<ChartOptions<'line'>>(() => ({
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
        legend: {
            display: true,
            position: 'bottom',
        },
        tooltip: {
            callbacks: {
                label: (context) => {
                    const value = context.parsed.y
                    const label = context.dataset.label ?? ''
                    // @ts-expect-error - read custom currency metadata
                    const currency = context.dataset.currency as
                        | string
                        | null
                        | undefined
                    const valuePart =
                        typeof value === 'number' ? value.toFixed(2) : value
                    return `${label}: ${currency ? `${currency} ` : ''}${valuePart}`
                },
            },
        },
    },
    scales: {
        x: {
            type: 'time',
            time: {
                unit: 'day',
                tooltipFormat: 'PPpp',
            },
            ticks: {
                maxRotation: 0,
                autoSkipPadding: 16,
            },
        },
        y: {
            beginAtZero: false,
            ticks: {
                callback: (value) =>
                    typeof value === 'number'
                        ? value.toFixed(2)
                        : String(value),
            },
        },
    },
}))

const destroyChart = () => {
    if (chart) {
        chart.destroy()
        chart = null
    }
}

const renderChart = () => {
    const canvas = canvasRef.value
    if (!canvas) return
    destroyChart()
    chart = new Chart(canvas, {
        type: 'line',
        data: chartData.value,
        options: options.value,
    })
}

onMounted(() => {
    if (datasets.value.length) {
        renderChart()
    }
})

watch([datasets, options], () => {
    if (!canvasRef.value) return
    if (!datasets.value.length) {
        destroyChart()
        return
    }
    if (!chart) {
        renderChart()
    } else {
        chart.data = chartData.value
        chart.options = options.value
        chart.update()
    }
})

onBeforeUnmount(() => {
    destroyChart()
})
</script>

<template>
    <div class="h-72">
        <canvas v-if="entries.length" ref="canvasRef"></canvas>
        <p v-else class="text-sm text-muted-color text-center py-6">
            No historical price data available yet.
        </p>
    </div>
</template>
