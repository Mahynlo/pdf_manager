<!-- Pestaña «Proteger»: cifrar un PDF con contraseña (AES-256) y permisos. -->
<script>
  import { call } from '$lib/api.js';
  import Banner from '$lib/components/Banner.svelte';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Fieldset from '$lib/components/Fieldset.svelte';
  import PasswordField from '$lib/components/PasswordField.svelte';
  import { fileName } from '$lib/dom.js';
  import Icon from '$lib/Icon.svelte';
  import FileBox from './FileBox.svelte';
  import Steps from './Steps.svelte';

  let file = $state(null);
  let options = $state({ presets: [], permissions: [] });
  let preset = $state('');
  let checked = $state({}); // clave del permiso -> marcado
  let userPwd = $state('');
  let ownerPwd = $state('');
  let msg = $state({ text: '', tone: 'success' });

  const show = (text, tone = 'success') => (msg = { text, tone });

  // Los niveles rápidos solo rellenan las casillas: se cifra con lo que esté marcado.
  function applyPreset(key) {
    const found = options.presets.find((p) => p.key === key);
    if (found) checked = Object.fromEntries(options.permissions.map((p) => [p.key, Boolean(found.values[p.key])]));
  }

  call('security.options').then((opts) => {
    options = opts;
    preset = opts.default_preset;
    applyPreset(preset);
  });

  async function pick() {
    const info = await call('security.pick_unprotected');
    if (!info) return;
    file = info;
    show('');
  }

  async function protect() {
    if (!file) return show('Selecciona un PDF primero', 'danger');
    try {
      const dest = await call('security.protect', file.path, userPwd.trim(), ownerPwd.trim(), { ...checked });
      if (!dest) return;
      show(`Documento protegido guardado con éxito: ${fileName(dest)}`);
      userPwd = '';
      ownerPwd = '';
    } catch (err) {
      show(err.message, 'danger');
    }
  }
</script>

{#snippet left()}
  <button class="btn btn--lg btn--block" type="button" onclick={pick}><Icon name="folder-open" />Seleccionar PDF a Proteger</button>
  <FileBox text={file?.name} />
  <label class="label" for="protect-preset">Nivel de protección rápido:</label>
  <select id="protect-preset" class="input select" bind:value={preset} onchange={() => applyPreset(preset)}>
    {#each options.presets as p (p.key)}
      <option value={p.key}>{p.label}</option>
    {/each}
  </select>
  <Fieldset legend="Permisos personalizados avanzados">
    {#each options.permissions as perm (perm.key)}
      <Checkbox label={perm.label} bind:checked={checked[perm.key]} />
    {/each}
  </Fieldset>
{/snippet}

{#snippet right()}
  <div class="info-card">
    <p class="info-card__title">¿Cuál es la diferencia entre contraseñas?</p>
    <p>• <b>Contraseña de Usuario:</b> El usuario final la necesita para abrir y ver el PDF. Restringe acciones según los permisos configurados.</p>
    <p>• <b>Contraseña de Propietario (Opcional):</b> Permite cambiar permisos y eliminar contraseñas sin requerir la clave de usuario.</p>
  </div>
  <Fieldset legend="Contraseña de Usuario (Para abrir el PDF)">
    <PasswordField bind:value={userPwd} placeholder="Contraseña obligatoria para abrir..." />
  </Fieldset>
  <Fieldset legend="Contraseña de Propietario (Opcional - Administrador)">
    <PasswordField bind:value={ownerPwd} placeholder="Contraseña para modificar permisos..." />
  </Fieldset>
  <button class="btn btn--primary btn--lg btn--block" type="button" onclick={protect}><Icon name="lock" />Cifrar y Guardar PDF</button>
  <Banner message={msg.text} tone={msg.tone} />
{/snippet}

<Steps leftTitle="Paso 1: Archivo y Nivel" rightTitle="Paso 2: Seguridad y Contraseñas" {left} {right} />
