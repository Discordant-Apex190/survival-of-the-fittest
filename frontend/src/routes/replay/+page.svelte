<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { z } from 'zod';
  import { get } from '$lib/api/client';
  import { FightSummarySchema, FightDetailSchema, FightEventSchema } from '$lib/schemas/fight';
  import type { FightSummary, FightDetail, FightEvent } from '$lib/schemas/fight';
  import { elementColor } from '$lib/theme';

  const REPLAY_PREFS_KEY = 'sotf_replay_prefs_v1';

  interface ReplayPrefs {
    playbackSpeed: number;
    eventSearch: string;
    activeEventTypes: string[];
    bookmarksByFight: Record<string, number[]>;
  }

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  let fights: FightSummary[]  = [];
  let selected: FightDetail | null = null;
  let events: FightEvent[]    = [];
  let turn = 0;                       // current scrub position (0 = start)
  let autoPlay = false;
  let autoInterval: ReturnType<typeof setInterval> | null = null;
  let playbackSpeed = 1;
  let bookmarkTurns: number[] = [];
  let eventSearch = '';
  let activeEventTypes: string[] = [];
  let bookmarksByFight: Record<string, number[]> = {};
  let prefsLoaded = false;

  let fightsLoading = true;
  let detailLoading = false;
  let fightsErr     = '';
  let detailErr     = '';

  let offset = 0;
  const LIMIT = 40;
  let hasMore = true;
  let loadingMore = false;

  // ---------------------------------------------------------------------------
  // Derived: all events up to current turn
  // ---------------------------------------------------------------------------

  $: maxTurn = events.length ? Math.max(...events.map((e) => e.turn)) : 0;
  $: visibleEvents = events.filter((e) => e.turn <= turn).slice().reverse();
  $: availableEventTypes = [...new Set(events.map((e) => e.event_type))].sort();
  $: filteredEvents = visibleEvents.filter((e) => {
    const typeMatch = activeEventTypes.length === 0 || activeEventTypes.includes(e.event_type);
    const q = eventSearch.trim().toLowerCase();
    if (!q) return typeMatch;
    const searchBlob = `${e.event_type} ${e.ability_name ?? ''} ${e.actor_id ?? ''} ${e.target_id ?? ''}`.toLowerCase();
    return typeMatch && searchBlob.includes(q);
  });
  $: turnsByIdx = [...new Set(events.map((e) => e.turn))].sort((a, b) => a - b);

  // HP snapshot at current turn — last hp_remaining that contains each creature
  $: hpSnap = (() => {
    const snap: Record<string, number> = {};
    for (const e of events.filter((ev) => ev.turn <= turn)) {
      for (const [id, hp] of Object.entries(e.hp_remaining)) {
        snap[id] = hp;
      }
    }
    return snap;
  })();

  $: if (prefsLoaded) {
    saveReplayPrefs();
  }

  // ---------------------------------------------------------------------------
  // Load fight list
  // ---------------------------------------------------------------------------

  async function loadFights(append = false) {
    if (!append) { fightsLoading = true; fights = []; offset = 0; hasMore = true; }
    else { loadingMore = true; }
    fightsErr = '';
    const r = await get(`/fights?offset=${offset}&limit=${LIMIT}`, z.array(FightSummarySchema));
    r.match(
      (d) => {
        fights = append ? [...fights, ...d] : d;
        hasMore = d.length === LIMIT;
        offset += d.length;
      },
      (e) => { fightsErr = e.message; },
    );
    if (!append) fightsLoading = false;
    else loadingMore = false;
  }

  // ---------------------------------------------------------------------------
  // Select fight → load detail + events
  // ---------------------------------------------------------------------------

  async function selectFight(id: string) {
    stopAutoPlay();
    detailLoading = true;
    detailErr = '';
    selected = null;
    events = [];
    turn = 0;
    bookmarkTurns = bookmarksByFight[id] ? [...bookmarksByFight[id]] : [];

    const [dRes, evRes] = await Promise.all([
      get(`/fights/${id}`, FightDetailSchema),
      get(`/fights/${id}/events`, z.array(FightEventSchema)),
    ]);

    dRes.match(
      (d) => { selected = d; },
      (e) => { detailErr = e.message; },
    );
    evRes.match(
      (e) => { events = e; turn = 0; },
      () => {},
    );
    detailLoading = false;
  }

  // ---------------------------------------------------------------------------
  // Auto-play
  // ---------------------------------------------------------------------------

  function toggleAutoPlay() {
    if (autoPlay) stopAutoPlay();
    else startAutoPlay();
  }

  function startAutoPlay() {
    if (!events.length) return;
    autoPlay = true;
    const intervalMs = Math.max(80, Math.round(300 / playbackSpeed));
    autoInterval = setInterval(() => {
      if (turn >= maxTurn) { stopAutoPlay(); return; }
      turn += 1;
    }, intervalMs);
  }

  function stopAutoPlay() {
    autoPlay = false;
    if (autoInterval) { clearInterval(autoInterval); autoInterval = null; }
  }

  function toggleBookmark(value: number) {
    if (bookmarkTurns.includes(value)) {
      bookmarkTurns = bookmarkTurns.filter((v) => v !== value);
      syncBookmarksForSelectedFight();
      return;
    }
    bookmarkTurns = [...bookmarkTurns, value].sort((a, b) => a - b);
    syncBookmarksForSelectedFight();
  }

  function toggleEventTypeFilter(eventType: string) {
    if (activeEventTypes.includes(eventType)) {
      activeEventTypes = activeEventTypes.filter((v) => v !== eventType);
      return;
    }
    activeEventTypes = [...activeEventTypes, eventType];
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  function fmtTime(iso: string) {
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  }

  function eventLabel(e: FightEvent): string {
    if (e.event_type === 'ability_use') return `${e.ability_name ?? '?'} → -${e.damage ?? 0}hp`;
    if (e.event_type === 'ko')          return `KO`;
    if (e.event_type === 'turn_start')  return `Turn ${e.turn} start`;
    return e.event_type;
  }

  function hpPct(hp: number, maxHp: number): number {
    return Math.max(0, Math.min(100, (hp / maxHp) * 100));
  }

  function syncBookmarksForSelectedFight() {
    if (!selected?.id) return;
    bookmarksByFight = {
      ...bookmarksByFight,
      [selected.id]: [...bookmarkTurns],
    };
  }

  function loadReplayPrefs() {
    if (typeof localStorage === 'undefined') return;
    try {
      const raw = localStorage.getItem(REPLAY_PREFS_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as ReplayPrefs;
      playbackSpeed = typeof parsed.playbackSpeed === 'number' ? parsed.playbackSpeed : 1;
      eventSearch = parsed.eventSearch ?? '';
      activeEventTypes = Array.isArray(parsed.activeEventTypes) ? parsed.activeEventTypes : [];
      bookmarksByFight = parsed.bookmarksByFight ?? {};
    } catch {
      // Ignore malformed local preferences and continue with defaults.
    }
  }

  function saveReplayPrefs() {
    if (typeof localStorage === 'undefined') return;
    const payload: ReplayPrefs = {
      playbackSpeed,
      eventSearch,
      activeEventTypes,
      bookmarksByFight,
    };
    localStorage.setItem(REPLAY_PREFS_KEY, JSON.stringify(payload));
  }

  onMount(() => {
    loadReplayPrefs();
    prefsLoaded = true;
    void loadFights();
  });
  onDestroy(() => stopAutoPlay());
</script>

<div class="replay-page">

  <!-- Fight list -->
  <div class="list-col">
    <div class="col-head">
      Fights
      <button class="btn-ghost sm" on:click={() => loadFights()}>↺</button>
    </div>

    {#if fightsLoading}
      <p class="hint">Loading…</p>
    {:else if fightsErr}
      <p class="hint err">{fightsErr}</p>
    {:else if !fights.length}
      <p class="hint">No fights recorded yet.</p>
    {:else}
      <div class="fight-list">
        {#each fights as f}
          <button
            class="fight-row"
            class:active={selected?.id === f.id}
            on:click={() => selectFight(f.id)}
            aria-label={`Open replay for fight ${f.id}`}
          >
            <span class="fight-tier">{f.tier}</span>
            <span class="fight-turns dim">{f.duration_turns}t</span>
            <span class="fight-time dim">{fmtTime(f.created_at).split(',')[0]}</span>
          </button>
        {/each}
        {#if hasMore}
          <button class="btn-more" on:click={() => loadFights(true)} disabled={loadingMore}>
            {loadingMore ? 'Loading…' : 'Load more'}
          </button>
        {/if}
      </div>
    {/if}
  </div>

  <!-- Replay panel -->
  <div class="replay-col">
    {#if !selected && !detailLoading}
      <div class="empty-state">
        <span>← Select a fight to replay</span>
      </div>
    {:else if detailLoading}
      <div class="empty-state"><span>Loading fight…</span></div>
    {:else if detailErr}
      <div class="empty-state err">{detailErr}</div>
    {:else if selected}
      <!-- Combatant header -->
      <div class="combatants">
        <div class="combatant">
          <span class="c-name" style="color:{elementColor(selected.creature_a_element)}">
            {selected.creature_a_name}
          </span>
          <span class="c-elem">{selected.creature_a_element}</span>
          {#if hpSnap[selected.creature_a_id] !== undefined}
            <div class="hp-bar-wrap">
              <div class="hp-bar" style="width:{hpPct(hpSnap[selected.creature_a_id], 100)}%"></div>
            </div>
            <span class="hp-num">{hpSnap[selected.creature_a_id]}hp</span>
          {/if}
          {#if selected.winner_id === selected.creature_a_id && turn >= maxTurn}
            <span class="badge-win">WIN</span>
          {/if}
        </div>

        <div class="vs-block">
          <span class="vs">vs</span>
          <span class="turn-label">T{turn}/{maxTurn}</span>
        </div>

        <div class="combatant right">
          <span class="c-name" style="color:{elementColor(selected.creature_b_element)}">
            {selected.creature_b_name}
          </span>
          <span class="c-elem">{selected.creature_b_element}</span>
          {#if hpSnap[selected.creature_b_id] !== undefined}
            <div class="hp-bar-wrap">
              <div class="hp-bar" style="width:{hpPct(hpSnap[selected.creature_b_id], 100)}%"></div>
            </div>
            <span class="hp-num">{hpSnap[selected.creature_b_id]}hp</span>
          {/if}
          {#if selected.winner_id === selected.creature_b_id && turn >= maxTurn}
            <span class="badge-win">WIN</span>
          {/if}
        </div>
      </div>

      <!-- Scrubber -->
      {#if events.length}
        <div class="scrubber">
          <button class="btn-ctrl" aria-label="Jump to start" on:click={() => { stopAutoPlay(); turn = 0; }}>⏮</button>
          <button class="btn-ctrl" aria-label="Previous turn" on:click={() => { stopAutoPlay(); turn = Math.max(0, turn - 1); }}>◀</button>
          <button class="btn-ctrl play" aria-label={autoPlay ? 'Pause replay autoplay' : 'Start replay autoplay'} on:click={toggleAutoPlay}>
            {autoPlay ? '⏸' : '▶'}
          </button>
          <button class="btn-ctrl" aria-label="Next turn" on:click={() => { stopAutoPlay(); turn = Math.min(maxTurn, turn + 1); }}>▶</button>
          <button class="btn-ctrl" aria-label="Jump to end" on:click={() => { stopAutoPlay(); turn = maxTurn; }}>⏭</button>
          <input
            type="range"
            min="0"
            max={maxTurn}
            bind:value={turn}
            on:input={stopAutoPlay}
            aria-label="Replay turn scrubber"
            class="scrub-range"
          />
          <select bind:value={playbackSpeed} class="speed-select" aria-label="Replay speed">
            <option value={0.5}>0.5x</option>
            <option value={1}>1x</option>
            <option value={1.5}>1.5x</option>
            <option value={2}>2x</option>
          </select>
          <button class="btn-ctrl" aria-label="Toggle bookmark for current turn" on:click={() => toggleBookmark(turn)}>★</button>
        </div>

        <div class="replay-tools">
          <input
            class="event-search"
            type="search"
            bind:value={eventSearch}
            placeholder="Search events"
            aria-label="Search replay events"
          />
          <div class="event-filters" role="group" aria-label="Event type filters">
            {#each availableEventTypes as eventType}
              <button
                class="filter-chip"
                class:active={activeEventTypes.includes(eventType)}
                on:click={() => toggleEventTypeFilter(eventType)}
                aria-label={`Toggle ${eventType} filter`}
              >
                {eventType}
              </button>
            {/each}
          </div>
          {#if bookmarkTurns.length > 0}
            <div class="bookmark-row" role="group" aria-label="Replay bookmarks">
              {#each bookmarkTurns as bookmarkTurn}
                <button class="bookmark-chip" on:click={() => { stopAutoPlay(); turn = bookmarkTurn; }}>
                  T{bookmarkTurn}
                </button>
              {/each}
            </div>
          {/if}
        </div>
      {:else}
        <p class="hint">No events recorded for this fight.</p>
      {/if}

      <!-- Event log -->
      <div class="event-log" role="log" aria-live="polite" aria-atomic="false">
        {#if filteredEvents.length === 0}
          <p class="hint">No events match current filters.</p>
        {:else}
        {#each filteredEvents as e}
          <div class="ev-row ev-{e.event_type}" class:ev-latest={e.turn === turn}>
            <span class="ev-turn">T{e.turn}</span>
            <span class="ev-type">{e.event_type}</span>
            <span class="ev-label">{eventLabel(e)}</span>
            {#if e.actor_id}
              <span class="ev-actor dim">{e.actor_id.slice(0, 8)}</span>
            {/if}
          </div>
        {/each}
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .replay-page {
    display: grid;
    grid-template-columns: 220px 1fr;
    height: 100%;
    overflow: hidden;
    gap: 1px;
    background: var(--border);
  }

  /* ── List column ─────────────────────────────────────────── */
  .list-col {
    background: var(--bg);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .col-head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    height: 36px;
    font-size: 9px;
    font-weight: 500;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .fight-list { overflow-y: auto; flex: 1; }
  .fight-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 12px;
    cursor: pointer;
    width: 100%;
    background: transparent;
    border: none;
    text-align: left;
    border-bottom: 1px solid var(--border);
    font-size: 11px;
    transition: background 0.1s;
  }
  .fight-row:hover   { background: var(--card); }
  .fight-row.active  { background: var(--card); border-left: 2px solid var(--uncommon); }
  .fight-tier { color: var(--text); min-width: 64px; }
  .fight-turns, .fight-time { color: var(--text-dim); font-size: 10px; }
  .btn-more {
    width: 100%;
    background: transparent;
    border: none;
    border-top: 1px solid var(--border);
    color: var(--text-dim);
    font-size: 11px;
    padding: 8px;
  }
  .btn-more:hover:not(:disabled) { color: var(--text); }

  /* ── Replay column ───────────────────────────────────────── */
  .replay-col {
    background: var(--bg);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .empty-state {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-dim);
    font-size: 12px;
  }
  .empty-state.err { color: var(--fail); }

  /* Combatants */
  .combatants {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 16px;
    padding: 14px 20px;
    background: var(--card);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .combatant {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .combatant.right { align-items: flex-end; }
  .c-name { font-size: 13px; font-weight: 700; }
  .c-elem { font-size: 10px; color: var(--text-dim); }
  .hp-bar-wrap { width: 100%; height: 4px; background: var(--border); border-radius: 2px; }
  .hp-bar { height: 4px; background: var(--pass); border-radius: 2px; transition: width 0.2s; }
  .hp-num { font-size: 10px; color: var(--text-dim); }
  .badge-win {
    font-size: 9px;
    color: var(--electric);
    border: 1px solid var(--electric);
    padding: 1px 5px;
    border-radius: 2px;
    align-self: flex-start;
  }
  .vs-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    font-size: 11px;
    color: var(--text-dim);
  }
  .turn-label { font-size: 10px; color: var(--retry); }

  /* Scrubber */
  .scrubber {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .btn-ctrl {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 3px;
    color: var(--text-mid);
    font-size: 12px;
    width: 28px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .btn-ctrl:hover { border-color: var(--border-hi); color: var(--text); }
  .btn-ctrl.play { color: var(--pass); }
  .scrub-range {
    flex: 1;
    accent-color: var(--uncommon);
    height: 4px;
    background: transparent;
    border: none;
    padding: 0;
  }

  .speed-select {
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text-mid);
    font-size: 10px;
    border-radius: 4px;
    padding: 3px 6px;
  }

  .replay-tools {
    border-bottom: 1px solid var(--border);
    padding: 8px 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .event-search {
    width: 100%;
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 4px;
    font-size: 11px;
    padding: 5px 8px;
  }

  .event-filters,
  .bookmark-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .filter-chip,
  .bookmark-chip {
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text-mid);
    border-radius: 999px;
    font-size: 10px;
    padding: 3px 8px;
  }

  .filter-chip.active {
    border-color: var(--uncommon);
    color: var(--uncommon);
  }

  /* Event log */
  .event-log {
    flex: 1;
    overflow-y: auto;
    padding: 8px 0;
  }
  .ev-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 16px;
    font-size: 11px;
    border-left: 2px solid transparent;
  }
  .ev-row.ev-latest { background: var(--card); border-left-color: var(--uncommon); }
  .ev-turn { color: var(--text-dim); font-size: 10px; min-width: 28px; }
  .ev-type { color: var(--text-dim); font-size: 9px; text-transform: uppercase; min-width: 72px; }
  .ev-label { color: var(--text); flex: 1; }
  .ev-actor { font-size: 9px; }
  .ev-row.ev-ko .ev-label { color: var(--fail); font-weight: 700; }

  /* Shared */
  .hint { font-size: 11px; color: var(--text-dim); padding: 12px 16px; }
  .hint.err { color: var(--fail); }
  .dim { color: var(--text-dim); }

  .btn-ghost {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 3px;
    color: var(--text-mid);
    font-size: 11px;
    padding: 2px 8px;
  }
  .btn-ghost.sm { padding: 1px 5px; font-size: 10px; }

  @media (max-width: 960px) {
    .replay-page {
      grid-template-columns: 1fr;
      grid-template-rows: 180px 1fr;
    }

    .list-col {
      border-bottom: 1px solid var(--border);
    }

    .fight-list {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1px;
      align-content: start;
    }

    .scrubber {
      flex-wrap: wrap;
      gap: 4px;
      padding: 8px 10px;
    }

    .btn-ctrl {
      width: 26px;
      height: 22px;
      font-size: 11px;
    }

    .speed-select {
      font-size: 9px;
      padding: 2px 5px;
    }

    .replay-tools {
      padding: 8px 10px;
      gap: 6px;
    }

    .ev-row {
      padding: 4px 10px;
      gap: 7px;
    }

    .ev-type {
      min-width: 58px;
    }

    .combatants {
      padding: 12px;
      gap: 10px;
    }

    .c-name {
      font-size: 12px;
    }
  }
</style>
