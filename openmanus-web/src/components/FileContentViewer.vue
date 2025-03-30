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
      <div v-if="content" class="code-container">
        <div v-html="highlightedCode" class="highlighted-code"></div>
      </div>
      <div v-else class="no-content">
        Select a file to view its content
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { useWebSocket } from '../composables/useWebSocket'
import { getHighlighter } from 'shiki'

const currentFile = ref(null)
const content = ref('')
const contentViewer = ref(null)
const { send, onMessage } = useWebSocket()
const highlighter = ref(null)
const isHighlighterReady = ref(false)

// Inicializar el highlighter
onMounted(async () => {
  try {
    highlighter.value = await getHighlighter({
      theme: 'dark-plus', // Tema de VS Code
      langs: [
        'javascript', 'typescript', 'jsx', 'tsx', 'html', 'css', 'scss',
        'json', 'python', 'java', 'php', 'ruby', 'go', 'rust', 'c', 'cpp',
        'csharp', 'markdown', 'yaml', 'bash', 'sql', 'xml'
      ],
    })
    isHighlighterReady.value = true
  } catch (e) {
    console.error('Error al inicializar Shiki:', e)
  }
})

// Función para determinar el lenguaje para Shiki
const getLanguage = () => {
  if (!currentFile.value) return 'text'

  const extension = currentFile.value.type.toLowerCase()
  const extensionMap = {
    'js': 'javascript',
    'ts': 'typescript',
    'jsx': 'jsx',
    'tsx': 'tsx',
    'py': 'python',
    'java': 'java',
    'html': 'html',
    'htm': 'html',
    'css': 'css',
    'scss': 'scss',
    'less': 'css',
    'json': 'json',
    'xml': 'xml',
    'md': 'markdown',
    'sh': 'bash',
    'bash': 'bash',
    'vue': 'html',
    'cpp': 'cpp',
    'cc': 'cpp',
    'c': 'c',
    'cs': 'csharp',
    'go': 'go',
    'rb': 'ruby',
    'php': 'php',
    'rs': 'rust',
    'swift': 'javascript', // Fallback para Swift
    'kt': 'java', // Fallback para Kotlin
    'sql': 'sql',
    'yaml': 'yaml',
    'yml': 'yaml'
  }

  return extensionMap[extension] || 'text'
}

// Computar el código resaltado
const highlightedCode = computed(() => {
  if (!content.value || !isHighlighterReady.value || !highlighter.value) {
    return `<pre class="plain-text">${escapeHtml(content.value)}</pre>`
  }

  try {
    // Primero decodificar cualquier entidad HTML que pueda estar en el contenido
    const decoded = decodeHtmlEntities(content.value)

    // Aplicar el resaltado de sintaxis
    const language = getLanguage()
    return highlighter.value.codeToHtml(decoded, { lang: language })
  } catch (e) {
    console.error('Error al resaltar el código:', e)
    return `<pre class="plain-text">${escapeHtml(content.value)}</pre>`
  }
})

// Función para escapar HTML
function escapeHtml(text) {
  if (!text) return ''

  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

// Función para decodificar entidades HTML
function decodeHtmlEntities(text) {
  if (!text) return ''

  return text
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&#x2F;/g, "/")
    .replace(/&#x3D;/g, "=")
    .replace(/&nbsp;/g, " ")
    .replace(/-&gt;/g, "->") // Para el caso específico de ->
}

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

// Observar cambios en el contenido
watch(content, () => {
  if (contentViewer.value) {
    contentViewer.value.scrollTop = 0
  }
})

defineExpose({
  handleFileSelect
})
</script>

<style>
/* Ajustes para la visualización del código */
.highlighted-code {
  margin: 0;
  padding: 0;
}

.highlighted-code pre {
  margin: 0;
  font-family: 'Fira Code', Menlo, Monaco, Consolas, monospace;
  font-size: 0.7rem !important; /* Tamaño reducido */
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  background-color: transparent !important;
}

.highlighted-code code {
  font-family: inherit;
  background-color: transparent !important;
}

.plain-text {
  font-family: 'Fira Code', Menlo, Monaco, Consolas, monospace;
  font-size: 0.7rem;
  line-height: 1.5;
  color: #d4d4d4;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>

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
  background-color: #1e1e1e; /* Fondo oscuro estilo VSCode */
}

.code-container {
  margin: 0;
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
</style>

