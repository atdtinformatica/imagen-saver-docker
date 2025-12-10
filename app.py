# app.py
import os
import logging
from functools import wraps
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import magic # NUEVA IMPORTACIÓN

# --- 1. Configuración de Rutas y Variables Globales (¡Desde Entorno!) ---
# Si la variable de entorno no existe, se usa el valor por defecto (segundo argumento).
LOG_FOLDER = os.environ.get('LOG_FOLDER', '/app/logs')
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', '/app/uploads')
TOKEN_FILE_PATH = os.environ.get('TOKEN_FILE_PATH', '/app/config/tokens.txt')
MASTER_TOKEN = os.environ.get('MASTER_TOKEN', 'ADMIN_MASTER_TOKEN_DEFAULT_CHANGE_ME')

VALID_TOKENS = set()
ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png'} # MIME types permitidos
ABSOLUTE_UPLOAD_FOLDER = os.path.abspath(UPLOAD_FOLDER)


# --- 2. Filtro de Logging para evitar KeyError ---
class DefaultIPFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, 'client_ip'):
            record.client_ip = 'SERVER'
        return True

# --- 3. Configuración del Logger Raíz ---

# Aseguramos que las carpetas existan
if not os.path.exists(LOG_FOLDER):
    os.makedirs(LOG_FOLDER)
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Inicializamos el formatter, handler y logger raíz
formatter = logging.Formatter('%(asctime)s - %(levelname)s - IP:%(client_ip)s - %(message)s')
handler_stream = logging.StreamHandler()
handler_stream.setFormatter(formatter)
handler_stream.addFilter(DefaultIPFilter())

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Eliminamos handlers antiguos y añadimos los nuestros
if root_logger.handlers:
    root_logger.handlers = []

root_logger.addHandler(handler_stream)

# Configuramos el FileHandler si no hay problemas de permisos.
LOG_FILE_PATH = os.path.join(LOG_FOLDER, 'server.log')
try:
    handler_file = logging.FileHandler(LOG_FILE_PATH)
    handler_file.setFormatter(formatter)
    handler_file.addFilter(DefaultIPFilter())
    root_logger.addHandler(handler_file)
    file_log_status = "activado"
except Exception as e:
    file_log_status = f"fallido ({e})"

logger = logging.getLogger(__name__)
logger.info(f"Servicio de subida iniciado. File logging: {file_log_status}.")
# -------------------------------------------------------------

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Aplicar ProxyFix para obtener la IP real del cliente si hay un proxy reverso
# Confiamos en un único proxy (el reverse proxy de Docker)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1, x_prefix=1, x_port=1, x_proto=1)

# --- 4. Función de Carga de Tokens (Mejorada) ---

def load_tokens():
    """Carga los tokens del archivo a la variable global VALID_TOKENS."""
    global VALID_TOKENS
    log_extra = {'client_ip': 'BOOTSTRAP'}

    try:
        with open(TOKEN_FILE_PATH, 'r') as f:
            file_tokens = {line.strip() for line in f if line.strip() and not line.strip().startswith('#')}
            VALID_TOKENS = file_tokens

            logger.info(f"Tokens cargados exitosamente DESDE ARCHIVO. Total: {len(VALID_TOKENS)}", extra=log_extra)

            if not file_tokens:
                 logger.warning("Archivo de tokens leído, pero no se encontró ningún token válido.", extra=log_extra)

    except FileNotFoundError:
        logger.critical(f"ERROR: Archivo de tokens NO ENCONTRADO en: {TOKEN_FILE_PATH}. El servicio no autenticará a nadie.", extra=log_extra)

    except OSError as e:
        logger.critical(f"ERROR FATAL DE PERMISOS/IO al acceder a {TOKEN_FILE_PATH}: {e}. El servicio no autenticará a nadie.", extra=log_extra)

    except Exception as e:
        logger.critical(f"Error desconocido al intentar leer el archivo: {e}. El servicio no autenticará a nadie.", extra=log_extra)

# --- 5. Lógica de Autenticación (Decorador) ---

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        client_ip = request.remote_addr
        log_extra = {'client_ip': client_ip}

        auth_header = request.headers.get('Authorization') or request.headers.get('authorization')
        if not auth_header and 'HTTP_AUTHORIZATION' in request.environ:
            auth_header = request.environ['HTTP_AUTHORIZATION']

        if not auth_header:
            logger.warning("Fallo de Autenticación: No se proporcionó encabezado.", extra=log_extra)
            return jsonify({"error": "Se requiere el encabezado Authorization. Use 'Bearer <token>'."}), 401

        token_parts = auth_header.split()
        token = token_parts[1] if len(token_parts) == 2 and token_parts[0].lower() == 'bearer' else (token_parts[0] if len(token_parts) == 1 else None)

        if not token or token not in VALID_TOKENS:
            token_prefix = token[:5] if token else 'N/A'
            logger.error(f"Fallo de Autenticación: Token inválido. Token prefix: '{token_prefix}'", extra=log_extra)
            return jsonify({"error": "Token inválido o no autorizado."}), 403

        logger.info(f"Autenticación exitosa. Token prefix: '{token[:5]}...'", extra=log_extra)
        return f(*args, **kwargs)
    return decorated

# ------------------- 6. NUEVA RUTA DE ADMINISTRACIÓN -------------------

