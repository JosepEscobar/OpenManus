<template>
  <div class="file-explorer">
    <div class="explorer-header">
      <h3>Workspace</h3>
    </div>
    <div class="file-tree">
      <TreeNode
        v-for="node in fileTree"
        :key="node.path"
        :node="node"
        :active-files="activeFiles"
        @select="handleFileSelect"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useWebSocket } from '../composables/useWebSocket'
import TreeNode from './TreeNode.vue'

const fileTree = ref([])
const activeFiles = ref(new Set())

const { onMessage } = useWebSocket()

const handleFileSelect = (filePath) => {
  emit('fileSelect', filePath)
}

onMessage((data) => {
  if (data.type === 'fileTree') {
    fileTree.value = data.tree
  } else if (data.type === 'activeFiles') {
    activeFiles.value = new Set(data.files)
  }
})

const emit = defineEmits(['fileSelect'])
</script>

<style scoped>
.file-explorer {
  width: 250px;
  border-right: 1px solid var(--vscode-secondary);
  display: flex;
  flex-direction: column;
  background-color: var(--vscode-bg);
}

.explorer-header {
  padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--vscode-secondary);
}

.explorer-header h3 {
  margin: 0;
  font-size: 0.9rem;
  color: var(--vscode-fg);
}

.file-tree {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem 0;
}
</style>
