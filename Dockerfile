# Usamos la imagen oficial de Playwright para Python
# Esta imagen ya incluye Chromium, Firefox y WebKit instalados
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Establecemos el directorio de trabajo
WORKDIR /app

# Copiamos los archivos de dependencias primero (para aprovechar la caché de Docker)
COPY requirements.txt .

# Instalamos las dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto del código
COPY . .

# Exponemos el puerto (Render usa el 10000 por defecto, pero lo lee de PORT)
EXPOSE 10000

# Comando de inicio
CMD ["python", "main.py"]
