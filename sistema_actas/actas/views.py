import os
from datetime import timedelta, datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_POST
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone
from django.conf import settings
from django.core.management import call_command

# ReportLab para generación de PDFs
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image

# Modelos y utilidades locales
from .models import Acta, Participante, Firma, Compromiso, ComentarioActa
from .utils import sanitizar_html, sanitizar_texto_plano
from .forms import ReporteCompromisoForm
from core.utils import generar_acta_con_ia, enviar_notificacion_participantes
from notifications.models import Notification
from accounts.models import User

# Create your views here.
@login_required
def detalle_acta(request, acta_id):
    acta = get_object_or_404(Acta, id=acta_id)

    # Verificar permisos
    # 1. El creador puede ver el acta en cualquier estado
    # 2. Los participantes solo pueden ver el acta si NO está en borrador
    # 3. Los administradores pueden ver cualquier acta
    es_creador = acta.creador == request.user
    es_participante = acta.participantes.filter(usuario=request.user).exists()
    es_admin = request.user.is_staff or request.user.rol == 'admin'

    if not (
        es_creador
        or (es_participante and acta.estado != 'borrador')
        or es_admin
    ):
        messages.error(request, "No tienes permisos para ver esta acta.")
        return redirect("actas:actas_list")

    # Obtener información personal
    participantes = acta.participantes.select_related("usuario").prefetch_related('firmas').all()
    firmas = acta.firmas.select_related("usuario").all()
    compromisos = acta.compromisos.select_related("responsable").all()

    # Verificar si el usuario puede firmar
    puede_firmar = (
        acta.estado == "en_revision"
        and acta.firmas.filter(usuario=request.user, firmado=False).exists()
    )

    if request.user.rol in ['aprendiz', 'invitado']:
        compromisos = compromisos.filter(responsable=request.user)

    context = {
        "acta": acta,
        "participantes": participantes,
        "firmas": firmas,
        "compromisos": compromisos,
        "puede_firmar": puede_firmar,
        "puede_editar": (
            request.user.rol in ['instructor', 'funcionario', 'coordinador', 'director']
            and acta.creador == request.user
            and acta.estado == "borrador"
        ),
        "puede_enviar_revision": (
            request.user.rol in ['instructor', 'funcionario', 'coordinador', 'director']
            and acta.creador == request.user
            and acta.estado == "borrador"
        ),
        "puede_finalizar": (
            request.user.rol in ['instructor', 'funcionario', 'coordinador', 'director']
            and acta.creador == request.user
            and acta.estado == "en_revision"
        ),
        "puede_archivar": (
            request.user.rol in ['instructor', 'funcionario', 'coordinador', 'director']
            and acta.creador == request.user
            and acta.estado == "finalizada"
        ),
        'puede_comentar': request.user.rol in ['instructor', 'funcionario', 'coordinador', 'director', 'aprendiz', 'invitado'],
        # Silencio administrativo: visible si es creador/admin y el acta puede aplicarlo
        "puede_aplicar_silencio": (
            (es_creador or es_admin)
            and acta.puede_aplicar_silencio_administrativo()
        ),
        "fecha_limite_firmas": acta.fecha_limite_firmas,
    }
    return render(request, "actas/detalle.html", context)

@login_required
def editar_acta(request, acta_id):
    # Bloquear acceso a invitados y aprendices
    if request.user.rol in ['invitado', 'aprendiz']:
        messages.error(request, "No tienes permisos para editar actas.")
        return redirect("core:dashboard")

    acta = get_object_or_404(Acta, id=acta_id, creador=request.user)
    if acta.estado != "borrador":
        messages.error(request, "Solo se pueden editar actas en estado de borrador.")
        return redirect("actas:detalle", acta_id=acta_id)

    if request.method == "POST":
        # Actualizar campos básicos (con sanitización para prevenir XSS)
        acta.titulo = sanitizar_texto_plano(request.POST.get("titulo", ""))
        acta.tipo_reunion = request.POST.get("tipo_reunion")
        acta.fecha_reunion = request.POST.get("fecha_reunion")
        acta.lugar_reunion = sanitizar_texto_plano(request.POST.get("lugar_reunion", ""))
        acta.modalidad = request.POST.get("modalidad")
        acta.orden_dia = sanitizar_html(request.POST.get("orden_dia", ""))
        acta.desarrollo = sanitizar_html(request.POST.get("desarrollo", ""))
        acta.observaciones = sanitizar_html(request.POST.get("observaciones", ""))
        acta.save()

        # Actualizar participantes
        participantes_emails = request.POST.getlist("participantes")

        # Eliminar participantes que ya no están en la lista
        for participante in acta.participantes.all():
            if participante.usuario.email not in participantes_emails:
                participante.delete()

        # Añadir o actualizar participantes
        for email in participantes_emails:
            try:
                usuario = User.objects.get(email=email)
                rol = request.POST.get(f"rol_{email}", "")
                participante, created = Participante.objects.get_or_create(
                    acta=acta,
                    usuario=usuario,
                    defaults={
                        'rol_en_reunion': rol,
                        'obligatorio_firma': True,
                    }
                )
                if not created and rol:
                    participante.rol_en_reunion = rol
                    participante.save()
            except User.DoesNotExist:
                messages.warning(request, f"Usuario con email {email} no encontrado.")

        # Actualizar compromisos
        compromisos_data = []
        for key in request.POST.keys():
            if key.startswith("compromiso_desc_"):
                index = key.split("_")[-1]
                descripcion = request.POST.get(f"compromiso_desc_{index}").strip()
                responsable_email = request.POST.get(f"compromiso_resp_{index}")
                fecha_limite = request.POST.get(f"compromiso_fecha_{index}")

                if descripcion and responsable_email and fecha_limite:
                    compromisos_data.append({
                        "descripcion": descripcion,
                        "responsable_email": responsable_email,
                        "fecha_limite": fecha_limite,
                    })

        # Eliminar compromisos existentes
        acta.compromisos.all().delete()

        # Añadir nuevos compromisos
        for comp_data in compromisos_data:
            try:
                responsable = User.objects.get(email=comp_data["responsable_email"])
                Compromiso.objects.create(
                    acta=acta,
                    descripcion=comp_data["descripcion"],
                    responsable=responsable,
                    fecha_limite=comp_data["fecha_limite"],
                )
            except User.DoesNotExist:
                messages.warning(request, f'Responsable {comp_data["responsable_email"]} no encontrado.')

        messages.success(request, "Acta actualizada exitosamente.")
        return redirect("actas:detalle", acta_id=acta.id)

    context = {
        "acta": acta,
        "tipos_reunion": Acta.TIPOS_REUNION,
        "participantes": acta.participantes.all(),
        "compromisos": acta.compromisos.all(),
        "usuarios": User.objects.all(),
    }
    return render(request, "actas/editar.html", context)

