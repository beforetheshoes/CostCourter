import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import SparklineChart from '../../src/components/SparklineChart.vue'

describe('SparklineChart', () => {
    it('renders a polyline for provided points', () => {
        const wrapper = mount(SparklineChart, {
            props: {
                points: [
                    { date: '2024-01-01', price: 10 },
                    { date: '2024-01-02', price: 15 },
                    { date: '2024-01-03', price: 12 },
                ],
            },
        })

        expect(wrapper.find('svg').exists()).toBe(true)
        const polyline = wrapper.find('polyline')
        expect(polyline.exists()).toBe(true)
        expect(polyline.attributes('points')).toContain(',')
        expect(wrapper.findAll('circle')).toHaveLength(1)
    })

    it('shows fallback when no data is available', () => {
        const wrapper = mount(SparklineChart, {
            props: { points: [] },
        })

        expect(wrapper.find('svg').exists()).toBe(false)
        expect(wrapper.text()).toContain('No data')
    })
})
