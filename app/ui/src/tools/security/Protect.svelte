<!-- Pestaña «Proteger»: cifrar un PDF con contraseña (AES-256) y permisos. -->
<script lang="ts">
  import { call } from '$lib/api.ts';
  import Banner from '$lib/components/Banner.svelte';
  import Checkbox from '$lib/components/Checkbox.svelte';
  import Fieldset from '$lib/components/Fieldset.svelte';
  import PasswordField from '$lib/components/PasswordField.svelte';
  import { fileName } from '$lib/dom.ts';
  import Icon from '$lib/Icon.svelte';
  import type { Tone } from '$lib/ui.ts';
  import { t } from '$texts';
  import FileBox from './FileBox.svelte';
  import Steps from './Steps.svelte';
  import type { Message, SecurityFile, SecurityOptions } from './types.ts';

  const T = t.security.protect;

  let file = $state<SecurityFile | null>(null);
  let options = $state<SecurityOptions>({ presets: [], permissions: [] });
  let preset = $state('');
  let checked = $state<Record<string, boolean>>({}); // clave del permiso -> marcado
  let userPwd = $state('');
  let ownerPwd = $state('');
  let msg = $state<Message>({ text: '', tone: 'success' });

  const show = (text: string, tone: Tone = 'success') => (msg = { text, tone });

  // Los niveles rápidos solo rellenan las casillas: se cifra con lo que esté marcado.
  function applyPreset(key: string) {
    const found = options.presets.find((p) => p.key === key);
    if (found) checked = Object.fromEntries(options.permissions.map((p) => [p.key, Boolean(found.values[p.key])]));
  }

  call<SecurityOptions>('security.options').then((opts) => {
    options = opts;
    preset = opts.default_preset ?? '';
    applyPreset(preset);
  });

  async function pick() {
    const info = await call<SecurityFile | null>('security.pick_unprotected');
    if (!info) return;
    file = info;
    show('');
  }

  async function protect() {
    if (!file) return show(t.security.pickFirst, 'danger');
    try {
      const dest = await call<string | null>('security.protect', file.path, userPwd.trim(), ownerPwd.trim(), { ...checked });
      if (!dest) return;
      show(T.saved(fileName(dest)));
      userPwd = '';
      ownerPwd = '';
    } catch (err) {
      show((err as Error).message, 'danger');
    }
  }
</script>

{#snippet left()}
  <button class="btn btn--lg btn--block" type="button" onclick={pick}><Icon name="folder-open" />{T.pick}</button>
  <FileBox text={file?.name} />
  <label class="label" for="protect-preset">{T.preset}</label>
  <select id="protect-preset" class="input select" bind:value={preset} onchange={() => applyPreset(preset)}>
    {#each options.presets as p (p.key)}
      <option value={p.key}>{p.label}</option>
    {/each}
  </select>
  <Fieldset legend={T.permissions}>
    {#each options.permissions as perm (perm.key)}
      <Checkbox label={perm.label} bind:checked={checked[perm.key]} />
    {/each}
  </Fieldset>
{/snippet}

{#snippet right()}
  <div class="info-card">
    <p class="info-card__title">{T.infoTitle}</p>
    <p>• <b>{T.infoUser}</b> {T.infoUserText}</p>
    <p>• <b>{T.infoOwner}</b> {T.infoOwnerText}</p>
  </div>
  <Fieldset legend={T.userLegend}>
    <PasswordField bind:value={userPwd} placeholder={T.userPlaceholder} />
  </Fieldset>
  <Fieldset legend={T.ownerLegend}>
    <PasswordField bind:value={ownerPwd} placeholder={T.ownerPlaceholder} />
  </Fieldset>
  <button class="btn btn--primary btn--lg btn--block" type="button" onclick={protect}><Icon name="lock" />{T.encrypt}</button>
  <Banner message={msg.text} tone={msg.tone} />
{/snippet}

<Steps leftTitle={T.step1} rightTitle={T.step2} {left} {right} />
