// Menú «Sellos» (equivale a _fill_stamps_menu en Qt). Las leyendas se guardan con el
// servicio `legends`, el mismo almacén que Qt; el gestor es LegendsDialog.svelte.
// `insert({ text, color, font_size })` coloca el sello en el visor.
import { call } from '$lib/api.ts';
import { openMenu, type MenuItem } from '$lib/menu.svelte.ts';
import { openModal, toast } from '$lib/ui.ts';
import { t } from '$texts';
import LegendsDialog from './LegendsDialog.svelte';

export const DEFAULT_COLOR = '#D32F2F';
export const DEFAULT_SIZE = 13;

/** Lo que se coloca en la página: texto, color y tamaño de letra. */
export interface Stamp {
  text: string;
  color: string;
  font_size: number;
}

/** Leyenda guardada (servicio `legends`). */
export interface Legend extends Stamp {
  id: string;
  name: string;
}

type Insert = (stamp: Stamp) => void;

/** Gestor de leyendas: lista, crear, eliminar e insertar (LegendsManagerDialog). */
export async function openLegendsManager(insert: Insert): Promise<void> {
  const stamp = await openModal<Stamp>(LegendsDialog);
  if (stamp) insert(stamp);
}

/** Abre el menú de sellos bajo `anchor` (se rellena al abrirse, como en Qt). */
export async function openStampsMenu(anchor: Element, insert: Insert): Promise<void> {
  let menu: { stamps: { text: string; color: string }[]; favorites: Legend[] };
  try {
    menu = await call('legends.menu');
  } catch (err) {
    toast((err as Error).message, 'danger');
    return;
  }
  const items: MenuItem[] = menu.stamps.map(({ text, color }) => ({
    label: text, icon: 'tag', onSelect: () => insert({ text, color, font_size: DEFAULT_SIZE }),
  }));
  if (menu.favorites.length) {
    items.push('separator', ...menu.favorites.map((legend) => ({
      label: legend.name, icon: 'star',
      onSelect: () => {
        call('legends.used', legend.id).catch(() => {});
        insert(legend);
      },
    })));
  }
  items.push('separator', { label: t.viewer.annotations.stamps.manage, icon: 'settings', onSelect: () => openLegendsManager(insert) });
  openMenu(anchor, items);
}
