<template>
  <Teleport to="body">
    <div v-if="open" class="dialog-overlay" @click.self="cancel" @keydown="onKeyDown">
      <section
        ref="dialog"
        class="confirmation-dialog"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        tabindex="-1"
      >
        <h2 :id="titleId">{{ tx(title) }}</h2>
        <div class="confirmation-body"><slot /></div>
        <div class="confirmation-actions">
          <button ref="cancelButton" type="button" class="btn" :disabled="busy" @click="cancel">
            {{ tx('Annuler') }}
          </button>
          <button
            type="button"
            class="btn"
            :class="danger ? 'btn-danger' : 'btn-primary'"
            :disabled="busy"
            @click="$emit('confirm')"
          >
            {{ tx(busy ? 'En cours…' : confirmLabel) }}
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
<script setup lang="ts">
import { tx } from '@/utils/locale'
import { ref, watch, nextTick, onUnmounted, useId } from 'vue'
const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    confirmLabel?: string
    busy?: boolean
    danger?: boolean
  }>(),
  { confirmLabel: 'Confirmer' },
)
const emit = defineEmits<{ (event: 'cancel'): void; (event: 'confirm'): void }>()
const dialog = ref<HTMLElement | null>(null),
  cancelButton = ref<HTMLButtonElement | null>(null)
const titleId = useId()
let returnFocus: HTMLElement | null = null
let previousOverflow = ''
let appRoot: HTMLElement | null = null
let previousInert = false
function restore() {
  if (appRoot) appRoot.inert = previousInert
  document.body.style.overflow = previousOverflow
  if (returnFocus?.isConnected) returnFocus.focus()
  returnFocus = null
}
watch(
  () => props.open,
  async (open) => {
    if (open) {
      returnFocus = document.activeElement as HTMLElement
      appRoot = document.getElementById('app')
      previousInert = appRoot?.inert || false
      if (appRoot) appRoot.inert = true
      previousOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      await nextTick()
      cancelButton.value?.focus()
    } else restore()
  },
  { immediate: true },
)
onUnmounted(() => {
  if (props.open) restore()
})
function cancel() {
  if (!props.busy) emit('cancel')
}
function onKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.stopPropagation()
    event.preventDefault()
    cancel()
  }
  if (event.key !== 'Tab') return
  const targets = [
    ...dialog.value!.querySelectorAll<HTMLElement>(
      'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled)',
    ),
  ]
  const first = targets[0],
    last = targets[targets.length - 1]
  if (!first) {
    event.preventDefault()
    dialog.value?.focus()
  } else if (
    event.shiftKey &&
    (document.activeElement === first || document.activeElement === dialog.value)
  ) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}
</script>
