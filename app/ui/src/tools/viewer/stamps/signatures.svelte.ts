// Firmas de EmbedPDF (plugin-signature): la firma y, si se quiere, las iniciales, dibujadas,
// escritas o desde una imagen (SignatureDialog.svelte). Se colocan como los sellos: clic en la
// firma y clic en la página. Es una firma visual (trazo o imagen), sin certificado.
//
// El usuario decide qué firmas se guardan en este equipo para reutilizarlas (servicio
// `stamps`, en el formato de serializeEntries); las demás duran mientras la app esté abierta.
import {
  deserializeEntries, serializeEntries, type SerializedSignatureEntry, type SignatureCapability,
  type SignatureEntry, type SignaturePlugin,
} from '@embedpdf/plugin-signature';
import { call } from '$lib/api.ts';
import { registry } from '../canvas/embed.ts';

class Signatures {
  entries = $state.raw<SignatureEntry[]>([]);
  kept = $state.raw<ReadonlySet<string>>(new Set()); // ids de las firmas guardadas en el equipo
  #ready: Promise<SignatureCapability> | null = null;

  /** El complemento, con las firmas guardadas ya cargadas. */
  ready(): Promise<SignatureCapability> {
    this.#ready ??= (async () => {
      const signatures = (await registry()).getPlugin<SignaturePlugin>('signature')!.provides();
      const saved = await call<SerializedSignatureEntry[]>('stamps.signatures').catch(() => []);
      signatures.onEntriesChange((entries) => (this.entries = entries));
      signatures.loadEntries(deserializeEntries(saved));
      this.kept = new Set(saved.map((entry) => entry.id));
      this.entries = signatures.getEntries();
      return signatures;
    })();
    return this.#ready;
  }

  /** Añade una firma; con `keep`, se guarda en el equipo. Devuelve su id. */
  async add(entry: Omit<SignatureEntry, 'id' | 'createdAt'>, keep: boolean): Promise<string> {
    const id = (await this.ready()).addEntry(entry);
    if (keep) await this.keep(id, true);
    return id;
  }

  async remove(id: string): Promise<void> {
    (await this.ready()).removeEntry(id);
    if (this.kept.has(id)) await this.keep(id, false);
  }

  /** Guarda la firma en el equipo para reutilizarla (o deja de guardarla). */
  async keep(id: string, keep: boolean): Promise<void> {
    const kept = new Set(this.kept);
    if (keep) kept.add(id);
    else kept.delete(id);
    this.kept = kept;
    const entries = (await this.ready()).exportEntries().filter((entry) => kept.has(entry.id));
    await call('stamps.save_signatures', serializeEntries(entries));
  }

  /** El siguiente clic en una página de `documentId` coloca la firma (o sus iniciales). */
  async place(documentId: string, id: string, initials = false): Promise<void> {
    const scope = (await this.ready()).forDocument(documentId);
    if (initials) scope.activateInitialsPlacement(id);
    else scope.activateSignaturePlacement(id);
  }
}

export const signatures = new Signatures();
