// Campos de formulario del visor, con el complemento de formularios de EmbedPDF (plugin-form).
//
// Los campos se rellenan en la página (sus dibujantes en PdfPages.svelte); con el puntero o una
// herramienta de formulario se desbloquean y la capa de anotaciones los selecciona, mueve y
// redimensiona como a las demás anotaciones (canvas.ts, FORM_DESIGN). Cada campo nuevo lleva un
// nombre único que le pone el complemento («TextField_1a2b3c4d»): en un PDF los campos con el mismo
// nombre son el mismo campo (comparten el valor). Aquí:
//   · las propiedades de un campo (FieldDialog.svelte): nombre, obligatorio, solo lectura, varias
//     líneas y las opciones de las listas (`editField`). Cambiar el nombre al de otro campo del mismo
//     tipo los une (así se agrupan los botones de opción).
import {
  PDF_FORM_FIELD_FLAG as F, PDF_FORM_FIELD_TYPE as K, type PdfWidgetAnnoField, type PdfWidgetAnnoObject,
} from '@embedpdf/models';
import type { FormScope } from '@embedpdf/plugin-form';
import { confirmDialog, openModal, toast } from '$lib/ui.ts';
import { t } from '$texts';
import FieldDialog from './FieldDialog.svelte';

const TX = t.viewer.forms;

/** Lo que se edita de un campo en FieldDialog.svelte. */
export interface FieldProps {
  name: string;
  required: boolean;
  readOnly: boolean;
  multiline: boolean; // solo el de texto
  options: string[] | null; // solo las listas
}

/** Lo que hace falta para cambiar un campo: el de las anotaciones (deshacer) y el de formularios (nombre). */
export interface FieldHost {
  update(items: PdfWidgetAnnoObject[], change: () => Record<string, unknown>): void;
  commit(): Promise<void>;
  form(): FormScope | null;
}

const hasOptions = (field: PdfWidgetAnnoField) => field.type === K.COMBOBOX || field.type === K.LISTBOX;

/** Las propiedades de `widget` para el diálogo. */
export function fieldProps(widget: PdfWidgetAnnoObject): FieldProps {
  const { field } = widget;
  return {
    name: field.name,
    required: Boolean(field.flag & F.REQUIRED),
    readOnly: Boolean(field.flag & F.READONLY),
    multiline: Boolean(field.flag & F.TEXT_MULTIPLINE),
    options: hasOptions(field) ? (field as { options: { label: string }[] }).options.map((option) => option.label) : null,
  };
}

/** El campo de `widget` con `props` (sin el nombre, que se cambia aparte), o null si no cambia. */
export function fieldPatch(widget: PdfWidgetAnnoObject, props: FieldProps): PdfWidgetAnnoField | null {
  const { field } = widget;
  const before = fieldProps(widget);
  let flag = field.flag & ~(F.REQUIRED | F.READONLY);
  if (props.required) flag |= F.REQUIRED;
  if (props.readOnly) flag |= F.READONLY;
  if (field.type === K.TEXTFIELD) flag = (flag & ~F.TEXT_MULTIPLINE) | (props.multiline ? F.TEXT_MULTIPLINE : 0);
  const sameOptions = JSON.stringify(props.options) === JSON.stringify(before.options);
  if (flag === field.flag && sameOptions) return null;
  const patched = { ...field, flag } as PdfWidgetAnnoField;
  if (props.options && !sameOptions) {
    // Si el valor elegido ya no está entre las opciones, queda sin elegir.
    const value = props.options.includes(field.value) ? field.value : '';
    Object.assign(patched, { value, options: props.options.map((label) => ({ label, isSelected: label === value })) });
  }
  return patched;
}

/** Abre las propiedades de `widget` y aplica lo que se cambie. */
export async function editField(host: FieldHost, widget: PdfWidgetAnnoObject): Promise<void> {
  const props = await openModal<FieldProps>(FieldDialog, { props: fieldProps(widget), kind: widget.field.type });
  if (!props) return;
  const field = fieldPatch(widget, props);
  if (field) {
    host.update([widget], () => ({ field })); // se deshace como cualquier cambio de una anotación
    await host.commit();
  }
  if (props.name !== widget.field.name) await rename(host, widget, props.name);
}

/** Cambia el nombre de `widget`; si es el de otro campo del mismo tipo, pregunta si unirlos. */
async function rename(host: FieldHost, widget: PdfWidgetAnnoObject, name: string): Promise<void> {
  const form = host.form();
  if (!form) return;
  try {
    const result = await form.renameField(widget.id, name).toPromise();
    if (result.outcome !== 'conflict') return;
    if (await confirmDialog(TX.joinTitle, TX.join(result.fieldName), TX.joinButton)) {
      await form.shareField(widget.id, result.targetAnnotationId).toPromise();
    }
  } catch {
    toast(TX.renameFailed, 'warning');
  }
}
