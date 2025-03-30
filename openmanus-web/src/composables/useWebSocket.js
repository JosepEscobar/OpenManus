import { ref, onMounted, onUnmounted } from 'vue'

export function useWebSocket() {
    const ws = ref(null)
    const isConnected = ref(false)
    const messageHandlers = ref(new Set())

    const connect = () => {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        const wsUrl = `${protocol}//${window.location.host}/ws`

        console.log('Connecting to WebSocket at:', wsUrl)
        ws.value = new WebSocket(wsUrl)

        ws.value.onopen = () => {
            console.log('WebSocket connected successfully')
            isConnected.value = true
        }

        ws.value.onclose = (event) => {
            console.log('WebSocket disconnected:', event.code, event.reason)
            isConnected.value = false
            // Attempt to reconnect after 5 seconds
            setTimeout(connect, 5000)
        }

        ws.value.onerror = (error) => {
            console.error('WebSocket error:', error)
            isConnected.value = false
        }

        ws.value.onmessage = (event) => {
            try {
                console.log('Received WebSocket message:', event.data)
                const data = JSON.parse(event.data)
                messageHandlers.value.forEach(handler => handler(data))
            } catch (error) {
                console.error('Error parsing WebSocket message:', error)
            }
        }
    }

    const send = (data) => {
        if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
            console.error('WebSocket is not connected, cannot send message:', data)
            throw new Error('WebSocket is not connected')
        }
        console.log('Sending WebSocket message:', data)
        ws.value.send(JSON.stringify(data))
    }

    const onMessage = (handler) => {
        messageHandlers.value.add(handler)
        return () => messageHandlers.value.delete(handler)
    }

    onMounted(() => {
        connect()
    })

    onUnmounted(() => {
        if (ws.value) {
            ws.value.close()
        }
    })

    return {
        isConnected,
        send,
        onMessage
    }
}
