import { definePreset, type Preset } from '@primeuix/themes'
import Aura from '@primeuix/themes/aura'

export const brandThemeIds = ['aurora', 'lagoon', 'ember'] as const

export type BrandThemeId = (typeof brandThemeIds)[number]

export type BrandThemePreview = {
    primary: string
    secondary: string
}

export type BrandThemeDefinition = {
    id: BrandThemeId
    label: string
    description: string
    preset: Preset
    preview: BrandThemePreview
}

type BrandThemeRecipe = {
    label: string
    description: string
    preview: BrandThemePreview
    overrides: Record<string, unknown>
}

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value))

const deepMerge = (
    target: Record<string, unknown>,
    source: Record<string, unknown>,
) => {
    const output: Record<string, unknown> = Array.isArray(target)
        ? [...(target as unknown[])]
        : { ...target }
    Object.entries(source).forEach(([key, value]) => {
        if (value && typeof value === 'object' && !Array.isArray(value)) {
            const baseValue = output[key]
            output[key] = deepMerge(
                baseValue &&
                    typeof baseValue === 'object' &&
                    !Array.isArray(baseValue)
                    ? (baseValue as Record<string, unknown>)
                    : {},
                value as Record<string, unknown>,
            )
        } else {
            output[key] = value
        }
    })
    return output
}

const baseOverrides = {
    primitive: {
        borderRadius: {
            sm: '0.65rem',
            md: '0.9rem',
            lg: '1.15rem',
            xl: '1.65rem',
        },
    },
    semantic: {
        focusRing: {
            width: '2px',
            style: 'solid',
            color: '{primary.300}',
            offset: '3px',
            shadow: '0 0 0 2px color-mix(in srgb, {primary.100} 60%, transparent)',
        },
        content: {
            borderRadius: '1.15rem',
        },
        navigation: {
            item: {
                borderRadius: '999px',
                padding: '0.6rem 0.9rem',
                gap: '0.6rem',
            },
        },
        overlay: {
            popover: {
                borderRadius: '1.25rem',
                padding: '1.25rem',
                shadow: '0 30px 45px -25px rgba(15, 23, 42, 0.35)',
            },
            modal: {
                borderRadius: '1.75rem',
                padding: '1.75rem',
                shadow: '0 55px 80px -45px rgba(15, 23, 42, 0.45)',
            },
        },
        colorScheme: {
            light: {
                primary: {
                    color: '{primary.600}',
                    contrastColor: '#ffffff',
                    hoverColor: '{primary.700}',
                    activeColor: '{primary.800}',
                },
                highlight: {
                    background:
                        'color-mix(in srgb, {primary.100} 65%, transparent)',
                    focusBackground:
                        'color-mix(in srgb, {primary.200} 75%, transparent)',
                    color: '#1f2937',
                    focusColor: '#111827',
                },
                mask: {
                    background:
                        'color-mix(in srgb, {primary.950} 18%, rgba(17, 24, 39, 0.55))',
                    color: '#ffffff',
                },
                formField: {
                    background: '#ffffff',
                    disabledBackground:
                        'color-mix(in srgb, {surface.100} 80%, #ffffff)',
                    filledBackground:
                        'color-mix(in srgb, {primary.50} 55%, #ffffff)',
                    filledHoverBackground:
                        'color-mix(in srgb, {primary.100} 60%, #ffffff)',
                    filledFocusBackground:
                        'color-mix(in srgb, {primary.50} 80%, #ffffff)',
                    borderColor:
                        'color-mix(in srgb, {primary.500} 32%, transparent)',
                    hoverBorderColor:
                        'color-mix(in srgb, {primary.500} 48%, transparent)',
                    focusBorderColor: '{primary.400}',
                    invalidBorderColor: '#f87171',
                    color: '#1f2937',
                    disabledColor: '#9ca3af',
                    placeholderColor: '#6b7280',
                    invalidPlaceholderColor: '#f87171',
                    floatLabelColor: '#6b7280',
                    floatLabelFocusColor: '{primary.500}',
                    floatLabelActiveColor: '{primary.600}',
                    floatLabelInvalidColor: '#ef4444',
                    iconColor: '{primary.500}',
                    shadow: '0 12px 40px -24px color-mix(in srgb, {primary.500} 45%, transparent)',
                },
                text: {
                    color: '#0f172a',
                    hoverColor: '#101a38',
                    mutedColor: '#475569',
                    hoverMutedColor: '#334155',
                },
                content: {
                    background: '#ffffff',
                    hoverBackground:
                        'color-mix(in srgb, {primary.50} 22%, #ffffff)',
                    borderColor:
                        'color-mix(in srgb, {primary.500} 18%, transparent)',
                    color: '#111827',
                    hoverColor: '#1f2937',
                },
                list: {
                    option: {
                        focusBackground:
                            'color-mix(in srgb, {primary.100} 55%, transparent)',
                        selectedBackground:
                            'color-mix(in srgb, {primary.100} 80%, transparent)',
                        selectedFocusBackground:
                            'color-mix(in srgb, {primary.200} 70%, transparent)',
                        color: '#1f2937',
                        focusColor: '#111827',
                        selectedColor: '{primary.800}',
                        selectedFocusColor: '{primary.800}',
                        icon: {
                            color: '{primary.500}',
                            focusColor: '{primary.600}',
                        },
                    },
                    optionGroup: {
                        background:
                            'color-mix(in srgb, {primary.200} 32%, transparent)',
                        color: 'color-mix(in srgb, {primary.700} 60%, #312e81)',
                    },
                },
                navigation: {
                    item: {
                        focusBackground:
                            'color-mix(in srgb, {primary.100} 50%, transparent)',
                        activeBackground:
                            'color-mix(in srgb, {primary.200} 55%, transparent)',
                        color: '#394264',
                        focusColor: '#1f2937',
                        activeColor: '{primary.800}',
                        icon: {
                            color: '{primary.500}',
                            focusColor: '{primary.600}',
                            activeColor: '{primary.700}',
                        },
                    },
                    submenuLabel: {
                        background:
                            'color-mix(in srgb, {primary.200} 30%, transparent)',
                        color: 'color-mix(in srgb, {primary.800} 65%, #312e81)',
                    },
                    submenuIcon: {
                        color: '{primary.500}',
                        focusColor: '{primary.600}',
                        activeColor: '{primary.700}',
                    },
                },
            },
        },
    },
}

