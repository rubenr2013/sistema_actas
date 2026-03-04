import json
import logging
from datetime import date

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

# Reutilizamos el helper de autenticación que ya existe en el proyecto
from actas.api_views import get_user_from_token

from .models import Programa, Ficha

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  ENDPOINT PÚBLICO — FICHAS ACTIVAS (para formulario de registro)
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def fichas_activas_api(request):
    """
    GET /formacion/api/fichas/activas/

    Devuelve la lista de fichas activas con su programa.
    Es pública (no requiere autenticación) para que la app móvil
    pueda poblar el selector de fichas en el formulario de registro.
    """
    fichas = Ficha.objects.filter(activa=True).select_related('programa').order_by('programa__nombre', 'numero')

    resultado = [
        {
            'id': ficha.id,
            'numero': ficha.numero,
            'programa_id': ficha.programa.id,
            'programa_nombre': ficha.programa.nombre,
            'programa_codigo': ficha.programa.codigo,
        }
        for ficha in fichas
    ]

    return JsonResponse({'success': True, 'fichas': resultado})


# ─────────────────────────────────────────────────────────────────────────────
#  PROGRAMAS
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def programas_api(request):
    """
    GET  /formacion/api/programas/  → Lista los programas activos (no requiere login)
    POST /formacion/api/programas/  → Crea un programa nuevo (solo admin)
    """
    if request.method == 'GET':
        # Cualquier usuario (o incluso sin login) puede ver los programas activos
        programas = Programa.objects.filter(activo=True).values(
            'id', 'nombre', 'codigo', 'descripcion'
        )
        return JsonResponse({'success': True, 'programas': list(programas)})

    # ── POST: crear programa ──────────────────────────────────────────────────
    # Verificar que el usuario esté autenticado
    user, error = get_user_from_token(request)
    if error:
        return error

    # Solo el admin puede crear programas
    if user.rol != 'admin':
        return JsonResponse(
            {'success': False, 'error': 'Solo administradores pueden crear programas.'},
            status=403
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'El cuerpo de la petición no es JSON válido.'}, status=400)

    nombre = data.get('nombre', '').strip()
    codigo = data.get('codigo', '').strip()
    descripcion = data.get('descripcion', '').strip()

    # Validar campos obligatorios
    if not nombre or not codigo:
        return JsonResponse(
            {'success': False, 'error': 'El nombre y el código son obligatorios.'},
            status=400
        )

    # Verificar que no exista ya un programa con el mismo nombre o código
    if Programa.objects.filter(nombre=nombre).exists():
        return JsonResponse(
            {'success': False, 'error': f'Ya existe un programa con el nombre "{nombre}".'},
            status=400
        )
    if Programa.objects.filter(codigo=codigo).exists():
        return JsonResponse(
            {'success': False, 'error': f'Ya existe un programa con el código "{codigo}".'},
            status=400
        )

    programa = Programa.objects.create(nombre=nombre, codigo=codigo, descripcion=descripcion)
    return JsonResponse(
        {'success': True, 'mensaje': 'Programa creado correctamente.', 'id': programa.id},
        status=201
    )


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
def programa_detalle_api(request, programa_id):
    """
    GET    /formacion/api/programas/<id>/  → Detalle de un programa (público)
    PUT    /formacion/api/programas/<id>/  → Editar programa (solo admin)
    DELETE /formacion/api/programas/<id>/  → Desactivar programa - soft delete (solo admin)
    """
    # Buscar el programa; si no existe, retornar 404
    try:
        programa = Programa.objects.get(id=programa_id)
    except Programa.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Programa no encontrado.'}, status=404)

    # ── GET: detalle público ──────────────────────────────────────────────────
    if request.method == 'GET':
        return JsonResponse({
            'success': True,
            'programa': {
                'id': programa.id,
                'nombre': programa.nombre,
                'codigo': programa.codigo,
                'descripcion': programa.descripcion,
                'activo': programa.activo,
                'total_fichas': programa.fichas.count(),
            }
        })

    # PUT y DELETE requieren ser admin
    user, error = get_user_from_token(request)
    if error:
        return error
    if user.rol != 'admin':
        return JsonResponse(
            {'success': False, 'error': 'Solo administradores pueden modificar programas.'},
            status=403
        )

    # ── PUT: editar programa ──────────────────────────────────────────────────
    if request.method == 'PUT':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'JSON inválido.'}, status=400)

        # Si no se envía un campo, conservar el valor actual
        nombre = data.get('nombre', programa.nombre).strip()
        codigo = data.get('codigo', programa.codigo).strip()
        descripcion = data.get('descripcion', programa.descripcion).strip()
        activo = data.get('activo', programa.activo)

        # Verificar unicidad del nombre y código excluyendo el programa actual
        if Programa.objects.filter(nombre=nombre).exclude(id=programa_id).exists():
            return JsonResponse(
                {'success': False, 'error': f'Ya existe otro programa con el nombre "{nombre}".'},
                status=400
            )
        if Programa.objects.filter(codigo=codigo).exclude(id=programa_id).exists():
            return JsonResponse(
                {'success': False, 'error': f'Ya existe otro programa con el código "{codigo}".'},
                status=400
            )

        programa.nombre = nombre
        programa.codigo = codigo
        programa.descripcion = descripcion
        programa.activo = activo
        programa.save()
        return JsonResponse({'success': True, 'mensaje': 'Programa actualizado correctamente.'})

    # ── DELETE: desactivar programa (soft delete) ─────────────────────────────
    if request.method == 'DELETE':
        # No borramos el registro de la base de datos, solo lo marcamos como inactivo.
        # Esto conserva el historial de fichas que pertenecen al programa.
        programa.activo = False
        programa.save()
        return JsonResponse(
            {'success': True, 'mensaje': f'Programa "{programa.nombre}" desactivado correctamente.'}
        )


