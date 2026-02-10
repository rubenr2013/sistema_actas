// === Funciones utilitarias globales ===

// Muestra un botón con estado de carga
function showButtonLoading($btn, text) {
  const originalText = $btn.html();
  $btn.prop("disabled", true);
  $btn.html(
    `<span class="spinner-border spinner-border-sm me-2" role="status"></span>${text}`
  );
  return originalText;
}

// Restaura el estado original del botón
function hideButtonLoading($btn, originalText) {
  $btn.prop("disabled", false);
  $btn.html(originalText);
}

// Mostrar alerta reutilizable
function showAlert(message, type = "success") {
  const alertClass =
    type === "error"
      ? "alert-danger"
      : type === "warning"
      ? "alert-warning"
      : "alert-success";

  const alertHtml = `
        <div class="alert ${alertClass} alert-dismissible fade show" role="alert">
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>
    `;

  $("#alerts-container").html(alertHtml);
  setTimeout(() => $(".alert").alert("close"), 5000);
}

// Funcionalidad específica para el módulo de actas
console.log(
  "El archivo JavaScript de ActasManager se ha cargado correctamente."
);
class ActasManager {
  constructor() {
    this.initializeEventListeners();
    this.setupAutoSave();
    this.initializeSignaturePad();
  }

  initializeEventListeners() {
    // Procesar con IA
    $("#btn-procesar-ia").on("click", (e) => {
      e.preventDefault();
      this.procesarConIA();
    });

    // Firmar acta
    $("#btn-firmar-acta").on("click", (e) => {
      e.preventDefault();
      this.firmarActa();
    });

    // Agregar participante
    $("#btn-agregar-participante").on("click", (e) => {
      console.log("Botón de agregar participante clickeado.");
      e.preventDefault();
      this.agregarParticipante();
    });

    // Agregar compromiso
    $("#btn-agregar-compromiso").on("click", (e) => {
      e.preventDefault();
      this.agregarCompromiso();
    });

    // Eliminar elementos dinámicos
    $(document).on("click", ".btn-eliminar", (e) => {
      e.preventDefault();
      $(e.target)
        .closest(".item-dinamico")
        .fadeOut(300, function () {
          $(this).remove();
        });
    });

    // Validación de email SENA
    $(document).on("blur", ".email-sena", (e) => {
      this.validarEmailSena(e.target);
    });
  }

  setupAutoSave() {
    // Auto-guardar borrador cada 30 segundos
    if ($("#form-acta").length > 0) {
      setInterval(() => {
        this.autoGuardar();
      }, 30000);
    }
  }

  procesarConIA() {
    const resumen = $("#resumen_reunion").val().trim();

    if (!resumen) {
      this.showAlert("Por favor ingrese un resumen de la reunión", "warning");
      return;
    }

    const $btn = $("#btn-procesar-ia");
    const originalText = showButtonLoading($btn, "Procesando con IA...");

    // Mostrar indicador visual
    $("#ai-processing-indicator").removeClass("d-none");

    $.ajax({
      url: "/actas/procesar-ia/", // ✅ Asegúrate de que esta ruta coincida con tu URL Django
      method: "POST",
      data: {
        resumen: resumen,
        csrfmiddlewaretoken: $("[name=csrfmiddlewaretoken]").val(),
      },
      success: (response) => {
        console.log("📤 Datos enviados a la IA:", resumen);
        console.log("📥 Respuesta JSON completa:", response);

        if (response.success) {
          // ✅ Mostrar el contenido generado
          const contenido =
            response.data.contenido || "⚠️ No se generó contenido";

          if (CKEDITOR.instances.desarrollo) {
            CKEDITOR.instances.desarrollo.setData(contenido);
          } else {
            $("#desarrollo").val(contenido);
          }

          // Si deseas llenar el orden del día con texto IA también:
          if (response.data.orden_dia) {
            $("#orden_dia").val(response.data.orden_dia);
          }

          this.showAlert("✅ Acta generada exitosamente con IA", "success");

          // Activar el siguiente paso si existe
          $("#btn-next-step-2").prop("disabled", false);

          // Efecto visual en campos actualizados
          $("#desarrollo, #orden_dia").addClass("updated-by-ai");
          setTimeout(
            () => $(".updated-by-ai").removeClass("updated-by-ai"),
            3000
          );
        } else {
          this.showAlert(
            response.message || "Error en la respuesta de la IA",
            "error"
          );
        }
      },
      error: (xhr, status, error) => {
        console.error("❌ Error al procesar con IA:", error);
        console.error("Detalles:", xhr.responseText);
        this.showAlert(
          "Error al procesar con IA. Inténtelo nuevamente.",
          "error"
        );
      },
      complete: () => {
        hideButtonLoading($btn, originalText);
        $("#ai-processing-indicator").addClass("d-none");
      },
    });
  }

