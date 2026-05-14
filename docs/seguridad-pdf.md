# Módulo de Seguridad de PDFs

## Descripción General

El módulo `pdf_security` proporciona funcionalidades **completas** para gestionar PDFs protegidos:

### Funcionalidades Principales

✅ **Desbloquear PDFs**
- Detectar si un PDF está protegido
- Validar y desbloquear con contraseña
- Abrir directamente en el visor
- Guardar copia sin protección

✅ **Crear PDFs Protegidos** 
- Proteger PDFs existentes con contraseña
- Asignar diferentes niveles de permisos
- Usar presets predefinidos o permisos personalizados
- Contraseña de propietario para cambios futuros

✅ **Gestionar Permisos**
- Impresión (normal y alta calidad)
- Modificación de contenido
- Copia de contenido
- Anotaciones
- Llenar formularios
- Ensamblaje de páginas
- Cambiar permisos de PDFs existentes

## Estructura

```
src/pdf_security/
├── __init__.py           # Exportación de componentes
├── security.py           # Lógica de seguridad y desbloqueo
└── tab.py               # UI (pestaña en la aplicación)
```

## Componentes Principales

### 1. `PDFSecurityManager` (security.py)

Clase que maneja todas las operaciones de seguridad:

#### Métodos Principales

**`get_security_info(path: str) -> PDFSecurityInfo`**
- Obtiene información de seguridad de un PDF sin abrirlo completamente
- Retorna un objeto `PDFSecurityInfo` con detalles de cifrado y permisos

**`is_protected(path: str) -> bool`**
- Verifica si un PDF está protegido con contraseña
- Retorna `True` si está protegido, `False` en caso contrario

**`unlock_pdf(path: str, password: str) -> Optional[fitz.Document]`**
- Intenta desbloquear un PDF con la contraseña proporcionada
- Retorna el documento abierto si es exitoso, `None` si falla

**`unlock_pdf_to_file(path: str, password: str, output_path: str) -> bool`**
- Desbloquea un PDF y lo guarda sin protección en una nueva ubicación
- Retorna `True` si es exitoso

**`check_permissions(path: str, password: Optional[str] = None) -> PDFSecurityInfo`**
- Obtiene información detallada de permisos del PDF
- Si está protegido, requiere la contraseña correcta

**`protect_pdf(...)`** ✨ NUEVO
- Protege un PDF existente con contraseña
- Permite asignar permisos específicos
- Soporta contraseña de propietario

**`protect_pdf_with_permissions(...)`** ✨ NUEVO
- Protege PDF con permisos específicos por nombre
- Más legible que especificar códigos binarios

**`change_pdf_permissions(...)`** ✨ NUEVO
- Cambia permisos de un PDF ya protegido
- Requiere contraseña de propietario

**`remove_protection(...)`** ✨ NUEVO
- Elimina totalmente la protección de un PDF
- Requiere contraseña de propietario

**`get_default_permissions()`** ✨ NUEVO
- Retorna diccionario con presets de permisos:
  - `sin_restricciones`: Acceso completo
  - `solo_lectura`: No puede mcon **dos pestañas**:

#### Pestaña 1: 🔓 Desbloquear

Permite:
- Seleccionar un PDF protegido
- Ver información de seguridad y permisos
- Ingresar contraseña para desbloquear
- Abrir el PDF directamente en el visor
- Guardar una copia desbloqueada

#### Pestaña 2: 🔒 Proteger

Permite:
- Seleccionar un PDF sin protección
- Elegir nivel de protección (presets)
- Ingresar contraseña de usuario
- Ingresar contraseña de propietario (opcional)
- Configurar permisos individuales (expandible)
- Crear copia protegida

#### Interfaz

