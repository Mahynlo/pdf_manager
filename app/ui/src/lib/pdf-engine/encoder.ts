// Codifica las imágenes que dibuja el motor (WebP, PNG…) en workers, para no ocupar la ventana.
// Hace lo que el ImageEncoderWorkerPool de EmbedPDF, que no se publica: createHybridImageConverter
// solo necesita `encode` y `destroy`.
import type { EncodeReply, EncodeRequest, ImagePixels } from './encoder-worker.ts';

export class ImageEncoderPool {
  private workers: Worker[];
  private next = 0;
  private ids = 0;
  private pending = new Map<number, { resolve(blob: Blob): void; reject(err: Error): void }>();

  constructor(size: number) {
    this.workers = Array.from({ length: size }, () => {
      const worker = new Worker(new URL('./encoder-worker.ts', import.meta.url), { type: 'module' });
      worker.onmessage = ({ data }: MessageEvent<EncodeReply>) => this.settle(data);
      return worker;
    });
  }

  encode(image: ImagePixels, type: string, quality?: number): Promise<Blob> {
    const id = ++this.ids;
    const worker = this.workers[this.next++ % this.workers.length];
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      worker.postMessage({ id, image, type, quality } satisfies EncodeRequest, [image.data.buffer]);
    });
  }

  private settle({ id, blob, error }: EncodeReply): void {
    const task = this.pending.get(id);
    this.pending.delete(id);
    if (blob) task?.resolve(blob);
    else task?.reject(new Error(error ?? 'No se pudo codificar la imagen'));
  }

  destroy(): void {
    for (const worker of this.workers) worker.terminate();
    for (const task of this.pending.values()) task.reject(new Error('Codificador cerrado'));
    this.pending.clear();
  }
}
