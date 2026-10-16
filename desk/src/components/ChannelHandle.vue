<template>
  <a
    v-if="url"
    :href="url"
    target="_blank"
    rel="noopener noreferrer"
    class="flex min-w-0 items-center gap-1 hover:underline"
    :title="__('Open on {0}', [__(handle.channel)])"
  >
    <Icon
      v-if="showIcon && handle.icon"
      :icon="handle.icon"
      :class="iconClass"
    />
    <span class="truncate">{{ handle.label }}</span>
  </a>
  <span v-else class="flex min-w-0 items-center gap-1">
    <Icon
      v-if="showIcon && handle.icon"
      :icon="handle.icon"
      :class="iconClass"
    />
    <span class="truncate">{{ handle.label }}</span>
  </span>
</template>

<script setup lang="ts">
import Icon from "@/components/Icon.vue";
import { __ } from "@/translation";
import type { ChannelHandle } from "@/types";
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    handle: ChannelHandle;
    showIcon?: boolean;
    iconClass?: string;
  }>(),
  { showIcon: true, iconClass: "size-4 shrink-0 text-ink-gray-6" }
);

// the link comes from an app; only ever open web pages
const url = computed(() =>
  /^https?:\/\//i.test(props.handle.url ?? "") ? props.handle.url : undefined
);
</script>
