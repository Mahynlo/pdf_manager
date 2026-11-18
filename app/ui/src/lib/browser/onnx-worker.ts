// Los modelos del OCR con onnxruntime-web, en su propio worker: el de Python espera bloqueado
// mientras tanto, y en la ventana bloquearían la interfaz. Lo usa client.ts.
import * as ort from 'onnxruntime-web/wasm';

export interface OnnxRequest {
  id: number;
  base: string; // URL de la raíz de la web
  model: string;
  input?: string; // sin él, solo carga el modelo
  shape?: number[];
  data?: ArrayBuffer;
}

export type OnnxReply = { id: number; shape?: readonly number[]; data?: ArrayBuffer; error?: string };

const scope = self as unknown as {
  postMessage(message: OnnxReply, transfer?: Transferable[]): void;
  onmessage: ((event: MessageEvent<OnnxRequest>) => void) | null;
};

const sessions = new Map<string, Promise<ort.InferenceSession>>();

function session(base: string, model: string): Promise<ort.InferenceSession> {
  // Sus archivos tal cual: cada hilo carga ese script, y empaquetado sería este worker (y se colgaría).
  ort.env.wasm.wasmPaths = `${base}onnx/`;
  if (!sessions.has(model)) sessions.set(model, ort.InferenceSession.create(`${base}ocr_models/${model}`));
  return sessions.get(model)!;
}

async function serve({ id, base, model, input, shape, data }: OnnxRequest): Promise<void> {
  try {
    const loaded = await session(base, model);
    if (!input) {
      scope.postMessage({ id });
      return;
    }
    const tensor = new ort.Tensor('float32', new Float32Array(data!), shape!);
    const outputs = await loaded.run({ [input]: tensor });
    const output = outputs[loaded.outputNames[0]];
    const values = (output.data as Float32Array).slice();
    scope.postMessage({ id, shape: output.dims, data: values.buffer }, [values.buffer]);
  } catch (err) {
    scope.postMessage({ id, error: (err as Error).message ?? String(err) });
  }
}

scope.onmessage = ({ data }) => void serve(data);