```
┌──────────────────────────────────────┐
│ 🔐 Gestión de Seguridad de PDFs      │
├──────────────────────────────────────┤
│  [🔓 Desbloquear]  [🔒 Proteger]     │
│                                       │
│ Pestaña: Desbloquear                 │
│ ─────────────────────────────         │
│ [Seleccionar PDF Protegido]          │
│                                       │
│ 📄 Archivo: documento.pdf 🔒         │
│ 🔒 Protegido por contraseña          │
│ Método: AES                    PDF

1. Usuario hace clic en "🔐 Seguridad" en navbar
2. Va a pestaña "🔓 Desbloquear"
3. Selecciona un PDF protegido
4. La aplicación muestra información de seguridad y permisos
5. Usuario ingresa la contraseña
6. Al hacer clic "Desbloquear y Abrir", se abre en el visor

### Flujo 2: Guardar PDF Sin Protección

1. Selecciona PDF protegido o sin protección
2. Si protegido, ingresa contraseña
3. Hace clic en "Guardar Desbloqueado"
4. Se guarda copia: `{nombre}_desbloqueado.pdf`

### Flujo 3: Crear PDF Protegido ✨

1. Usuario hace clic en "🔐 Seguridad" en navbar
2. Va a pestaña "🔒 Proteger"
3. Selecciona un PDF sin protección
4. Ingresa contraseña de usuario (requerida)
5. Ingresa contraseña de propietario (opcional)
6. Elige nivel de protección:
   - **Sin restricciones**: Acceso completo
   - **Solo lectura**: No puede modificar
   - **Solo impresión**: Sin copia
   - **Impresión y lectura**: Permisos limitados
   - **Muy restrictivo**: Solo visualización
7. Opcionalmente, personaliza permisos individuales
8. Hace clic "Crear PDF Protegido"
9. Se guarda copia: `{nombre}_protegido.pdf`

### Flujo 4: Cambiar Permisos Existentes (Programático)

```python
PDFSecurityManager.change_pdf_permissions(
    "documento_protegido.pdf",
    "documento_nuevos_perms.pdf",
    current_owner_password="adminpass",
    new_user_password="newpass123",
    permissions=PDFSecurityManager.PDF_PERM_PRINT
)
``
│ 📄 Archivo: documento.pdf            │
│                                       │
│ Contraseñas:                         │
│ [Contraseña de usuario]              │
│ [Contraseña de propietario]          │
│                                       │
│ Nivel de protección:                 │
│ [Solo lectura ▼]                     │
│                                       │
│ [Permisos personalizados ▼]          │
│   ☐ Permitir impresión               │
│   ☐ Permitir modificación            │
│   ☐ Permitir copia de contenido      │
│   ...                                │
│                                       │
│ [Crear PDF Protegido]                │
│ ✓ PDF protegido creado: doc_pro...  │
└PDF directamente en el visor
- Guardar una copia desbloqueada

#### Interfaz

```
┌────────────────────────────────────────────────┐
│ Gestión de Seguridad de PDFs                   │
├────────────────────────────────────────────────┤
│ [Seleccionar PDF Protegido]                    │
│                                                 │
│ 📄 Archivo: documento.pdf 🔒 (Protegido)       │
│                                                 │
│ 🔒 Protegido por contraseña                    │
│ Método de cifrado: AES                         │
│ Permisos:                                       │
│   ✓ Impresión permitida                        │
│   ✗ Copia de contenido bloqueada               │
│   ✗ Modificación bloqueada                     │
│   ✓ Anotaciones permitidas                     │
│                                                 │
│ [Contraseña] [Desbloquear y Abrir]             │
│              [Guardar Desbloqueado]            │
│                                                 │
│ ✓ PDF desbloqueado exitosamente                │
└────────────────────────────────────────────────┘
```

## Flujo de Uso

### Flujo 1: Desbloquear y Abrir PDF

1. Usuario hace clic en "🔐 Seguridad" en navbar
2. Va a pestaña "🔓 Desbloquear"
3. Selecciona un PDF protegido
4. La aplicación muestra información de seguridad y permisos
5. Usuario ingresa la contraseña
6. Al hacer clic "Desbloquear y Abrir", se abre en el visor

### Flujo 2: Guardar PDF Sin Protección

1. Selecciona PDF protegido o sin protección
2. Si protegido, ingresa contraseña
3. Hace clic en "Guardar Desbloqueado"
4. Se guarda copia: `{nombre}_desbloqueado.pdf`

### Flujo 3: Crear PDF Protegido ✨

1. Usuario hace clic en "🔐 Seguridad" en navbar
2. Va a pestaña "🔒 Proteger"
3. Selecciona un PDF sin protección
4. Ingresa contraseña de usuario (requerida)
5. Ingresa contraseña de propietario (opcional)
6. Elige nivel de protección:
   - **Sin restricciones**: Acceso completo
   - **Solo lectura**: No puede modificar
   - **Solo impresión**: Sin copia
   - **Impresión y lectura**: Permisos limitados
   - **Muy restrictivo**: Solo visualización
7. Opcionalmente, personaliza permisos individuales
8. Hace clic "Crear PDF Protegido"
9. Se guarda copia: `{nombre}_protegido.pdf`

### Flujo 4: Cambiar Permisos Existentes (Programático)

```python
PDFSecurityManager.change_pdf_permissions(
    "documento_protegido.pdf",
    "documento_nuevos_perms.pdf",
    current_owner_password="adminpass",
    new_user_password="newpass123",
    permissions=PDFSecurityManager.PDF_PERM_PRINT
)
```

## Integración con Aplicación Principal

### Cambios en `main.py`

