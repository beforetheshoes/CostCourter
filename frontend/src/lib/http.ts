import axios, { AxiosHeaders } from 'axios'

type ApiClientOptions = {
    baseURL?: string
}

export const createApiClient = ({ baseURL }: ApiClientOptions = {}) =>
    axios.create({
        baseURL: baseURL ?? import.meta.env.VITE_API_BASE_URL ?? '/api',
        headers: {
            'Content-Type': 'application/json',
        },
        withCredentials: true,
    })

export const apiClient = createApiClient()
export type ApiClient = typeof apiClient

type TokenProvider = () => string | null

export const attachAuthInterceptor = (
    client: ApiClient,
    getToken: TokenProvider,
) => {
    client.interceptors.request.use((config) => {
        const token = getToken()
        if (token) {
            if (typeof config.headers?.set === 'function') {
                config.headers.set('Authorization', `Bearer ${token}`)
            } else {
                const headers = AxiosHeaders.from(config.headers ?? {})
                headers.set('Authorization', `Bearer ${token}`)
                config.headers = headers
            }
        }
        return config
    })
}
