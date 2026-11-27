import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import SubstitutionCenter from '@/views/SubstitutionCenter.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/material-substitution', name: 'material-substitution', component: SubstitutionCenter },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
