import vue from 'eslint-plugin-vue'
import ts from '@vue/eslint-config-typescript'
import prettier from '@vue/eslint-config-prettier'

export default [
    {
        ignores: ['dist/**', 'node_modules/**', 'coverage/**'],
    },
    ...vue.configs['flat/recommended'],
    ...ts({
        tsconfigPath: './tsconfig.app.json',
    }),
    prettier,
    {
        files: ['src/**/*.{ts,tsx,vue}'],
        rules: {
            'vue/multi-word-component-names': 'off',
        },
    },
    {
        files: ['tests/**/*.{ts,tsx,vue}'],
        rules: {
            'vue/one-component-per-file': 'off',
        },
    },
]
