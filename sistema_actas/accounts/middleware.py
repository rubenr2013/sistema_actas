"""
Middleware que verifica el estado de la cuenta de cada usuario autenticado.

Si el estado no es 'activa', cierra la sesión automáticamente y redirige
a la página informativa /accounts/cuenta-pendiente/.

Excepciones (URLs que NO bloquea):
  - /accounts/login/, /logout/, /register/, /verificar-email/, etc.
  - /accounts/cuenta-pendiente/  (la propia página informativa)
  - /static/ y /media/  (archivos estáticos)
  - /admin/              (panel de Django, para superusuarios)
"""

from django.shortcuts import redirect
from django.contrib.auth import logout

# Prefijos de URL que quedan libres de verificación
URLS_EXCLUIDAS = [
    '/accounts/login/',
    '/accounts/logout/',
    '/accounts/register/',
    '/accounts/verificar-email/',
    '/accounts/reenviar-codigo/',
    '/accounts/cuenta-pendiente/',
    '/accounts/password_reset/',
    '/accounts/reset/',
    '/static/',
    '/media/',
    '/admin/',
]


class EstadoCuentaMiddleware:
    """
    Bloquea el acceso al sistema a usuarios cuyo estado_cuenta no sea 'activa'.

    Flujo:
      1. Si el usuario no está autenticado → dejar pasar (el login se encarga).
      2. Si es superusuario → dejar pasar siempre (acceso al admin de Django).
      3. Si la URL es una excepción → dejar pasar.
      4. Si estado_cuenta != 'activa' → guardar estado en sesión, cerrar sesión
         y redirigir a /accounts/cuenta-pendiente/.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.user.is_superuser:
            path = request.path
            url_excluida = any(path.startswith(u) for u in URLS_EXCLUIDAS)

            if not url_excluida:
                estado = getattr(request.user, 'estado_cuenta', 'activa')

                if estado != 'activa':
                    # Guardar estado en sesión ANTES de cerrar sesión
                    # para que cuenta_pendiente_view pueda mostrarlo.
                    request.session['estado_bloqueado'] = estado
                    request.session['motivo_bloqueo'] = getattr(
                        request.user, 'observaciones_aprobacion', ''
                    )
                    logout(request)
                    return redirect('accounts:cuenta_pendiente')

        return self.get_response(request)
