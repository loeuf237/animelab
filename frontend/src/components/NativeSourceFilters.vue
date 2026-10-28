<template>
  <div class="native-filters">
    <template v-for="(filter, index) in modelValue" :key="`${index}:${filter.name}`">
      <h4 v-if="filter.type === 'header'">{{ filter.name }}</h4>
      <hr v-else-if="filter.type === 'separator'" />
      <fieldset v-else-if="filter.type === 'group'">
        <legend>{{ filter.name }}</legend>
        <NativeSourceFilters
          :model-value="filter.children || []"
          @update:model-value="replace(index, { children: $event })"
        />
      </fieldset>
      <label v-else>
        {{ filter.name }}
        <input
          v-if="filter.type === 'text'"
          :aria-label="filter.name"
          type="text"
          :value="filter.state"
          @input="replace(index, { state: ($event.target as HTMLInputElement).value })"
        />
        <input
          v-else-if="filter.type === 'checkbox'"
          :aria-label="filter.name"
          type="checkbox"
          :checked="!!filter.state"
          @change="replace(index, { state: ($event.target as HTMLInputElement).checked })"
        />
        <select
          v-else-if="filter.type === 'select' || filter.type === 'triState'"
          :aria-label="filter.name"
          :value="filter.state"
          @change="replace(index, { state: Number(($event.target as HTMLSelectElement).value) })"
        >
          <option
            v-for="(option, i) in filter.type === 'triState'
              ? [tx('Ignorer'), tx('Inclure'), tx('Exclure')]
              : filter.options"
            :key="i"
            :value="i"
          >
            {{ option }}
          </option>
        </select>
        <template v-else-if="filter.type === 'sort'">
          <select
            :aria-label="filter.name"
            :value="sortState(filter)?.index ?? -1"
            @change="
              replace(index, {
                state:
                  Number(($event.target as HTMLSelectElement).value) < 0
                    ? null
                    : {
                        index: Number(($event.target as HTMLSelectElement).value),
                        ascending: sortState(filter)?.ascending ?? true,
                      },
              })
            "
          >
            <option :value="-1">{{ tx('Ordre par défaut') }}</option>
            <option v-for="(option, i) in filter.options" :key="i" :value="i">{{ option }}</option>
          </select>
          <select
            v-if="sortState(filter)"
            :aria-label="`${filter.name} : ${tx('sens du tri')}`"
            :value="String(sortState(filter)?.ascending)"
            @change="
              replace(index, {
                state: {
                  index: sortState(filter)!.index,
                  ascending: ($event.target as HTMLSelectElement).value === 'true',
                },
              })
            "
          >
            <option value="true">{{ tx('Croissant') }}</option>
            <option value="false">{{ tx('Décroissant') }}</option>
          </select>
        </template>
      </label>
    </template>
  </div>
</template>
<script setup lang="ts">
import type { NativeFilter } from '@/types/extensions'
import { tx } from '@/utils/locale'
const props = defineProps<{ modelValue: NativeFilter[] }>()
const emit = defineEmits<{ 'update:modelValue': [NativeFilter[]] }>()
const sortState = (filter: NativeFilter) =>
  typeof filter.state === 'object' && filter.state !== null ? filter.state : null
function replace(index: number, change: Partial<NativeFilter>) {
  emit(
    'update:modelValue',
    props.modelValue.map((filter, i) => (i === index ? { ...filter, ...change } : filter)),
  )
}
</script>
<style scoped>
.native-filters {
  display: grid;
  gap: 0.8rem;
}
label {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.6rem;
}
fieldset {
  border: 1px solid var(--border-color, #666);
  padding: 0.8rem;
}
</style>
