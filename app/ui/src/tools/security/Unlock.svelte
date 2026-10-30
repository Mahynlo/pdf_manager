<!-- Pestaña «Desbloquear»: analizar un PDF, ver sus permisos, abrirlo o guardarlo sin contraseña. -->
<script>
  import { call } from '$lib/api.js';
  import Banner from '$lib/components/Banner.svelte';
  import Fieldset from '$lib/components/Fieldset.svelte';
  import PasswordField from '$lib/components/PasswordField.svelte';
  import { fileName } from '$lib/dom.js';
  import Icon from '$lib/Icon.svelte';
  import FileBox from './FileBox.svelte';
  import Steps from './Steps.svelte';

  let file = $state(null);
  let audit = $state(null);
  let password = $state('');
  let msg = $state({ text: '', tone: 'success' });

  const show = (text, tone = 'success') => (msg = { text, tone });

  async function pick() {
    let info;
    try {
      info = await call('security.pick_protected');
    } catch (err) {
      show(`Error al analizar el archivo: ${err.message}`, 'danger');
      return;
    }
    if (!info) return;
    file = info;
    audit = info;
    password = '';
    show('');
  }

  async function tryUnlock() {
    if (!file) return show('Selecciona un PDF primero', 'danger');
    if (!password.trim()) return show('Ingresa la contraseña', 'danger');
    try {
      audit = await call('security.unlock', file.path, password.trim());
      show('PDF desbloqueado exitosamente');
    } catch (err) {
      show(err.message, 'danger');
    }
  }

  async function exportUnlocked() {
    if (!file) return show('Selecciona un PDF primero', 'danger');
    try {
      const dest = await call('security.export_unlocked', file.path, password.trim());
      if (dest) show(`PDF guardado con éxito: ${fileName(dest)}`);
    } catch (err) {
      show(err.message, 'danger');
    }
  }
</script>

{#snippet left()}
  <button class="btn btn--lg btn--block" type="button" onclick={pick}><Icon name="folder-open" />Seleccionar PDF Protegido</button>
  <FileBox text={file && `${file.name} (${file.protected ? 'Protegido' : 'No protegido'})`}
           tone={file && (file.protected ? 'danger' : 'success')} />
{/snippet}

{#snippet right()}
  {#if audit}
    <div class="card audit">
      {#if audit.protected}
        <p class="status-line tone-danger"><Icon name="lock" />Requiere Contraseña</p>
      {:else}
        <p class="status-line tone-success"><Icon name="lock-open" />Sin Protección</p>
      {/if}
      {#if audit.encryption}
        <p class="muted">Cifrado: {audit.encryption}</p>
        {#if !audit.authenticated}
          <p class="hint note">Nota: ingresa la contraseña para ver los permisos reales.</p>
        {/if}
      {/if}
      <hr class="divider" />
      <p class="label">Permisos actuales:</p>
      <ul class="perm-list">
        {#each audit.permissions as p (p.label)}
          <li class={p.allowed ? 'tone-success' : 'tone-danger'}>
            <Icon name={p.allowed ? 'check' : 'x'} size={14} /><span>{p.label}</span>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
  <Fieldset legend="Contraseña del Documento" hidden={!file?.protected}>
    <PasswordField bind:value={password} placeholder="Ingresa la contraseña para desbloquear..." onenter={tryUnlock} />
  </Fieldset>
  <div class="button-row" hidden={!file}>
    <button class="btn btn--primary btn--lg" type="button" hidden={!file?.protected} onclick={tryUnlock}>
      <Icon name="lock-open" />Desbloquear y Abrir
    </button>
    <button class="btn btn--lg" type="button" onclick={exportUnlocked}><Icon name="save" />Guardar Sin Contraseña</button>
  </div>
  <Banner message={msg.text} tone={msg.tone} />
{/snippet}

<Steps leftTitle="Paso 1: Archivo" rightTitle="Paso 2: Acciones" {left} {right} />
