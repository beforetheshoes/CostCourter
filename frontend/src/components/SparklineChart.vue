<script setup lang="ts">
import { computed } from 'vue'

type Point = {
    date: string
    price: number
}

const props = defineProps<{ points: Point[] }>()

const width = 320
const height = 96
const padding = 8

const chartPoints = computed(() => {
    if (props.points.length === 0)
        return [] as Array<Point & { x: number; y: number }>

    const prices = props.points.map((point) => point.price)
    const min = Math.min(...prices)
    const max = Math.max(...prices)
    const span = max - min
    const range = span === 0 ? 1 : span
    const lastIndex = Math.max(props.points.length - 1, 1)

    return props.points.map((point, index) => {
        const x = padding + (index / lastIndex) * (width - padding * 2)
        const y =
            height -
            padding -
            ((point.price - min) / range) * (height - padding * 2)
        return { ...point, x, y }
    })
})

const polylinePoints = computed(() =>
    chartPoints.value.map((point) => `${point.x},${point.y}`).join(' '),
)

const lastPoint = computed(() =>
    chartPoints.value.length > 0
        ? chartPoints.value[chartPoints.value.length - 1]
        : null,
)
</script>

<template>
    <svg
        v-if="chartPoints.length"
        :viewBox="`0 0 ${width} ${height}`"
        class="w-full h-full text-primary"
        role="img"
        aria-label="Price trend sparkline"
    >
        <polyline
            :points="polylinePoints"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
        />
        <circle
            v-if="lastPoint"
            :cx="lastPoint.x"
            :cy="lastPoint.y"
            r="3"
            fill="currentColor"
        />
    </svg>
    <div v-else class="text-sm text-muted-color text-center py-4">No data</div>
</template>
