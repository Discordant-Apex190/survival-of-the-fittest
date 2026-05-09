<script lang="ts">
  import { onMount } from 'svelte';
  import { z } from 'zod';
  import { get, post } from '$lib/api/client';
  import { elementColor, tierColor } from '$lib/theme';
  import { CreatureSummarySchema } from '$lib/schemas/creature';

  // ---------------------------------------------------------------------------
  // Schemas
  // ---------------------------------------------------------------------------

  const HealthSchema = z.object({
    status: z.string(),
    service: z.string(),
    environment: z.string(),
    debug: z.boolean(),
  });

  const GenerateResponseSchema = z.object({
    creature_id: z.string(),
    name: z.string(),
    tier: z.string(),
    element: z.string(),
    ability_count: z.number(),
    taunt_count: z.number(),
    retry_count: z.number(),
    graph_state: z.record(z.unknown()),
  });

  const TickResponseSchema = z.object({
    populate: z.object({ spawned: z.array(z.string()) }),
    fights: z.array(
      z.object({
        fight_id: z.string(),
        creature_a_id: z.string(),
        creature_b_id: z.string(),
        winner_id: z.string(),
        loser_id: z.string(),
        duration_turns: z.number(),
      }),
    ),
    resolve: z.object({
      evolved: z.array(z.string()),
      rival_triggered: z.array(z.string()),
      retired: z.array(z.string()),
    }),
    fight_count: z.number(),
    commentary_triggered: z.boolean(),
  });

  type Health = z.infer<typeof HealthSchema>;
  type GenResult = z.infer<typeof GenerateResponseSchema>;
  type TickResult = z.infer<typeof TickResponseSchema>;
  type Creature = z.infer<typeof CreatureSummarySchema>;

  // ---------------------------------------------------------------------------
  // Constants
  // ---------------------------------------------------------------------------

  const TIER_BUDGETS: Record<string, number> = {
    common: 80, uncommon: 100, rare: 125, legendary: 160,
  };
  const ELEMENTS = ['fire', 'void', 'nature', 'ice', 'electric'] as const;
  const TIERS    = ['common', 'uncommon', 'rare', 'legendary']   as const;

  // ---------------------------------------------------------------------------
  // Health
  // ---------------------------------------------------------------------------

  let health: Health | null = null;
  let healthErr = '';

  async function checkHealth() {
    health = null;
    healthErr = '';
    const r = await get('/health', HealthSchema);
    r.match(
      (d) => { health = d; },
      (e) => { healthErr = e.message; },
    );
  }

  // ---------------------------------------------------------------------------
  // Generation tester
  // ---------------------------------------------------------------------------

  let genTier: string    = 'common';
  let genElement: string = 'fire';
  let genArchetype       = 'warrior';
  let genBiome           = 'volcanic plains';
  let genLoading         = false;

  type GenEntry = { ts: string; result?: GenResult; error?: string };
  let genLog: GenEntry[] = [];

  $: genBudget = TIER_BUDGETS[genTier] ?? 80;

  $: latestValidationErrors =
    genLog[0]?.result
      ? ((genLog[0].result.graph_state['validation_errors'] as string[] | null) ?? [])
      : [];

  async function generate() {
    genLoading = true;
    const ts = new Date().toLocaleTimeString();
    const r = await post(
      '/creatures/generate',
      {
        seed_params: {
          element: genElement,
          tier: genTier,
          archetype: genArchetype,
          biome: genBiome,
          stat_budget: genBudget,
        },
      },
      GenerateResponseSchema,
    );
    r.match(
      (d) => { genLog = [{ ts, result: d }, ...genLog.slice(0, 19)]; },
      (e) => { genLog = [{ ts, error: e.message }, ...genLog.slice(0, 19)]; },
    );
    genLoading = false;
    loadCreatures();
  }

  // ---------------------------------------------------------------------------
  // Recent creatures
  // ---------------------------------------------------------------------------

  let creatures: Creature[] = [];
  let creaturesLoading = false;
  let creaturesErr = '';

  async function loadCreatures() {
    creaturesLoading = true;
    creaturesErr = '';
    const r = await get('/creatures?limit=30', z.array(CreatureSummarySchema));
    r.match(
      (d) => { creatures = d; },
      (e) => { creaturesErr = e.message; },
    );
    creaturesLoading = false;
  }

  // ---------------------------------------------------------------------------
  // Tick runner
  // ---------------------------------------------------------------------------

  let tickFights    = 3;
  let tickLoading   = false;

  type TickEntry = { ts: string; result?: TickResult; error?: string };
  let tickLog: TickEntry[] = [];

  async function runTick() {
    tickLoading = true;
    const ts = new Date().toLocaleTimeString();
    const r = await post('/simulation/tick', { fights_per_tick: tickFights }, TickResponseSchema);
    r.match(
      (d) => {
        tickLog = [{ ts, result: d }, ...tickLog.slice(0, 9)];
        loadCreatures();
      },
      (e) => { tickLog = [{ ts, error: e.message }, ...tickLog.slice(0, 9)]; },
    );
    tickLoading = false;
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  onMount(async () => {
    await Promise.all([checkHealth(), loadCreatures()]);
  });
</script>

<div class="debug-page">

  <!-- ─── Status bar ─────────────────────────────────────────────────── -->
  <div class="status-bar">
    <span class="status-label">DEBUG</span>
    {#if health}
      <span class="badge pass">{health.status}</span>
      <span class="status-text">{health.service} · {health.environment}</span>
      {#if health.debug}<span class="badge retry">debug=true</span>{/if}
    {:else if healthErr}
      <span class="badge fail">backend unreachable</span>
      <span class="status-text err">{healthErr}</span>
    {:else}
      <span class="status-text dim">checking…</span>
    {/if}
    <button class="btn-ghost" on:click={checkHealth}>↺ health</button>
    <span class="spacer"></span>
    <span class="status-text dim">{creatures.length} creatures in DB</span>
  </div>

  <!-- ─── Two-column body ────────────────────────────────────────────── -->
  <div class="body">

    <!-- LEFT: generate tester + log -->
    <div class="col">

      <!-- Generate form -->
      <div class="panel">
        <div class="panel-head">Generate Creature</div>
        <div class="form-grid">
          <label>
            <span>Tier</span>
            <select bind:value={genTier}>
              {#each TIERS as t}
                <option value={t} style="color: var(--{t})">{t}</option>
              {/each}
            </select>
          </label>
          <label>
            <span>Element</span>
            <select bind:value={genElement}>
              {#each ELEMENTS as el}
                <option value={el} style="color: var(--{el})">{el}</option>
              {/each}
            </select>
          </label>
          <label>
            <span>Archetype</span>
            <input type="text" bind:value={genArchetype} placeholder="e.g. warrior" />
          </label>
          <label>
            <span>Biome</span>
            <input type="text" bind:value={genBiome} placeholder="e.g. volcanic plains" />
          </label>
          <label class="readonly">
            <span>stat_budget</span>
            <input type="text" readonly value={genBudget} />
          </label>
        </div>
        <button
          class="btn-primary"
          on:click={generate}
          disabled={genLoading || !genArchetype.trim() || !genBiome.trim()}
        >
          {genLoading ? 'Generating…' : 'Generate'}
        </button>
      </div>

      <!-- Generation log -->
      <div class="panel grow">
        <div class="panel-head">Generation Log <span class="dim">({genLog.length})</span></div>
        {#if genLog.length === 0}
          <p class="empty">No generations yet this session.</p>
        {:else}
          <div class="log-list">
            {#each genLog as entry, i}
              <div class="log-entry" class:log-err={!!entry.error} class:log-ok={!!entry.result}>
                <div class="log-row">
                  <span class="log-ts">{entry.ts}</span>
                  {#if entry.result}
                    <span class="log-name" style="color:{tierColor(entry.result.tier)}">{entry.result.name}</span>
                    <span class="log-meta" style="color:{elementColor(entry.result.element)}">{entry.result.element}</span>
                    <span class="log-meta" style="color:{tierColor(entry.result.tier)}">{entry.result.tier}</span>
                    {#if entry.result.retry_count > 0}
                      <span class="badge retry">{entry.result.retry_count} retr{entry.result.retry_count === 1 ? 'y' : 'ies'}</span>
                    {:else}
                      <span class="badge pass">clean</span>
                    {/if}
                    <span class="log-meta dim">{entry.result.ability_count} abilities · {entry.result.taunt_count} taunts</span>
                  {:else}
                    <span class="badge fail">FAILED</span>
                    <span class="log-err-msg">{entry.error}</span>
                  {/if}
                </div>
                {#if i === 0 && entry.result}
                  {@const errs = (entry.result.graph_state['validation_errors'] as string[] | null) ?? []}
                  {#if errs.length > 0}
                    <div class="val-errors">
                      {#each errs as e}
                        <div class="val-err">⚠ {e}</div>
                      {/each}
                    </div>
                  {/if}
                  <div class="log-id dim">{entry.result.creature_id}</div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      </div>

    </div>

    <!-- RIGHT: tick runner + creature table -->
    <div class="col">

      <!-- Tick runner -->
      <div class="panel">
        <div class="panel-head">Simulation Tick</div>
        <div class="tick-controls">
          <label>
            <span>fights / tick</span>
            <input type="range" min="1" max="10" bind:value={tickFights} />
            <span class="tick-val">{tickFights}</span>
          </label>
          <button class="btn-primary" on:click={runTick} disabled={tickLoading}>
            {tickLoading ? 'Running…' : 'Run Tick'}
          </button>
        </div>

        {#if tickLog.length > 0}
          <div class="tick-log">
            {#each tickLog as entry}
              <div class="tick-entry" class:tick-err={!!entry.error}>
                <span class="log-ts">{entry.ts}</span>
                {#if entry.result}
                  <span class="badge pass">{entry.result.fight_count} fights</span>
                  {#if entry.result.populate.spawned.length > 0}
                    <span class="badge retry">+{entry.result.populate.spawned.length} spawned</span>
                  {/if}
                  {#if entry.result.resolve.evolved.length > 0}
                    <span class="badge" style="color:var(--rare);border-color:var(--rare)">↑ {entry.result.resolve.evolved.length} evolved</span>
                  {/if}
                  {#if entry.result.resolve.rival_triggered.length > 0}
                    <span class="badge" style="color:var(--void);border-color:var(--void)">⚔ rival</span>
                  {/if}
                  {#if entry.result.resolve.retired.length > 0}
                    <span class="badge" style="color:var(--text-dim);border-color:var(--border)">✕ {entry.result.resolve.retired.length} retired</span>
                  {/if}
                  {#if entry.result.commentary_triggered}
                    <span class="badge" style="color:var(--electric);border-color:var(--electric)">📜 commentary</span>
                  {/if}
                {:else}
                  <span class="badge fail">ERROR</span>
                  <span class="log-err-msg">{entry.error}</span>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      </div>

      <!-- Creature table -->
      <div class="panel grow">
        <div class="panel-head">
          Creatures
          <button class="btn-ghost sm" on:click={loadCreatures} disabled={creaturesLoading}>
            {creaturesLoading ? '…' : '↺'}
          </button>
        </div>
        {#if creaturesErr}
          <p class="empty err">{creaturesErr}</p>
        {:else if creatures.length === 0}
          <p class="empty">No creatures found.</p>
        {:else}
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Tier</th>
                  <th>El</th>
                  <th>Gen</th>
                  <th>W</th>
                  <th>L</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {#each creatures as c}
                  <tr class:retired={c.status === 'retired'} class:extinct={c.status === 'extinct'}>
                    <td class="name-cell">{c.name}</td>
                    <td style="color:{tierColor(c.tier)}">{c.tier}</td>
                    <td style="color:{elementColor(c.element)}">{c.element}</td>
                    <td class="num">{c.generation}</td>
                    <td class="num pass">{c.wins}</td>
                    <td class="num fail">{c.losses}</td>
                    <td><span class="status-chip status-{c.status}">{c.status}</span></td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>

    </div>
  </div>
</div>

<style>
  .debug-page {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  /* ── Status bar ─────────────────────────────────────────── */
  .status-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 16px;
    height: 36px;
    background: var(--card);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    font-size: 11px;
  }
  .status-label {
    font-family: var(--font-disp);
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.08em;
    color: var(--retry);
  }
  .status-text { color: var(--text-mid); }
  .status-text.err { color: var(--fail); }
  .status-text.dim { color: var(--text-dim); }
  .spacer { flex: 1; }

  /* ── Layout ─────────────────────────────────────────────── */
  .body {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    padding: 12px;
    overflow: hidden;
    flex: 1;
  }
  .col {
    display: flex;
    flex-direction: column;
    gap: 12px;
    overflow: hidden;
  }

  /* ── Panel ──────────────────────────────────────────────── */
  .panel {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    flex-shrink: 0;
  }
  .panel.grow {
    flex: 1;
    overflow: hidden;
  }
  .panel-head {
    font-family: var(--font-disp);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: var(--text-mid);
    text-transform: uppercase;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .panel-head .dim { color: var(--text-dim); font-weight: 400; }

  /* ── Form ───────────────────────────────────────────────── */
  .form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 11px;
    color: var(--text-dim);
  }
  label span { font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; }
  input, select {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 3px;
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 12px;
    padding: 4px 6px;
    outline: none;
  }
  input:focus, select:focus { border-color: var(--border-hi); }
  label.readonly input { color: var(--text-dim); }

  /* ── Buttons ────────────────────────────────────────────── */
  .btn-primary {
    background: var(--border-hi);
    border: 1px solid var(--border-hi);
    border-radius: 4px;
    color: var(--text);
    font-size: 12px;
    padding: 6px 14px;
    transition: background 0.1s;
    align-self: flex-start;
  }
  .btn-primary:hover:not(:disabled) { background: #4a506a; }
  .btn-primary:disabled { opacity: 0.4; cursor: default; }
  .btn-ghost {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 3px;
    color: var(--text-mid);
    font-size: 11px;
    padding: 2px 8px;
  }
  .btn-ghost:hover { border-color: var(--border-hi); color: var(--text); }
  .btn-ghost.sm { padding: 1px 6px; font-size: 10px; }

  /* ── Badges ─────────────────────────────────────────────── */
  .badge {
    display: inline-block;
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 3px;
    border: 1px solid currentColor;
    white-space: nowrap;
  }
  .badge.pass  { color: var(--pass); }
  .badge.fail  { color: var(--fail); }
  .badge.retry { color: var(--retry); }

  /* ── Generation log ─────────────────────────────────────── */
  .log-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
    overflow-y: auto;
    flex: 1;
  }
  .log-entry {
    padding: 6px 8px;
    border-radius: 4px;
    border-left: 2px solid var(--border);
    background: var(--bg);
    font-size: 11px;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .log-entry.log-ok  { border-left-color: var(--pass); }
  .log-entry.log-err { border-left-color: var(--fail); }
  .log-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .log-ts   { color: var(--text-dim); font-size: 10px; min-width: 60px; }
  .log-name { font-weight: 600; }
  .log-meta { font-size: 10px; }
  .log-meta.dim { color: var(--text-dim); }
  .log-err-msg { color: var(--fail); font-size: 11px; }
  .log-id  { font-size: 9px; }
  .val-errors { display: flex; flex-direction: column; gap: 2px; }
  .val-err { color: var(--retry); font-size: 10px; }
  .empty { color: var(--text-dim); font-size: 11px; padding: 8px 0; }
  .empty.err { color: var(--fail); }
  .dim { color: var(--text-dim); }

  /* ── Tick controls ──────────────────────────────────────── */
  .tick-controls {
    display: flex;
    align-items: center;
    gap: 16px;
  }
  .tick-controls label {
    flex-direction: row;
    align-items: center;
    gap: 8px;
  }
  .tick-controls label span { font-size: 11px; color: var(--text-mid); text-transform: none; letter-spacing: 0; }
  .tick-val { min-width: 16px; text-align: right; color: var(--text); }
  input[type='range'] {
    accent-color: var(--border-hi);
    width: 80px;
    padding: 0;
    border: none;
    background: transparent;
  }
  .tick-log {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .tick-entry {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    font-size: 11px;
    padding: 3px 0;
    border-top: 1px solid var(--border);
  }
  .tick-entry.tick-err .log-err-msg { color: var(--fail); }

  /* ── Creature table ─────────────────────────────────────── */
  .table-wrap {
    overflow-y: auto;
    flex: 1;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
  }
  th {
    text-align: left;
    color: var(--text-dim);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 4px 6px;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    background: var(--card);
  }
  td {
    padding: 4px 6px;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
  }
  tr:last-child td { border-bottom: none; }
  tr.retired td { opacity: 0.5; }
  tr.extinct td { opacity: 0.35; text-decoration: line-through; }
  .name-cell { color: var(--text); max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .num.pass { color: var(--pass); }
  .num.fail { color: var(--fail); }
  .status-chip {
    font-size: 9px;
    padding: 1px 5px;
    border-radius: 2px;
    border: 1px solid var(--border);
    color: var(--text-dim);
  }
  .status-chip.status-active   { color: var(--pass);     border-color: var(--pass); }
  .status-chip.status-retired  { color: var(--text-dim); }
  .status-chip.status-extinct  { color: var(--fail);     border-color: var(--fail); }
</style>
