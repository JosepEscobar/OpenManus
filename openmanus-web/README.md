# OpenManus Web Interface

Una interfaz web moderna para interactuar con OpenManus, permitiendo comunicación en tiempo real y visualización del estado del sistema.

## Características

- 🗣️ Chat en tiempo real con OpenManus
- 📁 Explorador de archivos en vivo
- 📝 Visualizador de contenido de archivos
- 🔄 Indicador de estado del sistema
- 🌐 Comunicación WebSocket para actualizaciones en tiempo real

## Requisitos

- Node.js (v16+)
- NPM o Yarn

## Instalación

```bash
# Instalar dependencias
npm install

# O si prefieres usar Yarn
yarn
```

## Desarrollo

```bash
# Iniciar servidor de desarrollo
npm run dev

# O con Yarn
yarn dev
```

Esto iniciará un servidor de desarrollo en `http://localhost:3000`.

## Compilación para producción

```bash
# Compilar para producción
npm run build

# O con Yarn
yarn build
```

## Estructura del proyecto

```
openmanus-web/
├── src/
│   ├── components/       # Componentes Vue
│   ├── composables/      # Composables (lógica reutilizable)
│   ├── App.vue           # Componente principal
│   ├── main.js           # Punto de entrada
│   └── style.css         # Estilos globales
├── index.html            # Plantilla HTML
├── vite.config.js        # Configuración de Vite
└── package.json          # Dependencias y scripts
```

## Comunicación con el backend

La interfaz web se comunica con el backend de OpenManus a través de WebSockets para las actualizaciones en tiempo real y peticiones HTTP para operaciones específicas.

La configuración del proxy en `vite.config.js` está configurada para conectarse a un servidor backend ejecutándose en `localhost:8000`.
