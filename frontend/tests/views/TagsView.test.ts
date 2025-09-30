import { h, defineComponent, PropType } from 'vue'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { render, fireEvent, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const get = vi.fn()
    const post = vi.fn()
    const patch = vi.fn()
    const del = vi.fn()
    return {
        apiClient: { get, post, patch, delete: del },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { get, post, patch, delete: del },
    }
})

import TagsView from '../../src/views/TagsView.vue'
import { apiClient } from '../../src/lib/http'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
    patch: ReturnType<typeof vi.fn>
    delete: ReturnType<typeof vi.fn>
}

type DropdownOption =
    | {
          id?: number | string
          value?: number | string
          name?: string
          label?: string
      }
    | string

const renderView = async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const utils = render(TagsView, {
        global: {
            plugins: [pinia],
            stubs: {
                PvButton: {
                    props: {
                        label: {
                            type: String,
                            default: '',
                        },
                    },
                    template:
                        '<button v-bind="$attrs"><slot />{{ label }}</button>',
                },
                PvInputText: defineComponent({
                    props: {
                        modelValue: {
                            type: [String, Number],
                            default: '',
                        },
                    },
                    emits: ['update:modelValue'],
                    setup(props, { emit, attrs }) {
                        return () =>
                            h('input', {
                                ...attrs,
                                value: props.modelValue ?? '',
                                onInput: (event: Event) =>
                                    emit(
                                        'update:modelValue',
                                        (event.target as HTMLInputElement)
                                            .value,
                                    ),
                            })
                    },
                }),
                PvDropdown: defineComponent({
                    props: {
                        modelValue: {
                            type: [String, Number],
                            default: '',
                        },
                        options: {
                            type: Array as PropType<DropdownOption[]>,
                            default: () => [],
                        },
                    },
                    emits: ['update:modelValue'],
                    setup(props, { emit }) {
                        return () =>
                            h(
                                'select',
                                {
                                    value: props.modelValue ?? '',
                                    onChange: (event: Event) =>
                                        emit(
                                            'update:modelValue',
                                            Number(
                                                (
                                                    event.target as HTMLSelectElement
                                                ).value,
                                            ),
                                        ),
                                },
                                [
                                    h('option', { value: '' }, ''),
                                    ...props.options.map((option) => {
                                        if (
                                            option &&
                                            typeof option === 'object'
                                        ) {
                                            const candidateValue =
                                                'value' in option
                                                    ? option.value
                                                    : option.id
                                            const label =
                                                'label' in option &&
                                                option.label
                                                    ? option.label
                                                    : 'name' in option
                                                      ? option.name
                                                      : (candidateValue ?? '')
                                            return h(
                                                'option',
                                                {
                                                    value: candidateValue ?? '',
                                                },
                                                label ?? '',
                                            )
                                        }
                                        return h(
                                            'option',
                                            { value: option ?? '' },
                                            option ?? '',
                                        )
                                    }),
                                ],
                            )
                    },
                }),
                PvCheckbox: defineComponent({
                    props: {
                        modelValue: {
                            type: [Boolean, Number],
                            default: false,
                        },
                    },
                    emits: ['update:modelValue'],
                    setup(props, { emit, attrs }) {
                        return () =>
                            h('input', {
                                ...attrs,
                                type: 'checkbox',
                                checked: Boolean(props.modelValue),
                                onChange: (event: Event) =>
                                    emit(
                                        'update:modelValue',
                                        (event.target as HTMLInputElement)
                                            .checked,
                                    ),
                            })
                    },
                }),
            },
        },
    })
    await waitFor(() => {
        expect(mocked.get).toHaveBeenCalledWith('/tags')
    })
    return utils
}

describe('TagsView', () => {
    let confirmSpy: ReturnType<typeof vi.spyOn>

    beforeEach(() => {
        mocked.get.mockReset()
        mocked.post.mockReset()
        mocked.patch.mockReset()
        mocked.delete.mockReset()
        mocked.get.mockResolvedValue({ data: [] })
        confirmSpy = vi.spyOn(window, 'confirm').mockImplementation(() => true)
    })

    afterEach(() => {
        confirmSpy.mockRestore()
    })

    it('renders tags and allows editing', async () => {
        mocked.get.mockResolvedValue({
            data: [{ id: 1, name: 'Clearance', slug: 'clearance' }],
        })
        mocked.patch.mockResolvedValue({
            data: { id: 1, name: 'Outlet', slug: 'outlet' },
        })

        const { getByRole, getByDisplayValue, getAllByText } =
            await renderView()

        expect(getAllByText('Clearance').length).toBeGreaterThan(0)

        await fireEvent.click(getByRole('button', { name: /edit/i }))

        const nameInput = getByDisplayValue('Clearance')
        const slugInput = getByDisplayValue('clearance')
        await fireEvent.update(nameInput, 'Outlet')
        await fireEvent.update(slugInput, 'outlet')

        await fireEvent.click(getByRole('button', { name: /save/i }))

        await waitFor(() => {
            expect(mocked.patch).toHaveBeenCalledWith('/tags/1', {
                name: 'Outlet',
                slug: 'outlet',
            })
            expect(getAllByText('Outlet').length).toBeGreaterThan(0)
        })
    })

    it('creates and deletes tags', async () => {
        mocked.post.mockResolvedValue({
            data: { id: 3, name: 'New Sale', slug: 'new-sale' },
        })
        mocked.delete.mockResolvedValue({ status: 204 })

        const { getByLabelText, getByRole, findAllByText, getAllByRole } =
            await renderView()

        const nameInput = getByLabelText(/^Name$/i)
        await fireEvent.update(nameInput, 'New Sale')

        await fireEvent.click(getByRole('button', { name: /create tag/i }))

        await waitFor(() => {
            expect(mocked.post).toHaveBeenCalledWith('/tags', {
                name: 'New Sale',
                slug: 'new-sale',
            })
        })

        const occurrences = await findAllByText('New Sale')
        expect(occurrences.length).toBeGreaterThan(0)

        const deleteButtons = getAllByRole('button', { name: /delete/i })
        await fireEvent.click(deleteButtons[0])

        await waitFor(() => {
            expect(mocked.delete).toHaveBeenCalledWith('/tags/3')
        })
    })

    it('merges tags via the merge form', async () => {
        mocked.get.mockResolvedValue({
            data: [
                { id: 1, name: 'Clearance', slug: 'clearance' },
                { id: 2, name: 'Sale', slug: 'sale' },
            ],
        })
        mocked.post.mockResolvedValue({
            data: {
                source_tag_id: 1,
                target_tag_id: 2,
                moved_links: 4,
                removed_duplicate_links: 1,
                deleted_source: true,
            },
        })

        const { getByLabelText, getByRole, findByText } = await renderView()

        const sourceSelect = getByLabelText(/^Source$/i)
        await fireEvent.update(sourceSelect, '1')
        const targetSelect = getByLabelText(/^Target$/i)
        await fireEvent.update(targetSelect, '2')

        mocked.get.mockResolvedValue({
            data: [{ id: 2, name: 'Sale', slug: 'sale' }],
        })

        await fireEvent.click(getByRole('button', { name: /merge tags/i }))

        await waitFor(() => {
            expect(mocked.post).toHaveBeenCalledWith('/tags/merge', {
                source_tag_id: 1,
                target_tag_id: 2,
                delete_source: true,
            })
        })
        expect(await findByText(/merged tags/i)).toBeTruthy()
    })
})
