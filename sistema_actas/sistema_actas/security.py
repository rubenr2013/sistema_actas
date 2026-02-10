from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
import logging
import re
from datetime import datetime
from django.core.cache import cache

logger = logging.getLogger('security')


class SecurityMiddleware:
    """Middleware de seguridad personalizado"""
    def __init__(self, get_response):
        self.get_response = get_response

        # Patrones de ataques comunes (mejorados)
        self.attack_patterns = [
            # XSS
            r'<script.*?>.*?</script>',
            r'javascript:',
            r'vbscript:',
            r'onload\s*=',
            r'onerror\s*=',
            r'onclick\s*=',
            r'onmouseover\s*=',
            r'onfocus\s*=',
            r'onblur\s*=',
            r'expression\s*\(',
            # SQL Injection
            r'union\s+select',
            r';\s*drop\s+',
            r';\s*delete\s+',
            r';\s*insert\s+',
            r';\s*update\s+',
            r'--\s*$',
            r'/\*.*\*/',
            # Code Injection
            r'eval\s*\(',
            r'exec\s*\(',
            r'system\s*\(',
            r'passthru\s*\(',
            r'shell_exec\s*\(',
            # Path Traversal
            r'\.\./\.\.',
            r'\.\.\\\\',
            # LDAP Injection
            r'\)\s*\(\|',
            r'\)\s*\(\&',
        ]

        # Rutas de autenticación (rate limiting más estricto)
        self.auth_paths = [
            '/actas/api/auth/login/',
            '/actas/api/auth/register/',
            '/actas/api/auth/verificar-codigo/',
            '/actas/api/auth/reenviar-codigo/',
            '/accounts/password_reset/',
        ]

    def __call__(self, request):
        # Verificar IP bloqueada
        if self.is_ip_blocked(request):
            logger.warning(f"Blocked IP attempt: {self.get_client_ip(request)}")
            return HttpResponseForbidden("Access denied")

        # Verificar patrones de ataque en parámetros
        if self.detect_attack_patterns(request):
            self.block_ip_temporarily(request)
            logger.critical(f"Attack pattern detected from IP: {self.get_client_ip(request)}")
            return HttpResponseForbidden("Malicious request detected")

        # Verificar rate limiting
        if self.is_rate_limited(request):
            # Devolver JSON para APIs, HTML para otras rutas
            if '/api/' in request.path:
                return JsonResponse({
                    'success': False,
                    'error': 'Demasiadas solicitudes. Intenta de nuevo en un momento.',
                    'codigo_error': 'RATE_LIMIT_EXCEEDED'
                }, status=429)
            return HttpResponseForbidden("Rate limit exceeded")

        response = self.get_response(request)

        # Evitar error si la vista devuelve None
        if response is None:
            return HttpResponseForbidden("Invalid response from view")

        # Agregar headers de seguridad
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        if settings.DEBUG is False:
            response['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'

        return response

    def get_client_ip(self, request):
        """Obtener IP real del cliente"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    def detect_attack_patterns(self, request):
        """Detectar patrones de ataque en la request"""
        # Verificar parámetros GET
        for _, value in request.GET.items():
            if self.contains_attack_pattern(value):
                return True

        # Verificar parámetros POST
        for _, value in request.POST.items():
            if self.contains_attack_pattern(str(value)):
                return True

        # Verificar headers sospechosos
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        if self.contains_attack_pattern(user_agent):
            return True

        return False

    def contains_attack_pattern(self, text):
        """Verificar si el texto contiene patrones de ataque"""
        text = text.lower()
        for pattern in self.attack_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def is_ip_blocked(self, request):
        """Verificar si la IP está bloqueada"""
        ip = self.get_client_ip(request)
        return cache.get(f"blocked_ip_{ip}", False)

    def block_ip_temporarily(self, request, duration=3600):
        """Bloquear IP temporalmente (1 hora por defecto)"""
        ip = self.get_client_ip(request)
        cache.set(f"blocked_ip_{ip}", True, duration)

    def is_rate_limited(self, request):
        """
        Verificar rate limiting con límites diferenciados:
        - APIs de autenticación: 10 requests por minuto (prevenir brute force)
        - APIs generales: 60 requests por minuto
        - Otras rutas: 100 requests por minuto
        """
        ip = self.get_client_ip(request)
        path = request.path

        # Rate limiting más estricto para rutas de autenticación
        if any(path.startswith(auth_path) for auth_path in self.auth_paths):
            key = f"rate_limit_auth_{ip}"
            limit = 10  # Solo 10 intentos por minuto para auth
            window = 60
        # Rate limiting para APIs
        elif '/api/' in path:
            key = f"rate_limit_api_{ip}"
            limit = 60  # 60 requests por minuto para APIs
            window = 60
        else:
            key = f"rate_limit_{ip}"
            limit = 100  # 100 requests por minuto para otras rutas
            window = 60

        # Obtener contador actual
        requests = cache.get(key, 0)

        if requests >= limit:
            # Logging del rate limit
            logger.warning(
                f"Rate limit exceeded: IP={ip}, path={path}, "
                f"requests={requests}, limit={limit}"
            )
            return True

        # Incrementar contador
        cache.set(key, requests + 1, window)
        return False


class AuditLogMiddleware:
    """Middleware para logging de auditoría"""
    def __init__(self, get_response):
        self.get_response = get_response
        self.audit_logger = logging.getLogger('audit')

    def __call__(self, request):
        start_time = datetime.now()

        response = self.get_response(request)

        # Evitar romper si la vista devuelve None
        if response is None:
            return HttpResponseForbidden("Invalid response from view")

        # Log de acciones importantes
        if self.should_audit(request):
            duration = datetime.now() - start_time
            self.audit_logger.info({
                'user': getattr(request.user, 'email', 'anonymous'),
                'ip': self.get_client_ip(request),
                'method': request.method,
                'path': request.path,
                'status': response.status_code,
                'duration_ms': duration.total_seconds() * 1000,
                'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                'timestamp': start_time.isoformat(),
            })

        return response

    def should_audit(self, request):
        """Determinar si la request debe ser auditada"""
        # Auditar todas las acciones POST, PUT, DELETE
        if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            return True

        # Auditar accesos a rutas sensibles
        sensitive_paths = {
            '/admin/',
            '/api/',
            '/actas/',
            '/accounts/',
        }

        for path in sensitive_paths:
            if request.path.startswith(path):
                return True
        return False

    def get_client_ip(self, request):
        """Obtener IP real del cliente"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
