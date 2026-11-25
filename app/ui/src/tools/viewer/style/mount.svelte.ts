// Los botones de estilo (StyleButtons.svelte) dentro de la barra de la selección, que se escribe
// a mano (editing.ts): se montan una vez y `set` cambia lo que muestran.
import { mount, unmount } from 'svelte';
import type { ToolStyle } from '../annotations/styles.svelte.ts';
import StyleButtons from './StyleButtons.svelte';

export interface MountedStyleButtons {
  set(style: Partial<ToolStyle> | null, colorTitle?: string): void;
  destroy(): void;
}

export function mountStyleButtons(target: HTMLElement, onChange: (patch: Partial<ToolStyle>) => void): MountedStyleButtons {
  const props = $state<{ style: Partial<ToolStyle> | null; colorTitle?: string; onChange: typeof onChange }>({ style: null, onChange });
  const app = mount(StyleButtons, { target, props });
  return {
    set(style, colorTitle) {
      props.style = style;
      props.colorTitle = colorTitle;
    },
    destroy: () => void unmount(app),
  };
}