@login_required
@require_POST
def firmar_acta(request, acta_id):
    acta = get_object_or_404(Acta, id=acta_id)

    if not acta.participantes.filter(usuario=request.user).exists():
        return JsonResponse(
            {"success": False, "message": "No eres participante de esta acta."},
            status=403
        )

    try:
        firma = Firma.objects.get(acta=acta, usuario=request.user)
        if firma.firmado:
            return JsonResponse(
                {"success": False, "message": "Ya has firmado esta acta."},
                status=400
            )
        if acta.estado != "en_revision":
            return JsonResponse(
                {
                    "success": False,
                    "message": "Esta acta no está en estado de revisión.",
                },
                status=400
            )

        # Obtener comentarios del POST
        comentarios = request.POST.get("comentarios", "")

        # Procesar Firma
        firma.comentarios = comentarios
        firma.firmado = True
        firma.fecha_firma = timezone.now()
        if request.user.firma_digital:
            firma.firma_imagen = request.user.firma_digital
        firma.save()

        # Crear notificaciones para el creador del acta
        Notification.objects.create(
            usuario=acta.creador,
            tipo="firma_completada",
            titulo="Nueva firma en acta",
            mensaje=f"{request.user.get_full_name()} ha firmado el acta {acta.numero_acta}",
            enlace=f"/actas/{acta.id}/",
        )

        # Verificar si todas las firmas están completas
        if acta.get_firmas_completadas() == acta.get_total_firmas():
            # Notificar al creador que el acta puede ser finalizada
            Notification.objects.create(
                usuario=acta.creador,
                tipo="acta_lista_finalizar",
                titulo="Acta lista para finalizar",
                mensaje=f"El acta {acta.numero_acta} tiene todas las firmas necesarias",
                enlace=f"/actas/{acta.id}/",
            )

        return JsonResponse(
            {
                "success": True,
                "message": "Acta firmada exitosamente.",
                "firmas_completadas": acta.get_firmas_completadas(),
                "total_firmas": acta.get_total_firmas(),
            }
        )
    except Firma.DoesNotExist:
        return JsonResponse(
            {"success": False, "message": "No tienes permisos para firmar esta acta."},
            status=403
        )
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Error al firmar: {str(e)}"}, status=500)

