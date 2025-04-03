<template>
  <div class="chat-container">
    <div class="chat-header">
      <h3>Chat</h3>
      <button @click="clearChat" class="clear-button" title="Limpiar chat">
        <i class="fas fa-trash"></i>
      </button>
    </div>
    <div class="chat-messages" ref="messagesContainer">
      <div v-for="(message, index) in messages"
           :key="index"
           :class="['message', message.sender === 'user' ? 'user-message' : 'assistant-message']">
        <div class="avatar" :class="message.sender">
          <span v-if="message.sender === 'user'">U</span>
          <span v-else>AI</span>
        </div>
        <div class="message-bubble">
          <div class="message-content" :class="{ 'user-content': message.sender === 'user' }">{{ message.content }}</div>
          <div class="message-timestamp">{{ formatTimestamp(message.timestamp) }}</div>
        </div>
      </div>
    </div>
    <div class="chat-input-container">
      <div class="input-wrapper">
        <textarea
          v-model="inputMessage"
          placeholder="Escribe tu tarea para OpenManus..."
          @keydown="handleKeyDown"
          @input="adjustTextareaHeight"
          ref="inputTextarea"
        ></textarea>

        <button @click="sendMessage" class="send-button" :disabled="!inputMessage.trim()">
          <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" class="send-icon">
            <path d="M22 2L11 13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
            <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
          </svg>
        </button>
      </div>
      <div class="chat-footer">
        <span class="shortcut-hint">Shift + Enter para nueva línea • Enter para enviar</span>
      </div>
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
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// Ajustar la altura del textarea automáticamente
const adjustTextareaHeight = () => {
  const textarea = inputTextarea.value
  if (!textarea) return

  textarea.style.height = 'auto'
  textarea.style.height = `${Math.min(textarea.scrollHeight, 150)}px`
}

// Manejar las teclas presionadas en el textarea
const handleKeyDown = (e) => {
  // Si es Shift+Enter, permitir nueva línea
  if (e.key === 'Enter' && e.shiftKey) {
    return
  }

  // Si es solo Enter, enviar mensaje
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
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

  const userContent = inputMessage.value.trim()
  let messageContent = userContent

  // Ya no agregamos instrucciones adicionales al primer mensaje
  // porque ahora esto lo maneja el CoordinatorAgent

  const message = {
    type: 'chat',
    content: userContent,
    sender: 'user',
    timestamp: new Date().toISOString()
  }

  messages.value.push(message)
  scrollToBottom()

  // Limpiar el input y restablecer su altura
  inputMessage.value = ''
  adjustTextareaHeight()

  try {
    // Enviar el mensaje al servidor WebSocket sin modificaciones
    await send({
      type: 'chat',
      content: messageContent,
      sender: 'user',
      timestamp: new Date().toISOString()
    })
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

// Observar cambios en los mensajes
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

// Limpiar el chat y resetear el estado
const clearChat = () => {
  // Eliminar todos los mensajes excepto el de bienvenida
  messages.value = messages.value.filter(msg =>
    msg.sender === 'assistant' &&
    msg.content === '¡Hola! Soy OpenManus. ¿En qué puedo ayudarte hoy?'
  )

  // Scroll al final para mostrar el mensaje de bienvenida
  scrollToBottom()
}
</script>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  background-color: var(--vscode-bg);
  color: var(--vscode-fg);
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--vscode-secondary);
  background-color: var(--vscode-secondary);
}

.chat-header h3 {
  margin: 0;
  font-size: 1rem;
  color: var(--vscode-fg);
}

.clear-button {
  background: none;
  border: none;
  color: var(--vscode-fg);
  cursor: pointer;
  opacity: 0.7;
  transition: opacity 0.2s;
  padding: 5px;
  border-radius: 4px;
}

.clear-button:hover {
  opacity: 1;
  background-color: rgba(255, 255, 255, 0.1);
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.message {
  display: flex;
  gap: 1rem;
  padding-bottom: 0.5rem;
  position: relative;
  max-width: 100%;
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 0.75rem;
  flex-shrink: 0;
}

.user-message {
  background-color: #16181d;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
  margin: 0.5rem 0;
  padding: 1rem;
}

.user-content {
  color: #d1d5db;
  font-size: 0.9rem;
}

.user-message .avatar {
  display: none;
}

.avatar.user {
  background-color: var(--vscode-primary);
  color: white;
}

.avatar.assistant {
  background-color: #10a37f;
  color: white;
}

.message-bubble {
  flex: 1;
  max-width: calc(100% - 50px);
}

.user-message .message-bubble {
  max-width: 100%;
}

.user-message .message-content {
  color: white;
}

.assistant-message .message-content {
  color: var(--vscode-fg);
}

.message-content {
  word-break: break-word;
  white-space: pre-wrap;
  line-height: 1.5;
}

.message-timestamp {
  font-size: 0.7rem;
  opacity: 0.7;
  text-align: right;
  margin-top: 0.25rem;
}

.user-message .message-timestamp {
  color: #9ca3af;
}

.chat-input-container {
  border-top: 1px solid var(--vscode-secondary);
  padding: 1rem;
  background-color: var(--vscode-bg);
}

.input-wrapper {
  position: relative;
  display: flex;
  align-items: flex-end;
  background-color: var(--vscode-secondary);
  border-radius: 8px;
  padding: 0.75rem;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}

textarea {
  flex: 1;
  resize: none;
  min-height: 24px;
  max-height: 150px;
  padding: 0;
  background-color: transparent;
  color: var(--vscode-fg);
  border: none;
  outline: none;
  font-family: inherit;
  font-size: 0.95rem;
  line-height: 1.5;
}

.first-message-notice {
  position: absolute;
  bottom: -22px;
  left: 0;
  font-size: 0.8rem;
  color: var(--vscode-fg);
  opacity: 0.7;
  padding: 2px 5px;
}

.send-button {
  background-color: transparent;
  color: var(--vscode-primary);
  border: none;
  width: 32px;
  height: 32px;
  padding: 6px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background-color 0.2s;
  align-self: flex-end;
  margin-left: 8px;
}

.send-button:hover:not(:disabled) {
  background-color: rgba(0, 122, 204, 0.1);
}

.send-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.send-icon {
  width: 100%;
  height: 100%;
}

.chat-footer {
  padding-top: 0.5rem;
  text-align: center;
  font-size: 0.75rem;
  color: var(--vscode-fg);
  opacity: 0.6;
}

.shortcut-hint {
  font-size: 0.75rem;
}
</style>
