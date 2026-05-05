<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import '../app.css';
  import { connect, disconnect } from '$lib/api/ws';

  const NAV = [
    { href: '/',          label: 'Spectator' },
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
  }
</style>
