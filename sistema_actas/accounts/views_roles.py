"""
Vistas para la gestión de roles y permisos.

ARQUITECTURA:
- user.rol  = CharField que controla el acceso a vistas (lógica de negocio)
- Group     = Objeto Django para agrupar permisos de Django (has_perm)
Cada rol del sistema tiene un Group asociado por nombre.
El conteo de usuarios usa user.rol, no la relación M2M con Group.
"""
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import Group, Permission
from django.db.models import Count

from .forms import RolForm, PERMISOS_UI, get_permission_obj
from .models import User

logger = logging.getLogger(__name__)

# Mapeo: clave de user.rol → nombre del Group de Django
ROL_A_GROUP = {
    'aprendiz':    'Aprendiz',
    'instructor':  'Instructor',
    'invitado':    'Invitado',
    'funcionario': 'Funcionario',
    'coordinador': 'Coordinador',
    'director':    'Director',
    'admin':       'Administrador',
}
GROUP_A_ROL = {v: k for k, v in ROL_A_GROUP.items()}

# Roles del sistema que no se pueden eliminar (usan la clave de user.rol)
ROLES_PROTEGIDOS = set(ROL_A_GROUP.keys())


def _solo_admin(request):
    if not request.user.is_authenticated or request.user.rol != 'admin':
        messages.error(request, "Solo los administradores pueden gestionar roles.")
        return False
    return True


def _get_or_create_group(rol_key):
    """Obtiene o crea el Group correspondiente al rol dado."""
    nombre = ROL_A_GROUP.get(rol_key, rol_key.capitalize())
    group, _ = Group.objects.get_or_create(name=nombre)
    return group


def _build_permisos_ui_context():
    grupos = []
    for modulo, items in PERMISOS_UI.items():
        permisos_modulo = []
        for codigo_full, label in items:
            app_label, codename = codigo_full.split('.', 1)
            perm = get_permission_obj(app_label, codename)
            if perm:
                permisos_modulo.append({
                    'codigo_full': codigo_full,
                    'perm_id': perm.pk,
                    'label': label,
                })
        if permisos_modulo:
            grupos.append({'modulo': modulo, 'permisos': permisos_modulo})
    return grupos


@login_required
def roles_list(request):
    if not _solo_admin(request):
        return redirect('core:dashboard')

    q = request.GET.get('q', '').strip()

    # Contar usuarios por rol usando user.rol (fuente de verdad real)
    conteo_usuarios = {
        item['rol']: item['count']
        for item in User.objects.values('rol').annotate(count=Count('id'))
    }

    # Asegurar que existan los grupos del sistema
    for rol_key in ROL_A_GROUP:
        _get_or_create_group(rol_key)

    # Construir lista unificada de roles del sistema
    roles_sistema = []
    for rol_key, rol_label in User.ROLES:
        if q and q.lower() not in rol_label.lower() and q.lower() not in rol_key.lower():
            continue
        group = Group.objects.filter(name=ROL_A_GROUP[rol_key]).first()
        num_permisos = group.permissions.count() if group else 0
        roles_sistema.append({
            'pk': group.pk if group else None,
            'name': rol_label,
            'rol_key': rol_key,
            'num_usuarios': conteo_usuarios.get(rol_key, 0),
            'num_permisos': num_permisos,
            'es_sistema': True,
            'group': group,
        })

    # Grupos personalizados (no corresponden a ningún rol del sistema)
    nombres_sistema = set(ROL_A_GROUP.values())
    grupos_custom = []
    for group in Group.objects.exclude(name__in=nombres_sistema).annotate(
        num_permisos=Count('permissions', distinct=True)
    ).order_by('name'):
        if q and q.lower() not in group.name.lower():
            continue
        grupos_custom.append({
            'pk': group.pk,
            'name': group.name,
            'rol_key': None,
            'num_usuarios': group.user_set.count(),
            'num_permisos': group.num_permisos,
            'es_sistema': False,
            'group': group,
        })

    return render(request, 'accounts/roles_list.html', {
        'roles_sistema': roles_sistema,
        'grupos_custom': grupos_custom,
        'q': q,
    })


