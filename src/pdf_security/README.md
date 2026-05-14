# Módulo pdf_security ✨

Gestión completa de PDFs protegidos con contraseña y permisos.

## Funcionalidades

### 🔓 Desbloquear
- Detectar si un PDF está protegido
- Validar contraseña
- Abrir en visor o guardar copia sin protección
- Ver información de permisos

### 🔒 Crear Protegido (NUEVO)
- Proteger PDFs existentes con contraseña
- Elegir nivel de protección o permisos personalizados
- Contraseña de propietario para cambios futuros
- 5 presets predefinidos

### 📋 Cambiar Permisos (NUEVO)
- Modificar permisos de PDFs ya protegidos
- Remover protección completamente
- Acceso programático a todas las operaciones

## Uso Rápido

### Importar

```python
from pdf_security import PDFSecurityManager, PDFSecurityTab
```

### Verificar si está protegido

```python
if PDFSecurityManager.is_protected("documento.pdf"):
    print("PDF protegido")
```

### Crear PDF Protegido ✨

```python
PDFSecurityManager.protect_pdf_with_permissions(
    "documento.pdf",
    "documento_protegido.pdf",
    user_password="contraseña123",
    owner_password="admin",
    allow_print=True,
    allow_copy=False,
    allow_modify=False
)
```

### Desbloquear PDF

```python
doc = PDFSecurityManager.unlock_pdf("documento.pdf", "contraseña")
if doc:
    doc.close()
```

### Usar Presets

```python
presets = PDFSecurityManager.get_default_permissions()
# Presets disponibles:
# - sin_restricciones
# - solo_lectura
# - solo_impresion
# - impresion_y_lectura
# - muy_restrictivo
```

## Integración en UI

El módulo está integrado en la aplicación con:
- **Botón navbar**: "🔐 Seguridad" entre Combinar y Configuración
- **Pestaña 1**: 🔓 Desbloquear PDFs protegidos
- **Pestaña 2**: 🔒 Crear PDFs protegidos
- Apertura automática en visor cuando se desbloquea

## Métodos Disponibles

### Verificación
- `is_protected(path)`: ¿Está protegido?
- `get_security_info(path)`: Obtener información
- `check_permissions(path, password)`: Obtener permisos

### Desbloqueo
- `unlock_pdf(path, password)`: Desbloquear (retorna documento)
- `unlock_pdf_to_file(path, password, output)`: Desbloquear y guardar

### Protección ✨
- `protect_pdf(path, output, user_pwd, owner_pwd, permissions)`: Proteger con códigos
- `protect_pdf_with_permissions(path, output, user_pwd, ...)`: Proteger con booleanos
- `get_default_permissions()`: Obtener presets

### Cambios ✨
- `change_pdf_permissions(path, output, owner_pwd, ...)`: Cambiar permisos
- `remove_protection(path, output, owner_pwd)`: Remover protección

## Constantes de Permisos

```python
PDFSecurityManager.PDF_PERM_PRINT          # Impresión
PDFSecurityManager.PDF_PERM_MODIFY         # Modificación
PDFSecurityManager.PDF_PERM_COPY           # Copia
PDFSecurityManager.PDF_PERM_ANNOTATE       # Anotaciones
PDFSecurityManager.PDF_PERM_FORMS          # Formularios
PDFSecurityManager.PDF_PERM_ASSEMBLY       # Ensamblaje
PDFSecurityManager.PDF_PERM_PRINT_HQ       # Impresión HD
```

## Ver Documentación Completa

[docs/seguridad-pdf.md](../../docs/seguridad-pdf.md) - Guía completa con ejemplos detallados

## Dependencias

- `pymupdf>=1.26.5`: Manejo de PDF y operaciones de cifrado
- `flet[all]==0.28.3`: Framework UI

