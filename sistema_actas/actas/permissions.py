"""
Decoradores y funciones de permisos para el sistema de actas.
Controla el acceso a las vistas basándose en el rol del usuario.
"""

from functools import wraps
from django.http import JsonResponse


def requiere_cuenta_verificada(view_func):
    """
    Decorador que verifica que el usuario tenga su cuenta verificada y aprobada.

    Uso:
        @requiere_cuenta_verificada
        def mi_vista_api(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Nota: Este decorador asume que ya se llamó a get_user_from_token()
        # y que el usuario ya está autenticado
        user = kwargs.get('user') or getattr(request, 'user', None)

        if not user or not user.is_authenticated:
            return JsonResponse({
                'success': False,
                'error': 'No autenticado'
            }, status=401)

        if not user.email_verificado:
            return JsonResponse({
                'success': False,
                'error': 'Debes verificar tu email antes de usar esta función'
            }, status=403)

        if not user.cuenta_aprobada:
            return JsonResponse({
                'success': False,
                'error': 'Tu cuenta aún no ha sido aprobada'
            }, status=403)

        return view_func(request, *args, **kwargs)

    return wrapper


def requiere_instructor_o_admin(view_func):
    """
    Decorador que verifica que el usuario sea instructor, funcionario, coordinador, director o admin.

    Uso:
        @requiere_instructor_o_admin
        def crear_acta_api(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = kwargs.get('user') or getattr(request, 'user', None)

        if not user or not user.is_authenticated:
            return JsonResponse({
                'success': False,
                'error': 'No autenticado'
            }, status=401)

        # Roles permitidos para crear/editar actas
        roles_permitidos = ['instructor', 'funcionario', 'coordinador', 'director', 'admin']

        if user.rol not in roles_permitidos:
            return JsonResponse({
                'success': False,
                'error': f'No tienes permisos para realizar esta acción. Se requiere rol: {", ".join(roles_permitidos)}'
            }, status=403)

        return view_func(request, *args, **kwargs)

    return wrapper


def requiere_admin(view_func):
    """
    Decorador que verifica que el usuario sea administrador.

    Uso:
        @requiere_admin
        def eliminar_usuario_api(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = kwargs.get('user') or getattr(request, 'user', None)

        if not user or not user.is_authenticated:
            return JsonResponse({
                'success': False,
                'error': 'No autenticado'
            }, status=401)

        if user.rol != 'admin' and not user.is_superuser:
            return JsonResponse({
                'success': False,
                'error': 'No tienes permisos para realizar esta acción. Se requiere rol de administrador'
            }, status=403)

        return view_func(request, *args, **kwargs)

    return wrapper


def usuario_puede_editar_acta(user, acta):
    """
    Verifica si un usuario puede editar una acta específica.

    Args:
        user: Instancia del modelo User
        acta: Instancia del modelo Acta

    Returns:
        tuple: (puede_editar: bool, mensaje_error: str)

    Reglas:
        - Solo el creador puede editar su propia acta
        - La acta debe estar en estado 'borrador'
        - El usuario debe tener rol de instructor o superior
    """
    # Verificar que el usuario tenga permiso por rol
    roles_permitidos = ['instructor', 'funcionario', 'coordinador', 'director', 'admin']
    if user.rol not in roles_permitidos:
        return False, 'No tienes permisos para editar actas'

    # Verificar que sea el creador
    if acta.creador != user:
        return False, 'Solo puedes editar tus propias actas'

    # Verificar el estado del acta
    if acta.estado != 'borrador':
        return False, 'Solo se pueden editar actas en estado borrador'

    return True, ''


def usuario_puede_eliminar_acta(user, acta):
    """
    Verifica si un usuario puede eliminar una acta específica.

    Args:
        user: Instancia del modelo User
        acta: Instancia del modelo Acta

    Returns:
        tuple: (puede_eliminar: bool, mensaje_error: str)

    Reglas:
        - Solo el creador o un admin pueden eliminar
        - La acta debe estar en estado 'borrador'
    """
    # Admins pueden eliminar cualquier acta
    if user.rol == 'admin' or user.is_superuser:
        return True, ''

    # El creador puede eliminar su propia acta si está en borrador
    if acta.creador == user and acta.estado == 'borrador':
        return True, ''

    return False, 'No tienes permisos para eliminar esta acta'


def usuario_puede_ver_acta(user, acta):
    """
    Verifica si un usuario puede ver una acta específica.

    Args:
        user: Instancia del modelo User
        acta: Instancia del modelo Acta

    Returns:
        tuple: (puede_ver: bool, mensaje_error: str)

    Reglas:
        - El creador siempre puede ver su acta
        - Los participantes pueden ver el acta
        - Instructores y admins pueden ver todas las actas
    """
    # Admins e instructores pueden ver todas
    if user.rol in ['admin', 'instructor', 'funcionario', 'coordinador', 'director']:
        return True, ''

    # El creador puede ver su acta
    if acta.creador == user:
        return True, ''

    # Los participantes pueden ver el acta
    if acta.participantes.filter(id=user.id).exists():
        return True, ''

    return False, 'No tienes permisos para ver esta acta'


def usuario_puede_firmar_acta(user, acta):
    """
    Verifica si un usuario puede firmar una acta específica.

    Args:
        user: Instancia del modelo User
        acta: Instancia del modelo Acta

    Returns:
        tuple: (puede_firmar: bool, mensaje_error: str)

    Reglas:
        - El usuario debe ser participante del acta
        - El acta debe estar en estado 'en_revision' o 'finalizada'
        - El usuario no debe haber firmado previamente
    """
    # Verificar que sea participante
    if not acta.participantes.filter(id=user.id).exists():
        return False, 'Solo los participantes pueden firmar el acta'

    # Verificar el estado del acta
    if acta.estado not in ['en_revision', 'finalizada']:
        return False, 'El acta debe estar en revisión o finalizada para poder firmar'

    # Verificar que no haya firmado antes
    from actas.models import Firma
    if Firma.objects.filter(acta=acta, usuario=user).exists():
        return False, 'Ya has firmado esta acta'

    return True, ''
