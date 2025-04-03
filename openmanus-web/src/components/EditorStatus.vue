<template>
  <div class="status-container">
    <div class="status-row">
      <div class="status-indicator" :class="status">
        <div class="status-dot"></div>
        <span class="status-text">{{ statusText }}</span>
      </div>
    </div>
    <div class="action-row" v-if="currentAction">
      <div class="current-action">
        {{ currentAction }}
      </div>
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
    case 'working':
      return 'Working...'
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
  flex-direction: column;
  justify-content: center;
  padding: 0.75rem 1rem;
  height: 100%;
  background-color: var(--vscode-secondary);
}

.status-row {
  display: flex;
  align-items: center;
  margin-bottom: 0.5rem;
}

.action-row {
  display: flex;
  align-items: flex-start;
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

.status-indicator.working .status-dot,
.status-indicator.executing .status-dot {
  background-color: var(--vscode-primary);
  animation: pulse 1s infinite;
}

.status-indicator.error .status-dot {
  background-color: var(--vscode-error);
}

.status-indicator.waiting .status-dot,
.status-indicator.idle .status-dot {
  background-color: var(--vscode-success);
}

.status-text {
  font-size: 0.95rem;
  font-weight: bold;
  color: var(--vscode-fg);
}

.current-action {
  font-size: 0.95rem;
  color: var(--vscode-fg);
  word-wrap: break-word;
  max-width: 100%;
  line-height: 1.3;
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
