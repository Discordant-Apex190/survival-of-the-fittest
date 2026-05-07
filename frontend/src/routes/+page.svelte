<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { z } from 'zod';
  import { get, post } from '$lib/api/client';
  import { CreatureSummarySchema } from '$lib/schemas/creature';
  import { leaderboardStore } from '$lib/stores/leaderboard';
  import { fightStore } from '$lib/stores/fight';
  import { betStore } from '$lib/stores/bet';
  import { voteStore } from '$lib/stores/votes';
  import { wsConnected } from '$lib/api/ws';
  import { elementColor, tierColor } from '$lib/theme';
  import Arena from '$lib/components/Arena.svelte';

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  let ticking = false;
  let tickError = '';

  // Bet UI local state
  const BET_PRESETS = [10, 25, 50, 100];
  let betAmount = 25;
  let customAmount = '';
  let betPlaced = false;

  // Vote progress during betting window
  $: votesIn   = $voteStore.fight_id === $fightStore.fight_id
    ? Object.values($voteStore.votes).reduce((a, b) => a + b, 0)
    : 0;

  // Reset betPlaced when a new preview window opens
  $: if ($fightStore.previewing) betPlaced = !!$betStore.active;

  // Auto-tick
  let autoTick = false;
  let autoInterval = 8;   // seconds between ticks
  let autoTimer: ReturnType<typeof setInterval> | null = null;

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  $: effectiveAmount = customAmount !== '' ? parseInt(customAmount) || 0 : betAmount;
  $: pendingBet  = $betStore.active?.status === 'pending' ? $betStore.active : null;
  $: lockedBet   = $betStore.active?.status === 'locked'  ? $betStore.active : null;
  $: resolvedBet = ($betStore.active?.status === 'won' || $betStore.active?.status === 'lost')
    ? $betStore.active : null;

  // After fight ends and bet is resolved, show result then auto-dismiss after 4s
  $: if (resolvedBet) {
    setTimeout(() => betStore.dismiss(), 4000);
  }

  // Reset local betPlaced when active bet is gone
  $: if (!$betStore.active) betPlaced = false;

  // ---------------------------------------------------------------------------
  // Tick / auto-tick
  // ---------------------------------------------------------------------------

  onMount(async () => {
    const result = await get('/creatures?limit=20&status=active', z.array(CreatureSummarySchema));
    result.match(
      (creatures) => leaderboardStore.set(creatures),
      (e) => console.warn('Leaderboard load failed:', e.message),
    );
  });

  onDestroy(() => {
    stopAuto();
  });

  async function runTick() {
    if (ticking) return;
    ticking = true;
    tickError = '';
    const result = await post('/simulation/tick', { fights_per_tick: 3 }, z.unknown());
    result.match(() => {}, (e) => { tickError = e.message; });
    ticking = false;
    const lb = await get('/creatures?limit=20&status=active', z.array(CreatureSummarySchema));
    lb.match((creatures) => leaderboardStore.set(creatures), () => {});
    if ($fightStore.active) await loadBetting();
  }

  function startAuto() {
    autoTick = true;
    autoTimer = setInterval(() => { void runTick(); }, autoInterval * 1000);
  }

  function stopAuto() {
    autoTick = false;
    if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
  }

  function toggleAuto() {
    autoTick ? stopAuto() : startAuto();
  }

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
    <Arena />

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
      {#if !$wsConnected}
        <span class="ws-status connecting">● Connecting…</span>
      {:else}
        <span class="ws-status connected">● Live</span>
      {/if}

      <button class="btn-tick" on:click={runTick} disabled={ticking || autoTick || !$wsConnected}>
        {ticking ? 'Running…' : '▶ Run Tick'}
      </button>

      <div class="auto-row">
        <button
          class="btn-auto"
          class:active={autoTick}
          on:click={toggleAuto}
          disabled={ticking || !$wsConnected}
        >
          {autoTick ? '⏹ Stop Auto' : '⏩ Auto'}
        </button>
        <select class="auto-interval" bind:value={autoInterval} disabled={autoTick}>
          <option value={4}>4s</option>
          <option value={8}>8s</option>
          <option value={15}>15s</option>
          <option value={30}>30s</option>
        </select>
      </div>

      {#if tickError}
        <span class="error">{tickError}</span>
      {/if}
    </div>
  </section>

  <!-- Right — Betting + Commentary -->
  <aside class="sidebar-right">

    <!-- Token balance -->
    <div class="token-bar">
      <span class="token-icon">◆</span>
      <span class="token-count">{$betStore.tokens.toLocaleString()}</span>
      <span class="token-label">tokens</span>
      <button class="reset-btn" on:click={() => betStore.reset()} title="Reset tokens to 1000">↺</button>
    </div>

    <!-- Bet result banner -->
    {#if resolvedBet}
      <div class="result-banner" class:won={resolvedBet.status === 'won'} class:lost={resolvedBet.status === 'lost'}>
        {#if resolvedBet.status === 'won'}
          Won! +{resolvedBet.payout} tokens
        {:else}
          Lost — -{resolvedBet.amount} tokens
        {/if}
      </div>
    {/if}

    <!-- Locked bet in-progress indicator -->
    {#if lockedBet}
      <div class="locked-banner">
        Bet locked: {lockedBet.amount}◆ @ {lockedBet.odds}x · fight in progress
      </div>
    {/if}

    <!-- Pre-fight betting panel — only visible during the 3-second preview window -->
    {#if $fightStore.previewing && !lockedBet && !resolvedBet}
      {@const ca = $fightStore.creature_a as Record<string,unknown>}
      {@const cb = $fightStore.creature_b as Record<string,unknown>}
      {@const caId  = ca?.id  as string}
      {@const cbId  = cb?.id  as string}
      {@const caEl  = ca?.element as string}
      {@const cbEl  = cb?.element as string}
      {@const caName = ca?.name as string}
      {@const cbName = cb?.name as string}
      {@const pA = $fightStore.prob_a}
      {@const pB = $fightStore.prob_b}

      <div class="panel-title">
        Place Bet
        <span class="vote-badge">
          {#if betPlaced}waiting…{:else}open{/if}
        </span>
      </div>
      <div class="bet-panel">
        <!-- Odds -->
        <div class="odds-row">
          <span class="odds-creature" style="color:{elementColor(caEl)}">{caName}</span>
          <span class="odds-num">{(pA * 100).toFixed(0)}%</span>
          <span class="odds-sep">vs</span>
          <span class="odds-num">{(pB * 100).toFixed(0)}%</span>
          <span class="odds-creature right" style="color:{elementColor(cbEl)}">{cbName}</span>
        </div>

        <!-- Amount presets -->
        <div class="preset-row">
          {#each BET_PRESETS as p}
            <button
              class="preset-btn"
              class:active={betAmount === p && customAmount === ''}
              disabled={betPlaced || $betStore.tokens < p}
              on:click={() => { betAmount = p; customAmount = ''; }}
            >{p}</button>
          {/each}
          <input
            class="custom-input"
            type="number"
            min="1"
            max={$betStore.tokens}
            placeholder="custom"
            bind:value={customAmount}
            disabled={betPlaced}
          />
        </div>

        <!-- Bet buttons -->
        <div class="bet-btns">
          <button
            class="bet-btn"
            disabled={betPlaced || $betStore.tokens < effectiveAmount || effectiveAmount <= 0}
            on:click={async () => {
              if (!$fightStore.fight_id) return;
              const odds = +(1 / pA).toFixed(2);
              const ok = betStore.place($fightStore.fight_id, caId, effectiveAmount, odds);
              if (ok) {
                betPlaced = true;
                // Signal backend that a bet has been placed (triggers threshold check)
                await post('/betting/vote',
                  { fight_id: $fightStore.fight_id, creature_id: caId }, z.unknown());
              }
            }}
          >
            <span style="color:{elementColor(caEl)}">{caName}</span>
            <span class="payout-hint">→ {Math.floor(effectiveAmount * +(1/pA).toFixed(2))}◆</span>
          </button>
          <button
            class="bet-btn"
            disabled={betPlaced || $betStore.tokens < effectiveAmount || effectiveAmount <= 0}
            on:click={async () => {
              if (!$fightStore.fight_id) return;
              const odds = +(1 / pB).toFixed(2);
              const ok = betStore.place($fightStore.fight_id, cbId, effectiveAmount, odds);
              if (ok) {
                betPlaced = true;
                await post('/betting/vote',
                  { fight_id: $fightStore.fight_id, creature_id: cbId }, z.unknown());
              }
            }}
          >
            <span style="color:{elementColor(cbEl)}">{cbName}</span>
            <span class="payout-hint">→ {Math.floor(effectiveAmount * +(1/pB).toFixed(2))}◆</span>
          </button>
        </div>

        <!-- Live bet tally (updates as votes arrive via WS) -->
        <div class="vote-progress">
          <span class="vote-count">{votesIn}</span>
          <span class="vote-label">
            {votesIn === 1 ? 'bet in' : 'bets in'} · fight starts at 50%
          </span>
        </div>

        {#if pendingBet}
          <div class="pending-note">
            Locked: {pendingBet.amount}◆ on
            <span style="color:{pendingBet.creatureId === caId ? elementColor(caEl) : elementColor(cbEl)}">
              {pendingBet.creatureId === caId ? caName : cbName}
            </span>
            (×{pendingBet.odds})
          </div>
        {/if}
      </div>
    {/if}

    <!-- Bet history -->
    {#if $betStore.history.length > 0}
      <div class="panel-title" style="margin-top:12px">Bet History</div>
      <ul class="history-list">
        {#each $betStore.history as h}
          <li class="history-row" class:win={h.result === 'won'} class:loss={h.result === 'lost'}>
            <span class="h-name">{h.creatureName}</span>
            <span class="h-result">{h.result === 'won' ? `+${h.payout}` : `-${h.amount}`}◆</span>
          </li>
        {/each}
      </ul>
    {/if}

  </aside>
</div>

<style>
  .page {
    display: grid;
    grid-template-columns: 220px 1fr 260px;
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
  .lb-list { list-style: none; display: flex; flex-direction: column; gap: 3px; }
  .lb-row {
    display: flex; align-items: center; gap: 6px; padding: 5px 6px;
    background: var(--card); border: 1px solid var(--border); border-radius: 4px; font-size: 10px;
  }
  .rank { color: var(--text-dim); width: 14px; flex-shrink: 0; }
  .name { color: var(--text); flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .score { color: var(--text-dim); font-size: 9px; white-space: nowrap; }
  .pill { font-size: 8px; text-transform: uppercase; letter-spacing: 0.06em; flex-shrink: 0; }

  /* Fight log */
  .fight-log-panel { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 6px; }
  .log-list { list-style: none; display: flex; flex-direction: column; gap: 2px; overflow-y: auto; flex: 1; }
  .log-row {
    display: flex; align-items: center; gap: 8px; padding: 3px 6px;
    border-radius: 3px; font-size: 10px; background: var(--card); border-left: 2px solid var(--border);
  }
  .log-row.ko      { border-left-color: var(--fail); }
  .log-row.ability { border-left-color: var(--rare); }
  .log-row.attack  { border-left-color: var(--fire); }
  .log-row.dodge   { border-left-color: var(--text-dim); }
  .log-row.taunt   { border-left-color: var(--electric); }
  .turn  { color: var(--text-dim); width: 28px; flex-shrink: 0; }
  .etype { color: var(--text-mid); width: 54px; flex-shrink: 0; }
  .actor { color: var(--text); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dmg   { color: var(--fail); flex-shrink: 0; }
  .ability { color: var(--rare); font-size: 9px; flex-shrink: 0; }

  /* Controls */
  .controls { display: flex; align-items: center; gap: 10px; padding: 8px 0; flex-wrap: wrap; }
  .ws-status { font-size: 9px; font-weight: 500; letter-spacing: 0.05em; }
  .ws-status.connecting { color: var(--text-dim); animation: blink 1.2s ease-in-out infinite; }
  .ws-status.connected  { color: #4ade80; }
  @keyframes blink { 0%,100% { opacity:1 } 50% { opacity:0.3 } }
  .auto-row { display: flex; align-items: center; gap: 4px; }
  .btn-tick {
    background: var(--card); border: 1px solid var(--border-hi); color: var(--text);
    font-size: 11px; padding: 6px 16px; border-radius: 4px; transition: background 0.12s, border-color 0.12s;
  }
  .btn-tick:hover:not(:disabled) { background: var(--border); border-color: var(--text-dim); }
  .btn-tick:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-auto {
    background: var(--card); border: 1px solid var(--border); color: var(--text-mid);
    font-size: 10px; padding: 5px 10px; border-radius: 4px; cursor: pointer;
    transition: all 0.12s;
  }
  .btn-auto.active { border-color: var(--rare); color: var(--rare); }
  .btn-auto:disabled { opacity: 0.4; cursor: not-allowed; }
  .auto-interval {
    background: var(--card); border: 1px solid var(--border); color: var(--text-mid);
    font-size: 10px; padding: 4px 6px; border-radius: 4px;
  }
  .error { color: var(--fail); font-size: 10px; }

  /* Vote badge inside panel-title */
  .vote-badge {
    float: right;
    font-size: 9px;
    font-weight: 600;
    color: var(--electric);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .vote-progress {
    display: flex; align-items: baseline; gap: 5px;
    padding: 4px 0 2px;
    border-top: 1px solid var(--border);
  }
  .vote-count { font-size: 14px; font-weight: 700; color: var(--electric); }
  .vote-label { font-size: 9px; color: var(--text-dim); }

  /* Token bar */
  .token-bar {
    display: flex; align-items: center; gap: 6px; padding: 8px 10px;
    background: var(--card); border: 1px solid var(--border); border-radius: 6px;
  }
  .token-icon { color: var(--electric); font-size: 12px; }
  .token-count { color: var(--text); font-size: 14px; font-weight: 700; }
  .token-label { color: var(--text-dim); font-size: 9px; flex: 1; }
  .reset-btn {
    background: none; border: none; color: var(--text-dim); font-size: 12px;
    cursor: pointer; padding: 2px 4px; border-radius: 3px;
  }
  .reset-btn:hover { color: var(--text); background: var(--border); }

  /* Result banner */
  .result-banner {
    text-align: center; padding: 8px 12px; border-radius: 6px;
    font-size: 13px; font-weight: 700;
    animation: fadeIn 0.3s ease;
  }
  .result-banner.won  { background: #1a3320; color: #4ade80; border: 1px solid #4ade8055; }
  .result-banner.lost { background: #2d1515; color: #f87171; border: 1px solid #f8717155; }

  .locked-banner {
    text-align: center; padding: 6px 10px; border-radius: 5px;
    font-size: 10px; color: var(--text-mid);
    background: var(--card); border: 1px solid var(--electric)44;
  }

  /* Bet panel */
  .bet-panel {
    background: var(--card); border: 1px solid var(--border); border-radius: 6px;
    padding: 10px; display: flex; flex-direction: column; gap: 8px;
  }
  .odds-row {
    display: grid; grid-template-columns: 1fr auto auto auto 1fr;
    align-items: center; gap: 4px; font-size: 10px;
  }
  .odds-creature { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .odds-creature.right { text-align: right; }
  .odds-num { color: var(--text-mid); font-size: 9px; text-align: center; }
  .odds-sep { color: var(--text-dim); font-size: 9px; }

  .preset-row { display: flex; gap: 4px; align-items: center; }
  .preset-btn {
    flex: 1; background: var(--bg); border: 1px solid var(--border);
    color: var(--text-mid); font-size: 10px; padding: 4px 2px; border-radius: 4px;
    cursor: pointer; transition: all 0.1s;
  }
  .preset-btn.active { border-color: var(--electric); color: var(--electric); }
  .preset-btn:hover:not(:disabled) { border-color: var(--text-dim); color: var(--text); }
  .preset-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .custom-input {
    width: 60px; background: var(--bg); border: 1px solid var(--border);
    color: var(--text-mid); font-size: 10px; padding: 4px 5px; border-radius: 4px;
    font-family: var(--font-mono);
  }
  .custom-input:focus { outline: none; border-color: var(--electric); }

  .bet-btns { display: flex; flex-direction: column; gap: 5px; }
  .bet-btn {
    display: flex; justify-content: space-between; align-items: center;
    background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
    padding: 6px 8px; font-family: var(--font-mono); font-size: 10px;
    cursor: pointer; transition: all 0.12s; text-align: left;
  }
  .bet-btn:hover:not(:disabled) { border-color: var(--text-dim); background: var(--card); }
  .bet-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .payout-hint { color: var(--text-dim); font-size: 9px; }

  .pending-note {
    font-size: 9px; color: var(--text-dim); display: flex; align-items: center; gap: 4px; flex-wrap: wrap;
  }
  .cancel-btn {
    background: none; border: 1px solid var(--border); color: var(--text-dim);
    font-size: 9px; padding: 1px 5px; border-radius: 3px; cursor: pointer;
    margin-left: auto;
  }
  .cancel-btn:hover { color: var(--fail); border-color: var(--fail); }

  .tally-bar {
    height: 3px; background: var(--border); border-radius: 2px; overflow: hidden;
  }
  .tally-a { height: 100%; border-radius: 2px; min-width: 2px; transition: width 0.3s; }
  .tally-labels {
    display: flex; justify-content: space-between; font-size: 8px; color: var(--text-dim);
  }
  .tally-total { color: var(--text-dim); font-size: 8px; }

  /* Bet history */
  .history-list { list-style: none; display: flex; flex-direction: column; gap: 2px; }
  .history-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 3px 6px; border-radius: 3px; font-size: 9px; background: var(--card);
    border-left: 2px solid var(--border);
  }
  .history-row.win  { border-left-color: #4ade80; }
  .history-row.loss { border-left-color: var(--fail); }
  .h-name { color: var(--text-mid); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
  .h-result { flex-shrink: 0; font-weight: 600; font-size: 10px; }
  .history-row.win  .h-result { color: #4ade80; }
  .history-row.loss .h-result { color: var(--fail); }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(-4px); }
    to   { opacity: 1; transform: translateY(0); }
  }
</style>
