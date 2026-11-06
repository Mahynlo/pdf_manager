// Atiende las tareas que Python le pide al motor de EmbedPDF (Host.run_engine): descarga el PDF,
// hace la tarea (engine-tasks.ts) y sube el resultado.
import { call, on } from '$lib/api.ts';
import { runTask, type TaskArgs, type TaskEngine } from '$lib/engine-tasks.ts';

interface EngineTask {
  id: number;
  task: string;
  url: string;
  upload: string;
  args: TaskArgs;
}

/** El motor del registro de EmbedPDF (se carga solo cuando hace falta). */
export async function engine(): Promise<TaskEngine> {
  const { registry } = await import('../tools/viewer/canvas/embed.ts');
  return (await registry()).getEngine() as unknown as TaskEngine;
}

async function serve({ id, task, url, upload, args }: EngineTask): Promise<void> {
  try {
    const source = await fetch(url);
    const result = await runTask(await engine(), task, await source.arrayBuffer(), args);
    const sent = await fetch(upload, { method: 'POST', body: result });
    if (!sent.ok) throw new Error(`HTTP ${sent.status}`);
    await call('app.engine_done', id, null);
  } catch (err) {
    await call('app.engine_done', id, (err as Error).message ?? String(err));
  }
}

/** Empieza a atender las tareas de Python. */
export function listenEngineTasks(): void {
  on<EngineTask>('engine:task', (task) => void serve(task));
}
