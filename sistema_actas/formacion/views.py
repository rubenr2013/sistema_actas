from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from .models import Programa, Ficha


def _solo_admin(request):
    if request.user.rol != 'admin':
        messages.error(request, 'No tienes permisos para acceder a esta sección.')
        return redirect('core:dashboard')
    return None


# ── PROGRAMAS ───────────────────────────────────────────────────────────────

@login_required
def programas_list(request):
    redir = _solo_admin(request)
    if redir:
        return redir

    search = request.GET.get('search', '').strip()
    estado = request.GET.get('estado', '')

    # Crear programa (POST desde modal)
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        codigo = request.POST.get('codigo', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()

        if not nombre or not codigo:
            messages.error(request, 'El nombre y el código son obligatorios.')
        elif Programa.objects.filter(nombre__iexact=nombre).exists():
            messages.error(request, f'Ya existe un programa con el nombre "{nombre}".')
        elif Programa.objects.filter(codigo__iexact=codigo).exists():
            messages.error(request, f'Ya existe un programa con el código "{codigo}".')
        else:
            Programa.objects.create(nombre=nombre, codigo=codigo, descripcion=descripcion)
            messages.success(request, f'Programa "{nombre}" creado correctamente.')
        return redirect('formacion:programas_list')

    qs = Programa.objects.annotate(total_fichas=Count('fichas')).order_by('nombre')
    if search:
        qs = qs.filter(Q(nombre__icontains=search) | Q(codigo__icontains=search))
    if estado == 'activo':
        qs = qs.filter(activo=True)
    elif estado == 'inactivo':
        qs = qs.filter(activo=False)

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'formacion/programas.html', {
        'page_obj': page_obj,
        'filtros': {'search': search, 'estado': estado},
    })


@login_required
def editar_programa(request, programa_id):
    redir = _solo_admin(request)
    if redir:
        return redir

    programa = get_object_or_404(Programa, id=programa_id)

    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        codigo = request.POST.get('codigo', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        activo = request.POST.get('activo') == 'on'

        if not nombre or not codigo:
            messages.error(request, 'El nombre y el código son obligatorios.')
            return redirect('formacion:programas_list')

        if Programa.objects.filter(nombre__iexact=nombre).exclude(id=programa_id).exists():
            messages.error(request, f'Ya existe otro programa con el nombre "{nombre}".')
            return redirect('formacion:programas_list')

        if Programa.objects.filter(codigo__iexact=codigo).exclude(id=programa_id).exists():
            messages.error(request, f'Ya existe otro programa con el código "{codigo}".')
            return redirect('formacion:programas_list')

        programa.nombre = nombre
        programa.codigo = codigo
        programa.descripcion = descripcion
        programa.activo = activo
        programa.save()
        messages.success(request, f'Programa "{nombre}" actualizado correctamente.')

    return redirect('formacion:programas_list')


@login_required
def eliminar_programa(request, programa_id):
    redir = _solo_admin(request)
    if redir:
        return redir

    if request.method == 'POST':
        programa = get_object_or_404(Programa, id=programa_id)
        if programa.fichas.exists():
            messages.error(
                request,
                f'No se puede eliminar "{programa.nombre}" porque tiene fichas asociadas. '
                'Primero elimina o reasigna las fichas.'
            )
        else:
            nombre = programa.nombre
            programa.delete()
            messages.success(request, f'Programa "{nombre}" eliminado correctamente.')

    return redirect('formacion:programas_list')


# ── FICHAS ───────────────────────────────────────────────────────────────────

@login_required
def fichas_list(request):
    redir = _solo_admin(request)
    if redir:
        return redir

    search = request.GET.get('search', '').strip()
    programa_id = request.GET.get('programa', '')
    estado = request.GET.get('estado', '')

    # Crear ficha (POST desde modal)
    if request.method == 'POST':
        numero = request.POST.get('numero', '').strip()
        prog_id = request.POST.get('programa', '')
        fecha_inicio = request.POST.get('fecha_inicio', '')
        fecha_fin = request.POST.get('fecha_fin', '')

        if not numero or not prog_id or not fecha_inicio or not fecha_fin:
            messages.error(request, 'Todos los campos son obligatorios.')
            return redirect('formacion:fichas_list')

        if not numero.isdigit():
            messages.error(request, 'El número de ficha solo puede contener dígitos.')
            return redirect('formacion:fichas_list')

        if Ficha.objects.filter(numero=numero).exists():
            messages.error(request, f'Ya existe una ficha con el número {numero}.')
            return redirect('formacion:fichas_list')

        programa = get_object_or_404(Programa, id=prog_id)

        ficha = Ficha(
            numero=numero,
            programa=programa,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
        )
        try:
            ficha.full_clean()
            ficha.save()
            messages.success(request, f'Ficha {numero} creada correctamente.')
        except Exception as e:
            messages.error(request, f'Error al crear la ficha: {e}')

        return redirect('formacion:fichas_list')

    qs = Ficha.objects.select_related('programa').order_by('-fecha_inicio')
    if search:
        qs = qs.filter(
            Q(numero__icontains=search) | Q(programa__nombre__icontains=search)
        )
    if programa_id:
        qs = qs.filter(programa_id=programa_id)
    if estado == 'activa':
        qs = qs.filter(activa=True)
    elif estado == 'inactiva':
        qs = qs.filter(activa=False)

    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    programas = Programa.objects.filter(activo=True).order_by('nombre')

    return render(request, 'formacion/fichas.html', {
        'page_obj': page_obj,
        'programas': programas,
        'filtros': {'search': search, 'programa': programa_id, 'estado': estado},
    })


@login_required
def editar_ficha(request, ficha_id):
    redir = _solo_admin(request)
    if redir:
        return redir

    ficha = get_object_or_404(Ficha, id=ficha_id)

    if request.method == 'POST':
        numero = request.POST.get('numero', '').strip()
        prog_id = request.POST.get('programa', '')
        fecha_inicio = request.POST.get('fecha_inicio', '')
        fecha_fin = request.POST.get('fecha_fin', '')
        activa = request.POST.get('activa') == 'on'

        if not numero or not prog_id or not fecha_inicio or not fecha_fin:
            messages.error(request, 'Todos los campos son obligatorios.')
            return redirect('formacion:fichas_list')

        if not numero.isdigit():
            messages.error(request, 'El número de ficha solo puede contener dígitos.')
            return redirect('formacion:fichas_list')

        if Ficha.objects.filter(numero=numero).exclude(id=ficha_id).exists():
            messages.error(request, f'Ya existe otra ficha con el número {numero}.')
            return redirect('formacion:fichas_list')

        programa = get_object_or_404(Programa, id=prog_id)
        ficha.numero = numero
        ficha.programa = programa
        ficha.fecha_inicio = fecha_inicio
        ficha.fecha_fin = fecha_fin
        ficha.activa = activa

        try:
            ficha.full_clean()
            ficha.save()
            messages.success(request, f'Ficha {numero} actualizada correctamente.')
        except Exception as e:
            messages.error(request, f'Error al actualizar la ficha: {e}')

    return redirect('formacion:fichas_list')


@login_required
def eliminar_ficha(request, ficha_id):
    redir = _solo_admin(request)
    if redir:
        return redir

    if request.method == 'POST':
        ficha = get_object_or_404(Ficha, id=ficha_id)
        numero = ficha.numero
        ficha.delete()
        messages.success(request, f'Ficha {numero} eliminada correctamente.')

    return redirect('formacion:fichas_list')
