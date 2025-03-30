<template>
  <div class="chat-container">
    <div class="chat-messages" ref="messagesContainer">
      <div v-for="(message, index) in messages"
           :key="index"
           :class="['message', message.sender === 'user' ? 'user-message' : 'assistant-message']">
        <div class="message-content">{{ message.content }}</div>
        <div class="message-timestamp">{{ formatTimestamp(message.timestamp) }}</div>
      </div>
    </div>
    <div class="chat-input">
      <textarea
        v-model="inputMessage"
        placeholder="Escribe un mensaje para OpenManus..."
        @keydown.enter.prevent="sendMessage"
        @input="adjustTextareaHeight"
        ref="inputTextarea"
      ></textarea>
      <button @click="sendMessage" class="send-button">
        <i class="fas fa-paper-plane"></i>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import { useWebSocket } from '../composables/useWebSocket'

const messages = ref([])
const inputMessage = ref('')
const messagesContainer = ref(null)
const inputTextarea = ref(null)
const { send, onMessage, isConnected } = useWebSocket()

// Formatear la marca de tiempo para mostrarla amigablemente
const formatTimestamp = (timestamp) => {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleTimeString()
}

// Ajustar la altura del textarea automáticamente
const adjustTextareaHeight = () => {
  const textarea = inputTextarea.value
  if (!textarea) return

  textarea.style.height = 'auto'
  textarea.style.height = `${Math.min(textarea.scrollHeight, 150)}px`
}

// Desplazarse al final del contenedor de mensajes
const scrollToBottom = () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

// Enviar un mensaje al backend
const sendMessage = async () => {
  if (!inputMessage.value.trim()) return

  const message = {
    type: 'chat',
    content: inputMessage.value.trim(),
    sender: 'user',
    timestamp: new Date().toISOString()
  }

  messages.value.push(message)
  scrollToBottom()

  // Limpiar el input y restablecer su altura
  inputMessage.value = ''
  adjustTextareaHeight()

  try {
    // Enviar el mensaje al servidor WebSocket
    await send(message)
  } catch (error) {
    console.error('Error al enviar mensaje:', error)
    messages.value.push({
      content: 'Error al enviar el mensaje. Por favor intenta de nuevo.',
      sender: 'system',
      timestamp: new Date().toISOString()
    })
    scrollToBottom()
  }
}

// Escuchar mensajes entrantes del WebSocket
onMessage((data) => {
  console.log('ChatBox received message:', data)
  if (data.type === 'chat') {
    messages.value.push({
      content: data.content,
      sender: data.sender || 'assistant',
      timestamp: data.timestamp || new Date().toISOString()
    })
    scrollToBottom()
  } else if (data.type === 'error') {
    messages.value.push({
      content: `Error: ${data.message}`,
      sender: 'system',
      timestamp: new Date().toISOString()
    })
    scrollToBottom()
  }
})

// Observar cambios en los mensajes para desplazarse al final
watch(messages, () => {
  scrollToBottom()
})

onMounted(() => {
  scrollToBottom()

  // Agregar un mensaje de bienvenida
  setTimeout(() => {
    messages.value.push({
      content: '¡Hola! Soy OpenManus. ¿En qué puedo ayudarte hoy?',
      sender: 'assistant',
      timestamp: new Date().toISOString()
    })
  }, 1000)
})
</script>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background-color: var(--vscode-bg);
  color: var(--vscode-fg);
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.message {
  max-width: 80%;
  padding: 0.75rem;
  border-radius: 8px;
  margin-bottom: 0.5rem;
  position: relative;
}

.user-message {
  align-self: flex-end;
  background-color: var(--vscode-primary);
  color: white;
}

.assistant-message {
  align-self: flex-start;
  background-color: var(--vscode-secondary);
  color: var(--vscode-fg);
}

.message-content {
  word-break: break-word;
  white-space: pre-wrap;
}

.message-timestamp {
  font-size: 0.7rem;
  opacity: 0.7;
  text-align: right;
  margin-top: 0.25rem;
}

.chat-input {
  display: flex;
  padding: 1rem;
  border-top: 1px solid var(--vscode-secondary);
}

textarea {
  flex: 1;
  resize: none;
  min-height: 40px;
  max-height: 150px;
  padding: 0.75rem;
  background-color: var(--vscode-secondary);
  color: var(--vscode-fg);
  border: none;
  border-radius: 8px;
  outline: none;
  font-family: inherit;
}

.send-button {
  background-color: var(--vscode-primary);
  color: white;
  border: none;
  border-radius: 8px;
  width: 40px;
  margin-left: 0.5rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.2s;
}

.send-button:hover {
  background-color: #0085e0;
}
</style>
