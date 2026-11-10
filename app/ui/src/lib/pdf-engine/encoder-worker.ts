// Un worker de ImageEncoderPool (encoder.ts): píxeles RGBA → imagen comprimida.

export interface ImagePixels {
  data: Uint8ClampedArray;
  width: number;
  height: number;
}

export interface EncodeRequest {
  id: number;
  image: ImagePixels;
  type: string;
  quality?: number;
}

export type EncodeReply = { id: number; blob?: Blob; error?: string };

const scope = self as unknown as {
  postMessage(message: EncodeReply): void;
  onmessage: ((event: MessageEvent<EncodeRequest>) => void) | null;
};

scope.onmessage = async ({ data: { id, image, type, quality } }) => {
  try {
    const canvas = new OffscreenCanvas(image.width, image.height);
    canvas.getContext('2d')!.putImageData(new ImageData(image.data as Uint8ClampedArray<ArrayBuffer>, image.width, image.height), 0, 0);
    scope.postMessage({ id, blob: await canvas.convertToBlob({ type, quality }) });
  } catch (err) {
    scope.postMessage({ id, error: (err as Error)?.message ?? String(err) });
  }
};