# ─────────────────────────────────────────────────────────────────────────────
#  FICHAS
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def fichas_api(request):
    """
    GET  /formacion/api/fichas/           → Lista fichas activas (público)
         /formacion/api/fichas/?programa=3 → Filtra por programa
    POST /formacion/api/fichas/           → Crea una ficha nueva (solo admin)
    """
    if request.method == 'GET':
        fichas = Ficha.objects.filter(activa=True).select_related('programa')

        # Filtro opcional: ?programa=<id>
        programa_id = request.GET.get('programa')
        if programa_id:
            fichas = fichas.filter(programa_id=programa_id)

        # Convertir cada ficha a diccionario para devolverla como JSON
        resultado = []
        for ficha in fichas:
            resultado.append({
                'id': ficha.id,
                'numero': ficha.numero,
                'programa_id': ficha.programa.id,
                'programa_nombre': ficha.programa.nombre,
                'programa_codigo': ficha.programa.codigo,
                'fecha_inicio': ficha.fecha_inicio.strftime('%Y-%m-%d'),
                'fecha_fin': ficha.fecha_fin.strftime('%Y-%m-%d'),
            })

        return JsonResponse({'success': True, 'fichas': resultado})

    # ── POST: crear ficha ─────────────────────────────────────────────────────
    user, error = get_user_from_token(request)
    if error:
        return error
    if user.rol != 'admin':
        return JsonResponse(
            {'success': False, 'error': 'Solo administradores pueden crear fichas.'},
            status=403
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'JSON inválido.'}, status=400)

    numero = data.get('numero', '').strip()
    programa_id = data.get('programa_id')
    fecha_inicio_str = data.get('fecha_inicio', '').strip()
    fecha_fin_str = data.get('fecha_fin', '').strip()

    # Validar que todos los campos lleguen
    if not numero or not programa_id or not fecha_inicio_str or not fecha_fin_str:
        return JsonResponse(
            {'success': False, 'error': 'Los campos número, programa_id, fecha_inicio y fecha_fin son obligatorios.'},
            status=400
        )

    # El número solo debe tener dígitos
    if not numero.isdigit():
        return JsonResponse(
            {'success': False, 'error': 'El número de ficha solo puede contener dígitos.'},
            status=400
        )

    # Verificar que el número de ficha no exista ya
    if Ficha.objects.filter(numero=numero).exists():
        return JsonResponse(
            {'success': False, 'error': f'Ya existe una ficha con el número {numero}.'},
            status=400
        )

    # Verificar que el programa exista
    try:
        programa = Programa.objects.get(id=programa_id)
    except Programa.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': 'El programa especificado no existe.'},
            status=400
        )

    # Parsear las fechas; si el formato es incorrecto lanzará ValueError
    try:
        fecha_inicio_obj = date.fromisoformat(fecha_inicio_str)  # "2024-01-15"
        fecha_fin_obj = date.fromisoformat(fecha_fin_str)
    except ValueError:
        return JsonResponse(
            {'success': False, 'error': 'Formato de fecha inválido. Use YYYY-MM-DD. Ej: 2024-03-15'},
            status=400
        )

    # La fecha de fin debe ser después de la fecha de inicio
    if fecha_inicio_obj >= fecha_fin_obj:
        return JsonResponse(
            {'success': False, 'error': 'La fecha de fin debe ser posterior a la fecha de inicio.'},
            status=400
        )

    ficha = Ficha.objects.create(
        numero=numero,
        programa=programa,
        fecha_inicio=fecha_inicio_obj,
        fecha_fin=fecha_fin_obj,
    )
    return JsonResponse(
        {'success': True, 'mensaje': 'Ficha creada correctamente.', 'id': ficha.id},
        status=201
    )


