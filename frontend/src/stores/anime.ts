import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { AnimeDetailResponse, AnimeResult, HomeFeedResponse } from '@/types'
import type { SourceChallenge } from '@/types'
import { useVerificationStore, challengeFromError } from './verification'

export const useAnimeStore = defineStore('anime', () => {
  const homeFeed = ref<HomeFeedResponse | null>(null)
  const currentDetail = ref<AnimeDetailResponse | null>(null)
  const searchResults = ref<AnimeResult[]>([])
  const searchQuery = ref('')
  const selectedSource = ref('all')
  const isLoading = ref(false)
  const isDetailLoading = ref(false)
  const isDetailRefreshing = ref(false)
  const isOfflineSnapshot = ref(false)
  const error = ref<string | null>(null)
  const searchChallenges = ref<SourceChallenge[]>([])
  const searchWarnings = ref<{ source: string; message: string; url?: string; domain?: string }[]>(
    [],
  )
  let searchSequence = 0
  let detailSequence = 0
  const detailChallenges = ref<SourceChallenge[]>([])

  async function fetchHomeFeed(force = false) {
    if (homeFeed.value && !force) return
    isLoading.value = true
    error.value = null
    try {
      homeFeed.value = await api.getHomeFeed()
      useVerificationStore().waitForVerification(
        'home-feed',
        homeFeed.value.challenges || [],
        async () => {
          await fetchHomeFeed(true)
        },
      )
    } catch (err: any) {
      error.value = err.message || 'Impossible de charger le flux'
      console.error('[useAnimeStore] fetchHomeFeed error:', err)
    } finally {
      isLoading.value = false
    }
  }

  async function search(query: string, source: string = 'all') {
    const sequence = ++searchSequence
    const verification = useVerificationStore()
    verification.clearPending('anime-search')
    searchChallenges.value = []
    searchWarnings.value = []
    searchQuery.value = query
    selectedSource.value = source
    if (!query.trim()) {
      searchResults.value = []
      isLoading.value = false
      error.value = null
      return
    }

    isLoading.value = true
    error.value = null
    try {
      const response = await api.searchAnimeDetailed(query, source)
      if (sequence !== searchSequence) return
      searchResults.value = response.results
      searchChallenges.value = response.challenges
      searchWarnings.value = response.errors
      verification.waitForVerification(
        'anime-search',
        [
          ...response.challenges,
          ...response.errors.flatMap((e) => (e.domain ? [{ domain: e.domain }] : [])),
        ],
        async () => {
          if (sequence === searchSequence) await search(query, source)
        },
      )
    } catch (err: any) {
      if (sequence !== searchSequence) return
      searchResults.value = []
      const challenge = challengeFromError(err)
      if (challenge) {
        searchChallenges.value = [challenge]
        verification.waitForVerification('anime-search', [challenge], async () => {
          if (sequence === searchSequence) await search(query, source)
        })
      }
      error.value = err.message || 'Erreur lors de la recherche'
      console.error('[useAnimeStore] search error:', err)
    } finally {
      if (sequence === searchSequence) isLoading.value = false
    }
  }

  async function refreshAnimeDetail(
    url: string,
    source: string = 'french-manga',
    options?: { silent?: boolean; expectedSequence?: number },
  ): Promise<{
    updated: boolean
    addedEpisodes?: number
    offline?: boolean
    challenge?: boolean
    cancelled?: boolean
    error?: string
    detail?: AnimeDetailResponse
  }> {
    const silent = Boolean(options?.silent)
    const sequence = options?.expectedSequence ?? ++detailSequence
    const verification = useVerificationStore()
    if (!silent) {
      verification.clearPending('anime-detail')
      detailChallenges.value = []
      if (!currentDetail.value) {
        isDetailLoading.value = true
        error.value = null
      }
    }
    isDetailRefreshing.value = true
    try {
      const fresh = await api.getAnimeDetail(url, source, { refresh: true })
      if (sequence !== detailSequence) return { updated: false, cancelled: true }
      const previousCount = currentDetail.value?.anime?.episodes?.length ?? 0
      const freshCount = fresh?.anime?.episodes?.length ?? 0
      const addedEpisodes = currentDetail.value ? Math.max(0, freshCount - previousCount) : 0
      currentDetail.value = fresh
      detailChallenges.value = []
      error.value = null
      isOfflineSnapshot.value = false
      return { updated: true, addedEpisodes, detail: fresh }
    } catch (err: any) {
      if (sequence !== detailSequence) return { updated: false, cancelled: true }
      const challenge = challengeFromError(err)
      if (currentDetail.value) {
        isOfflineSnapshot.value = true
        if (!silent && challenge) {
          detailChallenges.value = [challenge]
          verification.waitForVerification('anime-detail', [challenge], async () => {
            if (sequence === detailSequence) {
              await refreshAnimeDetail(url, source, { silent: false })
            }
          })
        }
        return {
          updated: false,
          offline: true,
          challenge: Boolean(challenge),
          error: err?.message || '',
        }
      }
      if (challenge) {
        detailChallenges.value = [challenge]
        verification.waitForVerification('anime-detail', [challenge], async () => {
          if (sequence === detailSequence) {
            await refreshAnimeDetail(url, source, { silent: false })
          }
        })
      }
      error.value = err?.message || "Impossible de charger la fiche de l'animé"
      console.error('[useAnimeStore] refreshAnimeDetail error:', err)
      return {
        updated: false,
        challenge: Boolean(challenge),
        error: err?.message || '',
      }
    } finally {
      if (sequence === detailSequence) {
        isDetailRefreshing.value = false
        isDetailLoading.value = false
      }
    }
  }

  async function fetchAnimeDetail(url: string, source: string = 'french-manga') {
    const sequence = ++detailSequence
    const verification = useVerificationStore()
    verification.clearPending('anime-detail')
    detailChallenges.value = []
    currentDetail.value = null
    isDetailLoading.value = true
    isDetailRefreshing.value = false
    isOfflineSnapshot.value = false
    error.value = null
    try {
      const res = await api.getAnimeDetail(url, source)
      if (sequence !== detailSequence) return
      currentDetail.value = res
      if (res?.fromCache) {
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
          isOfflineSnapshot.value = true
        } else {
          void refreshAnimeDetail(url, source, { silent: true, expectedSequence: sequence })
        }
      }
      return res
    } catch (err: any) {
      if (sequence !== detailSequence) return
      const challenge = challengeFromError(err)
      if (challenge) {
        detailChallenges.value = [challenge]
        verification.waitForVerification('anime-detail', [challenge], async () => {
          if (sequence === detailSequence) await fetchAnimeDetail(url, source)
        })
      }
      error.value = err.message || "Impossible de charger la fiche de l'animé"
      console.error('[useAnimeStore] fetchAnimeDetail error:', err)
    } finally {
      if (sequence === detailSequence) isDetailLoading.value = false
    }
  }

  function clearDetail() {
    detailSequence++
    useVerificationStore().clearPending('anime-detail')
    detailChallenges.value = []
    isDetailLoading.value = false
    isDetailRefreshing.value = false
    isOfflineSnapshot.value = false
    currentDetail.value = null
  }

  return {
    homeFeed,
    currentDetail,
    detailChallenges,
    searchResults,
    searchQuery,
    selectedSource,
    isLoading,
    isDetailLoading,
    isDetailRefreshing,
    isOfflineSnapshot,
    error,
    searchChallenges,
    searchWarnings,
    fetchHomeFeed,
    search,
    fetchAnimeDetail,
    refreshAnimeDetail,
    clearDetail,
  }
})
