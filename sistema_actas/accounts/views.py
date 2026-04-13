import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from .forms import CustomUserCreationForm, CustomAuthenticationForm, ProfileUpdateForm
from .models import User
from django.contrib.auth import update_session_auth_hash
from django.core.paginator import Paginator
from django.db.models import Q

logger = logging.getLogger(__name__)


# ============================================
# RATE LIMITING PARA LOGIN
# ============================================
MAX_LOGIN_ATTEMPTS = 5  # Máximo de intentos permitidos
LOCKOUT_TIME = 900  # Tiempo de bloqueo en segundos (15 minutos)


def get_client_ip(request):
    """Obtiene la IP real del cliente"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def is_login_blocked(ip):
    """Verifica si la IP está bloqueada"""
    blocked_key = f'login_blocked_{ip}'
    return cache.get(blocked_key, False)


def get_login_attempts(ip):
    """Obtiene el número de intentos de login para una IP"""
    attempts_key = f'login_attempts_{ip}'
    return cache.get(attempts_key, 0)


def increment_login_attempts(ip):
    """Incrementa los intentos de login y bloquea si excede el límite"""
    attempts_key = f'login_attempts_{ip}'
    blocked_key = f'login_blocked_{ip}'

    attempts = cache.get(attempts_key, 0) + 1
    cache.set(attempts_key, attempts, LOCKOUT_TIME)

    if attempts >= MAX_LOGIN_ATTEMPTS:
        cache.set(blocked_key, True, LOCKOUT_TIME)
        return True  # Bloqueado
    return False


def reset_login_attempts(ip):
    """Resetea los intentos de login después de un login exitoso"""
    attempts_key = f'login_attempts_{ip}'
    blocked_key = f'login_blocked_{ip}'
    cache.delete(attempts_key)
    cache.delete(blocked_key)


def login_view(request):
    # Si el usuario ya está autenticado, redirigir al dashboard
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    # Rate limiting: verificar si la IP está bloqueada
    client_ip = get_client_ip(request)

    if is_login_blocked(client_ip):
        remaining_time = LOCKOUT_TIME // 60  # Convertir a minutos
        messages.error(
            request,
            f"Demasiados intentos fallidos. Tu acceso está bloqueado por {remaining_time} minutos."
        )
        return render(request, "accounts/login.html", {"form": CustomAuthenticationForm(), "blocked": True})

    if request.method == "POST":
        form = CustomAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()

            # Bloquear login si el email no ha sido verificado
            if not user.email_verificado:
                messages.error(request, "Debes verificar tu correo electrónico antes de iniciar sesión.")
                return redirect("accounts:verificar_email", email=user.email)

            # Bloquear login si la cuenta no está activa
            if getattr(user, 'estado_cuenta', 'activa') != 'activa':
                # Guardar estado en sesión para mostrarlo sin exponer datos en la URL
                request.session['estado_bloqueado'] = user.estado_cuenta
                request.session['motivo_bloqueo'] = user.observaciones_aprobacion
                return redirect("accounts:cuenta_pendiente")

            # Login exitoso: resetear intentos
            reset_login_attempts(client_ip)
            login(request, user)
            messages.success(request, f"Bienvenido {user.get_full_name()}")
            return redirect("core:dashboard")
        else:
            # Login fallido: incrementar intentos
            is_blocked = increment_login_attempts(client_ip)
            attempts_left = MAX_LOGIN_ATTEMPTS - get_login_attempts(client_ip)

            if is_blocked:
                messages.error(
                    request,
                    f"Demasiados intentos fallidos. Tu acceso está bloqueado por {LOCKOUT_TIME // 60} minutos."
                )
            elif attempts_left > 0:
                messages.error(
                    request,
                    f"Correo o contraseña incorrectos. Te quedan {attempts_left} intentos."
                )
            else:
                messages.error(request, "Correo o contraseña incorrectos")
    else:
        form = CustomAuthenticationForm()
    return render(request, "accounts/login.html", {"form": form})


def register_view(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST, request.FILES)
        if form.is_valid():
            from actas.utils import detectar_rol_por_email, crear_codigo_verificacion, enviar_email_verificacion

            user = form.save(commit=False)

            # ✅ Detectar rol automáticamente por dominio de email
            rol_detectado = detectar_rol_por_email(user.email)
            user.rol = rol_detectado

            # ✅ Guardar tipo y número de documento (vienen del formulario)
            user.tipo_documento = form.cleaned_data.get('tipo_documento', '')
            user.numero_documento = form.cleaned_data.get('numero_documento', '')

            # ✅ Asignar ficha si el usuario es aprendiz y seleccionó una
            ficha_id = request.POST.get('ficha_id', '').strip()
            if ficha_id and user.email.endswith('@soy.sena.edu.co'):
                from formacion.models import Ficha
                try:
                    user.ficha = Ficha.objects.get(id=int(ficha_id), activa=True)
                except (Ficha.DoesNotExist, ValueError):
                    pass  # Si la ficha no existe, el usuario queda sin ficha asignada

            # ✅ Asignar firma digital si se subió
            firma = request.FILES.get("firma_digital")
            if firma:
                user.firma_digital = firma

            # ✅ Generar username único basado en primer nombre y primer apellido
            # Formato: "Ruben Reyes" (capitalizado, con espacio, sin acentos)
            import unicodedata

            def limpiar_palabra(texto):
                """Toma la primera palabra, elimina acentos y caracteres especiales, capitaliza."""
                texto = texto.strip()
                primera_palabra = texto.split()[0] if texto.split() else texto
                # Eliminar acentos
                primera_palabra = ''.join(c for c in unicodedata.normalize('NFD', primera_palabra)
                               if unicodedata.category(c) != 'Mn')
                # Eliminar caracteres especiales (solo letras)
                primera_palabra = ''.join(c for c in primera_palabra if c.isalpha())
                return primera_palabra.capitalize()

            primer_nombre = limpiar_palabra(user.first_name)
            primer_apellido = limpiar_palabra(user.last_name)
            base_username = f"{primer_nombre} {primer_apellido}"

            # Asegurar unicidad del username
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username} {counter}"
                counter += 1
            user.username = username

            # ✅ Configurar cuenta sin verificar ni aprobar
            user.email_verificado = False
            user.cuenta_aprobada = False
            user.activo = True

            # ✅ Guardar usuario en la base de datos
            user.save()

            # ✅ Crear código de verificación
            codigo_obj = crear_codigo_verificacion(user, tipo='registro')

            # ✅ Enviar email con el código
            email_enviado = enviar_email_verificacion(user, codigo_obj.codigo)

            if email_enviado:
                messages.success(request, f"Se ha enviado un código de verificación a {user.email}. Revisa tu correo.")
                return redirect("accounts:verificar_email", email=user.email)
            else:
                # Si no se pudo enviar el email, eliminar la cuenta creada
                user.delete()
                messages.error(request, "No se pudo enviar el correo de verificación. Verifica que el correo electrónico sea válido e intenta de nuevo.")
                return redirect("accounts:register")
        else:
            messages.error(request, "Por favor corrige los errores en el formulario.")
    else:
        form = CustomUserCreationForm()

    return render(request, "accounts/register.html", {"form": form})


def verificar_email_view(request, email):
    """Vista para verificar el código de email después del registro"""
    if request.method == "POST":
        from actas.utils import verificar_codigo, aprobar_usuario_automaticamente
        from accounts.models import CodigoVerificacion

        codigo_ingresado = request.POST.get('codigo', '').strip()

        try:
            user = User.objects.get(email=email)

            # Verificar el código
            es_valido, mensaje_error = verificar_codigo(user, codigo_ingresado, tipo='registro')

            if not es_valido:
                messages.error(request, mensaje_error)
                return render(request, "accounts/verificar_email.html", {"email": email})

            # Código válido: verificar email y determinar estado de la cuenta
            user = aprobar_usuario_automaticamente(user)

            # Marcar el código como usado
            codigo_obj = CodigoVerificacion.objects.filter(
                user=user, codigo=codigo_ingresado, tipo='registro', usado=False
            ).first()
            if codigo_obj:
                codigo_obj.marcar_usado()

            # Mostrar el mensaje correcto según el estado resultante
            if user.estado_cuenta == 'pendiente_aprobacion':
                messages.info(
                    request,
                    "¡Tu email fue verificado! Tu cuenta está pendiente de aprobación. "
                    "El administrador revisará tu solicitud y recibirás un correo cuando sea aprobada."
                )
            else:
                messages.success(
                    request,
                    "¡Email verificado exitosamente! Tu cuenta está activa. Ahora puedes iniciar sesión."
                )
            return redirect("accounts:login")

        except User.DoesNotExist:
            messages.error(request, "Usuario no encontrado.")
            return redirect("accounts:register")

    return render(request, "accounts/verificar_email.html", {"email": email})


def reenviar_codigo_view(request, email):
    """Vista para reenviar el código de verificación"""
    try:
        from actas.utils import crear_codigo_verificacion, enviar_email_verificacion

        user = User.objects.get(email=email)

        # Crear nuevo código
        codigo_obj = crear_codigo_verificacion(user, tipo='registro')

        # Enviar email
        email_enviado = enviar_email_verificacion(user, codigo_obj.codigo)

        if email_enviado:
            messages.success(request, f"Se ha enviado un nuevo código de verificación a {email}")
        else:
            messages.error(request, "Hubo un problema al enviar el email. Intenta de nuevo.")

        return redirect("accounts:verificar_email", email=email)

    except User.DoesNotExist:
        messages.error(request, "Usuario no encontrado.")
        return redirect("accounts:register")


@login_required
def logout_view(request):
    logout(request)
    messages.info(request, "Sesión cerrada correctamente")
    return redirect("accounts:login")

@login_required
def profile(request):
    return render(request, "accounts/profile.html")

@login_required
def settings_view(request):
    user = request.user

    # Si el archivo de firma ya no existe en disco, limpiar la referencia en BD
    if user.firma_digital:
        import os
        try:
            firma_path = user.firma_digital.path
            if not os.path.exists(firma_path):
                user.firma_digital = None
                User.objects.filter(pk=user.pk).update(firma_digital=None)
        except (NotImplementedError, ValueError):
            pass  # Almacenamiento remoto (S3), no verificar

    if request.method == 'POST':
        form = ProfileUpdateForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            user = form.save(commit=False)

            new_password = form.cleaned_data.get('password')
            password_changed = False

            # 🔐 Si hay una nueva contraseña, la actualizamos
            if new_password:
                user.set_password(new_password)
                password_changed = True

            user.save()

            if password_changed:
                # 👇 Cierra sesión para obligar al usuario a iniciar con la nueva contraseña
                messages.info(request, "🔐 Tu contraseña se actualizó. Vuelve a iniciar sesión.")
                logout(request)
                return redirect('accounts:login')
            else:
                # 👇 Si solo actualizó otros datos, mantiene la sesión activa
                update_session_auth_hash(request, user)
                messages.success(request, "✅ Perfil actualizado correctamente.")
                return redirect('accounts:profile')
        else:
            messages.error(request, "⚠️ Corrige los errores en el formulario.")
    else:
        form = ProfileUpdateForm(instance=user)

    return render(request, 'accounts/settings.html', {'form': form})


@login_required
def usuarios(request):
    # Obtener parámetros de búsqueda y filtros
    search = request.GET.get('search', '')
    rol = request.GET.get('rol', '')
    estado = request.GET.get('estado', '')
    
    # Filtrar usuarios
    lista_usuarios = User.objects.all().order_by('-fecha_registro')
    
    # Aplicar búsqueda
    if search:
        lista_usuarios = lista_usuarios.filter(
            Q(username__icontains=search) |
            Q(email__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)
        )
    
    # Aplicar filtro por rol
    if rol:
        lista_usuarios = lista_usuarios.filter(rol=rol)
    
    # Aplicar filtro por estado
    if estado == 'verificado':
        lista_usuarios = lista_usuarios.filter(email_verificado=True)
    elif estado == 'no_verificado':
        lista_usuarios = lista_usuarios.filter(email_verificado=False)
    elif estado in ('activa', 'pendiente_aprobacion', 'rechazada', 'suspendida'):
        lista_usuarios = lista_usuarios.filter(estado_cuenta=estado)

    # Paginación
    paginator = Paginator(lista_usuarios, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Opciones para los filtros
    roles = User.ROLES

    estados = [
        ('verificado', 'Email verificado'),
        ('no_verificado', 'Email no verificado'),
        ('activa', 'Cuenta activa'),
        ('pendiente_aprobacion', 'Pendiente de aprobación'),
        ('rechazada', 'Rechazada'),
        ('suspendida', 'Suspendida'),
    ]

    total_pendientes = User.objects.filter(estado_cuenta='pendiente_aprobacion').count()

    context = {
        'page_obj': page_obj,
        'usuarios': page_obj,
        'roles': roles,
        'estados': estados,
        'total_pendientes': total_pendientes,
        'filtros': {
            'search': search,
            'rol': rol,
            'estado': estado,
        }
    }

    return render(request, "accounts/usuarios.html", context)


@login_required
def editar_usuario(request, user_id):
    """Editar usuario - requiere autenticación y permisos de admin/coordinador"""
    # Verificar permisos: solo admin, coordinador o director pueden editar usuarios
    if request.user.rol not in ['admin', 'coordinador', 'director']:
        messages.error(request, 'No tienes permisos para editar usuarios.')
        return redirect('accounts:usuarios')

    usuario = get_object_or_404(User, id=user_id)

    if request.method == 'POST':
        # Obtenemos los valores del formulario
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        telefono = request.POST.get('telefono')
        rol = request.POST.get('rol')
        password = request.POST.get('password')
        firma = request.FILES.get('firma_digital')

        # Validar que el rol sea uno de los valores permitidos
        roles_validos = ['aprendiz', 'instructor', 'invitado', 'funcionario', 'coordinador', 'director', 'admin']
        if rol not in roles_validos:
            messages.error(request, 'Rol inválido.')
            return redirect('accounts:editar_usuario', user_id=user_id)

        # Protección: no permitir auto-remover privilegios de admin
        if request.user == usuario and usuario.rol == 'admin' and rol != 'admin':
            messages.error(request, 'No puedes remover tus propios privilegios de administrador.')
            return redirect('accounts:editar_usuario', user_id=user_id)

        # Protección: no dejar el sistema sin ningún admin
        if usuario.rol == 'admin' and rol != 'admin':
            otros_admins = User.objects.filter(rol='admin').exclude(pk=usuario.pk).count()
            if otros_admins == 0:
                messages.error(request, 'No puedes cambiar el rol de este usuario porque es el único administrador del sistema.')
                return redirect('accounts:editar_usuario', user_id=user_id)

        # Actualizamos los campos
        usuario.first_name = first_name
        usuario.last_name = last_name
        usuario.email = email
        usuario.telefono = telefono
        usuario.rol = rol
        usuario.is_staff = (rol == 'admin')

        # Si se subió una nueva firma digital
        if firma:
            usuario.firma_digital = firma

        # Si se ingresó una nueva contraseña, la ciframos
        if password:
            usuario.set_password(password)
            password_changed = True
        else:
            password_changed = False

        usuario.save()

        # Si cambió la contraseña y el usuario está logueado, actualizar sesión
        if password_changed:
            update_session_auth_hash(request, usuario)

        messages.success(request, 'Usuario actualizado correctamente.')
        return redirect('accounts:usuarios')

    return render(request, 'accounts/editar_usuario.html', {'usuario': usuario})

# Vista para eliminar usuario
@login_required
def eliminar_usuario(request, user_id):
    # Verificar que el usuario tenga permisos (solo admin y director pueden eliminar)
    if request.user.rol not in ['admin', 'director']:
        messages.error(request, 'No tienes permisos para eliminar usuarios.')
        return redirect('accounts:usuarios')

    usuario = get_object_or_404(User, id=user_id)

    # Evitar que el usuario se elimine a sí mismo
    if usuario.id == request.user.id:
        messages.error(request, 'No puedes eliminar tu propia cuenta.')
        return redirect('accounts:usuarios')

    # Evitar eliminar al superusuario principal
    if usuario.is_superuser and User.objects.filter(is_superuser=True).count() == 1:
        messages.error(request, 'No se puede eliminar el único superusuario del sistema.')
        return redirect('accounts:usuarios')

    usuario.delete()
    messages.success(request, f'Usuario {usuario.get_full_name()} eliminado correctamente.')
    return redirect('accounts:usuarios')


# ============================================================================
# SISTEMA DE ESTADOS DE CUENTA
# ============================================================================

def cuenta_pendiente_view(request):
    """
    Página informativa que se muestra cuando la cuenta del usuario no está activa.
    El estado y motivo se leen de la sesión (guardados por login_view o el middleware).
    No requiere login.
    """
    estado = request.session.pop('estado_bloqueado', 'pendiente_aprobacion')
    motivo = request.session.pop('motivo_bloqueo', '')
    return render(request, "accounts/cuenta_pendiente.html", {
        'estado': estado,
        'motivo': motivo,
    })


@login_required
def cuentas_pendientes_view(request):
    """
    Panel de administración: lista todos los usuarios con estado='pendiente_aprobacion'.
    Solo accesible para administradores.
    """
    if request.user.rol != 'admin':
        messages.error(request, "No tienes permisos para acceder a esta sección.")
        return redirect('core:dashboard')

    pendientes = User.objects.filter(
        estado_cuenta='pendiente_aprobacion'
    ).order_by('-fecha_registro')

    return render(request, "accounts/cuentas_pendientes.html", {
        'pendientes': pendientes,
    })


@login_required
def aprobar_cuenta_view(request, user_id):
    """
    Aprueba la cuenta de un usuario pendiente.
    POST: nuevo_rol (requerido), observaciones (opcional).
    Solo para administradores.
    """
    if request.method != 'POST':
        return redirect('accounts:cuentas_pendientes')

    if request.user.rol != 'admin':
        messages.error(request, "No tienes permisos para aprobar cuentas.")
        return redirect('core:dashboard')

    user_a_aprobar = get_object_or_404(User, id=user_id)

    if user_a_aprobar.estado_cuenta != 'pendiente_aprobacion':
        messages.warning(request, "Esta cuenta no está pendiente de aprobación.")
        return redirect('accounts:cuentas_pendientes')

    nuevo_rol = request.POST.get('nuevo_rol', '').strip()
    observaciones = request.POST.get('observaciones', '').strip()

    ROLES_VALIDOS = ['admin', 'director', 'coordinador', 'instructor', 'funcionario', 'aprendiz', 'invitado']
    if nuevo_rol not in ROLES_VALIDOS:
        messages.error(request, f"Rol inválido. Elige uno de: {', '.join(ROLES_VALIDOS)}")
        return redirect('accounts:cuentas_pendientes')

    from actas.utils import aprobar_cuenta_usuario
    aprobar_cuenta_usuario(user_a_aprobar, nuevo_rol, request.user, observaciones)

    messages.success(
        request,
        f"La cuenta de {user_a_aprobar.get_full_name()} fue aprobada con el rol '{nuevo_rol}'."
    )
    return redirect('accounts:cuentas_pendientes')


@login_required
def aprobar_todas_view(request):
    """
    Aprueba masivamente TODAS las cuentas pendientes con el rol especificado.
    POST: nuevo_rol (requerido). Solo admins.
    """
    if request.method != 'POST':
        return redirect('accounts:cuentas_pendientes')

    if request.user.rol != 'admin':
        messages.error(request, "No tienes permisos para esta acción.")
        return redirect('core:dashboard')

    nuevo_rol = request.POST.get('nuevo_rol', '').strip()
    ROLES_VALIDOS = ['admin', 'director', 'coordinador', 'instructor', 'funcionario', 'aprendiz', 'invitado']
    if nuevo_rol not in ROLES_VALIDOS:
        messages.error(request, f"Rol inválido. Elige uno de: {', '.join(ROLES_VALIDOS)}")
        return redirect('accounts:cuentas_pendientes')

    pendientes = User.objects.filter(estado_cuenta='pendiente_aprobacion')
    total = pendientes.count()

    if total == 0:
        messages.warning(request, "No hay cuentas pendientes para aprobar.")
        return redirect('accounts:cuentas_pendientes')

    from actas.utils import aprobar_cuenta_usuario
    aprobados = 0
    for usuario in pendientes:
        try:
            aprobar_cuenta_usuario(usuario, nuevo_rol, request.user)
            aprobados += 1
        except Exception as e:
            logger.warning(f"Error aprobando cuenta {usuario.email}: {e}")

    messages.success(
        request,
        f"Se aprobaron {aprobados} de {total} cuenta(s) pendiente(s) con el rol '{nuevo_rol}'."
    )
    return redirect('accounts:cuentas_pendientes')


@login_required
def rechazar_cuenta_view(request, user_id):
    """
    Rechaza la cuenta de un usuario pendiente.
    POST: motivo (requerido).
    Solo para administradores.
    """
    if request.method != 'POST':
        return redirect('accounts:cuentas_pendientes')

    if request.user.rol != 'admin':
        messages.error(request, "No tienes permisos para rechazar cuentas.")
        return redirect('core:dashboard')

    user_a_rechazar = get_object_or_404(User, id=user_id)

    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, "Debes proporcionar un motivo para el rechazo.")
        return redirect('accounts:cuentas_pendientes')

    from actas.utils import rechazar_cuenta_usuario
    rechazar_cuenta_usuario(user_a_rechazar, motivo, request.user)

    messages.success(
        request,
        f"La solicitud de {user_a_rechazar.get_full_name()} fue rechazada."
    )
    return redirect('accounts:cuentas_pendientes')