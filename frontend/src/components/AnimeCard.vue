<template>
  <PosterCard
    :title="anime.title"
    :image-url="anime.imageUrl"
    :to="{ path: '/anime', query: { url: anime.url, source: anime.source || 'french-manga' } }"
    :subtitle="anime.latestEpisode || anime.type || 'Animé'"
    :version="anime.source"
    :episode-info="anime.rating ? `★ ${Number(anime.rating).toFixed(1)}` : anime.status"
  />
</template>

<script setup lang="ts">
import PosterCard from '@/components/PosterCard.vue'
import type { AnimeResult } from '@/types'

defineProps<{
  anime: AnimeResult
}>()
</script>
