<template>
  <div class="theme-picker">
    <div class="theme-modes" role="group" :aria-label="tx('Mode d’affichage')">
      <button
        v-for="mode in modes"
        :key="mode.id"
        type="button"
        :aria-pressed="themeMode === mode.id"
        @click="choose(mode.id, palette)"
      >
        <Check v-if="themeMode === mode.id" aria-hidden="true" />{{ tx(mode.label) }}
      </button>
    </div>
    <div class="theme-variants" role="group" :aria-label="tx('Palette de couleurs')">
      <button
        v-for="variant in variants"
        :key="variant.id"
        type="button"
        class="theme-variant"
        :aria-pressed="palette === variant.id"
        @click="choose(themeMode, variant.id)"
      >
        <span class="theme-mini" :style="previewStyle(variant)">
          <span class="mini-heading"></span><span class="mini-card"><i></i><i></i></span>
          <span class="mini-nav"><i></i><i></i><i></i></span>
          <Check v-if="palette === variant.id" class="mini-check" aria-hidden="true" />
        </span>
        <span>{{ tx(variant.label) }}</span>
      </button>
    </div>
  </div>
</template>
<script setup lang="ts">
import { Check } from 'lucide-vue-next'
import { effectiveTheme, themeMode, palette, setAppearance } from '@/stores/appearance'
import type { Palette, ThemeMode } from '@/types/startup'
import { tx } from '@/utils/locale'
const emit = defineEmits<{ change: [] }>()
const modes: { id: ThemeMode; label: string }[] = [
  { id: 'system', label: 'Système' },
  { id: 'light', label: 'Clair' },
  { id: 'dark', label: 'Sombre' },
]
interface PreviewSwatches {
  bg: string
  card: string
  nav: string
  heading: string
  accent: string
}
interface PaletteVariant {
  id: Palette
  label: string
  dark: PreviewSwatches
  light: PreviewSwatches
}
const variants: PaletteVariant[] = [
  {
    id: 'classic',
    label: 'Classique',
    dark: { bg: '#1b1b1f', card: '#292730', nav: '#211f26', heading: '#e3e2e6', accent: '#b0c6ff' },
    light: {
      bg: '#fefbff',
      card: '#e8e5ef',
      nav: '#f3edf7',
      heading: '#1b1b1f',
      accent: '#0058ca',
    },
  },
  {
    id: 'teal',
    label: 'Turquoise',
    dark: { bg: '#0b1517', card: '#18272a', nav: '#0f1b1e', heading: '#dce7e9', accent: '#80d3dc' },
    light: {
      bg: '#f5fafb',
      card: '#e1edef',
      nav: '#eaf2f3',
      heading: '#15282b',
      accent: '#006874',
    },
  },
  {
    id: 'lavender',
    label: 'Violet',
    dark: { bg: '#15121d', card: '#252131', nav: '#191622', heading: '#dce7e9', accent: '#c6b5ff' },
    light: {
      bg: '#f8f6fc',
      card: '#e8e0f5',
      nav: '#eee8f6',
      heading: '#1c1826',
      accent: '#6844a0',
    },
  },
  {
    id: 'ember',
    label: 'Ambre',
    dark: { bg: '#1c1510', card: '#2d241d', nav: '#211913', heading: '#dce7e9', accent: '#ffbc87' },
    light: {
      bg: '#fcf7f4',
      card: '#ece0d7',
      nav: '#f2e7df',
      heading: '#241912',
      accent: '#8a4b0d',
    },
  },
  {
    id: 'amoled',
    label: 'AMOLED',
    dark: { bg: '#000000', card: '#141414', nav: '#000000', heading: '#ffffff', accent: '#ffffff' },
    light: {
      bg: '#ffffff',
      card: '#ebebeb',
      nav: '#f5f5f5',
      heading: '#000000',
      accent: '#141414',
    },
  },
]
function previewStyle(variant: PaletteVariant) {
  const s = effectiveTheme.value === 'light' ? variant.light : variant.dark
  return {
    '--mini-bg': s.bg,
    '--mini-card': s.card,
    '--mini-nav': s.nav,
    '--mini-heading': s.heading,
    '--mini-accent': s.accent,
  }
}
function choose(mode: ThemeMode, variant: Palette) {
  setAppearance(mode, variant)
  emit('change')
}
</script>
<style scoped>
.theme-picker {
  width: 100%;
}
.theme-modes {
  display: flex;
  border: 1px solid var(--line-strong);
  border-radius: 99px;
  overflow: hidden;
}
.theme-modes button {
  flex: 1;
  min-width: 0;
  min-height: 44px;
  background: transparent;
  color: var(--text);
  border: 0;
  border-right: 1px solid var(--line-strong);
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 6px;
}
.theme-modes button:last-child {
  border: 0;
}
.theme-modes button[aria-pressed='true'] {
  background: var(--accent-container);
  color: var(--on-accent-container);
}
.theme-modes svg {
  width: 16px;
  height: 16px;
}
.theme-variants {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  margin-top: 28px;
}
.theme-variant {
  background: transparent;
  color: var(--muted);
  border: 0;
  padding: 0;
  font-size: 12px;
  min-width: 0;
}
.theme-variant[aria-pressed='true'] {
  color: var(--text);
}
.theme-mini {
  display: flex;
  position: relative;
  flex-direction: column;
  padding: 10px 7px 0;
  height: 150px;
  background: var(--mini-bg);
  border: 3px solid transparent;
  box-shadow: inset 0 0 0 1px var(--line);
  border-radius: 18px;
  margin-bottom: 10px;
  overflow: hidden;
}
.theme-variant[aria-pressed='true'] .theme-mini {
  border-color: var(--accent);
  box-shadow: none;
}
.mini-heading {
  width: 70%;
  height: 10px;
  background: var(--mini-heading);
  border-radius: 9px;
  margin-bottom: 12px;
}
.mini-card {
  display: flex;
  align-items: start;
  gap: 3px;
  background: var(--mini-card);
  width: 75%;
  height: 54px;
  padding: 5px;
  border-radius: 8px;
}
.mini-card i {
  background: var(--mini-accent);
  width: 12px;
  height: 9px;
  border-radius: 4px;
}
.mini-card i:last-child {
  opacity: 0.45;
}
.mini-nav {
  display: flex;
  gap: 7px;
  align-items: center;
  margin: auto -7px 0;
  padding: 10px 7px;
  background: var(--mini-nav);
}
.mini-nav i {
  width: 10px;
  height: 10px;
  background: #899596;
  border-radius: 100%;
}
.mini-nav i:first-child {
  background: var(--mini-accent);
}
.mini-check {
  position: absolute;
  top: 7px;
  right: 4px;
  width: 18px;
  height: 18px;
  padding: 2px;
  background: var(--accent);
  color: var(--on-accent);
  border-radius: 99px;
}
@media (max-width: 520px) {
  .theme-variants {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }
}
@media (max-width: 380px) {
  .theme-variants {
    gap: 8px;
  }
  .theme-variant {
    font-size: 11px;
  }
  .theme-mini {
    height: 120px;
    padding-inline: 5px;
  }
}
</style>
