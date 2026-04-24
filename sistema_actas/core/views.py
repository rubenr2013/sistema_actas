import os
import shutil
from django.shortcuts import render, redirect, get_list_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Case, When, IntegerField
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse
from django.core.paginator import Paginator

from actas.models import Acta, Compromiso, Firma
from notifications.models import Notification
from core.utils import generar_acta_con_ia
from django.conf import settings
from django.core.management import call_command
from django.http import FileResponse, HttpResponse
from datetime import timedelta 
from datetime import datetime
from core import views
import zipfile

BACKUP_DIR = os.path.join(settings.BASE_DIR, "backups")

@login_required
def dashboard(request):
    user = request.user
    # Toggle vista personal para admin: ?vista=personal
    vista_personal = request.GET.get('vista') == 'personal'

    if user.rol == 'admin' and not vista_personal:
        # ===== DASHBOARD DE SUPERVISIÓN (ADMIN) =====
        from accounts.models import User as UserModel

        stats = {
            'total_actas': Acta.objects.count(),
            'actas_en_revision': Acta.objects.filter(estado='en_revision').count(),
            'firmas_pendientes_global': Firma.objects.filter(
                firmado=False, acta__estado='en_revision'
            ).count(),
            'compromisos_vencidos_global': Compromiso.objects.filter(
                fecha_limite__lt=timezone.now().date()
            ).exclude(estado='completado').count(),
            'total_usuarios': UserModel.objects.count(),
            'usuarios_no_verificados': UserModel.objects.filter(email_verificado=False).count(),
        }

        actas_recientes = Acta.objects.select_related('creador').order_by('-fecha_creacion')[:10]

        compromisos_vencidos_lista = Compromiso.objects.filter(
            estado='vencido'
        ).select_related('responsable', 'acta').order_by('-fecha_limite')[:10]

        firmas_pendientes_lista = Firma.objects.filter(
            firmado=False, acta__estado='en_revision'
        ).select_related('acta', 'usuario').order_by('acta__fecha_limite_firmas')[:10]

        notificaciones = Notification.objects.filter(
            usuario=user, leida=False
        ).order_by('-fecha_creacion')[:5]

        context = {
            'stats': stats,
            'actas_recientes': actas_recientes,
            'compromisos_vencidos_lista': compromisos_vencidos_lista,
            'firmas_pendientes_lista': firmas_pendientes_lista,
            'notificaciones': notificaciones,
            'es_vista_admin': True,
        }
    else:
        # ===== DASHBOARD PERSONAL (todos los roles + admin en modo personal) =====
        can_ver_actas     = user.has_perm('actas.view_acta')
        can_firmar        = user.has_perm('actas.firmar_acta')
        can_ver_compromisos = user.has_perm('actas.view_compromiso')

        actas_qs = Acta.objects.filter(
            Q(creador=user) |
            (Q(participantes__usuario=user) & ~Q(estado='borrador'))
        ).distinct()

        stats = {
            'total_actas': actas_qs.count() if can_ver_actas else 0,
            'actas_pendientes_firma': (
                Firma.objects.filter(usuario=user, firmado=False, acta__estado='en_revision').count()
                if can_firmar else 0
            ),
            'compromisos_pendientes': (
                Compromiso.objects.filter(responsable=user, estado__in=['pendiente', 'en_progreso']).count()
                if can_ver_compromisos else 0
            ),
            'compromisos_vencidos': (
                Compromiso.objects.filter(responsable=user, estado='vencido').count()
                if can_ver_compromisos else 0
            ),
        }

        actas_recientes = (
            actas_qs.order_by('-fecha_creacion')[:5] if can_ver_actas else []
        )

        compromisos_proximos = (
            Compromiso.objects.filter(
                responsable=user,
                estado__in=['pendiente', 'en_progreso'],
                fecha_limite__lte=timezone.now().date() + timedelta(days=7)
            ).order_by('fecha_limite')[:5]
            if can_ver_compromisos else []
        )

        firmas_pendientes = (
            Firma.objects.filter(
                usuario=user, firmado=False, acta__estado='en_revision'
            ).select_related('acta')[:5]
            if can_firmar else []
        )

        notificaciones = Notification.objects.filter(
            usuario=user, leida=False
        ).order_by('-fecha_creacion')[:5]

        context = {
            'stats': stats,
            'actas_recientes': actas_recientes,
            'compromisos_proximos': compromisos_proximos,
            'firmas_pendientes': firmas_pendientes,
            'notificaciones': notificaciones,
            'es_vista_admin': False,
        }

    return render(request, 'dashboard/index.html', context)

