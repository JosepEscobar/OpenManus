import asyncio
import os
import sys

# Agregar el directorio actual al path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.web.server import truncate_text
from app.agent.manus import Manus

async def test_long_message():
    """Prueba el truncado correcto de mensajes largos"""

    # Crear un mensaje muy largo para probar
    long_message = "Este es un mensaje extremadamente largo " * 50
    print(f"Longitud del mensaje original: {len(long_message)} caracteres")

    # Truncar el mensaje a 500 caracteres
    truncated_message = truncate_text(long_message, 500)
    print(f"Longitud del mensaje truncado: {len(truncated_message)} caracteres")
    print(f"Mensaje truncado termina con: '{truncated_message[-10:]}'")

    # Verificar que el mensaje truncado tiene la longitud correcta
    assert len(truncated_message) <= 500
    assert truncated_message.endswith("...")

    # Crear una función de callback para capturar los mensajes
    messages = []
    async def progress_callback(message):
        messages.append(message)
        print(f"[MENSAJE RECIBIDO] (longitud: {len(message)}): {message[:50]}...")

    # Crear una instancia de Manus
    agent = Manus()
    agent.set_progress_callback(progress_callback)

    # Ejecutar una tarea simple con un mensaje largo
    prompt = f"Echo test: {long_message}"
    print("\n=== Ejecutando prueba con mensaje largo ===")
    await agent.run(prompt)

    # Verificar que ninguno de los mensajes supera los 500 caracteres
    print("\n=== Verificando longitud de mensajes ===")
    for i, msg in enumerate(messages):
        if len(msg) > 500:
            print(f"ERROR: Mensaje {i+1} tiene {len(msg)} caracteres (debería ser ≤ 500)")
        else:
            print(f"OK: Mensaje {i+1} tiene {len(msg)} caracteres")

    # Contar cuántos mensajes exceden los 500 caracteres
    exceeding_messages = [msg for msg in messages if len(msg) > 500]

    if not exceeding_messages:
        print("\n✅ TEST EXITOSO: Todos los mensajes están correctamente truncados")
    else:
        print(f"\n❌ TEST FALLIDO: {len(exceeding_messages)} mensajes exceden el límite de 500 caracteres")

if __name__ == "__main__":
    asyncio.run(test_long_message())