  firmarActa() {
    const actaId = $("#acta-id").val();
    const comentarios = $("#comentarios-firma").val();

    const $btn = $("#btn-firmar-acta");
    const originalText = showButtonLoading($btn, "Firmando...");

    $.ajax({
      url: `/actas/${actaId}/firmar/`,
      method: "POST",
      data: {
        comentarios: comentarios,
        csrfmiddlewaretoken: $("[name=csrfmiddlewaretoken]").val(),
      },
      success: (response) => {
        if (response.success) {
          this.showAlert("¡Acta firmada exitosamente!", "success");

          // Actualizar interfaz
          $("#firma-status").html(`
                        <span class="badge bg-success">
                            <i class="fas fa-check-circle me-1"></i>Firmada
                        </span>
                    `);

          // Actualizar contador de firmas
          $("#firmas-completadas").text(response.firmas_completadas);
          $("#total-firmas").text(response.total_firmas);

          // Actualizar barra de progreso
          const porcentaje =
            (response.firmas_completadas / response.total_firmas) * 100;
          $("#progress-firmas .progress-bar").css("width", porcentaje + "%");

          // Ocultar formulario de firma
          $("#modal-firma").modal("hide");
          $("#seccion-firma").fadeOut();

          // Mostrar confetti si todas las firmas están completas
          if (response.firmas_completadas === response.total_firmas) {
            this.showConfetti();
            setTimeout(() => {
              this.showAlert(
                "¡Todas las firmas han sido completadas!",
                "success"
              );
            }, 1000);
          }
        } else {
          this.showAlert(response.message, "error");
        }
      },
      error: (xhr, status, error) => {
        this.showAlert("Error al firmar el acta.", "error");
        console.error("Error:", error);
      },
      complete: () => {
        hideButtonLoading($btn, originalText);
      },
    });
  }

  agregarParticipante() {
    console.log("Método agregarParticipante llamado.");
    const participanteHtml = `
            <div class="item-dinamico participante-item mb-3 p-3 border rounded bg-light fade-in-up">
                <div class="row align-items-center">
                    <div class="col-md-5">
                        <label class="form-label">Email del Participante</label>
                        <input type="email" name="participantes" class="form-control email-sena" 
                              placeholder="usuario@sena.edu.co" required>
                        <div class="email-validation-feedback"></div>
                    </div>
                    <div class="col-md-4">
                        <label class="form-label">Rol en la Reunión</label>
                        <input type="text" class="form-control rol-participante" 
                              placeholder="Ej: Coordinador, Instructor, etc.">
                    </div>
                    <div class="col-md-3 d-flex align-items-end">
                        <button type="button" class="btn btn-outline-danger btn-eliminar">
                            <i class="fas fa-trash"></i> Eliminar
                        </button>
                    </div>
                </div>
            </div>
        `;
    console.log("Agregando HTML del participante al contenedor.");
    $("#participantes-container").append(participanteHtml);

    // Animar entrada
    $(".participante-item:last").hide().fadeIn(300);
  }

