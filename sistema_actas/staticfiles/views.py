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
    
    # Estadísticas generales
    stats = {
        'total_actas': Acta.objects.filter(
            Q(creador=user) | Q(participantes__usuario=user)
        ).distinct().count(),
        'actas_pendientes_firma': Firma.objects.filter(
            usuario=user, firmado=False, acta__estado='en_revision'
        ).count(),
        'compromisos_pendientes': Compromiso.objects.filter(
            responsable=user, estado__in=['pendiente', 'en_progreso']
        ).count(),
        'compromisos_vencidos': Compromiso.objects.filter(
            responsable=user, estado='vencido'
        ).count()
    }
    
    # Actas recientes del usuario
    actas_recientes = Acta.objects.filter(
        Q(creador=user) | Q(participantes__usuario=user)
    ).distinct().order_by('-fecha_creacion')[:5]
    
    # Compromisos próximos a vencer
    compromisos_proximos = Compromiso.objects.filter(
        responsable=user,
        estado__in=['pendiente', 'en_progreso'],
        fecha_limite__lte=timezone.now().date() + timedelta(days=7)
    ).order_by('fecha_limite')[:5]
    
    # Actas pendientes de firma
    firmas_pendientes = Firma.objects.filter(
        usuario=user,
        firmado=False,
        acta__estado='en_revision'
    ).select_related('acta')[:5]
    
    # Notificaciones recientes
    notificaciones = Notification.objects.filter(
        usuario=user, leida=False
    ).order_by('-fecha_creacion')[:5]
    
    context = {
        'stats': stats,
        'actas_recientes': actas_recientes,
        'compromisos_proximos': compromisos_proximos,
        'firmas_pendientes': firmas_pendientes,
        'notificaciones': notificaciones,
    }
    
    return render(request, 'dashboard/index.html', context)

@login_required
def crear_copia_seguridad(request):
    """
    Crea una copia de seguridad ZIP válida solo con los archivos importantes.
    SOLO ADMINISTRADORES pueden crear backups generales del sistema.
    """
    # Verificar que el usuario sea administrador
    if request.user.rol != 'admin':
        messages.error(request, "❌ Solo los administradores pueden crear copias de seguridad del sistema.")
        return redirect("core:vista_backup")

    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)

        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"backup_sistema_{fecha}.zip"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        # Archivos y carpetas a incluir
        incluir = [
            "db.sqlite3",
            "actas",
            "accounts",
            "core",
        ]

        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for item in incluir:
                ruta_item = os.path.join(settings.BASE_DIR, item)
                if os.path.exists(ruta_item):
                    if os.path.isfile(ruta_item):
                        zipf.write(ruta_item, arcname=item)
                    else:
                        for root, dirs, files in os.walk(ruta_item):
                            for archivo in files:
                                if "_pycache_" not in root:
                                    ruta_completa = os.path.join(root, archivo)
                                    arcname = os.path.relpath(ruta_completa, settings.BASE_DIR)
                                    zipf.write(ruta_completa, arcname)

        # Descargar el archivo automáticamente
        response = FileResponse(open(backup_path, 'rb'), as_attachment=True, filename=backup_filename)
        response['Content-Type'] = 'application/zip'
        response['Content-Length'] = os.path.getsize(backup_path)
        return response

    except Exception as e:
        messages.error(request, f"❌ Error al crear la copia de seguridad: {str(e)}")
        return redirect("core:vista_backup")


@login_required
def crear_backup_personal(request):
    """
    Crea una copia de seguridad PERSONAL del usuario (solo sus datos).
    Descarga automáticamente el archivo ZIP.
    """
    try:
        import json
        from actas.models import Acta, Compromiso, Firma

        os.makedirs(BACKUP_DIR, exist_ok=True)

        user = request.user
        fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Formato: backup_personal_[username]_[fecha].zip
        backup_filename = f"backup_personal_{user.username}_{fecha}.zip"
        backup_path = os.path.join(BACKUP_DIR, backup_filename)

        # Recopilar datos del usuario
        datos_usuario = {
            'usuario': {
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'rol': user.rol,
                'telefono': user.telefono,
            },
            'actas_creadas': list(Acta.objects.filter(creador=user).values()),
            'actas_participante': list(Acta.objects.filter(participantes__usuario=user).values()),
            'compromisos': list(Compromiso.objects.filter(responsable=user).values()),
            'firmas': list(Firma.objects.filter(usuario=user).values()),
        }

        # Crear archivo ZIP con los datos del usuario
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            # Guardar datos en formato JSON
            datos_json = json.dumps(datos_usuario, indent=2, default=str)
            zipf.writestr(f"datos_usuario_{user.username}.json", datos_json)

            # Incluir firma digital si existe
            if user.firma_digital:
                try:
                    firma_path = user.firma_digital.path
                    if os.path.exists(firma_path):
                        zipf.write(firma_path, arcname=f"firma_digital_{user.username}{os.path.splitext(firma_path)[1]}")
                except:
                    pass  # Si no se puede acceder a la firma, continuar

        # Descargar el archivo automáticamente
        response = FileResponse(open(backup_path, 'rb'), as_attachment=True, filename=backup_filename)
        response['Content-Type'] = 'application/zip'
        response['Content-Length'] = os.path.getsize(backup_path)
        return response

    except Exception as e:
        messages.error(request, f"❌ Error al crear tu copia de seguridad: {str(e)}")
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
            if request.user.rol == 'admin':
                # Administradores ven:
                # 1. Backups del sistema (backup_sistema_*)
                # 2. Sus propios backups personales (backup_personal_{username}_*)
                es_backup_sistema = archivo.startswith("backup_sistema_")
                es_backup_propio = archivo.startswith(f"backup_personal_{request.user.username}_")
                mostrar = es_backup_sistema or es_backup_propio
            else:
                # Usuarios regulares solo ven sus propios backups personales
                mostrar = archivo.startswith(f"backup_personal_{request.user.username}_")

            if mostrar:
                tamaño_mb = os.path.getsize(ruta) / (1024 * 1024)
                fecha_mod = datetime.fromtimestamp(os.path.getmtime(ruta)).strftime("%d/%m/%Y %H:%M:%S")
                archivos.append({
                    "nombre": archivo,
                    "tamaño": f"{tamaño_mb:.2f} MB",
                    "fecha": fecha_mod,
                })

    archivos.sort(key=lambda x: x["fecha"], reverse=True)
    return render(request, "actas/backup.html", {"archivos": archivos})


