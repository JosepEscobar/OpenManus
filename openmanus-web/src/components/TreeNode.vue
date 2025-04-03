<template>
  <div class="tree-node">
    <div
      class="node-content"
      :class="{
        'is-active': isActive,
        'is-folder': node.type === 'directory',
        'is-file': node.type === 'file'
      }"
      @click="handleClick"
    >
      <span class="node-icon">
        <i v-if="node.type === 'directory'" class="fas fa-folder"></i>
        <i v-else class="fas fa-file"></i>
      </span>
      <span class="node-name">{{ node.name }}</span>
    </div>
    <div v-if="node.type === 'directory' && node.children" class="node-children">
      <TreeNode
        v-for="child in node.children"
        :key="child.path"
        :node="child"
        :active-files="activeFiles"
        @select="$emit('select', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  node: {
    type: Object,
    required: true
  },
  activeFiles: {
    type: Set,
    required: true
  }
})

const isActive = computed(() => {
  return props.activeFiles.has(props.node.path)
})

const handleClick = () => {
  if (props.node.type === 'file') {
    emit('select', props.node.path)
  }
}

const emit = defineEmits(['select'])
</script>

<style scoped>
.tree-node {
  font-size: 0.9rem;
}

.node-content {
  display: flex;
  align-items: center;
  padding: 0.25rem 0.5rem;
  cursor: pointer;
  user-select: none;
  transition: background-color 0.2s;
}

.node-content:hover {
  background-color: var(--vscode-secondary);
}

.node-content.is-active {
  background-color: var(--vscode-primary);
  color: white;
}

.node-icon {
  margin-right: 0.5rem;
  width: 16px;
  text-align: center;
}

.node-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-children {
  margin-left: 1rem;
}

.is-folder {
  color: var(--vscode-accent);
}

.is-file {
  color: var(--vscode-fg);
}
</style>
