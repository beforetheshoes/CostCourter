import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import Button from 'primevue/button'
import Card from 'primevue/card'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Password from 'primevue/password'
import Avatar from 'primevue/avatar'
import Dropdown from 'primevue/dropdown'
import Textarea from 'primevue/textarea'
import Checkbox from 'primevue/checkbox'
import Chart from 'primevue/chart'
import InlineMessage from 'primevue/inlinemessage'
import Tag from 'primevue/tag'
import Badge from 'primevue/badge'
import Divider from 'primevue/divider'
import Skeleton from 'primevue/skeleton'
import SelectButton from 'primevue/selectbutton'

import 'primeicons/primeicons.css'
import './style.css'

import App from './App.vue'
import router from './router'
import { registerAuthInterceptor, useAuthStore } from './stores/useAuthStore'
import { createPrimeVueThemeConfig, resolveBrandTheme } from './lib/theme'
import { initializeColorMode } from './lib/colorMode'
import {
    getStoredBrandThemeId,
    setDocumentBrandTheme,
} from './lib/themeManager'

initializeColorMode()

const app = createApp(App)

const pinia = createPinia()
app.use(pinia)
app.use(router)

const initialBrandThemeId = getStoredBrandThemeId()
const initialBrandTheme = resolveBrandTheme(initialBrandThemeId)

setDocumentBrandTheme(initialBrandTheme.id)

app.use(PrimeVue, {
    theme: createPrimeVueThemeConfig(initialBrandTheme.preset),
})

app.component('PvButton', Button)
app.component('PvCard', Card)
app.component('PvDialog', Dialog)
app.component('PvInputText', InputText)
app.component('PvPassword', Password)
app.component('PvAvatar', Avatar)
app.component('PvDropdown', Dropdown)
app.component('PvInputTextarea', Textarea)
app.component('PvCheckbox', Checkbox)
app.component('PvChart', Chart)
app.component('PvInlineMessage', InlineMessage)
app.component('PvTag', Tag)
app.component('PvBadge', Badge)
app.component('PvDivider', Divider)
app.component('PvSkeleton', Skeleton)
app.component('PvSelectButton', SelectButton)

registerAuthInterceptor()

const authStore = useAuthStore(pinia)
if (authStore.isAuthenticated && !authStore.currentUser) {
    authStore.fetchCurrentUser().catch(() => {
        // Swallow errors during bootstrap; UI will surface auth prompts.
    })
}

app.mount('#app')
