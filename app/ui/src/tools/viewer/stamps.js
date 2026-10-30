// Menú «Sellos» (equivale a _fill_stamps_menu en Qt). Las leyendas se guardan con el
// servicio `legends`, el mismo almacén que Qt; el gestor es LegendsDialog.svelte.
// `insert({ text, color, font_size })` coloca el sello en el visor.
import { call } from '$lib/api.js';
import { openMenu } from '$lib/menu.svelte.js';
import { openModal, toast } from '$lib/ui.js';
import LegendsDialog from './LegendsDialog.svelte';

export const DEFAULT_COLOR = '#D32F2F';
export const DEFAULT_SIZE = 13;

/** Gestor de leyendas: lista, crear, eliminar e insertar (LegendsManagerDialog). */
export async function openLegendsManager(insert) {
  const stamp = await openModal(LegendsDialog);
  if (stamp) insert(stamp);
}

/** Abre el menú de sellos bajo `anchor` (se rellena al abrirse, como en Qt). */
export async function openStampsMenu(anchor, insert) {
  let menu;
  try {
    menu = await call('legends.menu');
  } catch (err) {
    toast(err.message, 'danger');
    return;
  }
  const items = menu.stamps.map(({ text, color }) => ({ label: text, icon: 'tag', onSelect: () => insert({ text, color, font_size: DEFAULT_SIZE }) }));
  if (menu.favorites.length) {
    items.push('separator', ...menu.favorites.map((legend) => ({
      label: legend.name, icon: 'star',
      onSelect: () => {
        call('legends.used', legend.id).catch(() => {});
        insert(legend);
      },
    })));
  }
  items.push('separator', { label: 'Gestionar Leyendas y Sellos...', icon: 'settings', onSelect: () => openLegendsManager(insert) });
  openMenu(anchor, items);
}
