<script lang="ts">
  import { onMount } from 'svelte';
  import { z } from 'zod';
  import { get, post } from '$lib/api/client';
  import { CreatureDetailSchema, CreatureSummarySchema } from '$lib/schemas/creature';
  import { elementColor, tierColor } from '$lib/theme';

  const ELEMENTS = ['fire', 'void', 'nature', 'ice', 'electric'] as const;
  const TIERS = ['common', 'uncommon', 'rare', 'legendary'] as const;
  const TIER_BUDGETS: Record<string, number> = {
    common: 80,
    uncommon: 100,
    rare: 125,
    legendary: 160,
  };

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

  type GenerateResponse = z.infer<typeof GenerateResponseSchema>;
  type CreatureDetail = z.infer<typeof CreatureDetailSchema>;
  type CreatureSummary = z.infer<typeof CreatureSummarySchema>;

  let preferredName = '';
  let genTier = 'common';
  let genElement = 'fire';
  let genArchetype = 'warrior';
  let genBiome = 'volcanic plains';
  let showStatPreview = true;

  let generating = false;
  let errorMessage = '';
  let latest: GenerateResponse | null = null;
  let latestDetail: CreatureDetail | null = null;
  let activeCreatures: CreatureSummary[] = [];

  $: genBudget = TIER_BUDGETS[genTier] ?? 80;
  $: latestCreatureId = latest?.creature_id ?? '';
  $: createdInActivePool = latestCreatureId
    ? activeCreatures.some((creature) => creature.id === latestCreatureId)
    : false;

  async function loadActiveCreatures(): Promise<void> {
    const result = await get('/creatures?limit=30&status=active', z.array(CreatureSummarySchema));
    result.match(
      (creatures) => {
        activeCreatures = creatures;
      },
      () => {
        activeCreatures = [];
      },
    );
  }

  async function generateCreature(): Promise<void> {
    generating = true;
    errorMessage = '';
    latest = null;
    latestDetail = null;

    const response = await post(
      '/creatures/generate',
      {
        preferred_name: preferredName.trim() || undefined,
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

    await response.match(
      async (payload) => {
        latest = payload;

        if (showStatPreview) {
          const detailResult = await get(`/creatures/${payload.creature_id}`, CreatureDetailSchema);
          detailResult.match(
            (detail) => {
              latestDetail = detail;
            },
            (err) => {
              errorMessage = `Could not load stat preview: ${err.message}`;
            },
          );
        }

        await loadActiveCreatures();
      },
      (err) => {
        errorMessage = err.message;
      },
    );

    generating = false;
  }

  onMount(async () => {
    await loadActiveCreatures();
  });
</script>

<div class="builder-page">
  <section class="panel builder-form">
    <h2>Custom Character Builder</h2>
    <p class="sub">
      Uses the live creature generator endpoint and adds a quick stat preview.
      Preferred Name is persisted onto the generated creature when provided.
    </p>

    <div class="grid">
      <label>
        <span>Preferred Name</span>
        <input bind:value={preferredName} type="text" maxlength="30" placeholder="e.g. Ash Warden" />
      </label>

      <label>
        <span>Tier</span>
        <select bind:value={genTier}>
          {#each TIERS as tier}
            <option value={tier}>{tier}</option>
          {/each}
        </select>
      </label>

      <label>
        <span>Element</span>
        <select bind:value={genElement}>
          {#each ELEMENTS as element}
            <option value={element}>{element}</option>
          {/each}
        </select>
      </label>

      <label>
        <span>Archetype</span>
        <input bind:value={genArchetype} type="text" placeholder="e.g. sentinel" />
      </label>

      <label>
        <span>Biome</span>
        <input bind:value={genBiome} type="text" placeholder="e.g. storm plateau" />
      </label>

      <label>
        <span>Stat Budget</span>
        <input value={genBudget} readonly />
      </label>
    </div>

    <label class="toggle">
      <input type="checkbox" bind:checked={showStatPreview} />
      <span>Show stat preview after generation</span>
    </label>

    <button
      class="generate-btn"
      on:click={generateCreature}
      disabled={generating || !genArchetype.trim() || !genBiome.trim()}
    >
      {generating ? 'Generating...' : 'Generate Creature'}
    </button>

    {#if errorMessage}
      <p class="error">{errorMessage}</p>
    {/if}
  </section>

  <section class="panel result-panel">
    <h3>Latest Result</h3>

    {#if !latest}
      <p class="empty">No generated creature yet.</p>
    {:else}
      <div class="result-head">
        <div>
          <div class="name" style="color:{tierColor(latest.tier)}">{latest.name}</div>
          <div class="meta">
            <span style="color:{elementColor(latest.element)}">{latest.element}</span>
            <span style="color:{tierColor(latest.tier)}">{latest.tier}</span>
            <span>{latest.ability_count} abilities</span>
            <span>{latest.taunt_count} taunts</span>
          </div>
        </div>
        <div class="flags">
          {#if latest.retry_count > 0}
            <span class="badge retry">{latest.retry_count} retries</span>
          {:else}
            <span class="badge pass">clean</span>
          {/if}
          {#if createdInActivePool}
            <span class="badge pass">joined active pool</span>
          {:else}
            <span class="badge">pending list sync</span>
          {/if}
        </div>
      </div>

      {#if preferredName.trim()}
        <p class="preferred-name">Preferred Name for this build: {preferredName.trim()}</p>
      {/if}

      {#if showStatPreview}
        {#if latestDetail}
          <div class="stats-grid">
            <div><span>Health</span><strong>{latestDetail.stats.health}</strong></div>
            <div><span>Attack</span><strong>{latestDetail.stats.attack}</strong></div>
            <div><span>Defense</span><strong>{latestDetail.stats.defense}</strong></div>
            <div><span>Speed</span><strong>{latestDetail.stats.speed}</strong></div>
          </div>
        {:else}
          <p class="empty">Stat preview loading or unavailable.</p>
        {/if}
      {/if}
    {/if}
  </section>

  <section class="panel pool-panel">
    <h3>Active Pool Snapshot</h3>
    {#if activeCreatures.length === 0}
      <p class="empty">No active creatures loaded.</p>
    {:else}
      <ul>
        {#each activeCreatures as creature}
          <li>
            <span class="c-name">{creature.name}</span>
            <span class="c-meta" style="color:{tierColor(creature.tier)}">{creature.tier}</span>
            <span class="c-meta" style="color:{elementColor(creature.element)}">{creature.element}</span>
            <span class="c-score">{creature.wins}W {creature.losses}L</span>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</div>

<style>
  .builder-page {
    height: 100%;
    overflow: auto;
    padding: 16px;
    display: grid;
    grid-template-columns: 1.2fr 1fr;
    gap: 12px;
    background: var(--bg);
  }

  .panel {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
  }

  .builder-form {
    grid-row: span 2;
  }

  h2, h3 {
    margin: 0 0 8px 0;
    color: var(--text);
  }

  .sub {
    margin: 0 0 12px 0;
    color: var(--text-mid);
    font-size: 12px;
    line-height: 1.4;
  }

  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  label span {
    font-size: 10px;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  input, select {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 12px;
    padding: 8px;
  }

  .toggle {
    margin-top: 10px;
    flex-direction: row;
    align-items: center;
    gap: 8px;
  }

  .toggle span {
    text-transform: none;
    letter-spacing: 0;
    font-size: 12px;
    color: var(--text-mid);
  }

  .generate-btn {
    margin-top: 10px;
    border: 1px solid var(--border-hi);
    background: var(--bg);
    color: var(--text);
    border-radius: 6px;
    padding: 8px 10px;
    cursor: pointer;
    font-family: var(--font-mono);
    font-size: 12px;
  }

  .generate-btn:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .error {
    color: var(--fail);
    font-size: 11px;
    margin-top: 10px;
  }

  .result-head {
    display: flex;
    justify-content: space-between;
    gap: 8px;
  }

  .name {
    font-size: 18px;
    font-weight: 700;
  }

  .meta {
    margin-top: 3px;
    display: flex;
    gap: 8px;
    color: var(--text-mid);
    font-size: 11px;
  }

  .flags {
    display: flex;
    gap: 6px;
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .badge {
    border: 1px solid var(--border-hi);
    border-radius: 999px;
    padding: 2px 7px;
    color: var(--text-mid);
    font-size: 10px;
  }

  .badge.pass {
    border-color: var(--pass);
    color: var(--pass);
  }

  .badge.retry {
    border-color: var(--retry);
    color: var(--retry);
  }

  .preferred-name {
    margin: 10px 0 0;
    color: var(--text-mid);
    font-size: 12px;
  }

  .stats-grid {
    margin-top: 10px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
  }

  .stats-grid div {
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg);
    padding: 7px 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .stats-grid span {
    color: var(--text-mid);
    font-size: 11px;
  }

  .stats-grid strong {
    color: var(--text);
    font-size: 14px;
  }

  .pool-panel ul {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-height: 340px;
    overflow: auto;
  }

  .pool-panel li {
    display: grid;
    grid-template-columns: 1fr auto auto auto;
    gap: 8px;
    align-items: center;
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 5px 7px;
    background: var(--bg);
  }

  .c-name {
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .c-meta,
  .c-score {
    font-size: 11px;
    color: var(--text-mid);
  }

  .empty {
    color: var(--text-dim);
    font-size: 12px;
  }

  @media (max-width: 980px) {
    .builder-page {
      grid-template-columns: 1fr;
    }

    .builder-form {
      grid-row: auto;
    }
  }
</style>