@login_required
@require_POST
def enviar_revision(request, acta_id):
    acta = get_object_or_404(Acta, id=acta_id, creador=request.user)

    if request.user.rol not in ['instructor', 'funcionario', 'coordinador', 'director', 'admin']:
        messages.error(request, "No tienes permisos para enviar actas a revisión.")
        return redirect("actas:detalle", acta_id=acta_id)

    if acta.estado != "borrador":
        messages.error(request, "Solo se pueden enviar a revisión actas en estado de borrador.")
        return redirect("actas:detalle", acta_id=acta_id)

    # Verificar que hay participantes
    if not acta.participantes.exists():
        messages.error(request, "No hay participantes asignados a esta acta.")
        return redirect("actas:detalle", acta_id=acta_id)

    # Cambiar el estado del acta
    acta.estado = "en_revision"
    acta.fecha_limite_firmas = timezone.now() + timedelta(days=acta.aplicar_silencio_dias)
    acta.save()

    participantes_notificados = 0
    for participante in acta.participantes.all():
        # Crear o recuperar firma
        firma, created = Firma.objects.get_or_create(
            acta=acta,
            usuario=participante.usuario,
            defaults={"firmado": False}
        )

        # Crear notificación para que le aparezca al participante
        Notification.objects.create(
            usuario=participante.usuario,
            tipo="firma_pendiente",
            titulo="📝 Nueva acta pendiente de firma",
            mensaje=f"Tienes pendiente firmar el acta '{acta.numero_acta} - {acta.titulo}'. Fecha límite: {acta.fecha_limite_firmas.strftime('%d/%m/%Y')}",
            enlace=f"/actas/{acta.id}/",
        )

        # Enviar email de solicitud de firma
        try:
            from .email_service import enviar_email_solicitud_firma
            print(f"🔄 Intentando enviar email a: {participante.usuario.email}")
            resultado = enviar_email_solicitud_firma(acta, participante.usuario)
            if resultado:
                print(f"✅ Email enviado exitosamente a: {participante.usuario.email}")
            else:
                print(f"⚠️ No se pudo enviar email a: {participante.usuario.email} (función retornó False)")
        except Exception as e:
            print(f"❌ Error al enviar email a {participante.usuario.email}: {str(e)}")
            import traceback
            traceback.print_exc()

        participantes_notificados += 1

    # Enviar emails de compromisos asignados
    compromisos_notificados = 0
    for compromiso in acta.compromisos.all():
        if compromiso.responsable and compromiso.responsable.email:
            try:
                from .email_service import enviar_email_compromiso_asignado
                print(f"🔄 Intentando enviar email de compromiso a: {compromiso.responsable.email}")
                resultado = enviar_email_compromiso_asignado(compromiso, compromiso.responsable)
                if resultado:
                    print(f"✅ Email de compromiso enviado exitosamente a: {compromiso.responsable.email}")
                    compromisos_notificados += 1
                else:
                    print(f"⚠️ No se pudo enviar email de compromiso a: {compromiso.responsable.email}")
            except Exception as e:
                print(f"❌ Error al enviar email de compromiso a {compromiso.responsable.email}: {str(e)}")
                import traceback
                traceback.print_exc()

    messages.success(request, f"Acta enviada a revisión. {participantes_notificados} participantes y {compromisos_notificados} responsables de compromisos han sido notificados.")
    return redirect("actas:detalle", acta_id=acta_id)

@login_required
@require_POST
def procesar_con_ia(request):
    resumen = request.POST.get("resumen", "").strip()

    if not resumen:
        return JsonResponse(
            {"success": False, "message": "Debe proporcionar un resumen de la reunión."}
        )

    try:
        resultado = generar_acta_con_ia(resumen, request.user)
        return JsonResponse({"success": True, "data": resultado})
    except Exception as e:
        return JsonResponse(
            {"success": False, "message": f"Error al procesar con IA: {str(e)}"}
        )

# Tamaño máximo estándar para todas las firmas en el PDF
FIRMA_MAX_WIDTH = 1.8 * inch
FIRMA_MAX_HEIGHT = 0.7 * inch


def _escalar_firma(ruta):
    """Carga imagen de firma escalada proporcionalmente dentro del tamaño máximo."""
    from reportlab.platypus import Image
    from reportlab.lib.utils import ImageReader
    try:
        img_reader = ImageReader(ruta)
        img_w, img_h = img_reader.getSize()
        if img_w > 0 and img_h > 0:
            ratio = min(FIRMA_MAX_WIDTH / img_w, FIRMA_MAX_HEIGHT / img_h)
            return Image(ruta, width=img_w * ratio, height=img_h * ratio)
    except Exception:
        pass
    return Image(ruta, width=FIRMA_MAX_WIDTH, height=FIRMA_MAX_HEIGHT)


def obtener_firma_imagen(firma, usuario):
    """
    Intenta obtener la imagen de firma con múltiples fallbacks.
    Retorna un objeto Image de ReportLab o None.
    """
    from django.conf import settings

    # 1. Intentar desde Firma.firma_imagen
    if firma and firma.firma_imagen:
        try:
            ruta = os.path.join(settings.MEDIA_ROOT, str(firma.firma_imagen))
            if os.path.exists(ruta):
                return _escalar_firma(ruta)
        except Exception as e:
            print(f"Error cargando firma desde Firma.firma_imagen: {e}")

    # 2. Intentar desde User.firma_digital
    if usuario.firma_digital:
        try:
            ruta = os.path.join(settings.MEDIA_ROOT, str(usuario.firma_digital))
            if os.path.exists(ruta):
                return _escalar_firma(ruta)
        except Exception as e:
            print(f"Error cargando firma desde User.firma_digital: {e}")

    # 3. Si todo falla, retornar None
    return None

