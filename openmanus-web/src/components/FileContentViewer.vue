<template>
  <div class="file-content">
    <div class="content-header" v-if="currentFile">
      <div class="file-info">
        <span class="file-name">{{ currentFile.name }}</span>
        <span class="file-path">{{ currentFile.path }}</span>
      </div>
      <div class="file-actions">
        <button @click="refreshContent" title="Refresh">
          <i class="fas fa-sync"></i>
        </button>
      </div>
    </div>
    <div class="content-viewer" ref="contentViewer">
      <pre v-if="content" :class="['code-content', currentFile?.type]">{{ content }}</pre>
      <div v-else class="no-content">
        Select a file to view its content
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useWebSocket } from '../composables/useWebSocket'

const currentFile = ref(null)
const content = ref('')
const contentViewer = ref(null)
const { send, onMessage } = useWebSocket()

const refreshContent = async () => {
  if (!currentFile.value) return

  try {
    await send({
      type: 'getFileContent',
      path: currentFile.value.path
    })
  } catch (error) {
    console.error('Error refreshing file content:', error)
  }
}

const handleFileSelect = (filePath) => {
  currentFile.value = {
    path: filePath,
    name: filePath.split('/').pop(),
    type: filePath.split('.').pop()
  }
  refreshContent()
}

// Escuchar mensajes de contenido de archivo desde el servidor
onMessage((data) => {
  // Si recibimos contenido para el archivo actualmente seleccionado
  if (data.type === 'fileContent' && data.path === currentFile.value?.path) {
    content.value = data.content
  }
  // Si recibimos contenido para un archivo diferente (enviado por el servidor)
  else if (data.type === 'fileContent' && data.path && !currentFile.value) {
    currentFile.value = {
      path: data.path,
      name: data.path.split('/').pop(),
      type: data.path.split('.').pop()
    }
    content.value = data.content
  }
})

watch(content, () => {
  if (contentViewer.value) {
    contentViewer.value.scrollTop = 0
  }
})

defineExpose({
  handleFileSelect
})
</script>

<style scoped>
.file-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: var(--vscode-bg);
}

.content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--vscode-secondary);
  background-color: var(--vscode-secondary);
}

.file-info {
  display: flex;
  flex-direction: column;
}

.file-name {
  font-weight: 500;
  color: var(--vscode-fg);
}

.file-path {
  font-size: 0.8rem;
  color: var(--vscode-fg);
  opacity: 0.7;
}

.file-actions button {
  background: none;
  border: none;
  color: var(--vscode-fg);
  cursor: pointer;
  padding: 0.25rem;
  border-radius: 4px;
  transition: background-color 0.2s;
}

.file-actions button:hover {
  background-color: var(--vscode-primary);
}

.content-viewer {
  flex: 1;
  overflow: auto;
  padding: 1rem;
}

.code-content {
  margin: 0;
  font-family: 'Fira Code', monospace;
  font-size: 0.9rem;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.no-content {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--vscode-fg);
  opacity: 0.5;
  font-style: italic;
}

/* Syntax highlighting classes */
.code-content.python {
  color: #4ec9b0;
}

.code-content.js {
  color: #9cdcfe;
}

.code-content.html {
  color: #808080;
}

.code-content.css {
  color: #ce9178;
}

.code-content.json {
  color: #ce9178;
}

.code-content.md {
  color: #d4d4d4;
}
</style>
