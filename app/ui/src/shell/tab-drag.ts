// Reordenar las pestañas arrastrándolas (TabStrip.svelte), con el ratón y con el dedo.
//
// - Ratón o lápiz: se arrastra en cuanto se mueve unos píxeles.
// - Dedo: deslizar desplaza la tira; para arrastrar hay que mantener pulsada la pestaña. Mantenerla
//   sin moverla abre su menú (como el clic derecho).
// - La pestaña sigue al puntero y las demás le hacen sitio: el orden cambia mientras se arrastra
//   (`move`). Cerca de un borde, la tira se desplaza sola. Escape la devuelve a su sitio.
//
// Las pestañas son los elementos con `data-key` dentro de la tira.

export interface TabDragHost {
  /** La tira de pestañas (se desplaza). */
  strip: HTMLElement;
  /** Si la pestaña se puede mover (Inicio, no). */
  movable(key: string): boolean;
  /** Pone la pestaña en `index` y espera a que se vea el nuevo orden. */
  move(key: string, index: number): Promise<void>;
  /** Su menú, al mantenerla pulsada con el dedo sin moverla. */
  menu(key: string, x: number, y: number): void;
  /** Empieza (`key`) o termina (`null`) un arrastre. */
  dragging(key: string | null): void;
}

const DRAG_PX = 5; // ratón: lo que hay que mover para empezar a arrastrar
const TOUCH_SLOP_PX = 10; // dedo: si se mueve más antes de tiempo, desliza la tira
const LONG_PRESS_MS = 450;
const EDGE_PX = 36; // cerca del borde, la tira se desplaza sola
const EDGE_STEP_PX = 8; // por fotograma
const CLICK_GUARD_MS = 400; // el clic que sigue a un arrastre no activa la pestaña

interface Press {
  key: string;
  el: HTMLElement;
  pointerId: number;
  touch: boolean;
  startX: number;
  startY: number;
  x: number; // puntero ahora
  y: number;
  dragging: boolean;
  moved: boolean; // se movió después de empezar a arrastrar
  grab: number; // dónde se agarró la pestaña, desde su borde izquierdo
  origin: number; // su sitio al empezar
  timer: number;
  frame: number;
}

export class TabDrag {
  private host: TabDragHost;
  private press: Press | null = null;
  private moving = false; // esperando a que se vea un cambio de orden
  private guardUntil = 0;

  constructor(host: TabDragHost) {
    this.host = host;
  }

  /** Empieza a escuchar en la tira; devuelve cómo dejar de hacerlo. */
  attach(): () => void {
    const { strip } = this.host;
    const down = (ev: PointerEvent) => this.down(ev);
    const click = (ev: MouseEvent) => {
      if (performance.now() < this.guardUntil) ev.stopPropagation();
    };
    const contextMenu = (ev: MouseEvent) => {
      // Con el dedo, mantener pulsado es arrastrar o abrir el menú: lo decide `up`.
      if (this.press?.touch || performance.now() < this.guardUntil) ev.preventDefault();
    };
    strip.addEventListener('pointerdown', down);
    strip.addEventListener('click', click, true);
    strip.addEventListener('contextmenu', contextMenu, true);
    return () => {
      this.finish();
      strip.removeEventListener('pointerdown', down);
      strip.removeEventListener('click', click, true);
      strip.removeEventListener('contextmenu', contextMenu, true);
    };
  }

  // ── Puntero ────────────────────────────────────────────────────────────
  private down(ev: PointerEvent): void {
    if (this.press || !ev.isPrimary || ev.button !== 0) return;
    const target = ev.target as HTMLElement;
    const el = target.closest<HTMLElement>('[data-key]');
    if (!el || target.closest('button') || !this.host.movable(el.dataset.key!)) return;
    const touch = ev.pointerType === 'touch';
    this.press = {
      key: el.dataset.key!, el, pointerId: ev.pointerId, touch,
      startX: ev.clientX, startY: ev.clientY, x: ev.clientX, y: ev.clientY,
      dragging: false, moved: false, grab: 0, origin: 0, frame: 0,
      timer: touch ? window.setTimeout(() => this.begin(), LONG_PRESS_MS) : 0,
    };
    window.addEventListener('pointermove', this.onMove);
    window.addEventListener('pointerup', this.onUp);
    window.addEventListener('pointercancel', this.onCancel);
    window.addEventListener('keydown', this.onKey, true);
    window.addEventListener('touchmove', this.onTouchMove, { passive: false });
  }

  private onMove = (ev: PointerEvent): void => {
    const press = this.press;
    if (!press || ev.pointerId !== press.pointerId) return;
    press.x = ev.clientX;
    press.y = ev.clientY;
    const dx = press.x - press.startX;
    const dy = press.y - press.startY;
    if (!press.dragging) {
      if (press.touch && Math.hypot(dx, dy) > TOUCH_SLOP_PX) this.finish(); // desliza la tira
      else if (!press.touch && Math.abs(dx) > DRAG_PX) this.begin();
      return;
    }
    press.moved ||= Math.abs(dx) > DRAG_PX;
    void this.follow();
  };