@login_required
def generar_pdf(request, acta_id):
    """
    Genera PDF con formato oficial SENA GOR-F-084 V02
    """
    acta = get_object_or_404(Acta, id=acta_id)

    # Verificar permisos
    if not (
        acta.creador == request.user
        or acta.participantes.filter(usuario=request.user).exists()
        or request.user.is_staff
    ):
        messages.error(request, "No tienes permiso para descargar esta acta.")
        return redirect("actas:actas_list")

    # Crear PDF
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="ACTA_{acta.numero_acta}.pdf"'

    # Configurar documento
    doc = SimpleDocTemplate(
        response,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch
    )
    
    styles = getSampleStyleSheet()
    story = []

    # ==========================================
    # ENCABEZADO CON LOGO SENA
    # ==========================================
    # Intentar cargar logo (ajusta la ruta según tu proyecto)
    try:
        logo_path = os.path.join(settings.BASE_DIR, 'static', 'img', 'logo-sena.png')
        if os.path.exists(logo_path):
            logo = Image(logo_path, width=1*inch, height=1*inch)
            story.append(logo)
    except:
        pass  # Si no hay logo, continuar sin él

    story.append(Spacer(1, 10))

    # ==========================================
    # TABLA PRINCIPAL: ACTA No.
    # ==========================================
    acta_header = Table(
        [[Paragraph(f"<b>ACTA No. {acta.numero_acta}</b>", styles['Title'])]],
        colWidths=[7*inch]
    )
    acta_header.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 0), (-1, -1), colors.lightgrey),
    ]))
    story.append(acta_header)

    # ==========================================
    # NOMBRE DEL COMITÉ
    # ==========================================
    comite_table = Table(
        [
            [Paragraph("<b>NOMBRE DEL COMITÉ O DE LA REUNIÓN:</b>", styles['Normal'])],
            [Paragraph(acta.titulo, styles['Normal'])]
        ],
        colWidths=[7*inch],
        rowHeights=[0.3*inch, None]  # Altura mínima para primera fila
    )
    comite_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(comite_table)

    # ==========================================
    # FILA: CIUDAD/FECHA y HORA INICIO/FIN
    # ==========================================
    fecha_str = acta.fecha_reunion.strftime("%d/%m/%Y")
    hora_inicio = acta.fecha_reunion.strftime("%H:%M")
    hora_fin = (acta.fecha_reunion + timedelta(hours=2)).strftime("%H:%M")  # Estimado

    info_table = Table(
        [
            [
                Paragraph("<b>CIUDAD Y FECHA:</b>", styles['Normal']),
                Paragraph(f"{acta.lugar_reunion}, {fecha_str}", styles['Normal']),
                Paragraph("<b>HORA INICIO:</b>", styles['Normal']),
                Paragraph(hora_inicio, styles['Normal']),
                Paragraph("<b>HORA FIN:</b>", styles['Normal']),
                Paragraph(hora_fin, styles['Normal']),
            ]
        ],
        colWidths=[1.2*inch, 2*inch, 1*inch, 0.8*inch, 1*inch, 1*inch]  # Total = 7 pulgadas
    )
    info_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(info_table)

    # ==========================================
    # FILA: LUGAR/ENLACE y DIRECCIÓN/REGIONAL
    # ==========================================
    lugar_table = Table(
        [
            [
                Paragraph("<b>LUGAR Y/O ENLACE:</b>", styles['Normal']),
                Paragraph(acta.lugar_reunion, styles['Normal']),
                Paragraph("<b>DIRECCIÓN / REGIONAL / CENTRO:</b>", styles['Normal']),
                Paragraph("Centro Minero SENA", styles['Normal']),
            ]
        ],
        colWidths=[1.5*inch, 2*inch, 2*inch, 1.5*inch]
    )
    lugar_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(lugar_table)

    # ==========================================
    # AGENDA O PUNTOS PARA DESARROLLAR
    # ==========================================
    # Sanitizar contenido para prevenir XSS
    agenda_content = sanitizar_texto_plano(acta.orden_dia) if acta.orden_dia else "No especificada"
    agenda_table = Table(
        [
            [Paragraph("<b>AGENDA O PUNTOS PARA DESARROLLAR:</b>", styles['Normal'])],
            [Paragraph(agenda_content.replace('\n', '<br/>'), styles['Normal'])]
        ],
        colWidths=[7*inch],
        splitByRow=1
    )
    agenda_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(agenda_table)

    # ==========================================
    # OBJETIVO(S) DE LA REUNIÓN
    # ==========================================
    objetivo = f"Reunión de tipo {acta.get_tipo_reunion_display()}"
    if acta.generada_con_ia:
        objetivo += " (Generada con IA)"

    objetivo_table = Table(
        [
            [Paragraph("<b>OBJETIVO(S) DE LA REUNIÓN:</b>", styles['Normal'])],
            [Paragraph(sanitizar_texto_plano(objetivo), styles['Normal'])]
        ],
        colWidths=[7*inch]
    )
    objetivo_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(objetivo_table)

    # ==========================================
    # DESARROLLO DE LA REUNIÓN
    # ==========================================
    # Sanitizar contenido para prevenir XSS
    desarrollo_content = sanitizar_texto_plano(acta.desarrollo) if acta.desarrollo else "No especificado"
    desarrollo_table = Table(
        [
            [Paragraph("<b>DESARROLLO DE LA REUNIÓN</b>", styles['Normal'])],
            [Paragraph(desarrollo_content.replace('\n', '<br/>'), styles['Normal'])]
        ],
        colWidths=[7*inch],
        splitByRow=1
    )
    desarrollo_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(desarrollo_table)

    # ==========================================
    # CONCLUSIONES
    # ==========================================
    conclusiones = acta.observaciones if acta.observaciones else "Sin observaciones adicionales"
    conclusiones_table = Table(
        [
            [Paragraph("<b>CONCLUSIONES</b>", styles['Normal'])],
            [Paragraph(conclusiones.replace('\n', '<br/>'), styles['Normal'])]
        ],
        colWidths=[7*inch],
        splitByRow=1
    )
    conclusiones_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(conclusiones_table)

    # ==========================================
    # COMPROMISOS
    # ==========================================
    compromisos_data = [
        [
            Paragraph("<b>ACTIVIDAD/DECISIÓN</b>", styles['Normal']),
            Paragraph("<b>FECHA</b>", styles['Normal']),
            Paragraph("<b>RESPONSABLE</b>", styles['Normal']),
            Paragraph("<b>FIRMA</b>", styles['Normal']),
        ]
    ]

    if acta.compromisos.exists():
        for comp in acta.compromisos.all():
            compromisos_data.append([
                Paragraph(comp.descripcion, styles['Normal']),
                Paragraph(comp.fecha_limite.strftime("%d/%m/%Y"), styles['Normal']),
                Paragraph(comp.responsable.get_full_name(), styles['Normal']),
                Paragraph("", styles['Normal']),  # Espacio para firma
            ])
    else:
        compromisos_data.append([
            Paragraph("No se registraron compromisos", styles['Normal']),
            "", "", ""
        ])

    compromisos_table = Table(compromisos_data, colWidths=[2.5*inch, 1.2*inch, 1.8*inch, 1.5*inch])
    compromisos_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(compromisos_table)

    # ==========================================
    # ASISTENTES Y APROBACIÓN
    # ==========================================
    story.append(Spacer(1, 10))

    asistentes_data = [
        [
            Paragraph("<b>NOMBRE</b>", styles['Normal']),
            Paragraph("<b>DEPENDENCIA/EMPRESA</b>", styles['Normal']),
            Paragraph("<b>APRUEBA (SI/NO)</b>", styles['Normal']),
            Paragraph("<b>FIRMA O PARTICIPACIÓN VIRTUAL</b>", styles['Normal']),
        ]
    ]

    # Agregar participantes con sus firmas
    for participante in acta.participantes.select_related('usuario').all():
        firma_obj = acta.firmas.filter(usuario=participante.usuario).first()

        # Preparar celda de firma con múltiples fallbacks
        if firma_obj and firma_obj.firmado:
            # Intentar obtener imagen de firma
            firma_imagen = obtener_firma_imagen(firma_obj, participante.usuario)

            if firma_imagen:
                # ✅ Se encontró la imagen de firma
                firma_cell = firma_imagen
            else:
                # Sin imagen: mostrar nombre del usuario (silencio administrativo u otro caso)
                nombre = participante.usuario.get_full_name() or participante.usuario.username
                prefijo = "<font color='grey' size=7>[Silencio Adm.]</font><br/>" if getattr(firma_obj, 'firmado_por_silencio', False) else ""
                firma_cell = Paragraph(
                    f"{prefijo}<b>{nombre}</b><br/><font size=6>{firma_obj.fecha_firma.strftime('%d/%m/%Y') if firma_obj.fecha_firma else 'N/A'}</font>",
                    styles['Normal']
                )
        else:
            # ❌ No firmado
            firma_cell = Paragraph(
                "<font color='red'>Pendiente</font>",
                styles['Normal']
            )

        asistentes_data.append([
            Paragraph(participante.usuario.get_full_name(), styles['Normal']),
            Paragraph(participante.rol_en_reunion or "Participante", styles['Normal']),
            Paragraph("SÍ" if firma_obj and firma_obj.firmado else "NO", styles['Normal']),
            firma_cell
        ])

    asistentes_table = Table(asistentes_data, colWidths=[1.8*inch, 1.8*inch, 1.2*inch, 2.2*inch])
    asistentes_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(asistentes_table)

    # ==========================================
    # NOTA LEGAL
    # ==========================================
    story.append(Spacer(1, 10))
    nota_legal = Paragraph(
        "<font size=7>De acuerdo con La Ley 1581 de 2012, Protección de Datos Personales, el Servicio Nacional de Aprendizaje SENA, "
        "se compromete a garantizar la seguridad y protección de los datos personales que se encuentran almacenados en este "
        "documento, y les dará el tratamiento correspondiente en cumplimiento de lo establecido legalmente.</font>",
        styles['Normal']
    )
    story.append(nota_legal)

    # ==========================================
    # PIE DE PÁGINA
    # ==========================================
    story.append(Spacer(1, 20))
    footer_style = ParagraphStyle(
        'CenteredFooter',
        parent=styles['Normal'],
        alignment=TA_CENTER,
        fontSize=8,
    )
    footer = Paragraph("<b>GOR-F-084 V02</b>", footer_style)
    story.append(footer)

    # Construir PDF
    try:
        doc.build(story)
    except Exception as e:
        print(f"Error al construir PDF: {e}")
        messages.error(request, "Error al generar el PDF.")
        return redirect("actas:detalle", acta_id=acta.id)

    return response

