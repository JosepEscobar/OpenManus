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
        <pre v-html="highlightedCode" class="code-content"></pre>
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
import Prism from 'prismjs'

// Importar el tema - elegimos uno similar a GitHub
import 'prismjs/themes/prism-okaidia.css'

// Importar los idiomas necesarios
import 'prismjs/components/prism-markup'
import 'prismjs/components/prism-css'
import 'prismjs/components/prism-javascript'
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-jsx'
import 'prismjs/components/prism-tsx'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-java'
import 'prismjs/components/prism-bash'
import 'prismjs/components/prism-c'
import 'prismjs/components/prism-cpp'
import 'prismjs/components/prism-csharp'
import 'prismjs/components/prism-go'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-markdown'
import 'prismjs/components/prism-ruby'
import 'prismjs/components/prism-yaml'
import 'prismjs/components/prism-sql'
import 'prismjs/components/prism-rust'
import 'prismjs/components/prism-scss'
import 'prismjs/components/prism-php'

// Plugins para mejorar la visualización
import 'prismjs/plugins/line-numbers/prism-line-numbers'
import 'prismjs/plugins/line-numbers/prism-line-numbers.css'

// Definir variables reactivas
const currentFile = ref(null)
const content = ref('')
const contentViewer = ref(null)
const { send, onMessage } = useWebSocket()

// Mapa de extensiones de archivo a lenguajes de Prism.js
const languageMap = {
  'js': 'javascript',
  'jsx': 'jsx',
  'ts': 'typescript',
  'tsx': 'tsx',
  'py': 'python',
  'java': 'java',
  'html': 'html',
  'htm': 'html',
  'xml': 'xml',
  'css': 'css',
  'scss': 'scss',
  'less': 'css',
  'json': 'json',
  'md': 'markdown',
  'markdown': 'markdown',
  'sh': 'bash',
  'bash': 'bash',
  'zsh': 'bash',
  'c': 'c',
  'h': 'c',
  'cpp': 'cpp',
  'cc': 'cpp',
  'hpp': 'cpp',
  'cs': 'csharp',
  'go': 'go',
  'rb': 'ruby',
  'rs': 'rust',
  'php': 'php',
  'sql': 'sql',
  'yaml': 'yaml',
  'yml': 'yaml',
  'vue': 'markup',
  'txt': 'text',
  'gitignore': 'text',
  'dockerfile': 'docker',
  'env': 'text'
}

// Obtener el lenguaje basado en la extensión del archivo
const getLanguage = (filename) => {
  if (!filename) return 'text'

  // Extraer la extensión o usar el nombre de archivo para ciertos tipos
  let extension = ''
  if (filename.includes('.')) {
    extension = filename.split('.').pop().toLowerCase()
  } else {
    extension = filename.toLowerCase() // Para archivos sin extensión como Dockerfile o .gitignore
  }

  return languageMap[extension] || 'text'
}

// Función para decodificar entidades HTML
function decodeHtmlEntities(text) {
  if (!text) return ''

  const textarea = document.createElement('textarea')
  textarea.innerHTML = text
  return textarea.value
}

// Función para escapar HTML para mostrar seguramente
function escapeHtml(text) {
  if (!text) return ''

  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

// Código resaltado computado
const highlightedCode = computed(() => {
  if (!content.value) return ''

  try {
    // Decodificar cualquier entidad HTML primero
    const decodedContent = decodeHtmlEntities(content.value)

    // Obtener el lenguaje basado en el archivo actual
    const language = currentFile.value
      ? getLanguage(currentFile.value.name)
      : 'text'

    // Verificar si Prism soporta el lenguaje
    if (Prism.languages[language]) {
      // Aplicar resaltado usando Prism
      const highlighted = Prism.highlight(
        decodedContent,
        Prism.languages[language],
        language
      )

      // Retornar el código resaltado dentro de una etiqueta <code> con la clase correcta
      return `<code class="language-${language} line-numbers">${highlighted}</code>`
    } else {
      // Fallback para lenguajes no soportados
      return `<code class="language-text">${escapeHtml(decodedContent)}</code>`
    }
  } catch (e) {
    console.error('Error al aplicar Prism:', e)
    // Fallback en caso de error
    return `<code class="language-text">${escapeHtml(content.value)}</code>`
  }
})

// Refrescar el contenido del archivo
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

// Manejar la selección de archivo
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

// Después de que el componente se monta, inicializar Prism
onMounted(() => {
  // No es necesario inicializar Prism aquí, ya que usamos la función highlight directamente
})

// Exponer el método handleFileSelect para ser usado por el componente padre
defineExpose({
  handleFileSelect
})
</script>

<style>
/* Estilos globales para Prism */
pre[class*="language-"] {
  margin: 0;
  border-radius: 4px;
  background: #1e1e1e !important;
  font-family: 'Fira Code', Consolas, Monaco, 'Andale Mono', 'Ubuntu Mono', monospace;
  font-size: 0.7rem;
  white-space: pre-wrap;
  word-break: break-word;
}

code[class*="language-"] {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  background: transparent !important;
}

/* Mejoras específicas para operadores (como ->) para que se vean bien en Python */
.token.operator {
  background: transparent !important;
}

/* Mejorar la legibilidad de comentarios */
.token.comment {
  color: #6A9955;
}

/* Estilos para números de línea (opcional) */
.line-numbers .line-numbers-rows {
  border-right: 1px solid #404040;
}

.line-numbers-rows > span:before {
  color: #858585;
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
  width: 100%;
  height: 100%;
}

.code-content {
  margin: 0;
  padding: 1em;
  width: 100%;
  background-color: transparent;
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