@csrf_exempt
@require_http_methods(["GET", "PUT", "DELETE"])
def ficha_detalle_api(request, ficha_id):
    """
    GET    /formacion/api/fichas/<id>/  → Detalle de una ficha (público)
    PUT    /formacion/api/fichas/<id>/  → Editar ficha (solo admin)
    DELETE /formacion/api/fichas/<id>/  → Desactivar ficha - soft delete (solo admin)
    """
    try:
        ficha = Ficha.objects.select_related('programa').get(id=ficha_id)
    except Ficha.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Ficha no encontrada.'}, status=404)

    # ── GET: detalle público ──────────────────────────────────────────────────
    if request.method == 'GET':
        return JsonResponse({
            'success': True,
            'ficha': {
                'id': ficha.id,
                'numero': ficha.numero,
                'programa_id': ficha.programa.id,
                'programa_nombre': ficha.programa.nombre,
                'programa_codigo': ficha.programa.codigo,
                'fecha_inicio': ficha.fecha_inicio.strftime('%Y-%m-%d'),
                'fecha_fin': ficha.fecha_fin.strftime('%Y-%m-%d'),
                'activa': ficha.activa,
            }
        })

    # PUT y DELETE requieren ser admin
    user, error = get_user_from_token(request)
    if error:
        return error
    if user.rol != 'admin':
        return JsonResponse(
            {'success': False, 'error': 'Solo administradores pueden modificar fichas.'},
            status=403
        )

    # ── PUT: editar ficha ─────────────────────────────────────────────────────
    if request.method == 'PUT':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'JSON inválido.'}, status=400)

        # Si no se envía un campo, conservar el valor actual
        numero = data.get('numero', ficha.numero).strip()
        programa_id = data.get('programa_id', ficha.programa.id)
        fecha_inicio_str = data.get('fecha_inicio', ficha.fecha_inicio.strftime('%Y-%m-%d'))
        fecha_fin_str = data.get('fecha_fin', ficha.fecha_fin.strftime('%Y-%m-%d'))
        activa = data.get('activa', ficha.activa)

        if not numero.isdigit():
            return JsonResponse(
                {'success': False, 'error': 'El número de ficha solo puede contener dígitos.'},
                status=400
            )

        # Verificar unicidad del número excluyendo la ficha actual
        if Ficha.objects.filter(numero=numero).exclude(id=ficha_id).exists():
            return JsonResponse(
                {'success': False, 'error': f'Ya existe otra ficha con el número {numero}.'},
                status=400
            )

        try:
            programa = Programa.objects.get(id=programa_id)
        except Programa.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'El programa especificado no existe.'}, status=400)

        try:
            fecha_inicio_obj = date.fromisoformat(fecha_inicio_str)
            fecha_fin_obj = date.fromisoformat(fecha_fin_str)
        except ValueError:
            return JsonResponse(
                {'success': False, 'error': 'Formato de fecha inválido. Use YYYY-MM-DD.'},
                status=400
            )

        if fecha_inicio_obj >= fecha_fin_obj:
            return JsonResponse(
                {'success': False, 'error': 'La fecha de fin debe ser posterior a la fecha de inicio.'},
                status=400
            )

        ficha.numero = numero
        ficha.programa = programa
        ficha.fecha_inicio = fecha_inicio_obj
        ficha.fecha_fin = fecha_fin_obj
        ficha.activa = activa
        ficha.save()
        return JsonResponse({'success': True, 'mensaje': 'Ficha actualizada correctamente.'})

    # ── DELETE: desactivar ficha (soft delete) ────────────────────────────────
    if request.method == 'DELETE':
        ficha.activa = False
        ficha.save()
        return JsonResponse(
            {'success': True, 'mensaje': f'Ficha {ficha.numero} desactivada correctamente.'}
        )


@csrf_exempt
@require_http_methods(["GET"])
def buscar_ficha_api(request):
    """
    GET /formacion/api/fichas/buscar/?numero=2898734

    Busca una ficha por su número exacto.
    Útil para validar en tiempo real si un número de ficha existe.
    """
    numero = request.GET.get('numero', '').strip()

    if not numero:
        return JsonResponse(
            {'success': False, 'error': 'Debes enviar el parámetro "numero". Ej: ?numero=2898734'},
            status=400
        )

    try:
        ficha = Ficha.objects.select_related('programa').get(numero=numero)
        return JsonResponse({
            'success': True,
            'ficha': {
                'id': ficha.id,
                'numero': ficha.numero,
                'programa_id': ficha.programa.id,
                'programa_nombre': ficha.programa.nombre,
                'programa_codigo': ficha.programa.codigo,
                'fecha_inicio': ficha.fecha_inicio.strftime('%Y-%m-%d'),
                'fecha_fin': ficha.fecha_fin.strftime('%Y-%m-%d'),
                'activa': ficha.activa,
            }
        })
    except Ficha.DoesNotExist:
        return JsonResponse(
            {'success': False, 'error': f'No existe ninguna ficha con el número {numero}.'},
            status=404
        )