@login_required
def crear_copia_seguridad(request):
    """
    Crea backup del sistema completo usando dumpdata de Django.
    Compatible con PostgreSQL y SQLite. Solo administradores.
    """
    if request.user.rol != 'admin':
        messages.error(request, "Solo los administradores pueden crear copias de seguridad del sistema.")
        return redirect("core:vista_backup")

    try:
        from io import StringIO
        os.makedirs(BACKUP_DIR, exist_ok=True)

        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_sistema_{fecha}.zip"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        # Exportar toda la BD con dumpdata (funciona con PostgreSQL y SQLite)
        output = StringIO()
        call_command(
            'dumpdata',
            '--natural-foreign',
            '--exclude=contenttypes',
            '--exclude=auth.permission',
            '--exclude=sessions',
            '--indent=2',
            stdout=output,
        )
        json_data = output.getvalue()

        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr("sistema_backup.json", json_data)

        response = FileResponse(open(backup_path, 'rb'), as_attachment=True, filename=backup_filename)
        response['Content-Type'] = 'application/zip'
        response['Content-Length'] = os.path.getsize(backup_path)
        return response

    except Exception as e:
        messages.error(request, f"Error al crear la copia de seguridad: {str(e)}")
        return redirect("core:vista_backup")


@login_required
def crear_backup_personal(request):
    """
    Crea backup personal con datos completos de cada acta creada por el usuario.
    Incluye participantes, firmas y compromisos de cada acta para restauración completa.
    Disponible para todos los roles.
    """
    try:
        import json
        from actas.models import Acta, Compromiso, Firma, Participante

        os.makedirs(BACKUP_DIR, exist_ok=True)

        user = request.user
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Reemplazar espacios en username para el nombre de archivo
        username_safe = user.username.replace(' ', '_')
        backup_filename = f"backup_personal_{username_safe}_{fecha}.zip"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        # Construir datos completos de cada acta creada por el usuario
        actas_data = []
        for acta in Acta.objects.filter(creador=user).prefetch_related(
            'participantes__usuario', 'firmas__usuario', 'compromisos__responsable'
        ):
            acta_dict = {
                'numero_acta': acta.numero_acta,
                'titulo': acta.titulo,
                'tipo_reunion': acta.tipo_reunion,
                'fecha_reunion': str(acta.fecha_reunion),
                'lugar_reunion': acta.lugar_reunion,
                'modalidad': acta.modalidad,
                'estado': acta.estado,
                'fecha_creacion': str(acta.fecha_creacion),
                'orden_dia': acta.orden_dia,
                'desarrollo': acta.desarrollo,
                'resumen_ia': acta.resumen_ia,
                'observaciones': acta.observaciones,
                'fecha_limite_firmas': str(acta.fecha_limite_firmas) if acta.fecha_limite_firmas else None,
                'silencio_administrativo': acta.silencio_administrativo,
                'generada_con_ia': acta.generada_con_ia,
                'participantes': [
                    {
                        'usuario_email': p.usuario.email,
                        'usuario_nombre': p.usuario.get_full_name(),
                        'rol_en_reunion': p.rol_en_reunion,
                        'obligatorio_firma': p.obligatorio_firma,
                    }
                    for p in acta.participantes.all()
                ],
                'firmas': [
                    {
                        'usuario_email': f.usuario.email,
                        'firmado': f.firmado,
                        'fecha_firma': str(f.fecha_firma) if f.fecha_firma else None,
                        'firmado_por_silencio': f.firmado_por_silencio,
                        'comentarios': f.comentarios,
                    }
                    for f in acta.firmas.all()
                ],
                'compromisos': [
                    {
                        'descripcion': c.descripcion,
                        'responsable_email': c.responsable.email,
                        'responsable_nombre': c.responsable.get_full_name(),
                        'fecha_limite': str(c.fecha_limite),
                        'estado': c.estado,
                        'porcentaje_avance': c.porcentaje_avance,
                        'observaciones': c.observaciones,
                    }
                    for c in acta.compromisos.all()
                ],
            }
            actas_data.append(acta_dict)

        datos_usuario = {
            'version': '2.0',
            'usuario': {
                'email': user.email,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'rol': user.rol,
            },
            'total_actas': len(actas_data),
            'fecha_backup': datetime.now().isoformat(),
            'actas_creadas': actas_data,
        }

        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            datos_json = json.dumps(datos_usuario, indent=2, default=str, ensure_ascii=False)
            zipf.writestr(f"datos_usuario_{username_safe}.json", datos_json)

            # Incluir firma digital si existe
            if user.firma_digital:
                try:
                    firma_path = user.firma_digital.path
                    if os.path.exists(firma_path):
                        ext = os.path.splitext(firma_path)[1]
                        zipf.write(firma_path, arcname=f"firma_digital{ext}")
                except Exception:
                    pass

        response = FileResponse(open(backup_path, 'rb'), as_attachment=True, filename=backup_filename)
        response['Content-Type'] = 'application/zip'
        response['Content-Length'] = os.path.getsize(backup_path)
        return response

    except Exception as e:
        messages.error(request, f"Error al crear tu copia de seguridad: {str(e)}")
        return redirect("accounts:profile")


