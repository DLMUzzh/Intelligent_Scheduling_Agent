import { createRouter, createWebHashHistory } from 'vue-router'
import FoundationView from '../views/FoundationView.vue'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: FoundationView },
    { path: '/categories', component: () => import('../views/plans/CategoriesView.vue') },
    { path: '/resources', component: () => import('../views/resources/ResourcesView.vue') },
    { path: '/unavailability', component: () => import('../views/resources/UnavailabilityView.vue') },
    { path: '/logs', component: () => import('../views/logs/AuditView.vue') },
  ],
})
