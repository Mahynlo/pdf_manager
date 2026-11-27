// Formularios del visor, con el complemento de formularios de EmbedPDF (plugin-form).
//
// Los campos se rellenan en la página (sus dibujantes en PdfPages.svelte). En «Editar campos» (el
// puntero) y con las herramientas de crear, se desbloquean y la capa de anotaciones los selecciona,
// mueve y redimensiona como a las demás anotaciones (canvas.ts, FORM_DESIGN). La barra «Formularios»
// (toolbars/FormsBar.svelte) y su panel (FormsPanel.svelte) usan `FormFields`:
//   · la lista de campos del documento, ir a uno y pasar al anterior o al siguiente;
//   · las propiedades de un campo (FieldProperties.svelte), como en los editores de formularios:
//     nombre, obligatorio, solo lectura y no exportar; en el de texto, longitud máxima, varias líneas,
//     contraseña y un carácter por casilla; en las listas, sus opciones, selección múltiple (lista) o
//     permitir escribir (desplegable); en los botones de opción, los botones del grupo (añadir uno,
//     duplicar el grupo) y que los del mismo valor se activen a la vez; y su estilo. Cambiar el nombre
//     al de otro campo del mismo tipo los une (así se agrupan los botones de opción);
//   · los datos: exportarlos a un .json (sin los marcados «No exportar»), importarlos y vaciar el formulario.
// Y `nameNewFields`: cada campo nuevo nace con un nombre legible y libre («Texto 1», «Texto 2»…). En un PDF los campos con el mismo nombre son el
// mismo campo (comparten el valor). Los nombres van sin tildes ni otros caracteres fuera de ASCII
// (`fieldName`): el motor de EmbedPDF 2.15.1 los guarda mal («Opción» quedaba «OpciÃ³n» en el PDF) y
// entonces no se reconocen al unir campos.
//
// Lo que el motor 2.15.1 no permite (no llega al diccionario del campo cuando va aparte del widget, como
// en los que crea): la información sobre herramientas (/TU), el valor predeterminado (/DV) y el valor de
// exportación de cada opción. Los botones de opción toman como valor el id de su anotación (el motor no
// usa otro). Tampoco quitar /MaxLen (`NO_LIMIT`) ni desactivar «mantener uno activado» en los botones de
// opción (lo pone siempre).
import {
  PDF_FORM_FIELD_FLAG as F, PDF_FORM_FIELD_TYPE as K, PdfAnnotationSubtype, uuidV4,
  type PdfAnnotationObject, type PdfWidgetAnnoField, type PdfWidgetAnnoObject, type Rect,
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
// Los que EmbedPDF 2.15.1 actualiza; los demás (botones de acción, firmas) los cambia el motor de la app.
const UPDATABLE = new Set([K.TEXTFIELD, K.CHECKBOX, K.RADIOBUTTON, K.COMBOBOX, K.LISTBOX]);

/** Los indicadores del campo (/Ff) que se cambian en el panel. */
export const FLAGS = {
  required: F.REQUIRED,
  readOnly: F.READONLY,
  noExport: F.NOEXPORT,
  multiline: F.TEXT_MULTIPLINE,
  password: F.TEXT_PASSWORD,
  comb: F.TEXT_COMB, // un carácter por casilla: necesita longitud máxima; sin varias líneas ni contraseña
  multiSelect: F.CHOICE_MULTL_SELECT,
  edit: F.CHOICE_EDIT, // desplegable en el que se puede escribir
  unison: F.BUTTON_RADIOSINUNISON, // los botones con el mismo valor se activan a la vez
  keepOne: F.BUTTON_NOTOGGLETOOFF,
} as const;
export type FlagName = keyof typeof FLAGS;

/**
 * «Sin límite» de longitud. El motor no puede quitar /MaxLen una vez puesta, y con 0 el campo no deja
 * escribir: se guarda este máximo, que el panel muestra como sin límite.
 */
export const NO_LIMIT = 32767;
const BUTTON_GAP = 8; // puntos entre los botones de opción que se añaden

/** Un campo del documento (los widgets con el mismo nombre son el mismo campo). */
export interface FieldEntry {
  name: string;
  type: K;
  value: string;
  required: boolean;
  readOnly: boolean;
  noExport: boolean;
  widgets: PdfWidgetAnnoObject[]; // en el orden de las páginas
}

const isWidget = (object: PdfAnnotationObject): object is PdfWidgetAnnoObject => object.type === PdfAnnotationSubtype.WIDGET;
export const hasOptions = (field: PdfWidgetAnnoField) => field.type === K.COMBOBOX || field.type === K.LISTBOX;
export const hasText = (field: PdfWidgetAnnoField) => TEXT_KINDS.has(field.type);
export const hasFlag = (widget: PdfWidgetAnnoObject, name: FlagName) => Boolean(widget.field.flag & FLAGS[name]);
export const optionsOf = (field: PdfWidgetAnnoField): string[] =>
  hasOptions(field) ? (field as { options: { label: string }[] }).options.map((option) => option.label) : [];
/** La longitud máxima del campo de texto, o null si no tiene (o es `NO_LIMIT`). */
export const maxLenOf = (widget: PdfWidgetAnnoObject): number | null => {
  const max = (widget.field as { maxLen?: number }).maxLen;
  return max && max > 0 && max < NO_LIMIT ? Math.round(max) : null;
};
/** El valor que toma el campo cuando se marca este botón (casilla u opción). */
export const exportValueOf = (widget: PdfWidgetAnnoObject): string => (widget as { exportValue?: string }).exportValue ?? '';

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
      noExport: Boolean(field.flag & F.NOEXPORT),
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
export function freeName(taken: Iterable<string>, base: string, separator = ' '): string {
  const names = new Set(taken);
  let n = 1;
  while (names.has(`${base}${separator}${n}`)) n++;
  return `${base}${separator}${n}`;
}

/** Los indicadores `flag` con `name` puesto o quitado, y lo que no puede ir con él. */
export function withFlag(flag: number, name: FlagName, on: boolean): number {
  let next = on ? flag | FLAGS[name] : flag & ~FLAGS[name];
  // Un carácter por casilla no va con varias líneas ni con contraseña (PDF 32000, 12.7.4.3).
  if (on && name === 'comb') next &= ~(F.TEXT_MULTIPLINE | F.TEXT_PASSWORD);
  if (on && (name === 'multiline' || name === 'password')) next &= ~F.TEXT_COMB;
  return next;
}

/** El campo con las opciones `labels`; si el valor elegido ya no está entre ellas, queda sin elegir. */
export function withOptions(field: PdfWidgetAnnoField, labels: string[]): PdfWidgetAnnoField {
  const value = labels.includes(field.value) ? field.value : '';
  return { ...field, value, options: labels.map((label) => ({ label, isSelected: label === value })) } as PdfWidgetAnnoField;
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

/** Los valores que se exportan (nombre → valor): los campos con valor, salvo los marcados «No exportar». */
export function exportableValues(entries: FieldEntry[]): Record<string, string> {
  return Object.fromEntries(entries.filter((entry) => VALUED.has(entry.type) && !entry.noExport).map((entry) => [entry.name, entry.value]));
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
 * Cada campo nuevo nace con un nombre legible y libre en su documento («Texto 1»; plugin-form le pone
 * `TextField_1a2b3c4d`): se envuelve lo que crea cada herramienta de formulario. Se llama una vez, con el registro listo; el documento es el activo
 * (canvas.ts lo activa con estas herramientas).
 */
export function nameNewFields(registry: PluginRegistry): void {
  const annotation = registry.getPlugin<AnnotationPlugin>('annotation')!.provides();
  const documents = registry.getPlugin<DocumentManagerPlugin>('document-manager')!.provides();
  const named = (object: PdfWidgetAnnoObject, toolId: string): PdfWidgetAnnoObject => {
    const id = documents.getActiveDocumentId();
    const existing = id ? widgets(annotation.forDocument(id)) : [];
    const name = freeName(existing.map((widget) => widget.field.name), fieldName(NEW_NAMES[toolId]));
    return { ...object, field: { ...object.field, name, alternateName: name } };
  };
  for (const tool of annotation.getTools() as AnnotationTool<PdfWidgetAnnoObject>[]) {
    const factory = tool.pointerHandler as HandlerFactory<PdfWidgetAnnoObject> | undefined;
    if (!NEW_NAMES[tool.id] || !factory) continue;
    annotation.addTool({
      ...tool,
      pointerHandler: {
        ...factory,
        create: (context: HandlerContext<PdfWidgetAnnoObject>) =>
          factory.create({ ...context, onCommit: (object, extra) => context.onCommit(named(object, tool.id), extra) }),
      },
    } as AnnotationTool);
  }
}

/** Lo que el modelo necesita de las anotaciones del visor (annotations.ts). */
export interface FieldsHost {
  scope(): AnnotationScope | null;
  form(): FormScope | null;
  update(items: PdfWidgetAnnoObject[], change: () => Record<string, unknown>): void;
  create(items: (Record<string, unknown> & { type: PdfAnnotationSubtype; pageIndex: number; rect: Rect })[]): PdfAnnotationObject[];
  remove(items: PdfWidgetAnnoObject[]): void;
  select(items: PdfAnnotationObject[]): void;
  commit(): Promise<void>;
  setFieldFlags(widget: PdfWidgetAnnoObject, flag: number): Promise<boolean>;
  /** Termina cuando la anotación `id`, recién creada, ya está escrita en el PDF de EmbedPDF. */
  written(id: string): Promise<void>;
  pageSize(index: number): { width: number; height: number };
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

  /** Los widgets del campo de `widget` (los botones de un grupo de opciones), en orden. */
  group(widget: PdfWidgetAnnoObject): PdfWidgetAnnoObject[] {
    return this.list().find((entry) => entry.name === widget.field.name)?.widgets ?? [widget];
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

  // ── Propiedades ──────────────────────────────────────────────────────────
  /** Cambia el campo de `widget` (lo comparten sus botones: el complemento lo pasa a todos). Se deshace. */
  private setField(widget: PdfWidgetAnnoObject, field: PdfWidgetAnnoField): void {
    this.host.update([widget], () => ({ field }));
  }

  /** Pone o quita un indicador del campo (obligatorio, solo lectura, varias líneas…). */
  async setFlag(widget: PdfWidgetAnnoObject, name: FlagName, on: boolean): Promise<void> {
    if (name === 'comb' && on && !maxLenOf(widget)) return; // sin longitud máxima no hay casillas
    const flag = withFlag(widget.field.flag, name, on);
    if (flag === widget.field.flag) return;
    if (UPDATABLE.has(widget.field.type)) this.setField(widget, { ...widget.field, flag });
    else if (!(await this.host.setFieldFlags(widget, flag))) toast(TX.flagsFailed, 'warning');
  }

  /** Longitud máxima del campo de texto (null: sin límite; entonces tampoco un carácter por casilla). */
  setMaxLen(widget: PdfWidgetAnnoObject, max: number | null): void {
    const value = max && max > 0 ? Math.min(Math.round(max), NO_LIMIT - 1) : NO_LIMIT;
    if (value === ((widget.field as { maxLen?: number }).maxLen ?? NO_LIMIT)) return;
    const flag = value === NO_LIMIT ? widget.field.flag & ~F.TEXT_COMB : widget.field.flag;
    this.setField(widget, { ...widget.field, flag, maxLen: value } as PdfWidgetAnnoField);
  }

  /** Las opciones de una lista (desplegable o de opciones). */
  setOptions(widget: PdfWidgetAnnoObject, labels: string[]): void {
    const clean = labels.map((label) => label.trim()).filter(Boolean);
    if (!clean.length) {
      toast(TX.emptyOptions, 'warning');
      return;
    }
    if (JSON.stringify(clean) !== JSON.stringify(optionsOf(widget.field))) this.setField(widget, withOptions(widget.field, clean));
  }

  /** Cambia el estilo del campo (borde, fondo, grosor del borde, tamaño de letra). */
  restyle(widget: PdfWidgetAnnoObject, patch: Record<string, unknown>): void {
    this.host.update([widget], () => patch);
  }

  remove(widget: PdfWidgetAnnoObject): void {
    this.host.remove([widget]);
  }

  /** Cambia el nombre de `widget` (sin tildes); si es el de otro campo del mismo tipo, pregunta si unirlos. */
  async rename(widget: PdfWidgetAnnoObject, text: string): Promise<void> {
    const name = fieldName(text);
    const form = this.host.form();
    if (!form || !name || name === widget.field.name) return;
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

  // ── Botones de opción ────────────────────────────────────────────────────
  /** Añade al grupo de `widget` un botón como el último, a su derecha (o debajo, si no cabe). */
  async addButton(widget: PdfWidgetAnnoObject): Promise<void> {
    const group = this.group(widget);
    const last = group.at(-1)!;
    const { width, height } = last.rect.size;
    const page = this.host.pageSize(last.pageIndex);
    let { x, y } = last.rect.origin;
    x += width + BUTTON_GAP;
    if (x + width > page.width) [x, y] = [group[0].rect.origin.x, Math.min(page.height - height, y + height + BUTTON_GAP)];
    const created = await this.joinButton({ ...last, rect: { origin: { x, y }, size: last.rect.size } }, last);
    this.host.select([created]);
  }

  /** Copia el grupo de `widget` debajo de él, como un grupo nuevo («Opcion 2»…) con sus propios valores. */
  async duplicateGroup(widget: PdfWidgetAnnoObject): Promise<void> {
    const group = this.group(widget);
    const top = Math.min(...group.map((w) => w.rect.origin.y));
    const bottom = Math.max(...group.map((w) => w.rect.origin.y + w.rect.size.height));
    const page = this.host.pageSize(group[0].pageIndex);
    const dy = Math.min(bottom - top + BUTTON_GAP * 2, page.height - bottom);
    const name = freeName(this.list().map((entry) => entry.name), fieldName(TX.types.radio));
    const moved = (w: PdfWidgetAnnoObject) => ({ ...w, rect: { origin: { x: w.rect.origin.x, y: w.rect.origin.y + dy }, size: w.rect.size } });
    const first = await this.createButton(moved(group[0]), name);
    // De uno en uno, como «Añadir botón»: unidos varios creados a la vez, el motor no encontraba alguno.
    for (const w of group.slice(1)) await this.joinButton(moved(w), first);
    this.host.select([first]);
  }

  /**
   * Crea un botón de opción como `model` (sin marcar), en un campo propio llamado `name`, y espera a
   * que esté escrito en el PDF: `commit` podía volver antes (con el guardado automático ya en marcha)
   * y unirlo a un grupo fallaba con «annotation not found».
   */
  private async createButton(model: PdfWidgetAnnoObject, name: string): Promise<PdfAnnotationObject> {
    const { fieldObjectId: _, ...field } = model.field;
    const [created] = this.host.create([{
      ...model, id: uuidV4(), field: { ...field, name, alternateName: name, value: 'Off' },
    } as unknown as Record<string, unknown> & { type: PdfAnnotationSubtype; pageIndex: number; rect: Rect }]);
    await this.host.written(created.id);
    return created;
  }

  /** Crea un botón como `model` y lo une al grupo de `target` (antes, en un campo provisional). */
  private async joinButton(model: PdfWidgetAnnoObject, target: PdfAnnotationObject): Promise<PdfAnnotationObject> {
    // Un nombre que no se repite nunca: tras unirlo, el campo provisional puede seguir en el PDF sin
    // botones, y PDFium busca los campos por nombre (con «_nuevo 1» otra vez, no encontraba el botón).
    const temporary = `_nuevo ${uuidV4().slice(0, 8)}`;
    const created = await this.createButton(model, temporary);
    await this.host.form()?.shareField(created.id, target.id).toPromise();
    return created;
  }

  // ── Datos ────────────────────────────────────────────────────────────────
  /** Guarda los valores de los campos en un .json (lo escribe Python: viewer.save_form_data). */
  async exportData(): Promise<void> {
    if (!this.host.form()) return;
    const values = exportableValues(this.list());
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
