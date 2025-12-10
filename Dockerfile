# Dockerfile

# Usa una imagen base de Python oficial y ligera
FROM python:3.11-slim

# Establece el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia los archivos de dependencia e instala
COPY requirements.txt .

# NUEVO: Instalar la dependencia de sistema 'libmagic'
# Necesaria para que 'python-magic' funcione correctamente
RUN apt-get update && apt-get install -y libmagic1 && rm -rf /var/lib/apt/lists/*

# Asegura que las dependencias se instalen sin caché para mantener la imagen pequeña
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código de la aplicación (app.py y otros archivos necesarios)
COPY app.py .

# --- Configuración de USUARIO Y PERMISOS (CRÍTICO PARA VOLÚMENES) ---
# Creamos un grupo 'appgroup' y un usuario 'appuser' con el UID y GID 1001.
# ESTE UID/GID (1001) DEBE COINCIDIR CON EL OWNER DEL ARCHIVO 'tokens.txt' EN EL HOST.
RUN groupadd --gid 1001 appgroup && useradd --uid 1001 --gid 1001 --shell /bin/bash -m appuser

# Cambiamos la propiedad del directorio de la aplicación al nuevo usuario
RUN chown -R appuser:appgroup /app

# Exponer el puerto
EXPOSE 5000

# Cambiamos el contexto de ejecución al usuario 'appuser'
USER appuser

# Comando para ejecutar Gunicorn (servidor WSGI de producción).
# --access-logfile - y --error-logfile - aseguran que los logs se vayan a la consola (stdout/stderr)
# para que Docker los capture correctamente (Solución a los logs que no aparecían).
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app", "--access-logfile", "-", "--error-logfile", "-"]
