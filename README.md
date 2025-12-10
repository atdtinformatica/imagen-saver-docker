# 📸 Image Saver Service (image-saver-docker)

Servicio web ligero y seguro, contenedorizado con Docker y escrito en Python (Flask), diseñado para recibir imágenes (JPEG/PNG) a través de una API REST y persistirlas en el disco del servidor host mediante volúmenes.

Este proyecto implementa autenticación por tokens segregados, validación estricta del contenido del archivo y configuración flexible a través de variables de entorno.

## ✨ Características Principales

* **Autenticación Segura:** Acceso controlado mediante tokens listados en un archivo mapeado.
* **Validación de Contenido:** Verifica la firma binaria del archivo (MIME Type real) para aceptar **solo imágenes JPEG y PNG**, rechazando archivos renombrados.
* **Persistencia:** Utiliza volúmenes de Docker para guardar archivos en el host, creando automáticamente las estructuras de directorio (`save_path`) especificadas por el cliente.
* **Administración Remota:** Ruta de administración con Token Maestro dedicado para recargar la lista de tokens sin reiniciar el servicio.
* **Observabilidad:** Logging detallado que captura la IP real del cliente (gracias a `ProxyFix` si hay un *reverse proxy*).

## 🚀 Cómo Usar (Despliegue)

La forma más sencilla de levantar este servicio es utilizando `docker-compose`.

### A. Estructura de Carpetas en el Host

Crea los directorios necesarios en tu sistema host. Estos serán mapeados a los volúmenes del contenedor.

```bash
mkdir -p storage/images
mkdir -p storage/logs
mkdir -p config
touch config/tokens.txt