const brandThemeRecipes: Record<BrandThemeId, BrandThemeRecipe> = {
    aurora: {
        label: 'Aurora Violet',
        description: 'Indigo gradients with cool violet surfaces.',
        preview: {
            primary: '#6366f1',
            secondary: '#22d3ee',
        },
        overrides: {
            semantic: {
                primary: {
                    50: '#eef2ff',
                    100: '#e0e7ff',
                    200: '#c7d2fe',
                    300: '#a5b4fc',
                    400: '#818cf8',
                    500: '#6366f1',
                    600: '#4f46e5',
                    700: '#4338ca',
                    800: '#3730a3',
                    900: '#312e81',
                    950: '#1e1b4b',
                },
                colorScheme: {
                    light: {
                        surface: {
                            0: '#ffffff',
                            50: '#f8f9ff',
                            100: '#eef2ff',
                            200: '#e3e9ff',
                            300: '#d9defc',
                            400: '#c6cbf5',
                            500: '#aab1e8',
                            600: '#8c92cc',
                            700: '#7075a9',
                            800: '#575c87',
                            900: '#41456a',
                            950: '#2e3150',
                        },
                    },
                },
            },
        },
    },
    lagoon: {
        label: 'Lagoon Teal',
        description: 'Sea glass neutrals with bold teal accents.',
        preview: {
            primary: '#0d9488',
            secondary: '#38bdf8',
        },
        overrides: {
            semantic: {
                primary: {
                    50: '#f0fdfa',
                    100: '#ccfbf1',
                    200: '#99f6e4',
                    300: '#5eead4',
                    400: '#2dd4bf',
                    500: '#14b8a6',
                    600: '#0d9488',
                    700: '#0f766e',
                    800: '#115e59',
                    900: '#134e4a',
                    950: '#042f2e',
                },
                colorScheme: {
                    light: {
                        surface: {
                            0: '#ffffff',
                            50: '#f2fbfb',
                            100: '#daf5f2',
                            200: '#c4ece6',
                            300: '#aae2d9',
                            400: '#90d7cb',
                            500: '#74cabd',
                            600: '#57ad9f',
                            700: '#428a7d',
                            800: '#326863',
                            900: '#244b46',
                            950: '#16312f',
                        },
                    },
                },
            },
        },
    },
    ember: {
        label: 'Ember Glow',
        description: 'Warm amber highlights with soft sunset neutrals.',
        preview: {
            primary: '#f97316',
            secondary: '#facc15',
        },
        overrides: {
            semantic: {
                primary: {
                    50: '#fff7ed',
                    100: '#ffedd5',
                    200: '#fed7aa',
                    300: '#fdba74',
                    400: '#fb923c',
                    500: '#f97316',
                    600: '#ea580c',
                    700: '#c2410c',
                    800: '#9a3412',
                    900: '#7c2d12',
                    950: '#431407',
                },
                colorScheme: {
                    light: {
                        surface: {
                            0: '#ffffff',
                            50: '#fff8f1',
                            100: '#feecdc',
                            200: '#fde0c3',
                            300: '#fbcda0',
                            400: '#f9b87d',
                            500: '#f3a45f',
                            600: '#d98549',
                            700: '#b5673a',
                            800: '#8f4f30',
                            900: '#653723',
                            950: '#3f2116',
                        },
                    },
                },
            },
        },
    },
}

const buildPreset = (recipe: BrandThemeRecipe) => {
    const merged = deepMerge(clone(baseOverrides), recipe.overrides)
    return definePreset(Aura, merged)
}

const brandThemeEntries = (
    Object.entries(brandThemeRecipes) as [BrandThemeId, BrandThemeRecipe][]
).map(([id, recipe]) => [
    id,
    {
        id,
        label: recipe.label,
        description: recipe.description,
        preview: recipe.preview,
        preset: buildPreset(recipe),
    } satisfies BrandThemeDefinition,
])

export const brandThemes = Object.fromEntries(brandThemeEntries) as Record<
    BrandThemeId,
    BrandThemeDefinition
>

export const defaultBrandThemeId: BrandThemeId = 'aurora'

export const costCourterPreset = brandThemes[defaultBrandThemeId].preset

export const brandThemeOptions = brandThemeEntries.map(([id, theme]) => ({
    value: id,
    label: theme.label,
    description: theme.description,
    preview: theme.preview,
}))

export const themeLayerOptions = {
    cssLayer: {
        name: 'primevue',
        order: 'theme, base, primevue',
    },
} as const

export const createPrimeVueThemeConfig = (preset: Preset) => ({
    preset,
    options: themeLayerOptions,
})

export const isBrandThemeId = (value: unknown): value is BrandThemeId =>
    typeof value === 'string' &&
    (brandThemeIds as readonly string[]).includes(value)

export const resolveBrandTheme = (
    id: string | null | undefined,
): BrandThemeDefinition =>
    isBrandThemeId(id) ? brandThemes[id] : brandThemes[defaultBrandThemeId]
