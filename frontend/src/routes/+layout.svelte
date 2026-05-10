<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import '../app.css';
  import { connect, disconnect, wsConnectionState } from '$lib/api/ws';

  const NAV = [
    { href: '/',          label: 'Spectator' },
    { href: '/builder',   label: 'Builder'   },
    { href: '/lineage',   label: 'Lineage'   },
    { href: '/replay',    label: 'Replay'    },
    { href: '/analytics', label: 'Analytics' },
    { href: '/debug',     label: 'Debug'     },
  ];

  onMount(() => connect());
  onDestroy(() => disconnect());
</script>

<div class="shell">
  <header>
    <span class="title">Survival of the Fittest</span>
    <nav>
      {#each NAV as { href, label }}
        <a {href}>{label}</a>
      {/each}
    </nav>
  </header>

  <main>
    {#if $wsConnectionState.reconnecting}
      <div class="ws-toast" role="status" aria-live="polite" aria-atomic="true">
        <span class="dot">●</span>
        <span>
          Reconnecting live feed (attempt {$wsConnectionState.retryCount})
          {#if $wsConnectionState.lastError}
            · {$wsConnectionState.lastError}
          {/if}
        </span>
      </div>
    {/if}
    <slot />
  </main>
</div>

<style>
  .shell {
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }

  header {
    display: flex;
    align-items: center;
    gap: 32px;
    padding: 0 20px;
    height: 48px;
    background: var(--card);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .title {
    font-family: var(--font-disp);
    font-size: 15px;
    font-weight: 800;
    color: var(--text);
    letter-spacing: -0.01em;
    white-space: nowrap;
  }

  nav {
    display: flex;
    gap: 4px;
  }

  nav a {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--text-mid);
    padding: 5px 10px;
    border-radius: 4px;
    transition: color 0.12s, background 0.12s;
  }

  nav a:hover {
    color: var(--text);
    background: var(--border);
  }

  main {
    flex: 1;
    overflow: hidden;
    position: relative;
  }

  .ws-toast {
    position: absolute;
    top: 10px;
    right: 12px;
    z-index: 20;
    display: flex;
    align-items: center;
    gap: 8px;
    background: var(--card);
    border: 1px solid var(--retry);
    color: var(--text);
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 10px;
    letter-spacing: 0.04em;
  }

  .dot {
    color: var(--retry);
    animation: pulse 1.2s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }
</style>