@login_required
def actas_list(request):
    # Filtros
    estado = request.GET.get('estado')
    tipo = request.GET.get('tipo')
    search = request.GET.get('search')

    if request.user.rol in ['aprendiz', 'invitado']:
        # Aprendices e invitados solo ven actas donde son participantes Y que NO estén en borrador
        actas = Acta.objects.filter(
            participantes__usuario=request.user
        ).exclude(estado='borrador').distinct()

    elif request.user.rol in ['instructor', 'funcionario', 'coordinador', 'director']:
        # Instructores/funcionarios ven:
        # 1. Actas que crearon (cualquier estado)
        # 2. Actas donde son participantes (solo las que NO están en borrador)
        actas = Acta.objects.filter(
            Q(creador=request.user) |
            (Q(participantes__usuario=request.user) & ~Q(estado='borrador'))
        ).distinct()

    elif request.user.rol == 'admin' or request.user.is_superuser:
        actas = Acta.objects.all()
    else:
        actas = Acta.objects.none()

    if estado:
        actas = actas.filter(estado=estado)
    if tipo:
        actas = actas.filter(tipo_reunion=tipo)
    if search:
        actas = actas.filter(
            Q(titulo__icontains=search) |
            Q(numero_acta__icontains=search) |
            Q(desarrollo__icontains=search)
        )

    # Paginación
    paginator = Paginator(actas.order_by('-fecha_creacion'), 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'estados': Acta.ESTADOS,
        'tipos_reunion': Acta.TIPOS_REUNION,
        'filtros': {
            'estado': estado or '',
            'tipo': tipo or '',
            'search': search or '',
        },
        'es_aprendiz': request.user.rol == "aprendiz",
    }

    return render(request, 'actas/actas_list.html', context)