@login_required
def rol_detail(request, rol_id):
    if not _solo_admin(request):
        return redirect('core:dashboard')

    rol = get_object_or_404(Group, pk=rol_id)
    rol_key = GROUP_A_ROL.get(rol.name)

    # Contar usuarios: si es sistema usar user.rol, si es custom usar M2M
    if rol_key:
        usuarios = User.objects.filter(rol=rol_key)
    else:
        usuarios = rol.user_set.select_related().all()

    permisos_asignados = rol.permissions.all()
    grupos = _build_permisos_ui_context()
    asignados_ids = set(permisos_asignados.values_list('pk', flat=True))
    for grupo in grupos:
        for p in grupo['permisos']:
            p['asignado'] = p['perm_id'] in asignados_ids

    return render(request, 'accounts/rol_detail.html', {
        'rol': rol,
        'rol_label': dict(User.ROLES).get(rol_key, rol.name) if rol_key else rol.name,
        'grupos': grupos,
        'usuarios': usuarios,
        'es_protegido': rol_key in ROLES_PROTEGIDOS if rol_key else False,
    })


@login_required
def rol_crear(request):
    if not _solo_admin(request):
        return redirect('core:dashboard')

    grupos_ui = _build_permisos_ui_context()

    if request.method == 'POST':
        form = RolForm(request.POST)
        if form.is_valid():
            rol = form.save()
            perm_ids = request.POST.getlist('permisos')
            if perm_ids:
                rol.permissions.set(Permission.objects.filter(pk__in=perm_ids))
            logger.info("Admin %s creó el rol '%s'", request.user.email, rol.name)
            messages.success(request, f"Rol '{rol.name}' creado correctamente.")
            return redirect('accounts:roles_list')
        messages.error(request, "Corrige los errores del formulario.")
    else:
        form = RolForm()

    return render(request, 'accounts/rol_form.html', {
        'form': form,
        'grupos_ui': grupos_ui,
        'modo': 'crear',
        'permisos_seleccionados': set(),
    })


@login_required
def rol_editar(request, rol_id):
    if not _solo_admin(request):
        return redirect('core:dashboard')

    rol = get_object_or_404(Group, pk=rol_id)
    rol_key = GROUP_A_ROL.get(rol.name)
    grupos_ui = _build_permisos_ui_context()
    permisos_actuales = set(rol.permissions.values_list('pk', flat=True))

    # Contar usuarios reales para la advertencia
    if rol_key:
        num_usuarios = User.objects.filter(rol=rol_key).count()
    else:
        num_usuarios = rol.user_set.count()

    if request.method == 'POST':
        form = RolForm(request.POST, instance=rol)
        if form.is_valid():
            rol = form.save()
            perm_ids = request.POST.getlist('permisos')
            perms = Permission.objects.filter(pk__in=perm_ids) if perm_ids else Permission.objects.none()
            rol.permissions.set(perms)
            logger.info("Admin %s editó el rol '%s': %d permisos", request.user.email, rol.name, len(perm_ids))
            msg = f"Rol '{rol.name}' actualizado."
            if num_usuarios:
                msg += f" Los cambios afectan a {num_usuarios} usuario(s)."
            messages.success(request, msg)
            return redirect('accounts:roles_list')
        messages.error(request, "Corrige los errores del formulario.")
    else:
        form = RolForm(instance=rol)

    return render(request, 'accounts/rol_form.html', {
        'form': form,
        'rol': rol,
        'grupos_ui': grupos_ui,
        'modo': 'editar',
        'permisos_seleccionados': permisos_actuales,
        'num_usuarios': num_usuarios,
    })


@login_required
def rol_eliminar(request, rol_id):
    if not _solo_admin(request):
        return redirect('core:dashboard')

    rol = get_object_or_404(Group, pk=rol_id)
    rol_key = GROUP_A_ROL.get(rol.name)

    if rol_key in ROLES_PROTEGIDOS:
        messages.error(request, f"El rol '{rol.name}' es un rol del sistema y no puede eliminarse.")
        return redirect('accounts:roles_list')

    num_usuarios = rol.user_set.count()
    if num_usuarios > 0:
        messages.error(
            request,
            f"No se puede eliminar '{rol.name}' porque tiene {num_usuarios} usuario(s) asignado(s)."
        )
        return redirect('accounts:roles_list')

    if request.method == 'POST':
        nombre = rol.name
        rol.delete()
        logger.info("Admin %s eliminó el rol '%s'", request.user.email, nombre)
        messages.success(request, f"Rol '{nombre}' eliminado.")
        return redirect('accounts:roles_list')

    return render(request, 'accounts/rol_confirm_delete.html', {
        'rol': rol,
        'num_usuarios': num_usuarios,
    })
