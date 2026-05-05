<script lang="ts">
  import { onMount } from 'svelte';
  import { z } from 'zod';
  import { get } from '$lib/api/client';
  import { elementColor, tierColor } from '$lib/theme';

  // ---------------------------------------------------------------------------
  // Schemas
  // ---------------------------------------------------------------------------

  const ElementMatrixRowSchema = z.object({
    winner_element: z.string(), loser_element: z.string(), wins: z.number(),
  });
  const AbilityStatRowSchema = z.object({
    name: z.string(), type: z.string(), creature_count: z.number(), avg_energy_cost: z.number(),
  });
  const ExtinctCreatureSchema = z.object({
    id: z.string(), name: z.string(), tier: z.string(), element: z.string(),
    generation: z.number(), wins: z.number(), losses: z.number(),
    extinction_cause: z.string().nullable(), created_at: z.string(),
  });
  const PopulationDaySchema = z.object({
    date: z.string(), total: z.number(), active: z.number(),
    retired: z.number(), extinct: z.number(),
  });
  const SimStatsSchema = z.object({
    total_creatures: z.number(), active_creatures: z.number(), total_fights: z.number(),
    avg_fight_duration: z.number(), total_evolutions: z.number(), total_rivals: z.number(),
    total_extinct: z.number(), most_common_element: z.string().nullable(),
    most_common_tier: z.string().nullable(),
  });

  type ElementMatrixRow = z.infer<typeof ElementMatrixRowSchema>;
  type AbilityStatRow   = z.infer<typeof AbilityStatRowSchema>;
  type ExtinctCreature  = z.infer<typeof ExtinctCreatureSchema>;
  type PopulationDay    = z.infer<typeof PopulationDaySchema>;
  type SimStats         = z.infer<typeof SimStatsSchema>;

  // ---------------------------------------------------------------------------
  // Tab state
  // ---------------------------------------------------------------------------

  type Tab = 'matrix' | 'abilities' | 'extinction' | 'population' | 'simstats';
  let activeTab: Tab = 'simstats';

  // ---------------------------------------------------------------------------
  // Data state per tab
  // ---------------------------------------------------------------------------

  let matrix:    ElementMatrixRow[]  = [];
  let abilities: AbilityStatRow[]    = [];
  let extinct:   ExtinctCreature[]   = [];
  let population: PopulationDay[]    = [];
  let simStats:  SimStats | null     = null;

  let loading: Record<Tab, boolean> = {
    matrix: false, abilities: false, extinction: false, population: false, simstats: false,
  };
  let errors: Record<Tab, string> = {
    matrix: '', abilities: '', extinction: '', population: '', simstats: '',
  };

  // ---------------------------------------------------------------------------
  // Loaders (lazy — only fetch on first tab visit)
  // ---------------------------------------------------------------------------

  const loaded = new Set<Tab>();

  async function ensureLoaded(tab: Tab) {
    if (loaded.has(tab)) return;
    loaded.add(tab);
    loading[tab] = true;
    errors[tab]  = '';

    if (tab === 'simstats') {
      const r = await get('/analytics/sim-stats', SimStatsSchema);
      r.match((d) => { simStats = d; }, (e) => { errors.simstats = e.message; });
    } else if (tab === 'matrix') {
      const r = await get('/analytics/element-matrix', z.array(ElementMatrixRowSchema));
      r.match((d) => { matrix = d; }, (e) => { errors.matrix = e.message; });
    } else if (tab === 'abilities') {
      const r = await get('/analytics/ability-stats', z.array(AbilityStatRowSchema));
      r.match((d) => { abilities = d; }, (e) => { errors.abilities = e.message; });
    } else if (tab === 'extinction') {
      const r = await get('/analytics/extinction-log', z.array(ExtinctCreatureSchema));
      r.match((d) => { extinct = d; }, (e) => { errors.extinction = e.message; });
    } else if (tab === 'population') {
      const r = await get('/analytics/population', z.array(PopulationDaySchema));
      r.match((d) => { population = d; }, (e) => { errors.population = e.message; });
    }

    loading[tab] = false;
  }

  async function switchTab(tab: Tab) {
    activeTab = tab;
    await ensureLoaded(tab);
  }

  async function reload(tab: Tab) {
    loaded.delete(tab);
    await ensureLoaded(tab);
  }

  // ---------------------------------------------------------------------------
  // Element matrix helpers
  // ---------------------------------------------------------------------------

  const ELEMENTS = ['fire', 'void', 'nature', 'ice', 'electric'];

  function matrixWins(we: string, le: string): number {
    return matrix.find((r) => r.winner_element === we && r.loser_element === le)?.wins ?? 0;
  }

  function matrixMax(): number {
    return Math.max(1, ...matrix.map((r) => r.wins));
  }

  function heatColor(wins: number, max: number): string {
    if (wins === 0) return 'transparent';
    const t = wins / max;
    // lerp from border to pass
    const r = Math.round(37 + t * (34 - 37));
    const g = Math.round(40 + t * (197 - 40));
    const b = Math.round(80 + t * (94 - 80));
    return `rgba(${r},${g},${b},${0.2 + t * 0.75})`;
  }

  // ---------------------------------------------------------------------------
  // Population chart helpers
  // ---------------------------------------------------------------------------

  $: popMax = population.length ? Math.max(1, ...population.map((d) => d.total)) : 1;

  function barH(val: number, max: number, maxPx: number): number {
    return Math.max(1, (val / max) * maxPx);
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  onMount(() => ensureLoaded('simstats'));
</script>

<div class="analytics-page">

  <!-- Tab bar -->
  <div class="tab-bar">
    {#each [
      { id: 'simstats',   label: 'Sim Stats'     },
      { id: 'matrix',     label: 'Element Matrix' },
      { id: 'abilities',  label: 'Abilities'      },
      { id: 'extinction', label: 'Extinction Log' },
      { id: 'population', label: 'Population'     },
    ] as t}
      <button
        class="tab"
        class:active={activeTab === t.id}
        on:click={() => switchTab(t.id as Tab)}
      >{t.label}</button>
    {/each}
    <div class="tab-spacer"></div>
    <button class="btn-ghost sm" on:click={() => reload(activeTab)}>↺ Refresh</button>
  </div>

  <!-- Content -->
  <div class="content">

    <!-- ── Sim Stats ─────────────────────────────────────── -->
    {#if activeTab === 'simstats'}
      {#if loading.simstats}
        <p class="hint">Loading…</p>
      {:else if errors.simstats}
        <p class="hint err">{errors.simstats}</p>
      {:else if simStats}
        <div class="kpi-grid">
          <div class="kpi">
            <div class="kpi-val">{simStats.total_creatures}</div>
            <div class="kpi-label">Total Creatures</div>
          </div>
          <div class="kpi">
            <div class="kpi-val pass">{simStats.active_creatures}</div>
            <div class="kpi-label">Active Now</div>
          </div>
          <div class="kpi">
            <div class="kpi-val">{simStats.total_fights}</div>
            <div class="kpi-label">Fights Total</div>
          </div>
          <div class="kpi">
            <div class="kpi-val">{simStats.avg_fight_duration.toFixed(1)}</div>
            <div class="kpi-label">Avg Fight Duration (turns)</div>
          </div>
          <div class="kpi">
            <div class="kpi-val" style="color:var(--rare)">{simStats.total_evolutions}</div>
            <div class="kpi-label">Evolutions</div>
          </div>
          <div class="kpi">
            <div class="kpi-val" style="color:var(--void)">{simStats.total_rivals}</div>
            <div class="kpi-label">Rivals Spawned</div>
          </div>
          <div class="kpi">
            <div class="kpi-val fail">{simStats.total_extinct}</div>
            <div class="kpi-label">Extinctions</div>
          </div>
          {#if simStats.most_common_element}
            <div class="kpi">
              <div class="kpi-val" style="color:{elementColor(simStats.most_common_element)}">{simStats.most_common_element}</div>
              <div class="kpi-label">Most Common Element</div>
            </div>
          {/if}
          {#if simStats.most_common_tier}
            <div class="kpi">
              <div class="kpi-val" style="color:{tierColor(simStats.most_common_tier)}">{simStats.most_common_tier}</div>
              <div class="kpi-label">Most Common Tier</div>
            </div>
          {/if}
        </div>
      {:else}
        <p class="hint">No data yet.</p>
      {/if}

    <!-- ── Element Matrix ─────────────────────────────────── -->
    {:else if activeTab === 'matrix'}
      {#if loading.matrix}
        <p class="hint">Loading…</p>
      {:else if errors.matrix}
        <p class="hint err">{errors.matrix}</p>
      {:else if !matrix.length}
        <p class="hint">No fight data yet.</p>
      {:else}
        {@const mx = matrixMax()}
        <div class="matrix-wrap">
          <p class="matrix-caption dim">Rows = winner element · Columns = loser element · cell = win count</p>
          <table class="matrix-table">
            <thead>
              <tr>
                <th class="corner">W \ L</th>
                {#each ELEMENTS as el}
                  <th style="color:{elementColor(el)}">{el}</th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each ELEMENTS as we}
                <tr>
                  <td class="row-label" style="color:{elementColor(we)}">{we}</td>
                  {#each ELEMENTS as le}
                    {@const w = matrixWins(we, le)}
                    <td
                      class="matrix-cell"
                      class:self-match={we === le}
                      style="background:{we !== le ? heatColor(w, mx) : 'transparent'}"
                    >
                      {we === le ? '—' : w || ''}
                    </td>
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}

    <!-- ── Abilities ──────────────────────────────────────── -->
    {:else if activeTab === 'abilities'}
      {#if loading.abilities}
        <p class="hint">Loading…</p>
      {:else if errors.abilities}
        <p class="hint err">{errors.abilities}</p>
      {:else if !abilities.length}
        <p class="hint">No abilities yet.</p>
      {:else}
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ability</th><th>Type</th><th>Creatures</th><th>Avg Energy</th>
              </tr>
            </thead>
            <tbody>
              {#each abilities as a}
                <tr>
                  <td>{a.name}</td>
                  <td class="dim">{a.type}</td>
                  <td class="num">{a.creature_count}</td>
                  <td class="num dim">{a.avg_energy_cost}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}

    <!-- ── Extinction Log ─────────────────────────────────── -->
    {:else if activeTab === 'extinction'}
      {#if loading.extinction}
        <p class="hint">Loading…</p>
      {:else if errors.extinction}
        <p class="hint err">{errors.extinction}</p>
      {:else if !extinct.length}
        <p class="hint">No extinctions yet — the strong survive.</p>
      {:else}
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Name</th><th>Tier</th><th>El</th><th>Gen</th><th>W</th><th>L</th><th>Cause</th></tr>
            </thead>
            <tbody>
              {#each extinct as c}
                <tr>
                  <td>{c.name}</td>
                  <td style="color:{tierColor(c.tier)}">{c.tier}</td>
                  <td style="color:{elementColor(c.element)}">{c.element}</td>
                  <td class="num">{c.generation}</td>
                  <td class="num pass">{c.wins}</td>
                  <td class="num fail">{c.losses}</td>
                  <td class="dim">{c.extinction_cause ?? '—'}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}

    <!-- ── Population ────────────────────────────────────── -->
    {:else if activeTab === 'population'}
      {#if loading.population}
        <p class="hint">Loading…</p>
      {:else if errors.population}
        <p class="hint err">{errors.population}</p>
      {:else if !population.length}
        <p class="hint">No population data yet.</p>
      {:else}
        <div class="pop-wrap">
          <p class="dim" style="font-size:10px;padding:8px 16px">Creatures created per day (stacked: active · retired · extinct)</p>
          <div class="bar-chart">
            {#each population as day}
              {@const BAR_MAX = 120}
              {@const totalH = barH(day.total, popMax, BAR_MAX)}
              {@const activeH = barH(day.active, popMax, BAR_MAX)}
              {@const retiredH = barH(day.retired, popMax, BAR_MAX)}
              {@const extinctH = barH(day.extinct, popMax, BAR_MAX)}
              <div class="bar-col">
                <div class="bar-stack" style="height:{totalH}px">
                  <div class="bar-seg extinct"  style="flex:{day.extinct}"></div>
                  <div class="bar-seg retired"  style="flex:{day.retired}"></div>
                  <div class="bar-seg active"   style="flex:{day.active}"></div>
                </div>
                <div class="bar-label">{day.date.slice(5)}</div>
                <div class="bar-total">{day.total}</div>
              </div>
            {/each}
          </div>
          <div class="pop-legend">
            <span class="leg active">■ active</span>
            <span class="leg retired">■ retired</span>
            <span class="leg extinct">■ extinct</span>
          </div>
        </div>
      {/if}
    {/if}

  </div>
</div>

<style>
  .analytics-page {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  /* ── Tab bar ─────────────────────────────────────────────── */
  .tab-bar {
    display: flex;
    align-items: center;
    gap: 2px;
    padding: 0 12px;
    height: 40px;
    background: var(--card);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .tab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--text-dim);
    font-family: var(--font-mono);
    font-size: 11px;
    padding: 0 12px;
    height: 100%;
    cursor: pointer;
    transition: color 0.1s;
  }
  .tab:hover  { color: var(--text-mid); }
  .tab.active { color: var(--text); border-bottom-color: var(--uncommon); }
  .tab-spacer { flex: 1; }
  .btn-ghost {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 3px;
    color: var(--text-mid);
    font-family: var(--font-mono);
    font-size: 11px;
    padding: 2px 8px;
  }
  .btn-ghost.sm { padding: 1px 6px; font-size: 10px; }
  .btn-ghost:hover { border-color: var(--border-hi); color: var(--text); }

  /* ── Content area ────────────────────────────────────────── */
  .content {
    flex: 1;
    overflow: auto;
    padding: 20px;
  }

  .hint     { font-size: 12px; color: var(--text-dim); }
  .hint.err { color: var(--fail); }
  .dim      { color: var(--text-dim); }
  .pass     { color: var(--pass); }
  .fail     { color: var(--fail); }
  .num      { text-align: right; font-variant-numeric: tabular-nums; }

  /* ── KPI grid ────────────────────────────────────────────── */
  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 12px;
  }
  .kpi {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .kpi-val   { font-family: var(--font-disp); font-size: 28px; font-weight: 800; color: var(--text); }
  .kpi-label { font-size: 11px; color: var(--text-dim); }

  /* ── Element matrix ──────────────────────────────────────── */
  .matrix-wrap { overflow-x: auto; }
  .matrix-caption { font-size: 10px; margin-bottom: 10px; }
  .matrix-table { border-collapse: collapse; font-size: 12px; }
  .matrix-table th, .matrix-table td { padding: 6px 12px; text-align: center; }
  .matrix-table th { color: var(--text-dim); font-size: 10px; text-transform: uppercase; }
  .corner   { color: var(--text-dim) !important; font-size: 9px !important; }
  .row-label { text-align: right; font-size: 10px; text-transform: uppercase; }
  .matrix-cell { min-width: 40px; border-radius: 3px; font-variant-numeric: tabular-nums; }
  .self-match { color: var(--text-dim); }

  /* ── Tables ──────────────────────────────────────────────── */
  .table-wrap { overflow: auto; max-height: calc(100vh - 160px); }
  table { width: 100%; border-collapse: collapse; font-size: 11px; }
  th {
    text-align: left; color: var(--text-dim); font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.05em;
    padding: 6px 8px; border-bottom: 1px solid var(--border);
    position: sticky; top: 0; background: var(--bg);
  }
  td { padding: 5px 8px; border-bottom: 1px solid var(--border); }

  /* ── Population chart ────────────────────────────────────── */
  .pop-wrap { display: flex; flex-direction: column; }
  .bar-chart {
    display: flex;
    align-items: flex-end;
    gap: 6px;
    padding: 0 16px;
    height: 160px;
  }
  .bar-col {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    flex: 1;
    min-width: 30px;
    max-width: 60px;
  }
  .bar-stack {
    width: 100%;
    display: flex;
    flex-direction: column-reverse;
    border-radius: 2px 2px 0 0;
    overflow: hidden;
  }
  .bar-seg { min-height: 1px; }
  .bar-seg.active  { background: var(--pass);     opacity: 0.8; }
  .bar-seg.retired { background: var(--text-dim); opacity: 0.6; }
  .bar-seg.extinct { background: var(--fail);     opacity: 0.5; }
  .bar-label { font-size: 8px; color: var(--text-dim); white-space: nowrap; }
  .bar-total { font-size: 9px; color: var(--text-mid); }

  .pop-legend { display: flex; gap: 16px; padding: 8px 16px; font-size: 10px; }
  .leg.active  { color: var(--pass);     }
  .leg.retired { color: var(--text-dim); }
  .leg.extinct { color: var(--fail);     }
</style>