@login_required
def crear_acta(request):
    # Bloquear acceso a invitados y aprendices
    if request.user.rol in ['invitado', 'aprendiz']:
        messages.error(request, "No tienes permisos para crear actas.")
        return redirect("actas:actas_list")
    
    if request.method == 'POST':
        try:
            # Procesar con IA si se proporciona resumen
            resumen = request.POST.get('resumen_reunion', '').strip()
            
            if resumen:
                try:
                    contenido_ia = generar_acta_con_ia(resumen, request.user)
                    orden_dia = contenido_ia.get('orden_dia', '')
                    desarrollo = contenido_ia.get('desarrollo', '')
                except Exception as e:
                    messages.warning(request, f'No se pudo procesar con IA: {str(e)}')
                    orden_dia = request.POST.get('orden_dia', '')
                    desarrollo = request.POST.get('desarrollo', '')
            else:
                # Sin IA, tomar datos del formulario
                orden_dia = request.POST.get('orden_dia', '')
                desarrollo = request.POST.get('desarrollo', '')
            
            # Crear el acta
            acta = Acta.objects.create(
                titulo=request.POST.get('titulo'),
                tipo_reunion=request.POST.get('tipo_reunion'),
                fecha_reunion=request.POST.get('fecha_reunion'),
                lugar_reunion=request.POST.get('lugar_reunion'),
                modalidad=request.POST.get('modalidad'),
                orden_dia=orden_dia,
                desarrollo=desarrollo,
                observaciones=request.POST.get('observaciones', ''),
                resumen_ia=resumen if resumen else '',
                creador=request.user
            )
            
            # ========================================
            # PROCESAR PARTICIPANTES
            # ========================================
            participantes_emails = request.POST.getlist('participantes')
            participantes_agregados = set()  # Para evitar duplicados
            
            for email in participantes_emails:
                email = email.strip()
                if email and email not in participantes_agregados:  # ← Validar duplicados
                    try:
                        usuario = User.objects.get(email=email)
                        
                        # Verificar si ya existe
                        if not Participante.objects.filter(acta=acta, usuario=usuario).exists():
                            # Buscar el rol de este participante
                            rol = ''
                            for key in request.POST.keys():
                                if key.startswith('rol_participante_') or key.startswith(f'rol_{email}'):
                                    rol = request.POST.get(key, '')
                                    break
                            
                            # Crear participante
                            Participante.objects.create(
                                acta=acta,
                                usuario=usuario,
                                rol_en_reunion=rol if rol else 'Participante',
                                obligatorio_firma=True
                            )
                            participantes_agregados.add(email)
                            print(f"✅ Participante creado: {usuario.email}")
                        
                    except User.DoesNotExist:
                        messages.warning(request, f'Usuario con email {email} no encontrado.')
            
            # ========================================
            # PROCESAR COMPROMISOS
            # ========================================
            from datetime import datetime
            
            compromisos_data = []
            
            # Buscar todos los compromisos en el POST
            for key in request.POST.keys():
                if key.startswith('compromiso_desc_'):
                    index = key.split('_')[-1]
                    descripcion = request.POST.get(f'compromiso_desc_{index}', '').strip()
                    responsable_email = request.POST.get(f'compromiso_resp_{index}', '').strip()
                    fecha_limite_str = request.POST.get(f'compromiso_fecha_{index}', '').strip()
                    
                    if descripcion and responsable_email and fecha_limite_str:
                        # Convertir string a fecha
                        try:
                            fecha_limite = datetime.strptime(fecha_limite_str, '%Y-%m-%d').date()
                            compromisos_data.append({
                                'descripcion': descripcion,
                                'responsable_email': responsable_email,
                                'fecha_limite': fecha_limite
                            })
                        except ValueError:
                            messages.warning(request, f'Fecha inválida para compromiso: {fecha_limite_str}')
            
            # Crear los compromisos
            for comp_data in compromisos_data:
                try:
                    responsable = User.objects.get(email=comp_data['responsable_email'])
                    compromiso = Compromiso.objects.create(
                        acta=acta,
                        descripcion=comp_data['descripcion'],
                        responsable=responsable,
                        fecha_limite=comp_data['fecha_limite']  # Ya es un objeto date
                    )
                    print(f"✅ Compromiso creado para: {responsable.email}")

                    # NOTA: Los emails de compromisos se enviarán cuando el acta sea enviada a revisión,
                    # no al momento de crear el acta en borrador

                except User.DoesNotExist:
                    messages.warning(request, f'Responsable {comp_data["responsable_email"]} no encontrado.')
            
            # Mensaje de éxito
            messages.success(request, f'Acta {acta.numero_acta} creada exitosamente con {participantes_agregados.__len__()} participantes.')
            return redirect('actas:detalle', acta_id=acta.id)
            
        except Exception as e:
            messages.error(request, f'Error al crear el acta: {str(e)}')
            import traceback
            traceback.print_exc()
    
    # GET request - mostrar formulario
    context = {
        'tipos_reunion': Acta.TIPOS_REUNION,
        'usuarios': User.objects.filter(is_active=True).order_by('first_name', 'last_name'),
    }

    return render(request, 'actas/crear.html', context)

