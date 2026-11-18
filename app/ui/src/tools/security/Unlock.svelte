<!-- Pestaña «Desbloquear»: analizar un PDF, ver sus permisos, abrirlo o guardarlo sin contraseña. -->
<script lang="ts">
  import { call } from '$lib/api.ts';
  import Banner from '$lib/components/Banner.svelte';
  import Fieldset from '$lib/components/Fieldset.svelte';
  import PasswordField from '$lib/components/PasswordField.svelte';
  import { fileName } from '$lib/dom.ts';
  import Icon from '$lib/Icon.svelte';
  import type { Tone } from '$lib/ui.ts';
  import { t } from '$texts';
  import FileBox from './FileBox.svelte';
  import Steps from './Steps.svelte';
  import type { Message, SecurityAudit } from './types.ts';

  const T = t.security.unlock;

  let file = $state<SecurityAudit | null>(null);
  let audit = $state<SecurityAudit | null>(null);
  let password = $state('');
  let msg = $state<Message>({ text: '', tone: 'success' });

  const show = (text: string, tone: Tone = 'success') => (msg = { text, tone });

  async function pick() {
    let info: SecurityAudit | null;
    try {
      info = await call<SecurityAudit | null>('security.pick_protected');
    } catch (err) {
      show(T.analyzeError((err as Error).message), 'danger');
      return;
    }
    if (!info) return;
    file = info;
    audit = info;
    password = '';
    show('');
  }

  async function tryUnlock() {
    if (!file) return show(t.security.pickFirst, 'danger');
    if (!password.trim()) return show(T.enterPassword, 'danger');
    try {
      audit = await call<SecurityAudit>('security.unlock', file.path, password.trim());
      show(T.unlocked);
    } catch (err) {
      show((err as Error).message, 'danger');
    }
  }

  async function exportUnlocked() {
    if (!file) return show(t.security.pickFirst, 'danger');
    try {
      const dest = await call<string | null>('security.export_unlocked', file.path, password.trim());
      if (dest) show(T.saved(fileName(dest)));
    } catch (err) {
      show((err as Error).message, 'danger');
    }
  }
</script>

{#snippet left()}
  <button class="btn btn--lg btn--block" type="button" onclick={pick}><Icon name="folder-open" />{T.pick}</button>
  <FileBox text={file && T.fileState(file.name, file.protected)}
           tone={file && (file.protected ? 'danger' : 'success')} />
{/snippet}

{#snippet right()}
  {#if audit}
    <div class="card audit">
      {#if audit.protected}
        <p class="status-line tone-danger"><Icon name="lock" />{T.needsPassword}</p>
      {:else}
        <p class="status-line tone-success"><Icon name="lock-open" />{T.notProtected}</p>
      {/if}
      {#if audit.encryption}
        <p class="muted">{T.encryption(audit.encryption)}</p>
        {#if !audit.authenticated}
          <p class="hint note">{T.passwordNote}</p>
        {/if}
      {/if}
      {#if audit.permissions.length}
        <hr class="divider" />
        <p class="label">{T.permissions}</p>
        <ul class="perm-list">
          {#each audit.permissions as p (p.label)}
            <li class={p.allowed ? 'tone-success' : 'tone-danger'}>
              <Icon name={p.allowed ? 'check' : 'x'} size={14} /><span>{p.label}</span>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
  <Fieldset legend={T.passwordLegend} hidden={!file?.protected}>
    <PasswordField bind:value={password} placeholder={T.passwordPlaceholder} onenter={tryUnlock} />
  </Fieldset>
  <div class="button-row" hidden={!file}>
    <button class="btn btn--primary btn--lg" type="button" hidden={!file?.protected} onclick={tryUnlock}>
      <Icon name="lock-open" />{T.unlockOpen}
    </button>
    <button class="btn btn--lg" type="button" onclick={exportUnlocked}><Icon name="save" />{T.saveUnlocked}</button>
  </div>
  <Banner message={msg.text} tone={msg.tone} />
{/snippet}

<Steps leftTitle={T.step1} rightTitle={T.step2} {left} {right} />
