<template>
  <div class="app-container">
    <div class="workspace-column">
      <div class="status-section">
        <EditorStatus />
      </div>
      <div class="workspace-section">
        <FileExplorerLive @fileSelect="handleFileSelect" />
        <FileContentViewer ref="fileContentViewer" />
      </div>
    </div>
    <div class="chat-column">
      <ChatBox />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import ChatBox from './components/ChatBox.vue'
import EditorStatus from './components/EditorStatus.vue'
import FileExplorerLive from './components/FileExplorerLive.vue'
import FileContentViewer from './components/FileContentViewer.vue'
import { useWebSocket } from './composables/useWebSocket'

const fileContentViewer = ref(null)
const { onMessage } = useWebSocket()

const handleFileSelect = (filePath) => {
  fileContentViewer.value?.handleFileSelect(filePath)
}

// Manejar mensajes de selección de archivo automática
onMessage((data) => {
  if (data.type === 'selectFile' && data.path) {
    handleFileSelect(data.path)
  }
})
</script>

<style>
:root {
  --vscode-bg: #1e1e1e;
  --vscode-fg: #d4d4d4;
  --vscode-primary: #007acc;
  --vscode-secondary: #3c3c3c;
  --vscode-accent: #569cd6;
  --vscode-error: #f48771;
  --vscode-success: #4ec9b0;
}

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
  background-color: var(--vscode-bg);
  color: var(--vscode-fg);
}

.app-container {
  display: flex;
  height: 100vh;
  width: 100vw;
}

.chat-column {
  flex: 1.2;
  border-left: 1px solid var(--vscode-secondary);
  display: flex;
  flex-direction: column;
}

.workspace-column {
  flex: 2.8;
  display: flex;
  flex-direction: column;
}

.status-section {
  min-height: 90px;
  border-bottom: 1px solid var(--vscode-secondary);
}

.workspace-section {
  flex: 1;
  display: flex;
  overflow: hidden;
}
</style>
