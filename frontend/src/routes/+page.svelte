<script lang="ts">
  import { onMount } from 'svelte';
  import { z } from 'zod';
  import { get, post } from '$lib/api/client';
  import { CreatureSummarySchema } from '$lib/schemas/creature';
  import { UpcomingFightSchema } from '$lib/schemas/fight';
  import { leaderboardStore } from '$lib/stores/leaderboard';
  import { fightStore } from '$lib/stores/fight';
  import { commentaryStore } from '$lib/stores/commentary';
  import { elementColor, tierColor } from '$lib/theme';
  import type { UpcomingFight } from '$lib/schemas/fight';
  import Arena from '$lib/components/Arena.svelte';

  let ticking = false;
  let tickError = '';
  let upcoming: UpcomingFight | null = null;

  onMount(async () => {
    // Seed leaderboard from REST
    const result = await get('/creatures?limit=20&status=active', z.array(CreatureSummarySchema));
    result.match(
      (creatures) => leaderboardStore.set(creatures),
      (e) => console.warn('Leaderboard load failed:', e.message),
    );

    // Load upcoming fight
    const upResult = await get('/fights/upcoming', UpcomingFightSchema);
    upResult.match(
      (data) => { upcoming = 'message' in data ? null : data; },
      () => {},
    );
  });

  async function runTick() {
    ticking = true;
    tickError = '';
    const result = await post('/simulation/tick', { fights_per_tick: 3 }, z.unknown());
    result.match(
      () => {},
      (e) => { tickError = e.message; },
    );
    ticking = false;

    // Refresh leaderboard after tick
    const lb = await get('/creatures?limit=20&status=active', z.array(CreatureSummarySchema));
    lb.match((creatures) => leaderboardStore.set(creatures), () => {});
  }

  // Derive display lists reactively
  $: recentEvents = $fightStore.events.slice(-20).reverse();
</script>

