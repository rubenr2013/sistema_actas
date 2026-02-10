import requests
import traceback
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

class GroqService:
    """
    Servicio para comunicarse con la API de Groq (modelos de lenguaje tipo LLaMA).
    Incluye:
      - Verificación de conexión.
      - Generación de texto.
      - Manejo detallado de errores.
    """

    def __init__(self):
        # Leer clave desde settings
        self.api_key = getattr(settings, "GROQ_API_KEY", None)
        self.base_url = "https://api.groq.com/openai/v1"

        if not self.api_key:
            logger.error("❌ No se encontró GROQ_API_KEY en settings.py")

    # -------------------------------------------------------------------------
    # 1. Verificar conexión
    # -------------------------------------------------------------------------
    def verificar_conexion(self):
        """Verifica si la API responde correctamente."""
        try:
            if not self.api_key:
                logger.error("GROQ_API_KEY no configurada")
                return False

            headers = {"Authorization": f"Bearer {self.api_key}"}
            url = f"{self.base_url}/models"
            resp = requests.get(url, headers=headers, timeout=10)

            if resp.status_code == 200:
                logger.info("✅ Conexión exitosa con Groq.")
                return True
            else:
                logger.warning(f"⚠️ Error en conexión (status {resp.status_code}): {resp.text}")
                return False

        except Exception as e:
            logger.exception(f"Error al verificar conexión con Groq: {e}")
            return False

    # -------------------------------------------------------------------------
    # 2. Generar texto con Groq (modelo LLaMA)
    # -------------------------------------------------------------------------
    def generar_texto(self, prompt: str, modelo: str = "llama-3.1-8b-instant", max_tokens: int = 1000, temperature: float = 0.7):
        """Envía un prompt al modelo de Groq y devuelve el texto generado."""
        try:
            if not self.api_key:
                return "Error: GROQ_API_KEY no configurada en settings.py"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": modelo,
                "messages": [
                    {"role": "system", "content": "Eres un asistente útil y conciso."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": temperature,
                "max_tokens": max_tokens
            }

            url = f"{self.base_url}/chat/completions"
            response = requests.post(url, headers=headers, json=data, timeout=30)

            if response.status_code == 200:
                content = response.json()
                texto = content["choices"][0]["message"]["content"]
                logger.info(f"🧠 Respuesta generada correctamente. Tokens: {max_tokens}")
                return texto.strip()
            else:
                logger.warning(f"⚠️ Error ({response.status_code}): {response.text}")
                return f"Error {response.status_code}: {response.text}"

        except Exception as e:
            trace = traceback.format_exc()
            logger.error(f"Error al generar texto: {e}\n{trace}")
            return f"Excepción: {e}"

    # -------------------------------------------------------------------------
    # 3. Método de diagnóstico avanzado (opcional)
    # -------------------------------------------------------------------------
    def diagnostico(self):
        """Devuelve información detallada para depurar."""
        import os, actas.services.ia_service as mod

        return {
            "archivo_cargado": getattr(mod, "__file__", None),
            "api_key_longitud": len(self.api_key) if self.api_key else 0,
            "api_key_inicio": self.api_key[:6] + "..." if self.api_key else None,
            "variables_proxy": {
                "HTTP_PROXY": os.environ.get("HTTP_PROXY"),
                "HTTPS_PROXY": os.environ.get("HTTPS_PROXY"),
            },
            "endpoint": self.base_url
        }