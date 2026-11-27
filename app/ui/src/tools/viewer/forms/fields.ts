// Formularios del visor, con el complemento de formularios de EmbedPDF (plugin-form).
//
// Los campos se rellenan en la página (sus dibujantes en PdfPages.svelte). En «Editar campos» (el
// puntero) y con las herramientas de crear, se desbloquean y la capa de anotaciones los selecciona,
// mueve y redimensiona como a las demás anotaciones (canvas.ts, FORM_DESIGN). La barra «Formularios»
// (toolbars/FormsBar.svelte) y su panel (FormsPanel.svelte) usan `FormFields`:
//   · la lista de campos del documento, ir a uno y pasar al anterior o al siguiente;
//   · las propiedades de un campo: nombre, obligatorio, solo lectura, varias líneas, opciones y estilo.
//     Cambiar el nombre al de otro campo del mismo tipo los une (así se agrupan los botones de opción);
//   · los datos: exportarlos a un .json, importarlos y vaciar el formulario.
// Y `nameNewFields`: cada campo nuevo nace con un nombre legible y libre («Texto 1», «Texto 2»…). En
// un PDF los campos con el mismo nombre son el mismo campo (comparten el valor). Los nombres van sin
// tildes ni otros caracteres fuera de ASCII (`fieldName`): el motor de EmbedPDF 2.15.1 los guarda mal
// («Opción» quedaba «OpciÃ³n» en el PDF) y entonces no se reconocen al unir campos.
import {
  PDF_FORM_FIELD_FLAG as F, PDF_FORM_FIELD_TYPE as K, PdfAnnotationSubtype,
  type PdfAnnotationObject, type PdfWidgetAnnoField, type PdfWidgetAnnoObject,
} from '@embedpdf/models';
import type { PluginRegistry } from '@embedpdf/core';
import type { AnnotationPlugin, AnnotationScope, AnnotationTool, HandlerContext, HandlerFactory } from '@embedpdf/plugin-annotation';
import type { DocumentManagerPlugin } from '@embedpdf/plugin-document-manager';
import type { FormScope } from '@embedpdf/plugin-form';
import { call } from '$lib/api.ts';
import { confirmDialog, setStatus, toast } from '$lib/ui.ts';
import { t } from '$texts';

const TX = t.viewer.forms;

/** Herramienta de EmbedPDF que crea cada tipo de campo → nombre de los nuevos («Texto 1»…). */
const NEW_NAMES: Record<string, string> = {
  formTextField: TX.types.text,
  formCheckbox: TX.types.checkbox,
  formRadioButton: TX.types.radio,
  formCombobox: TX.types.combo,
  formListbox: TX.types.list,
};

/** Tipo de campo → [nombre, icono]. */
export const FIELD_KINDS: Partial<Record<K, [string, string]>> = {
  [K.TEXTFIELD]: [TX.types.text, 'text-cursor-input'],
  [K.CHECKBOX]: [TX.types.checkbox, 'square-check'],
  [K.RADIOBUTTON]: [TX.types.radio, 'circle-dot'],
  [K.COMBOBOX]: [TX.types.combo, 'square-chevron-down'],
  [K.LISTBOX]: [TX.types.list, 'list-checks'],
  [K.PUSHBUTTON]: [TX.types.button, 'pointer'],
  [K.SIGNATURE]: [TX.types.signature, 'signature'],
};
const OTHER_KIND: [string, string] = [TX.types.other, 'square'];
export const kindOf = (type: K): [string, string] => FIELD_KINDS[type] ?? OTHER_KIND;

/** Tipos que tienen valor (se exportan e importan). */
const VALUED = new Set([K.TEXTFIELD, K.CHECKBOX, K.RADIOBUTTON, K.COMBOBOX, K.LISTBOX]);
// Los que se pueden vaciar: el motor no deja una lista sin opción elegida (la conserva).
const CLEARABLE = new Set([K.TEXTFIELD, K.CHECKBOX, K.RADIOBUTTON]);
const TOGGLES = new Set([K.CHECKBOX, K.RADIOBUTTON]);
const TEXT_KINDS = new Set([K.TEXTFIELD, K.COMBOBOX, K.LISTBOX]); // con letra

/** Lo que se edita de un campo en el panel. */
export interface FieldProps {
  name: string;
  required: boolean;
  readOnly: boolean;
  multiline: boolean; // solo el de texto
  options: string[] | null; // solo las listas
}

/** Un campo del documento (los widgets con el mismo nombre son el mismo campo). */
export interface FieldEntry {
  name: string;
  type: K;
  value: string;
  required: boolean;
  readOnly: boolean;
  widgets: PdfWidgetAnnoObject[]; // en el orden de las páginas
}

const isWidget = (object: PdfAnnotationObject): object is PdfWidgetAnnoObject => object.type === PdfAnnotationSubtype.WIDGET;
export const hasOptions = (field: PdfWidgetAnnoField) => field.type === K.COMBOBOX || field.type === K.LISTBOX;
export const hasText = (field: PdfWidgetAnnoField) => TEXT_KINDS.has(field.type);