  agregarCompromiso() {
    const compromisoHtml = `
            <div class="item-dinamico compromiso-item mb-3 p-3 border rounded bg-light fade-in-up">
                <div class="row">
                    <div class="col-md-6">
                        <label class="form-label">Descripción del Compromiso</label>
                        <textarea class="form-control compromiso-descripcion" rows="2" 
                                  placeholder="Descripción detallada del compromiso..." required></textarea>
                    </div>
                    <div class="col-md-3">
                        <label class="form-label">Responsable</label>
                        <input type="email" class="form-control email-sena compromiso-responsable" 
                                placeholder="responsable@sena.edu.co" required>
                    </div>
                    <div class="col-md-2">
                        <label class="form-label">Fecha Límite</label>
                        <input type="date" class="form-control compromiso-fecha" 
                              min="${
                                new Date().toISOString().split("T")[0]
                              }" required>
                    </div>
                    <div class="col-md-1 d-flex align-items-end">
                        <button type="button" class="btn btn-outline-danger btn-eliminar btn-sm">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;

    $("#compromisos-container").append(compromisoHtml);
    $(".compromiso-item:last").hide().fadeIn(300);
  }

  agregarCompromisoSugerido(compromiso) {
    this.agregarCompromiso();

    const $ultimoCompromiso = $(".compromiso-item:last");
    $ultimoCompromiso
      .find(".compromiso-descripcion")
      .val(compromiso.descripcion);

    if (
      compromiso.responsable_sugerido &&
      compromiso.responsable_sugerido.includes("@")
    ) {
      $ultimoCompromiso
        .find(".compromiso-responsable")
        .val(compromiso.responsable_sugerido);
    }

    if (compromiso.fecha_limite_sugerida) {
      $ultimoCompromiso
        .find(".compromiso-fecha")
        .val(compromiso.fecha_limite_sugerida);
    }

    // Resaltar como sugerencia de IA
    $ultimoCompromiso.addClass("ai-suggested");
    $ultimoCompromiso.prepend(
      '<div class="ai-badge">Sugerido por IA <i class="fas fa-robot"></i></div>'
    );
  }

  validarEmailSena(input) {
    const $input = $(input);
    const email = $input.val();
    const $feedback = $input.siblings(".email-validation-feedback");

    if (email && !email.endsWith("@sena.edu.co")) {
      $input.addClass("is-invalid");
      $feedback.html(
        '<small class="text-danger">Debe usar un correo @sena.edu.co</small>'
      );
      return false;
    } else if (email) {
      $input.removeClass("is-invalid").addClass("is-valid");
      $feedback.html('<small class="text-success">Email válido</small>');
      return true;
    } else {
      $input.removeClass("is-invalid is-valid");
      $feedback.empty();
      return true;
    }
  }

  autoGuardar() {
    // Solo auto-guardar si hay cambios
    if ($("#form-acta").hasClass("form-changed")) {
      const formData = new FormData($("#form-acta")[0]);
      formData.append("auto_save", "true");

      $.ajax({
        url: $("#form-acta").attr("action"),
        method: "POST",
        data: formData,
        processData: false,
        contentType: false,
        success: (response) => {
          if (response.success) {
            this.showTempMessage(
              "Borrador guardado automáticamente",
              "info",
              2000
            );
            $("#form-acta").removeClass("form-changed");
          }
        },
        error: () => {
          console.log("Error en auto-guardado");
        },
      });
    }
  }

  initializeSignaturePad() {
    // Inicializar pad de firma si existe
    if ($("#signature-pad").length > 0) {
      const canvas = document.getElementById("signature-pad");
      const signaturePad = new SignaturePad(canvas);

      $("#clear-signature").on("click", () => {
        signaturePad.clear();
      });

      $("#save-signature").on("click", () => {
        if (!signaturePad.isEmpty()) {
          const dataURL = signaturePad.toDataURL();
          $("#signature-data").val(dataURL);
          this.showAlert("Firma capturada exitosamente", "success");
        } else {
          this.showAlert("Por favor dibuje su firma", "warning");
        }
      });
    }
  }

  showAlert(message, type) {
    const alertClass =
      {
        success: "alert-success",
        error: "alert-danger",
        warning: "alert-warning",
        info: "alert-info",
      }[type] || "alert-info";

    const alertHtml = `
            <div class="alert ${alertClass} alert-dismissible fade show" role="alert">
                <i class="fas fa-${
                  type === "error"
                    ? "exclamation-triangle"
                    : type === "success"
                    ? "check-circle"
                    : "info-circle"
                } me-2"></i>
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;

    $("#alerts-container").prepend(alertHtml);

    // Auto-remover después de 5 segundos
    setTimeout(() => {
      $(".alert:first").fadeOut();
    }, 5000);
  }

  showTempMessage(message, type, duration) {
    const $tempAlert = $(`
            <div class="alert alert-${type} temp-alert" style="position: fixed; top: 100px; right: 20px; z-index: 1060; min-width: 300px;">
                <i class="fas fa-info-circle me-2"></i>${message}
            </div>
        `);

    $("body").append($tempAlert);
    $tempAlert.fadeIn();

    setTimeout(() => {
      $tempAlert.fadeOut(() => $tempAlert.remove());
    }, duration);
  }

  showConfetti() {
    // Efecto confetti usando una librería externa o implementación simple
    for (let i = 0; i < 100; i++) {
      setTimeout(() => {
        const confetti = $('<div class="confetti"></div>');
        confetti.css({
          position: "fixed",
          left: Math.random() * window.innerWidth + "px",
          top: "-10px",
          width: "10px",
          height: "10px",
          backgroundColor: [
            "#ff6b6b",
            "#4ecdc4",
            "#45b7d1",
            "#96ceb4",
            "#ffeaa7",
          ][Math.floor(Math.random() * 5)],
          zIndex: 9999,
          borderRadius: "50%",
        });

        $("body").append(confetti);

        confetti.animate(
          {
            top: window.innerHeight + "px",
            left: "+=" + (Math.random() * 200 - 100) + "px",
          },
          3000,
          () => confetti.remove()
        );
      }, i * 20);
    }
  }
}

// Inicializar cuando el documento esté listo
$(document).ready(() => {
  window.actasManager = new ActasManager();

  // Marcar formulario como cambiado
  $("#form-acta input, #form-acta textarea, #form-acta select").on(
    "change input",
    () => {
      $("#form-acta").addClass("form-changed");
    }
  );

  // Validación de formulario mejorada
  $("#form-acta").on("submit", function (e) {
    let valid = true;

    // Validar emails SENA
    $(".email-sena").each(function () {
      if (!window.actasManager.validarEmailSena(this)) {
        valid = false;
      }
    });

    if (!valid) {
      e.preventDefault();
      window.actasManager.showAlert(
        "Por favor corrija los errores en el formulario",
        "error"
      );
    }
  });
});
console.log("jQuery cargado:", typeof jQuery !== "undefined");
