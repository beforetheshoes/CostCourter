import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/vue'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'

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

import StoresView from '../../src/views/StoresView.vue'
import { apiClient } from '../../src/lib/http'

const mocked = apiClient as unknown as {
    get: ReturnType<typeof vi.fn>
    post: ReturnType<typeof vi.fn>
    patch: ReturnType<typeof vi.fn>
    delete: ReturnType<typeof vi.fn>
}

const CardStub = defineComponent({
    setup(_, { slots, attrs }) {
        return () =>
            h('section', attrs, [
                slots.header ? h('header', slots.header()) : null,
                slots.content ? slots.content() : slots.default?.(),
            ])
    },
})

const ButtonStub = defineComponent({
    inheritAttrs: false,
    props: {
        label: { type: String, default: '' },
        icon: { type: String, default: '' },
    },
    emits: ['click'],
    setup(props, { emit, slots, attrs }) {
        return () => {
            const forwarded = { ...attrs }
            if (!('type' in forwarded)) {
                forwarded.type = 'button'
            }
            return h(
                'button',
                {
                    ...forwarded,
                    'data-icon': props.icon,
                    onClick: (event: Event) => emit('click', event),
                },
                slots.default?.() ?? props.label,
            )
        }
    },
})

const InputStub = defineComponent({
    props: {
        modelValue: { type: [String, Number], default: '' },
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
                        (event.target as HTMLInputElement).value,
                    ),
            })
    },
})

const renderView = async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    return render(StoresView, {
        global: {
            plugins: [pinia],
            stubs: {
                PvCard: CardStub,
                PvButton: ButtonStub,
                PvInputText: InputStub,
            },
        },
    })
}

beforeEach(() => {
    mocked.get.mockReset()
    mocked.post.mockReset()
    mocked.patch.mockReset()
    mocked.delete.mockReset()
})

describe('StoresView', () => {
    it('validates create form before submitting and creates store on success', async () => {
        mocked.get.mockResolvedValue({ data: [] })
        mocked.post.mockResolvedValue({
            data: {
                id: 10,
                name: 'Fresh Mart',
                slug: 'fresh-mart',
                website_url: 'https://fresh.example',
                active: true,
                domains: [{ domain: 'fresh.example' }],
                scrape_strategy: {},
                settings: {},
                notes: null,
                locale: 'en_US',
                currency: 'USD',
            },
        })

        const view = await renderView()
        const form = view.container.querySelector('form') as HTMLFormElement

        await fireEvent.submit(form)
        await waitFor(() =>
            expect(view.container.textContent).toContain(
                'Add at least one domain',
            ),
        )

        const inputs = form.querySelectorAll('input')
        const [nameInput, slugInput, websiteInput, localeInput, currencyInput] =
            Array.from(inputs).slice(0, 5)

        await fireEvent.update(nameInput, 'Fresh Mart')
        await fireEvent.update(slugInput, 'fresh-mart')
        await fireEvent.update(websiteInput, 'https://fresh.example')
        await fireEvent.update(localeInput, 'en_US')
        await fireEvent.update(currencyInput, 'usd')

        const selectorInputs = Array.from(inputs).slice(5)
        await fireEvent.update(selectorInputs[0], 'css')
        await fireEvent.update(selectorInputs[1], '.title')
        await fireEvent.update(selectorInputs[2], 'json')
        await fireEvent.update(selectorInputs[3], '$.price')
        await fireEvent.update(selectorInputs[4], 'attr')
        await fireEvent.update(selectorInputs[5], 'img::src')

        const domainsArea = form.querySelector(
            'textarea',
        ) as HTMLTextAreaElement
        await fireEvent.update(domainsArea, 'fresh.example\nshop.fresh.example')

        await fireEvent.submit(form)

        await waitFor(() => expect(mocked.post).toHaveBeenCalled())
        const [, payload] = mocked.post.mock.calls[0]
        expect(payload).toMatchObject({
            name: 'Fresh Mart',
            slug: 'fresh-mart',
            domains: [
                { domain: 'fresh.example' },
                { domain: 'shop.fresh.example' },
            ],
            currency: 'USD',
        })
        await waitFor(() => {
            expect((nameInput as HTMLInputElement).value).toBe('')
            expect(domainsArea.value).toBe('')
        })
    })

    it('prefills edit form, saves updates, and handles delete failures', async () => {
        const existing = {
            id: 7,
            name: 'Legacy Shop',
            slug: 'legacy-shop',
            website_url: 'https://legacy.example',
            active: true,
            domains: [{ domain: 'legacy.example' }],
            scrape_strategy: {
                title: { type: 'css', value: '.title' },
                price: { type: 'json', value: '$.price' },
                image: { type: 'attr', value: 'img::src' },
            },
            settings: {},
            notes: 'Original notes',
            locale: 'en_US',
            currency: 'usd',
        }
        mocked.get.mockResolvedValue({ data: [existing] })
        mocked.patch.mockResolvedValue({
            data: { ...existing, name: 'Legacy Hub' },
        })
        mocked.delete.mockRejectedValue({
            response: { data: { detail: 'In use' } },
        })
        const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

        const view = await renderView()

        await screen.findByText('Legacy Shop')
        await fireEvent.click(screen.getByRole('button', { name: /edit/i }))

        const forms = view.container.querySelectorAll('form')
        const editForm = forms[1] as HTMLFormElement
        const editInputs = editForm.querySelectorAll('input')
        const nameInput = editInputs[0] as HTMLInputElement
        expect(nameInput.value).toBe('Legacy Shop')

        await fireEvent.update(nameInput, 'Legacy Hub')
        const localeInput = editInputs[3] as HTMLInputElement
        await fireEvent.update(localeInput, 'fr_FR')
        const domainsArea = editForm.querySelector(
            'textarea',
        ) as HTMLTextAreaElement
        await fireEvent.update(domainsArea, 'legacy.example\nlegacy.fr')

        await fireEvent.click(
            screen.getByRole('button', { name: /save changes/i }),
        )

        await waitFor(() => expect(mocked.patch).toHaveBeenCalled())
        const [, updatePayload] = mocked.patch.mock.calls[0]
        expect(updatePayload).toMatchObject({
            name: 'Legacy Hub',
            locale: 'fr_FR',
            domains: [{ domain: 'legacy.example' }, { domain: 'legacy.fr' }],
        })

        await fireEvent.click(screen.getByRole('button', { name: /delete/i }))
        await waitFor(() => expect(mocked.delete).toHaveBeenCalled())
        await screen.findByText('In use')
        expect(confirmSpy).toHaveBeenCalled()

        confirmSpy.mockRestore()
    })
})
