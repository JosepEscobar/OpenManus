"""
Script para iniciar el servidor web de OpenManus.
Este servidor proporciona una interfaz web para interactuar con OpenManus.
"""

import uvicorn
from app.web.server import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host="0.0.0.0", port=8001)