  private onUp = (ev: PointerEvent): void => {
    const press = this.press;
    if (!press || ev.pointerId !== press.pointerId) return;
    if (press.dragging) this.guardUntil = performance.now() + CLICK_GUARD_MS;
    if (press.touch && press.dragging && !press.moved) {
      this.finish();
      this.host.menu(press.key, press.x, press.y);
      return;
    }
    this.finish();
  };

  private onCancel = (ev: PointerEvent): void => {
    if (this.press && ev.pointerId === this.press.pointerId) void this.cancel();
  };

  private onKey = (ev: KeyboardEvent): void => {
    if (ev.key !== 'Escape' || !this.press?.dragging) return;
    ev.preventDefault();
    ev.stopPropagation();
    void this.cancel();
  };

  /** Mientras se arrastra con el dedo, la tira no se desliza. */
  private onTouchMove = (ev: TouchEvent): void => {
    if (this.press?.dragging && ev.cancelable) ev.preventDefault();
  };

  // ── Arrastre ───────────────────────────────────────────────────────────
  private begin(): void {
    const press = this.press;
    if (!press || press.dragging) return;
    press.dragging = true;
    press.grab = press.startX - press.el.getBoundingClientRect().left;
    press.origin = this.tabs().indexOf(press.el);
    press.el.classList.add('is-dragging');
    this.host.strip.classList.add('is-reordering');
    this.host.dragging(press.key);
    if (press.touch) navigator.vibrate?.(10);
    const edge = () => {
      if (this.press !== press) return;
      this.scrollAtEdge(press);
      press.frame = requestAnimationFrame(edge);
    };
    press.frame = requestAnimationFrame(edge);
    void this.follow();
  }

  /** Pone la pestaña bajo el puntero y, si ha pasado la mitad de otra, cambia el orden. */
  private async follow(): Promise<void> {
    const press = this.press;
    if (!press?.dragging) return;
    const { strip } = this.host;
    const left = press.x - press.grab;
    press.el.style.transform = `translateX(${left - this.naturalLeft(press.el)}px)`;
    if (this.moving) return;
    const center = left + press.el.offsetWidth / 2;
    const others = this.tabs().filter((tab) => tab !== press.el);
    const index = others.filter((tab) => this.naturalLeft(tab) + tab.offsetWidth / 2 < center).length;
    const before = this.tabs().indexOf(press.el);
    if (index === before) return;
    this.moving = true;
    try {
      await this.host.move(press.key, index);
    } finally {
      this.moving = false;
    }
    // Si no se movió (no puede pasar delante de Inicio), se queda donde está.
    if (this.press === press && strip.isConnected && this.tabs().indexOf(press.el) !== before) void this.follow();
  }

  private scrollAtEdge(press: Press): void {
    const { strip } = this.host;
    const box = strip.getBoundingClientRect();
    const step = press.x < box.left + EDGE_PX ? -EDGE_STEP_PX : press.x > box.right - EDGE_PX ? EDGE_STEP_PX : 0;
    if (!step) return;
    const before = strip.scrollLeft;
    strip.scrollLeft += step;
    if (strip.scrollLeft !== before) void this.follow();
  }

  /** Escape o el sistema interrumpió el gesto: la pestaña vuelve a su sitio. */
  private async cancel(): Promise<void> {
    const press = this.press;
    this.finish();
    if (press?.dragging) await this.host.move(press.key, press.origin);
  }

  private finish(): void {
    const press = this.press;
    if (!press) return;
    this.press = null;
    clearTimeout(press.timer);
    cancelAnimationFrame(press.frame);
    press.el.style.transform = '';
    press.el.classList.remove('is-dragging');
    this.host.strip.classList.remove('is-reordering');
    if (press.dragging) this.host.dragging(null);
    window.removeEventListener('pointermove', this.onMove);
    window.removeEventListener('pointerup', this.onUp);
    window.removeEventListener('pointercancel', this.onCancel);
    window.removeEventListener('keydown', this.onKey, true);
    window.removeEventListener('touchmove', this.onTouchMove);
  }

  // ── Posiciones ─────────────────────────────────────────────────────────
  private tabs(): HTMLElement[] {
    return [...this.host.strip.querySelectorAll<HTMLElement>(':scope > [data-key]')];
  }

  /** Dónde está una pestaña en la ventana sin contar desplazamientos animados (offsetLeft). */
  private naturalLeft(tab: HTMLElement): number {
    const { strip } = this.host;
    return strip.getBoundingClientRect().left + strip.clientLeft + tab.offsetLeft - strip.scrollLeft;
  }
}
