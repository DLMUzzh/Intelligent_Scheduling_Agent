import { createRouter, createWebHashHistory } from 'vue-router'
import FoundationView from '../views/FoundationView.vue'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [{ path: '/', component: FoundationView }],
})
