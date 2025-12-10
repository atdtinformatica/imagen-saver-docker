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

Archivo config/tokens.txt
Añade los tokens de cliente que usarán la ruta /upload (uno por línea):

# Ejemplo de tokens de cliente (solo para la ruta /upload)
CLIENTE-A-TOKEN-123
WEBAPP-PROD-98765

## 💡 Endpoints de la API

| Endpoint               | Método      | Función                                 | Autenticación Requerida                    |
| :---                   | :---        | :---                                    | :---                                       |
| `/upload`              | `POST`      | Sube y guarda una imagen en disco.      | Token de Cliente (desde `tokens.txt`)      |
| `/admin/reload-tokens` | `POST`      | Recarga la lista de tokens del archivo. | **Token Maestro** (`MASTER_TOKEN` env var) |


Ejemplo de Invocación (Subida de Imagen):

curl -X POST http://localhost:8080/upload \
  -H "Authorization: Bearer CLIENTE-A-TOKEN-123" \
  -F "image=@./local_image.jpg" \
  -F "save_path=users/premium/profile.jpg"

## 🔒 Administración y Recarga de Tokens

El endpoint `/admin/reload-tokens` permite recargar el archivo `tokens.txt` en la memoria de los workers de Gunicorn **sin necesidad de reiniciar el contenedor**.

**Requisitos:**
1.  Debe enviarse por el método `POST`.
2.  Debe usar el valor exacto definido en la variable de entorno **`MASTER_TOKEN`**.

### Ejemplo de Invocación (Recarga de Tokens)

Supongamos que tu `MASTER_TOKEN` es `MI-TOKEN-ADMIN-SECRETO-XYZ`:

```bash
curl -X POST http://localhost:8080/admin/reload-tokens \
  -H "Authorization: Bearer MI-TOKEN-ADMIN-SECRETO-XYZ"

Si la recarga es exitosa, la respuesta será un JSON con el nuevo conteo de tokens, y un mensaje de éxito aparecerá en los logs:

{
  "message": "Tokens recargados exitosamente.",
  "total_tokens": 5
}

🚨 Nota de Seguridad Crítica: El MASTER_TOKEN es la llave de administración del servicio. Nunca debe ser compartido con clientes de subida de imágenes y nunca debe ser listado en el archivo tokens.txt. Asegúrate de que esta variable de entorno sea un valor complejo y secreto.


