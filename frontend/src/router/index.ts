import { createRouter, createWebHistory } from 'vue-router'
import { getRouterBase } from './base'
import { useSearchContext } from '@/stores/searchContext'

const routes = [
  {
    path: '/sources/:sourceId?',
    name: 'sources',
    component: () => import('@/views/SourcesView.vue'),
    meta: { titleKey: 'Explorer', rootTab: 'explore', isSubPage: false },
  },
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { titleKey: 'Accueil', rootTab: 'home', isSubPage: false },
  },
  {
    path: '/anime',
    name: 'anime-detail',
    component: () => import('@/views/AnimeDetailView.vue'),
    meta: { titleKey: 'Fiche animé', isSubPage: true },
  },
  {
    path: '/downloads',
    name: 'downloads',
    component: () => import('@/views/DownloadsView.vue'),
    meta: { titleKey: 'Téléchargements', rootTab: 'downloads', isSubPage: false },
  },
  {
    path: '/library',
    name: 'library',
    component: () => import('@/views/LibraryView.vue'),
    meta: { titleKey: 'Bibliothèque', rootTab: 'library', isSubPage: false },
  },
  {
    path: '/favorites',
    redirect: '/library',
  },
  {
    path: '/more',
    name: 'more',
    component: () => import('@/views/MoreView.vue'),
    meta: { titleKey: 'Plus', rootTab: 'more', isSubPage: false },
  },
  {
    path: '/history',
    name: 'history',
    component: () => import('@/views/HistoryView.vue'),
    meta: { titleKey: 'Historique', rootTab: 'more', isSubPage: true },
  },
  {
    path: '/extensions',
    name: 'extensions',
    component: () => import('@/views/ExtensionsView.vue'),
    meta: { titleKey: 'Extensions', rootTab: 'explore', isSubPage: true },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { titleKey: 'Paramètres', rootTab: 'more', isSubPage: true },
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const positions = new Map<string, { left: number; top: number }>()
const router = createRouter({
  history: createWebHistory(getRouterBase(window.location.pathname)),
  routes,
  scrollBehavior(to, _from, savedPosition) {
    return savedPosition || positions.get(to.fullPath) || { top: 0 }
  },
})

router.beforeEach((_to, from) => {
  positions.set(from.fullPath, { left: window.scrollX, top: window.scrollY })
  if (positions.size > 50) positions.delete(positions.keys().next().value!)
})

router.afterEach((to, from, failure) => {
  if (!failure && from.name === 'anime-detail' && to.name !== 'anime-detail') {
    useSearchContext().detailUrl = ''
  }
})

export default router