1. **Importación**: Se importa `PDFSecurityTab` del módulo
2. **Variable**: Se añade `security_tab` al estado global
3. **Funciones**: Se añaden `_open_security()` y `_close_security_tab()`
4. **Callback**: `_on_pdf_unlocked()` abre el PDF desbloqueado en el visor
5. **Botón Navbar**: Se añade botón "🔐 Seguridad" entre Combinar y Configuración

## Manejo de Errores

La aplicación maneja los siguientes errores:

- **Contraseña incorrecta**: Mensaje "❌ Contraseña incorrecta"
- **PDF no legible**: Se muestra excepción
- **Archivo no seleccionado**: Se solicita seleccionar primero
- **Contraseña vacía**: Se valida entrada

## Permisos Soportados

El módulo detecta y muestra estos permisos PDF:

| Permiso | Descripción |
|---------|-------------|
| `PDF_PERM_PRINT` | Permite impresión |
| `PDF_PERM_MODIFY` | Permite modificación del contenido |
| `PDF_PERM_COPY` | Permite copia de contenido |
| `PDF_PERM_ANNOTATE` | Permite anotaciones |
| `PDF_PERM_FORMS` | Permite llenar formularios |
| `PDF_PERM_ASSEMBLY` | Permite ensamblaje de páginas |
| `PDF_PERM_PRINT_HQ` | Permite impresión de alta calidad |

## Ejemplos de Uso

### Uso Programático

```python
from pdf_security import PDFSecurityManager

# ─── Verificar si PDF está protegido ───
if PDFSecurityManager.is_protected("documento.pdf"):
    print("PDF está protegido")

# ─── Obtener información de seguridad ───
info = PDFSecurityManager.get_security_info("documento.pdf")
print(f"Cifrado: {info.is_encrypted}")
print(f"Permisos: {info.get_permissions_text()}")

# ─── Desbloquear PDF ───
doc = PDFSecurityManager.unlock_pdf("documento.pdf", "contraseña123")
if doc:
    print("PDF desbloqueado exitosamente")
    doc.close()

# ─── Desbloquear y guardar sin protección ───
PDFSecurityManager.unlock_pdf_to_file(
    "documento.pdf",
    "contraseña123",
    "documento_desbloqueado.pdf"
)

# ─── CREAR PDF PROTEGIDO ✨ ───
# Opción 1: Usar presets
PDFSecurityManager.protect_pdf_with_permissions(
    "documento.pdf",
    "documento_protegido.pdf",
    user_password="contraseña123",
    owner_password="adminpass",
    allow_print=True,
    allow_copy=False,
    allow_modify=False,
    allow_annotate=False
)

# Opción 2: Usar presets disponibles
presets = PDFSecurityManager.get_default_permissions()
print(presets)  # Muestra: solo_lectura, sin_restricciones, etc.

# ─── Cambiar permisos de PDF protegido ───
PDFSecurityManager.change_pdf_permissions(
    "documento_viejo.pdf",
    "documento_nuevo.pdf",
    current_owner_password="adminpass",
    new_user_password="nuevapass",
    permissions=PDFSecurityManager.PDF_PERM_PRINT | 
               PDFSecurityManager.PDF_PERM_COPY
)

# ─── Remover protección ───
PDFSecurityManager.remove_protection(
    "documento_protegido.pdf",
    "documento_sin_proteccion.pdf",
    owner_password="adminpass"
)
```

### Uso en UI

```python
from pdf_security import PDFSecurityTab

# Crear pestaña de seguridad
def on_pdf_unlocked(path, password):
    print(f"PDF desbloqueado: {path}")

security_tab = PDFSecurityTab(page, on_pdf_unlocked)
```

## Notas de Seguridad

- Las contraseñas se procesan en memoria y no se almacenan
- Los PDFs desbloqueados se guardan solo en la ubicación especificada por el usuario
- No se recopilan ni transmiten datos de contraseñas
- La validación usa PyMuPDF (fitz) que implementa estándares PDF

## Dependencias

- `pymupdf>=1.26.5`: Manejo de PDF y operaciones de cifrado
- `flet[all]==0.28.3`: Framework UI

## Limitaciones Actuales

1. No soporta PDFs con certificados digitales especiales
2. Solo soporta contraseñas de usuario básicas
3. No muestra detalles específicos del algoritmo AES
4. La exportación sin protección puede no preservar algunos metadatos avanzados
5. No hay GUI para cambiar permisos de PDFs ya protegidos (solo API)

## Futuras Mejoras

- [ ] GUI para cambiar permisos de PDFs existentes
- [ ] Soporte para múltiples contraseñas
- [ ] Batch processing de múltiples PDFs
- [ ] Historial de PDFs desbloqueados/protegidos
- [ ] Integración con gestor de contraseñas
- [ ] Opción de desbloqueo sin guardar (solo lectura temporal)
- [ ] Exportación de información de seguridad (reporte PDF)
- [ ] Soporte para certificados digitales
