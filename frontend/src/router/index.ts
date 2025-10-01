import { createRouter, createWebHistory } from 'vue-router'
import type { NavigationGuard, Router, RouterHistory } from 'vue-router'

import { useAuthStore } from '../stores/useAuthStore'

export const routes = [
    {
        path: '/',
        name: 'login',
        component: () => import('../views/LoginView.vue'),
    },
    {
        path: '/dashboard',
        name: 'dashboard',
        component: () => import('../views/HomeView.vue'),
        meta: { requiresAuth: true, requiredRole: 'admin' },
    },
    {
        path: '/settings',
        name: 'settings',
        component: () => import('../views/SettingsView.vue'),
        meta: { requiresAuth: true, requiredRole: 'admin' },
    },
    {
        path: '/products',
        name: 'products',
        component: () => import('../views/ProductsView.vue'),
        meta: { requiresAuth: true, requiredRole: 'admin' },
    },
    {
        path: '/products/:id',
        name: 'product-detail',
        component: () => import('../views/ProductDetailView.vue'),
        meta: { requiresAuth: true, requiredRole: 'admin' },
    },
    {
        path: '/search',
        name: 'search',
        component: () => import('../views/SearchView.vue'),
        meta: { requiresAuth: true, requiredRole: 'admin' },
    },
    {
        path: '/stores',
        name: 'stores',
        component: () => import('../views/StoresView.vue'),
        meta: { requiresAuth: true, requiredRole: 'admin' },
    },
    {
        path: '/tags',
        name: 'tags',
        redirect: { name: 'settings', query: { section: 'tags' } },
        meta: { requiresAuth: true, requiredRole: 'admin' },
    },
    {
        path: '/notifications',
        name: 'notifications',
        redirect: { name: 'settings', query: { section: 'notifications' } },
        meta: { requiresAuth: true },
    },
    {
        path: '/auth/callback',
        name: 'auth-callback',
        component: () => import('../views/AuthCallbackView.vue'),
    },
]

export const createAuthGuard = (
    resolveStore: () => ReturnType<typeof useAuthStore> = useAuthStore,
): NavigationGuard => {
    return (to, _from, next) => {
        const authStore = resolveStore()
        const LOGIN_ROUTE = 'login'
        const isLoginRoute = to.name === LOGIN_ROUTE
        const isAuthFlowRoute = to.name === 'auth-callback'

        if (isLoginRoute && authStore.isAuthenticated) {
            next({ name: 'dashboard' })
            return
        }
        if (!authStore.isAuthenticated && !isLoginRoute && !isAuthFlowRoute) {
            next({
                name: LOGIN_ROUTE,
                query: { redirect: to.fullPath },
            })
            return
        }
        if (to.meta.requiresAuth && !authStore.isAuthenticated) {
            next({
                name: LOGIN_ROUTE,
                query: { redirect: to.fullPath },
            })
            return
        }
        const requiredRole = to.meta.requiredRole as string | undefined
        if (requiredRole && !authStore.hasRole(requiredRole)) {
            next({
                name: LOGIN_ROUTE,
                query: { redirect: to.fullPath },
            })
            return
        }
        next()
    }
}

export const applyGuards = (
    router: Router,
    resolveStore: () => ReturnType<typeof useAuthStore> = useAuthStore,
) => {
    router.beforeEach(createAuthGuard(resolveStore))
}

export const createAppRouter = (
    history: RouterHistory = createWebHistory(),
) => {
    const router = createRouter({
        history,
        routes,
    })
    applyGuards(router)
    return router
}

const router = createAppRouter()

export default router
