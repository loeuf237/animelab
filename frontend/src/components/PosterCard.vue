<template>
  <article class="anime-card poster-card">
    <router-link :to="to" class="card-link">
      <div class="poster-card-media">
        <div
          v-if="imageUrl && !imageBroken && !imageLoaded"
          class="poster-card-shimmer"
          aria-hidden="true"
        />
        <img
          v-if="imageUrl && !imageBroken"
          ref="imgEl"
          :src="imageUrl"
          :alt="tx(title)"
          :class="{ 'is-loaded': imageLoaded }"
          loading="lazy"
          @load="imageLoaded = true"
          @error="imageBroken = true"
        />
        <div v-else class="poster-card-fallback" aria-hidden="true">
          <Film :size="28" />
        </div>

        <div
          v-if="version || episodeInfo || favorite || autoDownload || $slots.badges"
          class="poster-card-scrim"
        >
          <slot name="badges">
            <span v-if="favorite" class="fav-badge">{{ tx('Favori') }}</span>
            <span v-if="autoDownload" class="chip chip-auto">Auto-DL</span>
            <span v-if="version" class="version-badge">{{ tx(version) }}</span>
            <span v-if="episodeInfo" class="ep-badge">{{ tx(episodeInfo) }}</span>
          </slot>
        </div>
      </div>

      <div class="poster-card-body">
        <h3 class="poster-card-title" :title="tx(title)">{{ tx(title) }}</h3>
        <span v-if="subtitle" class="poster-card-sub">{{ tx(subtitle) }}</span>
      </div>
    </router-link>

    <div v-if="$slots.footer" class="poster-card-footer">
      <slot name="footer" />
    </div>
  </article>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import type { RouteLocationRaw } from 'vue-router'
import { Film } from 'lucide-vue-next'
import { tx } from '@/utils/locale'

const props = defineProps<{
  title: string
  imageUrl?: string | null
  to: RouteLocationRaw
  subtitle?: string | null
  version?: string | null
  episodeInfo?: string | null
  favorite?: boolean
  autoDownload?: boolean
}>()

const imageBroken = ref(false)
const imageLoaded = ref(false)
const imgEl = ref<HTMLImageElement | null>(null)

function syncCompleteState() {
  if (imgEl.value?.complete && imgEl.value.naturalWidth > 0) {
    imageLoaded.value = true
  }
}

onMounted(syncCompleteState)
watch(
  () => props.imageUrl,
  () => {
    imageBroken.value = false
    imageLoaded.value = false
  },
)
</script>

<style scoped>
.poster-card {
  animation: posterReveal 0.24s cubic-bezier(0.2, 0, 0, 1) both;
}

.poster-card-shimmer {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    105deg,
    var(--surface-3) 20%,
    var(--surface-4) 50%,
    var(--surface-3) 80%
  );
  background-size: 240% 100%;
  animation: posterImgShimmer 1.35s ease-in-out infinite;
}

.poster-card-media img {
  opacity: 0;
  transform: scale(1.02);
  transition:
    opacity 0.28s ease,
    transform 0.32s ease;
}

.poster-card-media img.is-loaded {
  opacity: 1;
  transform: scale(1);
}

@keyframes posterReveal {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes posterImgShimmer {
  0% {
    background-position: 120% 0;
  }
  100% {
    background-position: -120% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .poster-card,
  .poster-card-shimmer {
    animation: none;
  }
  .poster-card-media img {
    opacity: 1;
    transform: none;
    transition: none;
  }
}
</style>