@login_required
def restaurar_backup(request, nombre_archivo):
    """
    Restaura una copia de seguridad existente desde la lista.
    """
    ruta_backup = os.path.join(BACKUP_DIR, nombre_archivo)

    if not os.path.exists(ruta_backup):
        messages.error(request, "❌ El archivo seleccionado no existe.")
        return redirect("core:vista_backup")

    try:
        with zipfile.ZipFile(ruta_backup, "r") as zip_ref:
            zip_ref.extractall(settings.BASE_DIR)

        messages.success(request, f"✅ El backup '{nombre_archivo}' fue restaurado correctamente.")
    except zipfile.BadZipFile:
        messages.error(request, f"❌ Error: el archivo '{nombre_archivo}' no es un archivo ZIP válido.")
    except Exception as e:
        messages.error(request, f"❌ Error al restaurar '{nombre_archivo}': {str(e)}")

    return redirect("core:vista_backup")

@login_required
def restaurar_backup_personal(request):
    """
    Restaura un backup personal que el usuario sube desde su computadora.
    TODOS LOS USUARIOS pueden restaurar su propio backup.
    """
    if request.method != 'POST':
        messages.error(request, "❌ Método no permitido.")
        return redirect("accounts:profile")

    try:
        import json
        from actas.models import Acta, Compromiso, Firma

        # Verificar que se subió un archivo
        if 'backup_file' not in request.FILES:
            messages.error(request, "❌ No se seleccionó ningún archivo.")
            return redirect("accounts:profile")

        backup_file = request.FILES['backup_file']

        # Verificar que sea un archivo ZIP
        if not backup_file.name.endswith('.zip'):
            messages.error(request, "❌ El archivo debe ser un ZIP.")
            return redirect("accounts:profile")

        user = request.user

        # Guardar temporalmente el archivo
        temp_path = os.path.join(BACKUP_DIR, f"temp_{user.username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
        with open(temp_path, 'wb+') as destination:
            for chunk in backup_file.chunks():
                destination.write(chunk)

        # Extraer y restaurar datos
        with zipfile.ZipFile(temp_path, 'r') as zipf:
            # Buscar el archivo JSON con los datos del usuario
            json_files = [f for f in zipf.namelist() if f.startswith('datos_usuario_') and f.endswith('.json')]

            if not json_files:
                os.remove(temp_path)
                messages.error(request, "❌ El archivo de backup no contiene datos válidos.")
                return redirect("accounts:profile")

            # Leer los datos del JSON
            with zipf.open(json_files[0]) as json_file:
                datos = json.load(json_file)

            # Verificar que el backup sea del usuario actual (seguridad)
            if datos.get('usuario', {}).get('username') != user.username:
                os.remove(temp_path)
                messages.error(request, "❌ Este backup no pertenece a tu cuenta.")
                return redirect("accounts:profile")

            # Restaurar firma digital si existe en el backup
            firma_files = [f for f in zipf.namelist() if f.startswith(f'firma_digital_{user.username}')]
            if firma_files and not user.firma_digital:
                # Solo restaurar si el usuario no tiene firma actual
                zipf.extract(firma_files[0], BACKUP_DIR)
                # Aquí podrías mover la firma al directorio de medios si lo deseas

        # Eliminar archivo temporal
        os.remove(temp_path)

        messages.success(request, f"✅ Tu copia de seguridad ha sido restaurada correctamente. Se recuperaron {len(datos.get('actas_creadas', []))} actas creadas y {len(datos.get('compromisos', []))} compromisos.")
        messages.info(request, "ℹ️ Nota: La restauración completa de datos requiere acceso administrativo a la base de datos.")

    except Exception as e:
        messages.error(request, f"❌ Error al restaurar el backup: {str(e)}")

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

    # Construir la ruta completa y segura al archivo
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