/** Los campos (widgets) del documento de `scope`, por página y de arriba abajo. */
export function widgets(scope: AnnotationScope): PdfWidgetAnnoObject[] {
  const state = scope.getState();
  return Object.keys(state.pages).map(Number).sort((a, b) => a - b).flatMap((page) =>
    (state.pages[page] ?? []).map((uid) => state.byUid[uid]?.object).filter((o): o is PdfWidgetAnnoObject => Boolean(o) && isWidget(o!))
      .sort((a, b) => a.rect.origin.y - b.rect.origin.y || a.rect.origin.x - b.rect.origin.x));
}

/** Los campos de `list` (widgets) agrupados por nombre, en el orden en que aparecen. */
export function groupFields(list: PdfWidgetAnnoObject[]): FieldEntry[] {
  const byName = new Map<string, FieldEntry>();
  for (const widget of list) {
    const { field } = widget;
    const entry = byName.get(field.name);
    if (entry) {
      entry.widgets.push(widget);
      if (TOGGLES.has(field.type) && field.value !== 'Off') entry.value = field.value;
      continue;
    }
    byName.set(field.name, {
      name: field.name, type: field.type, value: field.value ?? '', widgets: [widget],
      required: Boolean(field.flag & F.REQUIRED), readOnly: Boolean(field.flag & F.READONLY),
    });
  }
  return [...byName.values()];
}

/** ¿Tiene valor el campo? (una casilla o una opción sin marcar no lo tiene). */
export const isFilled = (entry: FieldEntry) => (TOGGLES.has(entry.type) ? entry.value !== 'Off' && entry.value !== '' : entry.value !== '');

/**
 * `text` como nombre de campo: sin tildes (á → a, ñ → n), sin caracteres fuera de ASCII ni puntos (en
 * un PDF el punto separa los niveles del nombre), y sin espacios de sobra.
 */
export function fieldName(text: string): string {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\x20-\x7E]|\./g, '_').replace(/\s+/g, ' ').trim();
}

/** `base` con el primer número que no use ningún nombre de `taken` («Texto 1», «Texto 2»…). */
export function freeName(taken: Iterable<string>, base: string): string {
  const names = new Set(taken);
  let n = 1;
  while (names.has(`${base} ${n}`)) n++;
  return `${base} ${n}`;
}

/** Las propiedades de `widget` para el panel. */
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

/**
 * Los valores para dejar vacío el formulario (nombre → valor), solo de los campos que tienen alguno:
 * texto, casillas y botones de opción (las listas conservan su opción: ver CLEARABLE).
 */
export function emptyValues(entries: FieldEntry[]): Record<string, string> {
  const values: Record<string, string> = {};
  for (const entry of entries) {
    if (CLEARABLE.has(entry.type) && !entry.readOnly && isFilled(entry)) values[entry.name] = TOGGLES.has(entry.type) ? 'Off' : '';
  }
  return values;
}

/**
 * Los datos de un .json importado (nombre → valor) que corresponden a campos de `entries` con
 * valor y que se pueden cambiar; los demás se cuentan en `skipped`.
 * @throws Error si no es un objeto de textos.
 */
export function importableValues(text: string, entries: FieldEntry[]): { values: Record<string, string>; skipped: number } {
  const data: unknown = JSON.parse(text);
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error(TX.data.badFile);
  const fields = new Map(entries.map((entry) => [entry.name, entry]));
  const values: Record<string, string> = {};
  let skipped = 0;
  for (const [name, value] of Object.entries(data)) {
    const entry = fields.get(name);
    if (typeof value !== 'string' || !entry || !VALUED.has(entry.type) || entry.readOnly) skipped++;
    else values[name] = value;
  }
  return { values, skipped };
}

/**
 * Cada campo nuevo nace con un nombre legible y libre en su documento («Texto 1»): se envuelve
 * lo que crea cada herramienta de formulario (plugin-form le pone `TextField_1a2b3c4d`). Se llama una
 * vez, con el registro listo; el documento es el activo (canvas.ts lo activa con estas herramientas).
 */
export function nameNewFields(registry: PluginRegistry): void {
  const annotation = registry.getPlugin<AnnotationPlugin>('annotation')!.provides();
  const documents = registry.getPlugin<DocumentManagerPlugin>('document-manager')!.provides();
  const named = (object: PdfWidgetAnnoObject, base: string): PdfWidgetAnnoObject => {
    const id = documents.getActiveDocumentId();
    const taken = id ? widgets(annotation.forDocument(id)).map((widget) => widget.field.name) : [];
    const name = freeName(taken, fieldName(base));
    return { ...object, field: { ...object.field, name, alternateName: name } };
  };
  for (const tool of annotation.getTools() as AnnotationTool<PdfWidgetAnnoObject>[]) {
    const base = NEW_NAMES[tool.id];
    const factory = tool.pointerHandler as HandlerFactory<PdfWidgetAnnoObject> | undefined;
    if (!base || !factory) continue;
    annotation.addTool({
      ...tool,
      pointerHandler: {
        ...factory,
        create: (context: HandlerContext<PdfWidgetAnnoObject>) =>
          factory.create({ ...context, onCommit: (object, extra) => context.onCommit(named(object, base), extra) }),
      },
    } as AnnotationTool);
  }
}