@login_required
def eliminar_acta(request, acta_id):
    acta = get_object_or_404(Acta, id=acta_id)
    
    # Solo el creador o un admin pueden eliminar
    if request.user != acta.creador and not request.user.is_superuser:
        messages.error(request, "No tienes permisos para eliminar esta acta.")
        return redirect("actas:detalle", acta_id=acta.id)

    acta.delete()
    messages.success(request, "El acta ha sido eliminada correctamente.")
    return redirect("actas:actas_list")

# ✅ Finalizar Acta
@login_required
def finalizar_acta(request, acta_id):
    acta = get_object_or_404(Acta, id=acta_id)

    if request.user.rol not in ['instructor', 'funcionario', 'coordinador', 'director', 'admin']:
        messages.error(request, "No tienes permisos para finalizar actas.")
        return redirect("actas:detalle", acta_id=acta.id)

    # Instructores y funcionarios solo pueden finalizar sus propias actas
    if request.user.rol in ['instructor', 'funcionario'] and acta.creador != request.user:
        messages.error(request, "Solo puedes finalizar actas que tú has creado.")
        return redirect("actas:detalle", acta_id=acta.id)

    if acta.estado not in ["borrador", "en_revision"]:
        messages.warning(request, "El acta no se puede finalizar en este estado.")
        return redirect("actas:detalle", acta_id=acta.id)

    # Antes de finalizar, verificamos firmas
    if acta.get_firmas_completadas() < acta.get_total_firmas():
        messages.warning(request, "No se puede finalizar el acta porque aún faltan firmas.")
        return redirect("actas:detalle", acta_id=acta.id)

    acta.estado = "finalizada"
    acta.fecha_modificacion = timezone.now()
    acta.save()

    messages.success(request, "El acta ha sido finalizada con éxito.")
    return redirect("actas:detalle", acta_id=acta.id)

# 📂 Archivar Acta
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.utils import timezone

@login_required
@require_POST
def archivar_acta(request, acta_id):
    acta = get_object_or_404(Acta, id=acta_id)
    
    # Verificar permisos
    if request.user.rol not in ['instructor', 'funcionario', 'coordinador', 'director', 'admin']:
        return JsonResponse({
            'success': False,
            'message': 'No tienes permisos para archivar actas.'
        }, status=403)
    
    # Verificar que sea el creador
    if acta.creador != request.user and not request.user.is_superuser:
        return JsonResponse({
            'success': False,
            'message': 'Solo el creador puede archivar esta acta.'
        }, status=403)

    # Verificar estado
    if acta.estado != "finalizada":
        return JsonResponse({
            'success': False,
            'message': 'Solo las actas finalizadas se pueden archivar.'
        }, status=400)

    # Archivar
    acta.estado = "archivada"
    acta.fecha_modificacion = timezone.now()
    acta.save()

    return JsonResponse({
        'success': True,
        'message': 'El acta ha sido archivada exitosamente.'
    })

# ✍️ Firmas pendientes
@login_required
def firmas_pendientes(request):
    if request.user.rol == 'admin':
        firmas = Firma.objects.filter(
            firmado=False, acta__estado="en_revision"
        ).select_related('acta', 'usuario')
    else:
        firmas = Firma.objects.filter(
            usuario=request.user, firmado=False, acta__estado="en_revision"
        ).select_related('acta')

    return render(request, "actas/firmas_pendientes.html", {
        "firmas": firmas,
        "es_admin": request.user.rol == 'admin',
    })
    
@login_required
def lista_compromisos(request, acta_id):
    acta = get_object_or_404(Acta, id=acta_id)
    compromisos = acta.compromisos.all()
    return render(request, "actas/compromisos/lista.html", {"acta": acta, "compromisos": compromisos})

