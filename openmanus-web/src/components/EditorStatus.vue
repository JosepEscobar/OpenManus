<template>
  <div class="status-container">
    <div class="status-indicator" :class="status">
      <div class="status-dot"></div>
      <span class="status-text">{{ statusText }}</span>
    </div>
    <div class="current-action" v-if="currentAction">
      {{ currentAction }}
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useWebSocket } from '../composables/useWebSocket'

const status = ref('idle')
const currentAction = ref('')

const { onMessage } = useWebSocket()

const statusText = computed(() => {
  switch (status.value) {
    case 'thinking':
      return 'Thinking...'
    case 'executing':
      return 'Executing...'
    case 'waiting':
      return 'Waiting for instructions'
    case 'error':
      return 'Error'
    default:
      return 'Idle'
  }
})

onMessage((data) => {
  if (data.type === 'status') {
    status.value = data.status
    currentAction.value = data.action || ''
  }
})
</script>

<style scoped>
.status-container {
  display: flex;
  align-items: center;
  padding: 0 1rem;
  height: 100%;
  background-color: var(--vscode-secondary);
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--vscode-fg);
}

.status-indicator.thinking .status-dot {
  background-color: var(--vscode-accent);
  animation: pulse 1.5s infinite;
}

.status-indicator.executing .status-dot {
  background-color: var(--vscode-primary);
  animation: pulse 1s infinite;
}

.status-indicator.error .status-dot {
  background-color: var(--vscode-error);
}

.status-indicator.waiting .status-dot {
  background-color: var(--vscode-success);
}

.status-text {
  font-size: 0.9rem;
  color: var(--vscode-fg);
}

.current-action {
  margin-left: 2rem;
  font-size: 0.9rem;
  color: var(--vscode-fg);
  opacity: 0.8;
}

@keyframes pulse {
  0% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
  100% {
    opacity: 1;
  }
}
</style>