@login_required
def vista_backup(request):
    """
    Muestra una lista de las copias de seguridad disponibles.
    ADMINISTRADORES: Ven backups del sistema Y sus propios backups personales
    USUARIOS REGULARES: Solo ven sus propios backups personales
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)

    archivos = []
    for archivo in os.listdir(BACKUP_DIR):
        ruta = os.path.join(BACKUP_DIR, archivo)
        if os.path.isfile(ruta) and archivo.endswith(".zip"):
            # Filtrar según el rol del usuario
            # Sanitizar username para comparar con nombre de archivo (espacios → guiones bajos)
            username_safe = request.user.username.replace(' ', '_')
            if request.user.rol == 'admin':
                es_backup_sistema = archivo.startswith("backup_sistema_")
                es_backup_propio = archivo.startswith(f"backup_personal_{username_safe}_")
                mostrar = es_backup_sistema or es_backup_propio
            else:
                mostrar = archivo.startswith(f"backup_personal_{username_safe}_")

            if mostrar:
                tamaño_mb = os.path.getsize(ruta) / (1024 * 1024)
                fecha_mod = datetime.fromtimestamp(os.path.getmtime(ruta)).strftime("%d/%m/%Y %H:%M:%S")
                archivos.append({
                    "nombre": archivo,
                    "tamaño": f"{tamaño_mb:.2f} MB",
                    "fecha": fecha_mod,
                    "tipo": "sistema" if archivo.startswith("backup_sistema_") else "personal",
                })

    archivos.sort(key=lambda x: x["fecha"], reverse=True)
    return render(request, "actas/backup.html", {"archivos": archivos})


@login_required
def restaurar_backup(request, nombre_archivo):
    """
    Restaura backup del sistema completo usando loaddata de Django.
    Vacia la BD y recarga todos los datos del backup.
    Solo administradores.
    """
    if request.user.rol != 'admin':
        messages.error(request, "Solo los administradores pueden restaurar copias de seguridad.")
        return redirect("core:vista_backup")

    # Sanitizar nombre de archivo para prevenir path traversal
    nombre_archivo = os.path.basename(nombre_archivo)
    ruta_backup = os.path.join(BACKUP_DIR, nombre_archivo)

    if not os.path.exists(ruta_backup):
        messages.error(request, "El archivo seleccionado no existe.")
        return redirect("core:vista_backup")

    temp_json = None
    try:
        with zipfile.ZipFile(ruta_backup, "r") as zip_ref:
            if "sistema_backup.json" not in zip_ref.namelist():
                messages.error(
                    request,
                    "Este archivo no es un backup del sistema valido. "
                    "Solo los backups creados con la nueva version pueden restaurarse."
                )
                return redirect("core:vista_backup")

            json_data = zip_ref.read("sistema_backup.json").decode("utf-8")

        # Escribir JSON en archivo temporal para loaddata
        temp_json = os.path.join(BACKUP_DIR, f"_temp_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(temp_json, "w", encoding="utf-8") as f:
            f.write(json_data)

        # Vaciar la BD y recargar desde el backup
        call_command("flush", "--no-input", verbosity=0)
        call_command("loaddata", temp_json, verbosity=0)

        os.remove(temp_json)

        # Limpiar la sesion actual: el admin debe iniciar sesion nuevamente
        request.session.flush()

        # Retornar HTML directamente (no podemos usar messages porque la sesion fue limpiada)
        return HttpResponse("""
            <!DOCTYPE html>
            <html lang="es">
            <head>
                <meta charset="UTF-8">
                <title>Backup Restaurado</title>
                <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            </head>
            <body class="d-flex justify-content-center align-items-center bg-light" style="min-height:100vh">
                <div class="card shadow-lg p-5 text-center" style="max-width:480px;border-radius:1rem">
                    <div class="mb-3" style="font-size:3.5rem;color:#198754">&#10003;</div>
                    <h4 class="mb-2">Sistema restaurado correctamente</h4>
                    <p class="text-muted mb-1">
                        El sistema fue restaurado al estado del backup:
                    </p>
                    <p class="fw-bold text-dark mb-3">""" + nombre_archivo + """</p>
                    <div class="alert alert-warning py-2">
                        Debes iniciar sesion nuevamente con las credenciales del backup.
                    </div>
                    <a href="/accounts/login/" class="btn btn-success mt-2 px-4">Ir al Login</a>
                </div>
            </body>
            </html>
        """)

    except zipfile.BadZipFile:
        messages.error(request, "El archivo no es un ZIP valido.")
    except Exception as e:
        messages.error(request, f"Error al restaurar el sistema: {str(e)}")
    finally:
        if temp_json and os.path.exists(temp_json):
            try:
                os.remove(temp_json)
            except Exception:
                pass

    return redirect("core:vista_backup")

@login_required
def restaurar_backup_personal(request, nombre_archivo):
    """
    Restaura backup personal desde el archivo almacenado en el servidor.
    Recrea unicamente las actas que ya no existen en la BD.
    Disponible para todos los roles.
    """
    import json
    from actas.models import Acta, Compromiso, Firma, Participante
    from accounts.models import User as UserModel
    from django.utils.dateparse import parse_datetime, parse_date
    from django.db import transaction

    user = request.user

    # Sanitizar nombre de archivo para prevenir path traversal
    nombre_archivo = os.path.basename(nombre_archivo)

    # Verificar que el backup pertenece al usuario actual
    username_safe = user.username.replace(' ', '_')
    if not nombre_archivo.startswith(f"backup_personal_{username_safe}_"):
        messages.error(request, "No tienes permiso para restaurar este backup.")
        return redirect("core:vista_backup")

    ruta_backup = os.path.join(BACKUP_DIR, nombre_archivo)
    if not os.path.exists(ruta_backup):
        messages.error(request, "El archivo de backup no existe.")
        return redirect("core:vista_backup")

    try:
        with zipfile.ZipFile(ruta_backup, "r") as zipf:
            json_files = [f for f in zipf.namelist() if f.endswith(".json")]
            if not json_files:
                messages.error(request, "El backup no contiene datos validos.")
                return redirect("core:vista_backup")

            with zipf.open(json_files[0]) as f:
                datos = json.load(f)

        # Verificar que el backup pertenece a este usuario (por email)
        backup_email = datos.get("usuario", {}).get("email", "")
        if backup_email != user.email:
            messages.error(request, "Este backup no pertenece a tu cuenta.")
            return redirect("core:vista_backup")

        # Verificar version del backup
        version = datos.get("version", "1.0")
        if version == "1.0":
            messages.warning(
                request,
                "Este backup fue creado con una version antigua y no incluye datos completos. "
                "Crea un nuevo backup para obtener restauracion completa."
            )
            return redirect("core:vista_backup")

        actas_restauradas = 0
        actas_omitidas = 0

        for acta_data in datos.get("actas_creadas", []):
            numero_acta = acta_data.get("numero_acta", "")

            # Omitir si el acta ya existe
            if Acta.objects.filter(numero_acta=numero_acta).exists():
                actas_omitidas += 1
                continue

            try:
                with transaction.atomic():
                    # Crear acta (numero_acta ya definido, save() no lo regenera)
                    acta = Acta(
                        numero_acta=numero_acta,
                        titulo=acta_data.get("titulo", ""),
                        tipo_reunion=acta_data.get("tipo_reunion", "otra"),
                        fecha_reunion=acta_data.get("fecha_reunion"),
                        lugar_reunion=acta_data.get("lugar_reunion", ""),
                        modalidad=acta_data.get("modalidad", "presencial"),
                        estado=acta_data.get("estado", "finalizada"),
                        creador=user,
                        orden_dia=acta_data.get("orden_dia", ""),
                        desarrollo=acta_data.get("desarrollo", ""),
                        resumen_ia=acta_data.get("resumen_ia", ""),
                        observaciones=acta_data.get("observaciones", ""),
                        silencio_administrativo=acta_data.get("silencio_administrativo", False),
                        generada_con_ia=acta_data.get("generada_con_ia", False),
                    )
                    if acta_data.get("fecha_limite_firmas"):
                        acta.fecha_limite_firmas = parse_datetime(acta_data["fecha_limite_firmas"])
                    acta.save()

                    # Restaurar participantes (solo si el usuario sigue existiendo)
                    for p_data in acta_data.get("participantes", []):
                        try:
                            usuario_p = UserModel.objects.get(email=p_data["usuario_email"])
                            Participante.objects.get_or_create(
                                acta=acta,
                                usuario=usuario_p,
                                defaults={
                                    "rol_en_reunion": p_data.get("rol_en_reunion", ""),
                                    "obligatorio_firma": p_data.get("obligatorio_firma", True),
                                },
                            )
                        except UserModel.DoesNotExist:
                            pass

                    # Restaurar firmas
                    for f_data in acta_data.get("firmas", []):
                        try:
                            usuario_f = UserModel.objects.get(email=f_data["usuario_email"])
                            fecha_firma = parse_datetime(f_data["fecha_firma"]) if f_data.get("fecha_firma") else None
                            Firma.objects.get_or_create(
                                acta=acta,
                                usuario=usuario_f,
                                defaults={
                                    "firmado": f_data.get("firmado", False),
                                    "fecha_firma": fecha_firma,
                                    "firmado_por_silencio": f_data.get("firmado_por_silencio", False),
                                    "comentarios": f_data.get("comentarios", ""),
                                },
                            )
                        except UserModel.DoesNotExist:
                            pass

                    # Restaurar compromisos
                    for c_data in acta_data.get("compromisos", []):
                        try:
                            responsable = UserModel.objects.get(email=c_data["responsable_email"])
                            Compromiso.objects.create(
                                acta=acta,
                                descripcion=c_data.get("descripcion", ""),
                                responsable=responsable,
                                fecha_limite=parse_date(c_data["fecha_limite"]),
                                estado=c_data.get("estado", "pendiente"),
                                porcentaje_avance=c_data.get("porcentaje_avance", 0),
                                observaciones=c_data.get("observaciones", ""),
                            )
                        except UserModel.DoesNotExist:
                            pass

                    actas_restauradas += 1

            except Exception:
                # Si falla una acta, continuar con las demas
                continue

        if actas_restauradas > 0:
            messages.success(request, f"Se restauraron {actas_restauradas} acta(s) correctamente.")
        if actas_omitidas > 0:
            messages.info(request, f"{actas_omitidas} acta(s) ya existian y no fueron modificadas.")
        if actas_restauradas == 0 and actas_omitidas == 0:
            messages.warning(request, "No habia actas para restaurar en este backup.")

    except zipfile.BadZipFile:
        messages.error(request, "El archivo no es un ZIP valido.")
    except Exception as e:
        messages.error(request, f"Error al restaurar el backup: {str(e)}")

    return redirect("core:vista_backup")


@login_required
def restaurar_backup_personal_upload(request):
    """
    Restaura backup personal desde un archivo ZIP subido por el usuario.
    El ZIP debe ser un backup exportado desde el perfil.
    """
    import json
    from actas.models import Acta, Compromiso, Firma, Participante
    from accounts.models import User as UserModel
    from django.utils.dateparse import parse_datetime, parse_date
    from django.db import transaction

    if request.method != "POST":
        return redirect("accounts:profile")

    user = request.user
    archivo = request.FILES.get("backup_file")

    if not archivo:
        messages.error(request, "No se seleccionó ningún archivo.")
        return redirect("accounts:profile")

    try:
        with zipfile.ZipFile(archivo, "r") as zipf:
            json_files = [f for f in zipf.namelist() if f.endswith(".json")]
            if not json_files:
                messages.error(request, "El backup no contiene datos válidos.")
                return redirect("accounts:profile")

            with zipf.open(json_files[0]) as f:
                datos = json.load(f)

        backup_email = datos.get("usuario", {}).get("email", "")
        if backup_email != user.email:
            messages.error(request, "Este backup no pertenece a tu cuenta.")
            return redirect("accounts:profile")

        version = datos.get("version", "1.0")
        if version == "1.0":
            messages.warning(
                request,
                "Este backup fue creado con una versión antigua. "
                "Crea un nuevo backup desde tu perfil para obtener restauración completa."
            )
            return redirect("accounts:profile")

        actas_restauradas = 0
        actas_omitidas = 0

        for acta_data in datos.get("actas_creadas", []):
            numero_acta = acta_data.get("numero_acta", "")

            if Acta.objects.filter(numero_acta=numero_acta).exists():
                actas_omitidas += 1
                continue

            try:
                with transaction.atomic():
                    acta = Acta(
                        numero_acta=numero_acta,
                        titulo=acta_data.get("titulo", ""),
                        tipo_reunion=acta_data.get("tipo_reunion", "otra"),
                        fecha_reunion=acta_data.get("fecha_reunion"),
                        lugar_reunion=acta_data.get("lugar_reunion", ""),
                        modalidad=acta_data.get("modalidad", "presencial"),
                        estado=acta_data.get("estado", "finalizada"),
                        creador=user,
                        orden_dia=acta_data.get("orden_dia", ""),
                        desarrollo=acta_data.get("desarrollo", ""),
                        resumen_ia=acta_data.get("resumen_ia", ""),
                        observaciones=acta_data.get("observaciones", ""),
                        silencio_administrativo=acta_data.get("silencio_administrativo", False),
                        generada_con_ia=acta_data.get("generada_con_ia", False),
                    )
                    if acta_data.get("fecha_limite_firmas"):
                        acta.fecha_limite_firmas = parse_datetime(acta_data["fecha_limite_firmas"])
                    acta.save()

                    for p_data in acta_data.get("participantes", []):
                        try:
                            usuario_p = UserModel.objects.get(email=p_data["usuario_email"])
                            Participante.objects.get_or_create(
                                acta=acta, usuario=usuario_p,
                                defaults={
                                    "rol_en_reunion": p_data.get("rol_en_reunion", ""),
                                    "obligatorio_firma": p_data.get("obligatorio_firma", True),
                                },
                            )
                        except UserModel.DoesNotExist:
                            pass

                    for f_data in acta_data.get("firmas", []):
                        try:
                            usuario_f = UserModel.objects.get(email=f_data["usuario_email"])
                            fecha_firma = parse_datetime(f_data["fecha_firma"]) if f_data.get("fecha_firma") else None
                            Firma.objects.get_or_create(
                                acta=acta, usuario=usuario_f,
                                defaults={
                                    "firmado": f_data.get("firmado", False),
                                    "fecha_firma": fecha_firma,
                                    "firmado_por_silencio": f_data.get("firmado_por_silencio", False),
                                    "comentarios": f_data.get("comentarios", ""),
                                },
                            )
                        except UserModel.DoesNotExist:
                            pass

                    for c_data in acta_data.get("compromisos", []):
                        try:
                            responsable = UserModel.objects.get(email=c_data["responsable_email"])
                            Compromiso.objects.create(
                                acta=acta,
                                descripcion=c_data.get("descripcion", ""),
                                responsable=responsable,
                                fecha_limite=parse_date(c_data["fecha_limite"]),
                                estado=c_data.get("estado", "pendiente"),
                                porcentaje_avance=c_data.get("porcentaje_avance", 0),
                                observaciones=c_data.get("observaciones", ""),
                            )
                        except UserModel.DoesNotExist:
                            pass

                    actas_restauradas += 1

            except Exception:
                continue

        if actas_restauradas > 0:
            messages.success(request, f"Se restauraron {actas_restauradas} acta(s) correctamente.")
        if actas_omitidas > 0:
            messages.info(request, f"{actas_omitidas} acta(s) ya existían y no fueron modificadas.")
        if actas_restauradas == 0 and actas_omitidas == 0:
            messages.warning(request, "No había actas para restaurar en este backup.")

    except zipfile.BadZipFile:
        messages.error(request, "El archivo no es un ZIP válido.")
    except Exception as e:
        messages.error(request, f"Error al restaurar el backup: {str(e)}")

    return redirect("accounts:profile")


@login_required
def eliminar_copia_seguridad(request, nombre_archivo):
    """
    Elimina un archivo de copia de seguridad específico.
    SOLO ADMINISTRADORES pueden eliminar backups.
    """
    # Verificar que el usuario sea administrador
    if request.user.rol != 'admin':
        messages.error(request, "❌ Solo los administradores pueden eliminar copias de seguridad.")
        return redirect("core:vista_backup")

    # Sanitizar nombre de archivo para prevenir path traversal
    nombre_archivo = os.path.basename(nombre_archivo)
    ruta_backup = os.path.join(BACKUP_DIR, nombre_archivo)

    # 1. Verificar que el archivo realmente existe antes de intentar borrarlo
    if not os.path.exists(ruta_backup):
        messages.error(request, f"❌ El archivo de backup '{nombre_archivo}' no fue encontrado.")
        return redirect("core:vista_backup")

    try:
        # 2. Eliminar el archivo del sistema
        os.remove(ruta_backup)
        messages.success(request, f"🗑️ La copia de seguridad '{nombre_archivo}' ha sido eliminada correctamente.")
    except Exception as e:
        # 3. Capturar cualquier error inesperado durante la eliminación
        messages.error(request, f"❌ Error al eliminar el archivo '{nombre_archivo}': {str(e)}")

    # 4. Redirigir siempre a la lista de backups
    return redirect("core:vista_backup")