<div class="page">
  <!-- Left — Leaderboard -->
  <aside class="sidebar-left">
    <div class="panel-title">Leaderboard</div>
    {#if $leaderboardStore.length === 0}
      <p class="empty">No active creatures</p>
    {:else}
      <ul class="lb-list">
        {#each $leaderboardStore as c, i}
          <li class="lb-row">
            <span class="rank">{i + 1}</span>
            <span class="name">{c.name}</span>
            <span class="pill" style="color: {tierColor(c.tier)}">{c.tier}</span>
            <span class="pill" style="color: {elementColor(c.element)}">{c.element}</span>
            <span class="score">{c.wins}W {c.losses}L</span>
          </li>
        {/each}
      </ul>
    {/if}
  </aside>

  <!-- Center — Arena + Fight log + Controls -->
  <section class="center">
    <!-- Pixi.js arena -->
    <Arena />

    <!-- Fight log -->
    <div class="fight-log-panel">
      <div class="panel-title">Fight Log</div>
      {#if recentEvents.length === 0}
        <p class="empty">Waiting for a fight…</p>
      {:else}
        <ul class="log-list">
          {#each recentEvents as ev}
            <li class="log-row {ev.event_type}">
              <span class="turn">T{ev.turn}</span>
              <span class="etype">{ev.event_type}</span>
              <span class="actor">{ev.actor_id ?? '—'}</span>
              {#if ev.damage !== null}
                <span class="dmg">-{ev.damage}hp</span>
              {/if}
              {#if ev.ability_name}
                <span class="ability">{ev.ability_name}</span>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    <!-- Controls -->
    <div class="controls">
      <button class="btn-tick" on:click={runTick} disabled={ticking}>
        {ticking ? 'Running…' : '▶ Run Tick'}
      </button>
      {#if tickError}
        <span class="error">{tickError}</span>
      {/if}
    </div>
  </section>

  <!-- Right — Commentary + Upcoming -->
  <aside class="sidebar-right">
    {#if upcoming}
      <div class="panel-title">Next Fight</div>
      <div class="upcoming-card">
        <div class="up-name" style="color:{elementColor(String(upcoming.creature_a.element ?? ''))}">
          {String(upcoming.creature_a.name ?? '?')}
        </div>
        <div class="up-prob">{(upcoming.prob_a * 100).toFixed(0)}%</div>
        <div class="up-vs">vs</div>
        <div class="up-prob">{(upcoming.prob_b * 100).toFixed(0)}%</div>
        <div class="up-name" style="color:{elementColor(String(upcoming.creature_b.element ?? ''))}">
          {String(upcoming.creature_b.name ?? '?')}
        </div>
      </div>
    {/if}

    <div class="panel-title" style="margin-top: 16px;">The Chronicler</div>
    {#if $commentaryStore.length === 0}
      <p class="empty">Awaiting the Chronicler…</p>
    {:else}
      <ul class="commentary-list">
        {#each $commentaryStore as line}
          <li class="commentary-line">{line}</li>
        {/each}
      </ul>
    {/if}
  </aside>
</div>

<style>
  .page {
    display: grid;
    grid-template-columns: 220px 1fr 240px;
    height: 100%;
    overflow: hidden;
    gap: 1px;
    background: var(--border);
  }

  .sidebar-left, .sidebar-right, .center {
    background: var(--bg);
    overflow-y: auto;
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .panel-title {
    font-size: 9px;
    font-weight: 500;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    border-bottom: 1px solid var(--border);
    padding-bottom: 6px;
    margin-bottom: 4px;
  }

  .empty {
    font-size: 11px;
    color: var(--text-dim);
    padding: 8px 0;
  }

  /* Leaderboard */
  .lb-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .lb-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 6px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 10px;
  }

  .rank { color: var(--text-dim); width: 14px; flex-shrink: 0; }
  .name { color: var(--text); flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .score { color: var(--text-dim); font-size: 9px; white-space: nowrap; }

  .pill {
    font-size: 8px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    flex-shrink: 0;
  }


  /* Fight log */
  .fight-log-panel {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .log-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 2px;
    overflow-y: auto;
    flex: 1;
  }

  .log-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 6px;
    border-radius: 3px;
    font-size: 10px;
    background: var(--card);
    border-left: 2px solid var(--border);
  }

  .log-row.ko       { border-left-color: var(--fail); }
  .log-row.ability  { border-left-color: var(--rare); }
  .log-row.attack   { border-left-color: var(--fire); }
  .log-row.dodge    { border-left-color: var(--text-dim); }
  .log-row.taunt    { border-left-color: var(--electric); }

  .turn  { color: var(--text-dim); width: 28px; flex-shrink: 0; }
  .etype { color: var(--text-mid); width: 54px; flex-shrink: 0; }
  .actor { color: var(--text); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dmg   { color: var(--fail); flex-shrink: 0; }
  .ability { color: var(--rare); font-size: 9px; flex-shrink: 0; }

  /* Controls */
  .controls {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 0;
  }

  .btn-tick {
    background: var(--card);
    border: 1px solid var(--border-hi);
    color: var(--text);
    font-size: 11px;
    padding: 6px 16px;
    border-radius: 4px;
    transition: background 0.12s, border-color 0.12s;
  }

  .btn-tick:hover:not(:disabled) {
    background: var(--border);
    border-color: var(--text-dim);
  }

  .btn-tick:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .error { color: var(--fail); font-size: 10px; }

  /* Right sidebar */
  .upcoming-card {
    display: grid;
    grid-template-columns: 1fr auto auto auto 1fr;
    align-items: center;
    gap: 6px;
    padding: 8px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
  }

  .up-name { font-size: 10px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .up-prob { font-size: 9px; color: var(--text-mid); }
  .up-vs   { font-size: 9px; color: var(--text-dim); }

  .commentary-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .commentary-line {
    font-size: 11px;
    color: var(--text-mid);
    font-style: italic;
    padding: 6px 8px;
    border-left: 2px solid var(--rare);
    background: var(--card);
    border-radius: 0 4px 4px 0;
    line-height: 1.5;
  }
</style>
