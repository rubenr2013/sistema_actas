"""
Vistas para la gestión de roles y permisos.
Solo accesible para administradores (user.rol == 'admin').
"""
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import Group, Permission
from django.db.models import Count

from .forms import RolForm, PERMISOS_UI, get_permission_obj

logger = logging.getLogger(__name__)

# Roles del sistema que no se pueden eliminar
ROLES_PROTEGIDOS = {'admin', 'coordinador', 'instructor', 'funcionario', 'director', 'invitado'}


def _solo_admin(request):
    """Retorna True si el request puede continuar; False + mensaje si no tiene permiso."""
    if not request.user.is_authenticated or request.user.rol != 'admin':
        messages.error(request, "Solo los administradores pueden gestionar roles.")
        return False
    return True


def _build_permisos_ui_context():
    """
    Construye la estructura de permisos para el template.
    Retorna lista de dicts: {'modulo': str, 'permisos': [(codename_full, label, perm_obj), ...]}
    """
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

    roles = Group.objects.annotate(
        num_usuarios=Count('user', distinct=True),
        num_permisos=Count('permissions', distinct=True),
    ).order_by('name')

    q = request.GET.get('q', '').strip()
    if q:
        roles = roles.filter(name__icontains=q)

    return render(request, 'accounts/roles_list.html', {
        'roles': roles,
        'q': q,
        'roles_protegidos': ROLES_PROTEGIDOS,
    })


@login_required
def rol_detail(request, rol_id):
    if not _solo_admin(request):
        return redirect('core:dashboard')

    rol = get_object_or_404(Group, pk=rol_id)
    permisos_asignados = rol.permissions.all()
    usuarios = rol.user_set.select_related().all()

    # Construir permisos agrupados con estado marcado/desmarcado
    grupos = _build_permisos_ui_context()
    asignados_ids = set(permisos_asignados.values_list('pk', flat=True))
    for grupo in grupos:
        for p in grupo['permisos']:
            p['asignado'] = p['perm_id'] in asignados_ids

    return render(request, 'accounts/rol_detail.html', {
        'rol': rol,
        'grupos': grupos,
        'usuarios': usuarios,
        'es_protegido': rol.name.lower() in ROLES_PROTEGIDOS,
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
            # Asignar permisos seleccionados
            perm_ids = request.POST.getlist('permisos')
            if perm_ids:
                perms = Permission.objects.filter(pk__in=perm_ids)
                rol.permissions.set(perms)
            logger.info("Admin %s creó el rol '%s' con %d permisos", request.user.email, rol.name, len(perm_ids))
            messages.success(request, f"Rol '{rol.name}' creado correctamente.")
            return redirect('accounts:roles_list')
        else:
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
    grupos_ui = _build_permisos_ui_context()
    permisos_actuales = set(rol.permissions.values_list('pk', flat=True))

    if request.method == 'POST':
        form = RolForm(request.POST, instance=rol)
        if form.is_valid():
            rol = form.save()
            perm_ids = request.POST.getlist('permisos')
            perms = Permission.objects.filter(pk__in=perm_ids) if perm_ids else Permission.objects.none()
            rol.permissions.set(perms)
            num_usuarios = rol.user_set.count()
            logger.info("Admin %s editó el rol '%s': %d permisos", request.user.email, rol.name, len(perm_ids))
            msg = f"Rol '{rol.name}' actualizado."
            if num_usuarios:
                msg += f" Los cambios afectan a {num_usuarios} usuario(s)."
            messages.success(request, msg)
            return redirect('accounts:roles_list')
        else:
            messages.error(request, "Corrige los errores del formulario.")
    else:
        form = RolForm(instance=rol)

    return render(request, 'accounts/rol_form.html', {
        'form': form,
        'rol': rol,
        'grupos_ui': grupos_ui,
        'modo': 'editar',
        'permisos_seleccionados': permisos_actuales,
        'num_usuarios': rol.user_set.count(),
    })


@login_required
def rol_eliminar(request, rol_id):
    if not _solo_admin(request):
        return redirect('core:dashboard')

    rol = get_object_or_404(Group, pk=rol_id)

    if rol.name.lower() in ROLES_PROTEGIDOS:
        messages.error(request, f"El rol '{rol.name}' es un rol del sistema y no puede eliminarse.")
        return redirect('accounts:roles_list')

    num_usuarios = rol.user_set.count()
    if num_usuarios > 0:
        messages.error(
            request,
            f"No se puede eliminar el rol '{rol.name}' porque tiene {num_usuarios} usuario(s) asignado(s). "
            "Primero reasigna esos usuarios a otro rol."
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