@app.route('/admin/reload-tokens', methods=['POST'])
def reload_tokens_route():
    client_ip = request.remote_addr
    log_extra = {'client_ip': client_ip}

    # Lógica de extracción de token (similar a token_required)
    auth_header = request.headers.get('Authorization') or request.headers.get('authorization')
    if not auth_header and 'HTTP_AUTHORIZATION' in request.environ:
        auth_header = request.environ['HTTP_AUTHORIZATION']

    token_parts = auth_header.split() if auth_header else []
    token = token_parts[1] if len(token_parts) == 2 and token_parts[0].lower() == 'bearer' else (token_parts[0] if len(token_parts) == 1 else None)

    # Comprobación del Token Maestro
    if token == MASTER_TOKEN and MASTER_TOKEN != 'ADMIN_MASTER_TOKEN_DEFAULT_CHANGE_ME':
        load_tokens()
        logger.info("Tokens recargados exitosamente mediante Token Maestro.", extra=log_extra)
        return jsonify({
            "message": "Tokens recargados exitosamente.",
            "total_tokens": len(VALID_TOKENS)
        }), 200
    else:
        logger.warning(f"Intento de acceso NO autorizado a la ruta de administración. Token prefix: '{token[:5] if token else 'N/A'}'", extra=log_extra)
        return jsonify({"error": "Acceso no autorizado. Se requiere Token Maestro válido."}), 403


# ------------------- 7. RUTA PRINCIPAL DE SUBIDA (upload_image) -------------------

@app.route('/upload', methods=['POST'])
@token_required
def upload_image():
    client_ip = request.remote_addr
    log_extra = {'client_ip': client_ip}

    image_file = request.files.get('image')
    save_path_input = request.form.get('save_path', '')

    if not image_file or image_file.filename == '':
        logger.error("No se encontró el campo 'image'.", extra=log_extra)
        return jsonify({"error": "No se encontró el campo 'image' o no se seleccionó archivo."}), 400

    if not save_path_input:
        logger.error("El campo 'save_path' es requerido.", extra=log_extra)
        return jsonify({"error": "El campo 'save_path' es requerido."}), 400

    # --- NUEVA VALIDACIÓN ESTRICTA POR CONTENIDO ---

    # 1. Leer los primeros bytes del archivo (sin mover el puntero)
    image_file.stream.seek(0)
    file_head = image_file.stream.read(2048) # Leer los primeros 2KB
    image_file.stream.seek(0) # ¡CRÍTICO! Regresar el puntero al inicio para que .save() funcione.

    # 2. Usar python-magic para determinar el MIME type real
    try:
        real_mime_type = magic.from_buffer(file_head, mime=True)
    except Exception as e:
        logger.error(f"Error al determinar MIME type real: {e}", extra=log_extra)
        return jsonify({"error": "Error interno al validar el archivo."}), 500

    if real_mime_type not in ALLOWED_MIME_TYPES:
        logger.error(f"Archivo inválido. Contenido ('{real_mime_type}') no permitido.", extra=log_extra)
        return jsonify({
            "error": "Tipo de archivo no permitido. Solo se permiten imágenes JPEG o PNG (verificación por contenido).",
            "received_type": real_mime_type
        }), 400

    # Reemplazamos la variable que se loguea con el valor real
    mime_type = real_mime_type
    # ------------------------------------------

    original_filename = image_file.filename


    # --- PROCESAMIENTO Y SEGURIDAD DE RUTA ---
    relative_dir, filename = os.path.split(save_path_input)
    safe_filename = secure_filename(filename)
    final_relative_path = os.path.join(relative_dir, safe_filename)
    full_path_in_container = os.path.join(app.config['UPLOAD_FOLDER'], final_relative_path)

    # SEGURIDAD CRÍTICA: Path Traversal
    absolute_target_path = os.path.abspath(full_path_in_container)

    if not absolute_target_path.startswith(ABSOLUTE_UPLOAD_FOLDER):
        logger.error(f"Error 403: Intento de Path Traversal detectado. Ruta: {save_path_input}", extra=log_extra)
        return jsonify({"error": "Ruta de guardado inválida: Intento de acceder fuera del directorio permitido."}), 403

    target_dir = os.path.dirname(full_path_in_container)

    logger.info(f"Procesando archivo: '{original_filename}'. MIME REAL: {mime_type}. Destino: '{full_path_in_container}'", extra=log_extra)

    # Crear directorios intermedios
    if not os.path.exists(target_dir):
        try:
            os.makedirs(target_dir)
            logger.info(f"Directorios intermedios creados: {target_dir}", extra=log_extra)
        except OSError as e:
            logger.critical(f"Error 500 al crear directorios para '{target_dir}': {e}", extra=log_extra)
            return jsonify({"error": f"Error al crear directorios: {e}"}), 500

    # Guardar el archivo
    try:
        image_file.save(full_path_in_container)

        success_msg = f"Archivo guardado. Original: '{original_filename}', Destino: '{final_relative_path}'"
        logger.info(success_msg, extra=log_extra)

        return jsonify({
            "message": "Imagen guardada exitosamente.",
            "relative_path_reported": final_relative_path,
        }), 200
    except Exception as e:
        error_msg = f"Error 500 al guardar archivo. Destino: '{final_relative_path}', Error: {e}"
        logger.error(error_msg, extra=log_extra)
        return jsonify({"error": f"Error al guardar el archivo: {e}"}), 500

# 8. Ejecución de la Carga de Tokens (Fuera del if __name__ == '__main__' para Gunicorn)
load_tokens()


# 9. Ejecución del Servidor de Desarrollo (Solo si se corre directamente)
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
