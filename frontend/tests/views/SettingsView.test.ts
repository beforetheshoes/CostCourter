import { h, defineComponent, PropType } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../../src/lib/http', () => {
    const post = vi.fn()
    const get = vi.fn()
    const put = vi.fn()
    return {
        apiClient: { post, get, put },
        createApiClient: vi.fn(),
        attachAuthInterceptor: vi.fn(),
        __mock: { post, get, put },
    }
})

vi.mock('primevue/config', () => ({
    usePrimeVue: () => ({ config: { theme: {} } }),
}))

import SettingsView from '../../src/views/SettingsView.vue'
import { apiClient } from '../../src/lib/http'

const mockedHttp = apiClient as unknown as {
    post: ReturnType<typeof vi.fn>
    get: ReturnType<typeof vi.fn>
    put: ReturnType<typeof vi.fn>
}
const { post: mockedPost, get: mockedGet, put: mockedPut } = mockedHttp

const originalCreateObjectURL = URL.createObjectURL
const originalRevokeObjectURL = URL.revokeObjectURL

const createButtonStub = () =>
    defineComponent({
        name: 'PvButtonStub',
        props: {
            label: { type: String, default: '' },
            loading: { type: Boolean, default: false },
        },
        emits: ['click'],
        setup(props, { emit, slots, attrs }) {
            return () =>
                h(
                    'button',
                    (() => {
                        const restAttrs = { ...attrs } as Record<
                            string,
                            unknown
                        >
                        const disabledAttr = restAttrs.disabled
                        delete restAttrs.disabled
                        const attrDisabled =
                            disabledAttr === '' ||
                            disabledAttr === true ||
                            disabledAttr === 'true'
                        const handleClick = () => {
                            if (props.loading || attrDisabled) return
                            emit('click')
                        }
                        return {
                            type: 'button',
                            ...restAttrs,
                            disabled: props.loading || attrDisabled,
                            onClick: handleClick,
                        }
                    })(),
                    slots.default ? slots.default() : props.label,
                )
        },
    })

const createCardStub = () =>
    defineComponent({
        name: 'PvCardStub',
        setup(_, { slots, attrs }) {
            return () =>
                h('section', attrs, [
                    slots.header ? h('header', slots.header()) : null,
                    h(
                        'div',
                        {},
                        slots.content
                            ? slots.content()
                            : (slots.default?.() ?? null),
                    ),
                ])
        },
    })

const createInputTextStub = () =>
    defineComponent({
        name: 'PvInputTextStub',
        props: {
            modelValue: { type: [String, Number], default: '' },
        },
        emits: ['update:modelValue'],
        setup(props, { emit, attrs }) {
            return () =>
                h('input', {
                    ...attrs,
                    value: props.modelValue,
                    onInput: (event: Event) =>
                        emit(
                            'update:modelValue',
                            (event.target as HTMLInputElement).value,
                        ),
                })
        },
    })