/** Lo que el modelo necesita de las anotaciones del visor (annotations.ts). */
export interface FieldsHost {
  scope(): AnnotationScope | null;
  form(): FormScope | null;
  update(items: PdfWidgetAnnoObject[], change: () => Record<string, unknown>): void;
  remove(items: PdfWidgetAnnoObject[]): void;
  select(items: PdfWidgetAnnoObject[]): void;
  commit(): Promise<void>;
}

/** Formularios del documento de un visor: lo que usan su barra y su panel. */
export class FormFields {
  host: FieldsHost;
  docId: number;
  /** Lleva la vista al rectángulo de un widget (canvas.scrollToRect con sus coordenadas). */
  reveal: (widget: PdfWidgetAnnoObject) => void;

  constructor(host: FieldsHost, docId: number, reveal: (widget: PdfWidgetAnnoObject) => void) {
    this.host = host;
    this.docId = docId;
    this.reveal = reveal;
  }

  /** Los campos del documento (vacío mientras no hay ninguno abierto). */
  list(): FieldEntry[] {
    const scope = this.host.scope();
    return scope ? groupFields(widgets(scope)) : [];
  }

  /** El campo `id` (widget) tal como está ahora. */
  widget(id: string): PdfWidgetAnnoObject | null {
    const object = this.host.scope()?.getAnnotationById(id)?.object;
    return object && isWidget(object) ? object : null;
  }

  /** Va al campo: en «Editar campos» lo selecciona; si no, lo deja listo para escribir. */
  goTo(widget: PdfWidgetAnnoObject, editing: boolean): void {
    this.reveal(widget);
    if (editing) this.host.select([widget]);
    else if (!(widget.field.flag & F.READONLY)) this.host.form()?.selectField(widget.id);
  }

  /** Al campo siguiente (o al anterior) del orden de tabulación del documento, para rellenarlo. */
  step(forward: boolean): void {
    const form = this.host.form();
    if (!form) return;
    if (forward) form.selectNextField();
    else form.selectPreviousField();
    const id = form.getSelectedFieldId();
    const widget = id ? this.widget(id) : null;
    if (widget) this.reveal(widget);
  }

  /** Aplica `props` al campo `widget` (el nombre aparte: puede unirlo con otro campo). */
  async apply(widget: PdfWidgetAnnoObject, props: FieldProps): Promise<void> {
    const field = fieldPatch(widget, props);
    if (field) {
      this.host.update([widget], () => ({ field })); // se deshace como cualquier cambio de una anotación
      await this.host.commit();
    }
    const name = fieldName(props.name);
    if (name && name !== widget.field.name) await this.rename(widget, name);
  }

  /** Cambia el estilo del campo (borde, fondo, grosor del borde, tamaño de letra). */
  restyle(widget: PdfWidgetAnnoObject, patch: Record<string, unknown>): void {
    this.host.update([widget], () => patch);
  }

  remove(widget: PdfWidgetAnnoObject): void {
    this.host.remove([widget]);
  }

  /** Cambia el nombre de `widget`; si es el de otro campo del mismo tipo, pregunta si unirlos. */
  async rename(widget: PdfWidgetAnnoObject, name: string): Promise<void> {
    const form = this.host.form();
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

  // ── Datos ────────────────────────────────────────────────────────────────
  /** Guarda los valores de los campos en un .json (lo escribe Python: viewer.save_form_data). */
  async exportData(): Promise<void> {
    const form = this.host.form();
    if (!form) return;
    const values = Object.fromEntries(this.list().filter((entry) => VALUED.has(entry.type)).map((entry) => [entry.name, entry.value]));
    const path = await call<string | null>('viewer.save_form_data', this.docId, JSON.stringify(values));
    if (path) setStatus(TX.data.exported(Object.keys(values).length, path.split(/[\\/]/).pop()!));
  }

  /** Rellena los campos con los valores del .json `text` (se deshacen uno a uno). */
  async importData(text: string): Promise<void> {
    const form = this.host.form();
    if (!form) return;
    let result: { values: Record<string, string>; skipped: number };
    try {
      result = importableValues(text, this.list());
    } catch {
      toast(TX.data.badFile, 'warning');
      return;
    }
    await form.setFormValues(result.values).toPromise();
    const count = Object.keys(result.values).length;
    toast(result.skipped ? TX.data.importedSkipped(count, result.skipped) : TX.data.imported(count), count ? 'success' : 'warning');
  }

  /** Deja vacíos los campos que tienen valor (salvo los de solo lectura). */
  async clear(): Promise<void> {
    const form = this.host.form();
    const values = emptyValues(this.list());
    if (!form || !Object.keys(values).length) return;
    if (!(await confirmDialog(TX.data.clearTitle, TX.data.clearConfirm(Object.keys(values).length), TX.data.clear))) return;
    await form.setFormValues(values).toPromise();
  }
}
