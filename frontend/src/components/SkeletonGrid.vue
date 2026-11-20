<template>
  <template v-if="inline">
    <div
      v-for="n in count"
      :key="n"
      class="skeleton-card"
      :style="{ '--skel-delay': `${Math.min(n - 1, 8) * 90}ms` }"
      aria-hidden="true"
    >
      <div class="skeleton-poster" />
      <div class="skeleton-line" />
      <div class="skeleton-line short" />
    </div>
  </template>

  <div v-else class="skeleton-section" aria-busy="true" :aria-label="label || tx('Chargement…')">
    <div v-if="label" class="skeleton-status" role="status">
      <span class="skeleton-status-dot" aria-hidden="true" />
      <span>{{ label }}</span>
    </div>
    <div class="results-grid">
      <div
        v-for="n in count"
        :key="n"
        class="skeleton-card"
        :style="{ '--skel-delay': `${Math.min(n - 1, 8) * 90}ms` }"
        aria-hidden="true"
      >
        <div class="skeleton-poster" />
        <div class="skeleton-line" />
        <div class="skeleton-line short" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { tx } from '@/utils/locale'

withDefaults(defineProps<{ count?: number; label?: string; inline?: boolean }>(), {
  count: 10,
  label: '',
  inline: false,
})
</script>

<style scoped>
.skeleton-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skeleton-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--muted);
}

.skeleton-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--accent);
  animation: skeletonDot 1.2s ease-in-out infinite;
}

.skeleton-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-radius: var(--radius);
  border: 1px solid var(--line);
  background: var(--panel);
  padding-bottom: 12px;
  overflow: hidden;
}

.skeleton-poster {
  aspect-ratio: 2 / 3;
  background: linear-gradient(
    105deg,
    var(--surface-3) 20%,
    var(--surface-4) 45%,
    rgba(var(--accent-rgb), 0.14) 50%,
    var(--surface-4) 55%,
    var(--surface-3) 80%
  );
  background-size: 240% 100%;
  animation: skeletonShimmer 1.4s ease-in-out infinite;
  animation-delay: var(--skel-delay, 0ms);
}

.skeleton-line {
  height: 12px;
  margin: 0 12px;
  border-radius: 6px;
  background: linear-gradient(
    105deg,
    var(--surface-3) 20%,
    var(--surface-4) 50%,
    var(--surface-3) 80%
  );
  background-size: 240% 100%;
  animation: skeletonShimmer 1.4s ease-in-out infinite;
  animation-delay: var(--skel-delay, 0ms);
}

.skeleton-line.short {
  width: 58%;
  height: 10px;
}

@keyframes skeletonShimmer {
  0% {
    background-position: 120% 0;
  }
  100% {
    background-position: -120% 0;
  }
}

@keyframes skeletonDot {
  0%,
  100% {
    opacity: 0.4;
    transform: scale(0.85);
  }
  50% {
    opacity: 1;
    transform: scale(1.1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-poster,
  .skeleton-line,
  .skeleton-status-dot {
    animation: none;
  }
}
</style>