describe('SettingsView', () => {
    beforeEach(() => {
        setActivePinia(createPinia())
        window.localStorage.clear()
        mockedPost.mockReset()
        mockedGet.mockReset()
        mockedPut.mockReset()
        mockedGet.mockResolvedValue({
            data: { entries: [] },
        })
        mockedPut.mockResolvedValue({
            data: { entries: [] },
        })
    })

    const TagPanelStub = defineComponent({
        name: 'TagManagementPanelStub',
        setup() {
            return () => h('div', { 'data-testid': 'tags-panel' }, 'Tags panel')
        },
    })

    afterEach(() => {
        if (originalCreateObjectURL) {
            ;(
                URL as unknown as {
                    createObjectURL: typeof originalCreateObjectURL
                }
            ).createObjectURL = originalCreateObjectURL
        } else {
            delete (URL as { createObjectURL?: typeof URL.createObjectURL })
                .createObjectURL
        }
        if (originalRevokeObjectURL) {
            ;(
                URL as unknown as {
                    revokeObjectURL: typeof originalRevokeObjectURL
                }
            ).revokeObjectURL = originalRevokeObjectURL
        } else {
            delete (URL as { revokeObjectURL?: typeof URL.revokeObjectURL })
                .revokeObjectURL
        }
    })

    type SelectOption = {
        value: string | number
        label?: string
        name?: string
    }

    const DropdownStub = defineComponent({
        name: 'PvDropdownStub',
        props: {
            modelValue: { type: [String, Number, Object], default: null },
            options: {
                type: Array as PropType<SelectOption[]>,
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
                                (event.target as HTMLSelectElement).value,
                            ),
                    },
                    props.options.map((option) =>
                        h(
                            'option',
                            { value: option.value },
                            option.label ?? option.name ?? option.value,
                        ),
                    ),
                )
        },
    })

    const CheckboxStub = defineComponent({
        name: 'PvCheckboxStub',
        props: { modelValue: { type: Boolean, default: false } },
        emits: ['update:modelValue'],
        setup(props, { emit }) {
            return () =>
                h('input', {
                    type: 'checkbox',
                    checked: props.modelValue,
                    onChange: (event: Event) =>
                        emit(
                            'update:modelValue',
                            (event.target as HTMLInputElement).checked,
                        ),
                })
        },
    })

    const SelectButtonStub = defineComponent({
        name: 'PvSelectButtonStub',
        props: {
            modelValue: { type: [String, Number], default: null },
            options: {
                type: Array as PropType<SelectOption[]>,
                default: () => [],
            },
        },
        emits: ['update:modelValue'],
        setup(props, { emit }) {
            return () =>
                h(
                    'div',
                    { role: 'group' },
                    props.options.map((option) =>
                        h(
                            'button',
                            {
                                type: 'button',
                                'data-value': option.value,
                                onClick: () =>
                                    emit('update:modelValue', option.value),
                            },
                            option.label ?? option.value,
                        ),
                    ),
                )
        },
    })

    const renderView = () =>
        render(SettingsView, {
            global: {
                stubs: {
                    RouterLink: defineComponent({
                        props: {
                            to: { type: [String, Object], required: true },
                        },
                        setup(props, { slots }) {
                            return () =>
                                h(
                                    'a',
                                    { href: String(props.to) },
                                    slots.default?.(),
                                )
                        },
                    }),
                    PvButton: createButtonStub(),
                    PvCard: createCardStub(),
                    PvInputText: createInputTextStub(),
                    PvInputTextarea: defineComponent({
                        name: 'PvInputTextareaStub',
                        props: { modelValue: { type: String, default: '' } },
                        emits: ['update:modelValue'],
                        setup(props, { emit }) {
                            return () =>
                                h('textarea', {
                                    value: props.modelValue,
                                    onInput: (event: Event) =>
                                        emit(
                                            'update:modelValue',
                                            (
                                                event.target as HTMLTextAreaElement
                                            ).value,
                                        ),
                                })
                        },
                    }),
                    PvCheckbox: CheckboxStub,
                    PvDropdown: DropdownStub,
                    PvSelectButton: SelectButtonStub,
                    TagManagementPanel: TagPanelStub,
                    NotificationPreferencesPanel: defineComponent({
                        name: 'NotificationPreferencesPanelStub',
                        setup() {
                            return () =>
                                h(
                                    'div',
                                    { 'data-testid': 'notifications-panel' },
                                    'Notifications panel',
                                )
                        },
                    }),
                },
            },
        })

    it('triggers refresh when authenticated', async () => {
        window.localStorage.setItem(
            'costcourter.tokens',
            JSON.stringify({ accessToken: 'token', tokenType: 'Bearer' }),
        )
        mockedPost.mockResolvedValue({
            data: {
                total_urls: 1,
                successful_urls: 0,
                failed_urls: 1,
                results: [
                    {
                        product_url_id: 201,
                        success: false,
                        price: null,
                        currency: null,
                        reason: 'http_error',
                    },
                ],
            },
        })

        const { getByRole, getByText, findByRole } = renderView()
        const refreshButton = getByRole('button', {
            name: /refresh all prices/i,
        })
        refreshButton.click()

        await waitFor(() => {
            expect(mockedPost).toHaveBeenCalledWith(
                '/pricing/products/fetch-all',
                undefined,
                { params: { logging: true } },
            )
            expect(getByText(/urls processed/i)).toBeTruthy()
        })

        const resultTable = await findByRole('table', {
            name: /price fetch results/i,
        })
        expect(resultTable.textContent).toContain('201')
        expect(resultTable.textContent).toContain('Failed')
        expect(resultTable.textContent).toContain('http_error')
    })

    it('saves schedule updates via JSON editor', async () => {
        mockedGet.mockResolvedValueOnce({
            data: {
                entries: [
                    {
                        name: 'pricing.update_all_products',
                        task: 'pricing.update_all_products',
                        schedule: null,
                        enabled: true,
                        args: [],
                        kwargs: { logging: false },
                        minute: 0,
                        hour: '*/6',
                        day_of_week: '*',
                        day_of_month: '*',
                        month_of_year: '*',
                        last_run_at: null,
                        next_run_at: '2025-09-29T00:00:00Z',
                    },
                ],
            },
        })
        mockedPut.mockResolvedValueOnce({
            data: {
                entries: [
                    {
                        name: 'pricing.update_all_products',
                        task: 'pricing.update_all_products',
                        schedule: 7200,
                        enabled: false,
                        args: [],
                        kwargs: { logging: false },
                        minute: 15,
                        hour: '*/3',
                        day_of_week: '*',
                        day_of_month: '*',
                        month_of_year: '*',
                        last_run_at: null,
                        next_run_at: '2025-09-29T00:00:00Z',
                    },
                ],
            },
        })

        const { findByRole, getByRole } = renderView()

        const toggleJsonButton = await findByRole('button', {
            name: /toggle json editor/i,
        })
        await fireEvent.click(toggleJsonButton)

        const textarea = document.querySelector(
            'textarea',
        ) as HTMLTextAreaElement
        const updatedJson = JSON.stringify(
            [
                {
                    name: 'pricing.update_all_products',
                    task: 'pricing.update_all_products',
                    schedule: 7200,
                    enabled: false,
                    args: [],
                    kwargs: { logging: false },
                    minute: 15,
                    hour: '*/3',
                    day_of_week: '*',
                    day_of_month: '*',
                    month_of_year: '*',
                },
            ],
            null,
            2,
        )
        await fireEvent.update(textarea, updatedJson)

        const saveButton = getByRole('button', { name: /save schedule/i })
        await fireEvent.click(saveButton)

        await waitFor(() => {
            expect(mockedPut).toHaveBeenCalled()
        })
    })

    it('toggles schedule entries between enabled and disabled', async () => {
        mockedGet.mockResolvedValueOnce({
            data: {
                entries: [
                    {
                        name: 'pricing.update_all_products',
                        task: 'pricing.update_all_products',
                        schedule: 3600,
                        enabled: true,
                        args: [],
                        kwargs: {},
                        minute: null,
                        hour: null,
                        day_of_week: '*',
                        day_of_month: '*',
                        month_of_year: '*',
                        last_run_at: null,
                        next_run_at: null,
                    },
                ],
            },
        })
        mockedPut.mockResolvedValueOnce({
            data: {
                entries: [
                    {
                        name: 'pricing.update_all_products',
                        task: 'pricing.update_all_products',
                        schedule: 3600,
                        enabled: false,
                        args: [],
                        kwargs: {},
                        minute: null,
                        hour: null,
                        day_of_week: '*',
                        day_of_month: '*',
                        month_of_year: '*',
                        last_run_at: null,
                        next_run_at: null,
                    },
                ],
            },
        })

        const { findByRole } = renderView()

        const toggleButton = await findByRole('button', { name: /disable/i })
        await fireEvent.click(toggleButton)

        await waitFor(() => {
            expect(mockedPut).toHaveBeenCalledTimes(1)
        })

        const [, payload] = mockedPut.mock.calls[0] ?? []
        expect(payload).toBeDefined()
        expect(payload.entries[0]?.enabled).toBe(false)

        const enableButton = await findByRole('button', { name: /enable/i })
        expect(enableButton).toBeTruthy()
    })

    it('edits an existing schedule entry via inline form', async () => {
        mockedGet.mockResolvedValueOnce({
            data: {
                entries: [
                    {
                        name: 'pricing.update_all_products',
                        task: 'pricing.update_all_products',
                        schedule: 3600,
                        enabled: true,
                        args: [],
                        kwargs: {},
                        minute: null,
                        hour: null,
                        day_of_week: '*',
                        day_of_month: '*',
                        month_of_year: '*',
                        last_run_at: null,
                        next_run_at: null,
                    },
                ],
            },
        })
        mockedPut.mockResolvedValueOnce({
            data: {
                entries: [
                    {
                        name: 'pricing.update_all_products',
                        task: 'pricing.update_all_products',
                        schedule: { cron: '@hourly' },
                        enabled: false,
                        args: [],
                        kwargs: {},
                        minute: 15,
                        hour: '*/2',
                        day_of_week: '*',
                        day_of_month: 1,
                        month_of_year: 'Jan',
                        last_run_at: null,
                        next_run_at: null,
                    },
                ],
            },
        })

        const { findByRole, findByLabelText, findAllByText } = renderView()

        await findAllByText('pricing.update_all_products')
        await fireEvent.click(await findByRole('button', { name: /^Edit$/i }))

        const intervalInput = await findByLabelText(/Interval \/ schedule/i)
        await fireEvent.update(intervalInput, '{"cron":"@hourly"}')
        await fireEvent.update(await findByLabelText(/^Minute$/i), '15')
        await fireEvent.update(await findByLabelText(/^Hour$/i), '*/2')
        await fireEvent.update(await findByLabelText(/Day of month/i), '1')
        await fireEvent.update(await findByLabelText(/Month of year/i), 'Jan')
        const enabledCheckbox = await findByLabelText(/Enabled/i)
        await fireEvent.click(enabledCheckbox)

        await fireEvent.click(
            await findByRole('button', { name: /save changes/i }),
        )

        await waitFor(() => {
            expect(mockedPut).toHaveBeenCalledWith('/pricing/schedule', {
                entries: [
                    {
                        name: 'pricing.update_all_products',
                        task: 'pricing.update_all_products',
                        schedule: { cron: '@hourly' },
                        enabled: false,
                        args: [],
                        kwargs: {},
                        minute: 15,
                        hour: '*/2',
                        day_of_week: '*',
                        day_of_month: 1,
                        month_of_year: 'Jan',
                    },
                ],
            })
        })
    })

    it('exports a products backup and surfaces a success message', async () => {
        const backupPayload = {
            version: 1,
            exported_at: '2024-01-01T00:00:00Z',
            products: [
                {
                    product: {
                        name: 'Widget',
                        slug: 'widget',
                        description: null,
                        is_active: true,
                        status: 'published',
                        favourite: true,
                        only_official: false,
                        notify_price: null,
                        notify_percent: null,
                        ignored_urls: [],
                        image_url: null,
                        tag_slugs: [],
                        tags: [],
                    },
                    urls: [],
                    price_history: [],
                },
            ],
        }

        mockedGet.mockResolvedValueOnce({ data: { entries: [] } })
        mockedGet.mockResolvedValueOnce({ data: backupPayload })

        const objectUrlSpy = vi.fn(() => 'blob:mock')
        const revokeSpy = vi.fn()
        ;(
            URL as unknown as { createObjectURL: typeof objectUrlSpy }
        ).createObjectURL = objectUrlSpy
        ;(
            URL as unknown as { revokeObjectURL: typeof revokeSpy }
        ).revokeObjectURL = revokeSpy

        const { findByRole, findByText } = renderView()

        const exportButton = await findByRole('button', {
            name: /export products json/i,
        })
        await fireEvent.click(exportButton)

        await waitFor(() => {
            expect(mockedGet).toHaveBeenCalledWith('/backups/products')
            expect(objectUrlSpy).toHaveBeenCalled()
        })

        expect(await findByText(/exported 1 product/i)).toBeTruthy()
    })

    it('imports a products backup from a JSON file', async () => {
        const backupPayload = {
            version: 1,
            exported_at: '2024-01-01T00:00:00Z',
            products: [
                {
                    product: {
                        name: 'Widget',
                        slug: 'widget',
                        description: null,
                        is_active: true,
                        status: 'published',
                        favourite: true,
                        only_official: false,
                        notify_price: null,
                        notify_percent: null,
                        ignored_urls: [],
                        image_url: null,
                        tag_slugs: [],
                        tags: [],
                    },
                    urls: [
                        {
                            url: 'https://example.com/widget',
                            is_primary: true,
                            active: true,
                            store: {
                                slug: 'example',
                                name: 'Example',
                                website_url: 'https://example.com',
                                active: true,
                                locale: null,
                                currency: 'USD',
                                domains: [],
                                scrape_strategy: {},
                                settings: {},
                                notes: null,
                            },
                        },
                    ],
                    price_history: [
                        {
                            price: 42,
                            currency: 'USD',
                            recorded_at: '2024-01-01T00:00:00Z',
                            url: 'https://example.com/widget',
                        },
                    ],
                },
            ],
        }

        const importSummary = {
            products_created: 1,
            products_updated: 0,
            product_urls_created: 1,
            product_urls_updated: 0,
            price_history_created: 1,
            price_history_skipped: 0,
            stores_created: 1,
            stores_updated: 0,
            tags_created: 0,
            tags_updated: 0,
        }

        mockedGet.mockResolvedValueOnce({ data: { entries: [] } })
        mockedPost.mockResolvedValueOnce({ data: importSummary })

        const { getByLabelText, getByRole, findByText } = renderView()

        const fileInput = getByLabelText(/backup file/i) as HTMLInputElement
        const file = {
            name: 'backup.json',
            text: () => Promise.resolve(JSON.stringify(backupPayload)),
        } as unknown as File
        await fireEvent.change(fileInput, { target: { files: [file] } })

        const importButton = getByRole('button', { name: /import backup/i })

        await waitFor(() => {
            expect(importButton).not.toBeDisabled()
        })

        await fireEvent.click(importButton)

        await waitFor(() => {
            expect(mockedPost).toHaveBeenCalledWith(
                '/backups/products',
                backupPayload,
            )
        })

        expect(await findByText(/1 product/)).toBeTruthy()
    })

    it('updates appearance preferences and reacts to broadcast events', async () => {
        const { getByLabelText, getByRole } = renderView()

        const displayDropdown = getByLabelText(
            /Display mode/i,
        ) as HTMLSelectElement
        await fireEvent.change(displayDropdown, { target: { value: 'dark' } })
        expect(displayDropdown.value).toBe('dark')

        const tableButton = getByRole('button', { name: /Table view/i })
        await fireEvent.click(tableButton)
        expect(
            window.localStorage.getItem('costcourter.products.defaultView'),
        ).toBe('table')

        const emberButton = getByRole('button', { name: /Ember Glow/i })
        await fireEvent.click(emberButton)
        expect(emberButton.getAttribute('aria-pressed')).toBe('true')

        window.dispatchEvent(
            new CustomEvent('costcourter:brand-theme-changed', {
                detail: { id: 'lagoon' },
            }),
        )
        await waitFor(() => {
            const lagoonButton = getByRole('button', { name: /Lagoon/i })
            expect(lagoonButton.getAttribute('aria-pressed')).toBe('true')
        })

        window.dispatchEvent(
            new CustomEvent('costcourter:color-mode-changed', {
                detail: { mode: 'light' },
            }),
        )
        await waitFor(() => expect(displayDropdown.value).toBe('light'))

        window.dispatchEvent(
            new CustomEvent('costcourter:color-mode-changed', { detail: {} }),
        )
        await waitFor(() => expect(displayDropdown.value).toBe('light'))
    })

    it('clears backup selections when requested', async () => {
        const backupPayload = {
            version: 1,
            exported_at: '2024-01-01T00:00:00Z',
            products: [],
        }

        const { getByLabelText, getByRole, findByText, queryByText } =
            renderView()

        const fileInput = getByLabelText(/backup file/i) as HTMLInputElement
        const file = {
            name: 'backup.json',
            text: () => Promise.resolve(JSON.stringify(backupPayload)),
        } as unknown as File
        await fireEvent.change(fileInput, { target: { files: [file] } })

        expect(await findByText(/Selected: backup.json/)).toBeTruthy()

        await fireEvent.click(getByRole('button', { name: /clear selection/i }))

        await waitFor(() => {
            expect(queryByText(/Selected:/)).toBeNull()
        })
        expect(getByRole('button', { name: /import backup/i })).toBeDisabled()
    })

    it('surfaces validation errors when a backup file is malformed', async () => {
        const { getByLabelText, findByText, getByRole } = renderView()

        const fileInput = getByLabelText(/backup file/i) as HTMLInputElement
        const invalidFile = {
            name: 'invalid-backup.json',
            text: () => Promise.resolve('{"version":1}'),
        } as unknown as File

        await fireEvent.change(fileInput, { target: { files: [invalidFile] } })

        expect(
            await findByText('Backup is missing product entries'),
        ).toBeTruthy()
        const importButton = getByRole('button', { name: /import backup/i })
        expect(importButton).toBeDisabled()
    })

    it('shows an error message when backup import fails', async () => {
        const backupPayload = {
            version: 1,
            exported_at: '2024-01-01T00:00:00Z',
            products: [],
        }

        mockedPost.mockRejectedValueOnce(new Error('import failed'))

        const { getByLabelText, getByRole, findByText } = renderView()
        const fileInput = getByLabelText(/backup file/i) as HTMLInputElement
        const file = {
            name: 'backup.json',
            text: () => Promise.resolve(JSON.stringify(backupPayload)),
        } as unknown as File
        await fireEvent.change(fileInput, { target: { files: [file] } })

        const importButton = getByRole('button', { name: /import backup/i })
        await waitFor(() => expect(importButton).not.toBeDisabled())

        await fireEvent.click(importButton)

        expect(await findByText('import failed')).toBeTruthy()
    })

    it('handles backup export failures gracefully', async () => {
        mockedGet
            .mockResolvedValueOnce({ data: { entries: [] } })
            .mockRejectedValueOnce(new Error('export failed'))
        const objectUrlSpy = vi.fn(() => 'blob:mock')
        const revokeSpy = vi.fn()
        ;(
            URL as unknown as { createObjectURL: typeof objectUrlSpy }
        ).createObjectURL = objectUrlSpy
        ;(
            URL as unknown as { revokeObjectURL: typeof revokeSpy }
        ).revokeObjectURL = revokeSpy

        const { getByRole, findByText } = renderView()

        await fireEvent.click(
            getByRole('button', { name: /export products json/i }),
        )

        expect(await findByText('export failed')).toBeTruthy()
        expect(objectUrlSpy).not.toHaveBeenCalled()
    })
})
