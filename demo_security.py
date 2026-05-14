#!/usr/bin/env python3
"""
Demo script para probar el módulo pdf_security.
Muestra cómo usar PDFSecurityManager programáticamente.
"""

from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from pdf_security import PDFSecurityManager, PDFSecurityInfo


def demo_security_info() -> None:
    """Demostración: Obtener información de seguridad."""
    print("\n" + "="*60)
    print("DEMO 1: Obtener Información de Seguridad")
    print("="*60)
    
    # Crear un PDF de prueba (aquí asumimos uno existente)
    test_pdf = Path("pdf_destino/test.pdf")
    
    if not test_pdf.exists():
        print(f"⚠️  No encontrado: {test_pdf}")
        print("Para este demo, necesitas un PDF en esa ubicación.\n")
        return
    
    try:
        info = PDFSecurityManager.get_security_info(str(test_pdf))
        
        print(f"📄 Archivo: {test_pdf.name}")
        print(f"🔐 Protegido: {'Sí' if info.is_protected else 'No'}")
        print(f"🔒 Cifrado: {'Sí' if info.is_encrypted else 'No'}")
        print(f"📋 Método: {info.encryption_method}")
        print(f"\n📖 Permisos:")
        for perm in info.get_permissions_text():
            print(f"   {perm}")
            
    except Exception as e:
        print(f"❌ Error: {e}")


def demo_is_protected() -> None:
    """Demostración: Verificar si PDF está protegido."""
    print("\n" + "="*60)
    print("DEMO 2: Verificar si PDF está Protegido")
    print("="*60)
    
    test_files = [
        "pdf_destino/test.pdf",
        "README.md",  # Archivo no-PDF para prueba de error
    ]
    
    for filepath in test_files:
        if not Path(filepath).exists():
            print(f"⏭️  Saltando {filepath} (no existe)\n")
            continue
        
        try:
            is_protected = PDFSecurityManager.is_protected(filepath)
            status = "🔒 Protegido" if is_protected else "🔓 Sin protección"
            print(f"📄 {filepath}: {status}")
        except Exception as e:
            print(f"📄 {filepath}: ❌ Error: {type(e).__name__}")
        
        print()


def demo_unlock_flow() -> None:
    """Demostración: Flujo de desbloqueo."""
    print("\n" + "="*60)
    print("DEMO 3: Flujo de Desbloqueo")
    print("="*60)
    
    print("Este demo muestra el flujo de desbloqueo:")
    print()
    print("1. Seleccionar PDF protegido")
    print("   → Usar PDFSecurityManager.is_protected(path)")
    print()
    print("2. Obtener información de seguridad")
    print("   → Usar PDFSecurityManager.get_security_info(path)")
    print()
    print("3. Solicitar contraseña al usuario")
    print("   → En UI: password_field.value")
    print()
    print("4. Intentar desbloqueo")
    print("   → doc = PDFSecurityManager.unlock_pdf(path, password)")
    print("   → if doc is None: mostrar error 'Contraseña incorrecta'")
    print()
    print("5. Opciones:")
    print("   a) Abrir en visor: call on_pdf_unlocked(path, password)")
    print("   b) Guardar copia: PDFSecurityManager.unlock_pdf_to_file(...)")
    print()


def demo_class_info() -> None:
    """Mostrar estructura de clases."""
    print("\n" + "="*60)
    print("INFO: Estructura de Clases")
    print("="*60)
    
    print("\n📦 PDFSecurityInfo (dataclass)")
    print("   Atributos:")
    print("   - is_protected: bool")
    print("   - is_encrypted: bool")
    print("   - permissions: int")
    print("   - has_user_password: bool")
    print("   - has_owner_password: bool")
    print("   - encryption_method: str")
    print("   Métodos:")
    print("   - get_permissions_text() -> list[str]")
    
    print("\n📦 PDFSecurityManager (clase estática)")
    print("   Métodos:")
    print("   - get_security_info(path: str) -> PDFSecurityInfo")
    print("   - is_protected(path: str) -> bool")
    print("   - unlock_pdf(path: str, password: str) -> Optional[fitz.Document]")
    print("   - unlock_pdf_to_file(path: str, password: str, output: str) -> bool")
    print("   - check_permissions(path: str, password: Optional[str]) -> PDFSecurityInfo")
    
    print("\n📦 PDFSecurityTab (UI)")
    print("   Integrada en: navbar -> botón '🔐 Seguridad'")
    print("   Funcionalidades:")
    print("   - Seleccionar PDF protegido")
    print("   - Mostrar información de seguridad")
    print("   - Ingresar contraseña")
    print("   - Desbloquear y abrir o guardar copia")


def main() -> None:
    """Ejecutar demostraciones."""
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*10 + "DEMOSTRACIÓN: Módulo pdf_security" + " "*14 + "║")
    print("╚" + "="*58 + "╝")
    
    demo_class_info()
    demo_security_info()
    demo_is_protected()
    demo_unlock_flow()
    
    print("\n" + "="*60)
    print("ℹ️  Para usar en la aplicación:")
    print("   1. Ejecutar: uv run flet run")
    print("   2. Hacer clic en botón '🔐 Seguridad' en navbar")
    print("   3. Seleccionar PDF protegido")
    print("   4. Ingresar contraseña para desbloquear")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
