import { defineStore } from 'pinia'
import { jwtDecode } from 'jwt-decode'

import { apiClient, attachAuthInterceptor } from '../lib/http'

export type Tokens = {
    accessToken: string
    tokenType: string
}

type OIDCStartResponse = {
    state: string
    authorization_url: string
}

type TokenResponse = {
    access_token: string
    token_type: string
}

type OidcState = {
    state: string
    createdAt: string
}

type CurrentUser = {
    id: number
    email: string
    full_name: string | null
    is_superuser: boolean
    roles: string[]
}

type AccessTokenClaims = {
    sub?: string
    scope?: string
    exp?: number
    [key: string]: unknown
}

const TOKENS_STORAGE_KEY = 'costcourter.tokens'
const OIDC_STATE_STORAGE_KEY = 'costcourter.oidc.state'
const POST_LOGIN_REDIRECT_KEY = 'costcourter.postLoginRedirect'

const readJSON = <T>(key: string): T | null => {
    try {
        const raw = window.localStorage.getItem(key)
        return raw ? (JSON.parse(raw) as T) : null
    } catch {
        return null
    }
}

const writeJSON = <T>(key: string, value: T | null) => {
    if (value === null) {
        window.localStorage.removeItem(key)
    } else {
        window.localStorage.setItem(key, JSON.stringify(value))
    }
}

const decodeClaims = (token: string): AccessTokenClaims => {
    try {
        return jwtDecode<AccessTokenClaims>(token)
    } catch (error) {
        console.warn('Failed to decode access token', error)
        return {}
    }
}

export const useAuthStore = defineStore('auth', {
    state: () => ({
        tokens: readJSON<Tokens>(TOKENS_STORAGE_KEY),
        oidcState: readJSON<OidcState>(OIDC_STATE_STORAGE_KEY),
        currentUser: null as CurrentUser | null,
        claims: null as AccessTokenClaims | null,
        roles: (import.meta.env.VITE_AUTH_BYPASS === 'true'
            ? ['admin']
            : []) as string[],
        loading: false,
        error: null as string | null,
        refreshTimer: null as number | null,
    }),
    getters: {
        isAuthenticated: (state) =>
            Boolean(state.tokens?.accessToken) ||
            import.meta.env.VITE_AUTH_BYPASS === 'true',
        accessToken: (state) => state.tokens?.accessToken ?? null,
        tokenType: (state) => state.tokens?.tokenType ?? null,
    },
    actions: {
        hasRole(role: string) {
            if (import.meta.env.VITE_AUTH_BYPASS === 'true') return true
            return this.roles.includes(role)
        },
        async beginOidcLogin(redirectUri?: string): Promise<OIDCStartResponse> {
            this.loading = true
            this.error = null
            try {
                const response = await apiClient.post<OIDCStartResponse>(
                    '/auth/oidc/start',
                    redirectUri ? { redirect_uri: redirectUri } : {},
                )
                const statePayload: OidcState = {
                    state: response.data.state,
                    createdAt: new Date().toISOString(),
                }
                this.oidcState = statePayload
                writeJSON(OIDC_STATE_STORAGE_KEY, statePayload)
                return response.data
            } catch (error) {
                this.error =
                    error instanceof Error ? error.message : 'OIDC login failed'
                throw error
            } finally {
                this.loading = false
            }
        },
        async completeOidcLogin(payload: { state: string; code: string }) {
            this.loading = true
            this.error = null
            try {
                const response = await apiClient.post<TokenResponse>(
                    '/auth/oidc/callback',
                    payload,
                )
                this.oidcState = null
                writeJSON(OIDC_STATE_STORAGE_KEY, null)
                this.setTokens({
                    accessToken: response.data.access_token,
                    tokenType: response.data.token_type,
                })
                await this.fetchCurrentUser()
            } catch (error) {
                this.error =
                    error instanceof Error
                        ? error.message
                        : 'OIDC callback failed'
                throw error
            } finally {
                this.loading = false
            }
        },
        async fetchCurrentUser() {
            if (!this.isAuthenticated) {
                this.currentUser = null
                this.roles = []
                return
            }
            try {
                const response = await apiClient.get<CurrentUser>('/auth/me')
                this.currentUser = response.data
                this.roles = this.extractRoles()
            } catch (error) {
                this.error =
                    error instanceof Error
                        ? error.message
                        : 'Failed to load current user'
            }
        },
        setTokens(tokens: Tokens | null) {
            this.clearRefreshTimer()
            this.tokens = tokens
            writeJSON(TOKENS_STORAGE_KEY, tokens)
            if (tokens) {
                this.claims = decodeClaims(tokens.accessToken)
                this.roles = this.extractRoles()
                this.scheduleTokenRefresh()
            } else {
                this.claims = null
                this.roles = []
            }
        },
        extractRoles(): string[] {
            const roles = new Set<string>()
            const scope = this.claims?.scope
            if (scope) {
                scope
                    .split(' ')
                    .map((entry) => entry.trim())
                    .filter(Boolean)
                    .forEach((entry) => {
                        if (entry.toLowerCase() in { admin: true }) {
                            roles.add('admin')
                        }
                    })
            }
            if (this.currentUser?.is_superuser) {
                roles.add('admin')
            }
            return Array.from(roles)
        },
        scheduleTokenRefresh() {
            const exp = this.claims?.exp
            if (!exp) {
                return
            }
            const expiresInMs = exp * 1000 - Date.now() - 60_000
            if (expiresInMs <= 0) {
                this.error = 'Session expired. Please sign in again.'
                this.logout(false)
                return
            }
            this.refreshTimer = window.setTimeout(() => {
                this.error = 'Session expired. Please sign in again.'
                this.logout(false)
            }, expiresInMs)
        },
        clearRefreshTimer() {
            if (this.refreshTimer !== null) {
                window.clearTimeout(this.refreshTimer)
                this.refreshTimer = null
            }
        },
        logout(redirect: boolean = true) {
            this.clearRefreshTimer()
            this.tokens = null
            this.claims = null
            this.roles = []
            this.currentUser = null
            this.error = null
            writeJSON(TOKENS_STORAGE_KEY, null)
            writeJSON(OIDC_STATE_STORAGE_KEY, null)
            window.localStorage.removeItem(POST_LOGIN_REDIRECT_KEY)
            if (redirect) {
                window.location.href = '/'
            }
        },
    },
})

const safeTokenProvider = () => {
    try {
        return useAuthStore().accessToken
    } catch {
        return null
    }
}

export const registerAuthInterceptor = () => {
    attachAuthInterceptor(apiClient, safeTokenProvider)
}