@login_required
def crear_compromiso(request, acta_id):
    acta = get_object_or_404(Acta, id=acta_id)

    # Solo el creador del acta o roles superiores pueden crear compromisos
    roles_superiores = ['coordinador', 'director', 'admin']
    if acta.creador != request.user and request.user.rol not in roles_superiores:
        messages.error(request, "Solo el creador del acta puede agregar compromisos.")
        return redirect("actas:detalle", acta_id=acta.id)

    if request.method == "POST":
        descripcion = request.POST.get("descripcion")
        responsable_id = request.POST.get("responsable")
        fecha_limite = request.POST.get("fecha_limite")

        Compromiso.objects.create(
            acta=acta,
            descripcion=descripcion,
            responsable_id=responsable_id,
            fecha_limite=fecha_limite
        )
        return redirect("actas:lista_compromisos", acta_id=acta.id)
    return render(request, "actas/compromisos/form.html", {"acta": acta})

@login_required
def editar_compromiso(request, compromiso_id):
    compromiso = get_object_or_404(Compromiso, id=compromiso_id)
    
    # *** 1. Validar que el usuario es el responsable ***
    if request.user != compromiso.responsable:
        # Si no es el responsable, lo rediriges o le das un error 403 (Prohibido)
        # Por ahora, simplemente lo redirigiremos a su lista de compromisos.
        return redirect("actas:mis_compromisos") 
    
    # *** 2. Usar el formulario de reporte ***
    if request.method == "POST":
        form = ReporteCompromisoForm(request.POST, instance=compromiso)
        if form.is_valid():
            compromiso_guardado = form.save(commit=False)
            
            # Si el responsable marca 100%, Git actualiza el estado a 'completado' 
            # (tu método save() ya lo hace)
            if compromiso_guardado.porcentaje_avance == 100:
                compromiso_guardado.fecha_completado = timezone.now()
            
            compromiso_guardado.save()
            # Puedes usar messages.success para notificar al usuario.
            return redirect("actas:mis_compromisos")
    else:
        form = ReporteCompromisoForm(instance=compromiso)
        
    context = {
        "compromiso": compromiso,
        "form": form
    }
    # NOTA: Debes crear la template 'actas/compromisos/reporte_form.html'
    return render(request, "actas/reporte_form.html", context)

@login_required
def eliminar_compromiso(request, compromiso_id):
    compromiso = get_object_or_404(Compromiso, id=compromiso_id)

    # Solo el creador del acta o roles superiores pueden eliminar compromisos
    roles_superiores = ['coordinador', 'director', 'admin']
    if compromiso.acta.creador != request.user and request.user.rol not in roles_superiores:
        messages.error(request, "Solo el creador del acta puede eliminar compromisos.")
        return redirect("actas:lista_compromisos", acta_id=compromiso.acta.id)

    acta_id = compromiso.acta.id
    compromiso.delete()
    return redirect("actas:lista_compromisos", acta_id=acta_id)

@login_required
def mis_compromisos(request):
    if request.user.rol == 'admin':
        compromisos = Compromiso.objects.all().select_related(
            'responsable', 'acta'
        ).order_by('-fecha_limite')
    else:
        compromisos = Compromiso.objects.filter(
            responsable=request.user
        ).select_related('acta').order_by('-fecha_limite')

    return render(request, "actas/mis_compromisos.html", {
        "compromisos": compromisos,
        "es_admin": request.user.rol == 'admin',
    })

@login_required
@require_POST
def agregar_comentario(request, acta_id):
    acta = get_object_or_404(Acta, id=acta_id)

    if request.user.rol not in ["aprendiz", "invitado"]:
        return JsonResponse({"success": False, "message": "Solo los aprendices pueden comentar."})

    texto = request.POST.get("comentario", "").strip()
    if not texto:
        return JsonResponse({"success": False, "message": "El comentario no puede estar vacío."})

    # Sanitizar el texto para prevenir XSS
    texto_sanitizado = sanitizar_html(texto)

    ComentarioActa.objects.create(acta=acta, autor=request.user, texto=texto_sanitizado)
    return JsonResponse({"success": True, "message": "Comentario agregado correctamente."})

@login_required
def aprendiz_pendientes(request):
    if request.user.rol not in ['aprendiz', 'invitado']:
        messages.error(request, "No tienes permisos para acceder a esta sección.")
        return redirect('actas:actas_list')

    # Filtramos las actas que están en revisión y que el aprendiz debe firmar
    firmas = Firma.objects.filter(
        usuario=request.user,
        firmado=False,
        acta__estado='en_revision'
    ).select_related('acta')

    context = {
        'firmas': firmas,
        'titulo': "Actas pendientes por firmar"
    }
    return render(request, 'actas/aprendiz/pendientes.html', context)

@login_required
def aprendiz_compromisos(request):
    if request.user.rol not in ['aprendiz', 'invitado']:
        messages.error(request, "No tienes permisos para acceder a esta sección.")
        return redirect('actas:actas_list')

    compromisos = Compromiso.objects.filter(
        responsable=request.user
    ).select_related('acta').order_by('-fecha_limite')

    context = {
        'compromisos': compromisos,
        'titulo': "Mis compromisos asignados"
    }
    return render(request, 'actas/aprendiz/compromisos.html', context)