<script lang="ts">
  import { onMount } from 'svelte';
  import { z } from 'zod';
  import { get } from '$lib/api/client';
  import { elementColor, tierColor } from '$lib/theme';

  // ---------------------------------------------------------------------------
  // Schema
  // ---------------------------------------------------------------------------

  const LineageNodeSchema = z.object({
    id: z.string(),
    name: z.string(),
    tier: z.string(),
    element: z.string(),
    generation: z.number(),
    wins: z.number(),
    losses: z.number(),
    status: z.string(),
    parent_id: z.string().nullable(),
    rival_of: z.string().nullable(),
  });
  type LineageNode = z.infer<typeof LineageNodeSchema>;

  // ---------------------------------------------------------------------------
  // Layout types
  // ---------------------------------------------------------------------------

  interface LayoutNode {
    node: LineageNode;
    x: number;
    y: number;
  }

  interface Edge {
    x1: number; y1: number;
    x2: number; y2: number;
    type: 'evolution' | 'rival';
  }

  // ---------------------------------------------------------------------------
  // Constants
  // ---------------------------------------------------------------------------

  const NODE_W   = 120;
  const NODE_H   = 44;
  const COL_GAP  = 160;  // horizontal between generation columns
  const ROW_GAP  = 60;   // vertical between siblings

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------

  let nodes: LineageNode[] = [];
  let loading = true;
  let error   = '';
  let selected: LineageNode | null = null;

  let layout: LayoutNode[] = [];
  let edges: Edge[] = [];
  let svgW = 0;
  let svgH = 0;

  // ---------------------------------------------------------------------------
  // Load
  // ---------------------------------------------------------------------------

  async function load() {
    loading = true;
    error   = '';
    const r = await get('/creatures/lineage', z.array(LineageNodeSchema));
    r.match(
      (d) => { nodes = d; buildLayout(d); },
      (e) => { error = e.message; },
    );
    loading = false;
  }

  // ---------------------------------------------------------------------------
  // Layout: column = generation, rows = siblings sorted by creation order
  // ---------------------------------------------------------------------------

  function buildLayout(all: LineageNode[]) {
    if (!all.length) { layout = []; edges = []; return; }

    // Group by generation
    const byGen = new Map<number, LineageNode[]>();
    for (const n of all) {
      const g = n.generation;
      if (!byGen.has(g)) byGen.set(g, []);
      byGen.get(g)!.push(n);
    }

    const gens = [...byGen.keys()].sort((a, b) => a - b);

    // Assign x per generation column
    const genX = new Map<number, number>();
    gens.forEach((g, i) => genX.set(g, 40 + i * COL_GAP));

    // Assign y per node within its column (evenly spaced)
    const posMap = new Map<string, { x: number; y: number }>();
    for (const g of gens) {
      const bucket = byGen.get(g)!;
      bucket.forEach((n, i) => {
        const x = genX.get(g)! + NODE_W / 2;
        const y = 40 + i * ROW_GAP + NODE_H / 2;
        posMap.set(n.id, { x, y });
      });
    }

    layout = all.map((n) => {
      const pos = posMap.get(n.id)!;
      return { node: n, x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 };
    });

    // Edges
    const edgeList: Edge[] = [];
    for (const n of all) {
      const to = posMap.get(n.id);
      if (!to) continue;

      if (n.parent_id) {
        const from = posMap.get(n.parent_id);
        if (from) {
          edgeList.push({
            x1: from.x + NODE_W / 2,
            y1: from.y,
            x2: to.x - NODE_W / 2,
            y2: to.y,
            type: 'evolution',
          });
        }
      }

      if (n.rival_of) {
        const from = posMap.get(n.rival_of);
        if (from) {
          edgeList.push({
            x1: from.x + NODE_W / 2,
            y1: from.y,
            x2: to.x - NODE_W / 2,
            y2: to.y,
            type: 'rival',
          });
        }
      }
    }
    edges = edgeList;

    // SVG canvas dimensions
    const maxX = Math.max(...layout.map((l) => l.x + NODE_W)) + 40;
    const maxY = Math.max(...layout.map((l) => l.y + NODE_H)) + 40;
    svgW = maxX;
    svgH = maxY;
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------

  onMount(load);

  function statusOpacity(s: string) {
    if (s === 'active')  return '1';
    if (s === 'retired') return '0.5';
    return '0.3'; // extinct
  }
</script>

<div class="lineage-page">
  <!-- Header -->
  <div class="top-bar">
    <span class="title">Lineage</span>
    <span class="sub">Evolution tree · rivals shown in <span style="color:var(--void)">violet</span></span>
    <button class="btn-ghost" on:click={load} disabled={loading}>↺ Refresh</button>
    {#if nodes.length}
      <span class="count dim">{nodes.length} creatures</span>
    {/if}
  </div>

  <div class="body">
    <!-- SVG tree -->
    <div class="svg-wrap">
      {#if loading}
        <p class="hint">Loading…</p>
      {:else if error}
        <p class="hint err">{error}</p>
      {:else if !nodes.length}
        <p class="hint">No creatures yet.</p>
      {:else}
        <svg width={svgW} height={svgH} xmlns="http://www.w3.org/2000/svg">
          <defs>
            <marker id="arrow-evo" markerWidth="6" markerHeight="6"
                    refX="5" refY="3" orient="auto">
              <path d="M0,0 L0,6 L6,3 z" fill="#363a50" />
            </marker>
            <marker id="arrow-rival" markerWidth="6" markerHeight="6"
                    refX="5" refY="3" orient="auto">
              <path d="M0,0 L0,6 L6,3 z" fill="#9b59d4" />
            </marker>
          </defs>

          <!-- Edges -->
          {#each edges as e}
            <line
              x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2}
              stroke={e.type === 'rival' ? '#9b59d4' : '#363a50'}
              stroke-width={e.type === 'rival' ? 1.5 : 1}
              stroke-dasharray={e.type === 'rival' ? '4 3' : 'none'}
              marker-end={e.type === 'rival' ? 'url(#arrow-rival)' : 'url(#arrow-evo)'}
              opacity="0.7"
            />
          {/each}

          <!-- Nodes -->
          {#each layout as { node: n, x, y }}
            <!-- svelte-ignore a11y-click-events-have-key-events -->
            <!-- svelte-ignore a11y-no-static-element-interactions -->
            <g
              transform="translate({x},{y})"
              opacity={statusOpacity(n.status)}
              on:click={() => selected = (selected?.id === n.id ? null : n)}
              style="cursor:pointer"
            >
              <rect
                width={NODE_W} height={NODE_H}
                rx="4"
                fill="#13151e"
                stroke={selected?.id === n.id ? elementColor(n.element) : '#252836'}
                stroke-width={selected?.id === n.id ? 2 : 1}
              />
              <!-- Tier stripe -->
              <rect width="3" height={NODE_H} rx="2" fill={tierColor(n.tier)} />
              <!-- Name -->
              <text
                x="10" y="16"
                font-size="11" font-family="'DM Mono', monospace" font-weight="600"
                fill={elementColor(n.element)}
                text-anchor="start"
              >{n.name.length > 13 ? n.name.slice(0, 12) + '…' : n.name}</text>
              <!-- Gen + stats -->
              <text
                x="10" y="32"
                font-size="9" font-family="'DM Mono', monospace"
                fill="#4a4f63"
                text-anchor="start"
              >G{n.generation} · {n.wins}W {n.losses}L</text>
              <!-- Rival indicator -->
              {#if n.rival_of}
                <text x={NODE_W - 6} y="12" font-size="9" fill="#9b59d4" text-anchor="end">⚔</text>
              {/if}
            </g>
          {/each}
        </svg>
      {/if}
    </div>

    <!-- Detail panel -->
    {#if selected}
      <div class="detail-panel">
        <div class="d-header">
          <span class="d-name" style="color:{elementColor(selected.element)}">{selected.name}</span>
          <button class="btn-ghost sm" on:click={() => selected = null}>✕</button>
        </div>
        <div class="d-row">
          <span class="d-label">Tier</span>
          <span style="color:{tierColor(selected.tier)}">{selected.tier}</span>
        </div>
        <div class="d-row">
          <span class="d-label">Element</span>
          <span style="color:{elementColor(selected.element)}">{selected.element}</span>
        </div>
        <div class="d-row"><span class="d-label">Generation</span><span>{selected.generation}</span></div>
        <div class="d-row"><span class="d-label">Record</span><span class="pass">{selected.wins}W</span> / <span class="fail">{selected.losses}L</span></div>
        <div class="d-row">
          <span class="d-label">Status</span>
          <span class="chip chip-{selected.status}">{selected.status}</span>
        </div>
        {#if selected.parent_id}
          <div class="d-row"><span class="d-label">Evolved from</span><span class="dim">{selected.parent_id.slice(0, 8)}…</span></div>
        {/if}
        {#if selected.rival_of}
          <div class="d-row"><span class="d-label">Rival of</span><span style="color:var(--void)">{selected.rival_of.slice(0, 8)}…</span></div>
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .lineage-page {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
  }

  .top-bar {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 16px;
    height: 40px;
    background: var(--card);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    font-size: 12px;
  }
  .title { font-family: var(--font-disp); font-size: 13px; font-weight: 800; color: var(--text); }
  .sub   { color: var(--text-dim); font-size: 11px; }
  .count { color: var(--text-dim); font-size: 11px; margin-left: auto; }
  .dim   { color: var(--text-dim); }

  .btn-ghost {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 3px;
    color: var(--text-mid);
    font-size: 11px;
    padding: 2px 8px;
  }
  .btn-ghost:hover:not(:disabled) { border-color: var(--border-hi); color: var(--text); }
  .btn-ghost.sm { padding: 1px 5px; font-size: 10px; }

  .body {
    display: flex;
    flex: 1;
    overflow: hidden;
  }

  .svg-wrap {
    flex: 1;
    overflow: auto;
    padding: 16px;
  }

  .hint {
    font-size: 12px;
    color: var(--text-dim);
    padding: 24px;
  }
  .hint.err { color: var(--fail); }

  /* Detail panel */
  .detail-panel {
    width: 200px;
    flex-shrink: 0;
    background: var(--card);
    border-left: 1px solid var(--border);
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    font-size: 12px;
    overflow-y: auto;
  }
  .d-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4px;
  }
  .d-name { font-weight: 700; font-size: 13px; }
  .d-row  { display: flex; gap: 8px; align-items: baseline; }
  .d-label { color: var(--text-dim); font-size: 10px; text-transform: uppercase; min-width: 72px; }
  .pass { color: var(--pass); }
  .fail { color: var(--fail); }

  .chip {
    font-size: 9px;
    padding: 1px 5px;
    border-radius: 2px;
    border: 1px solid var(--border);
    color: var(--text-dim);
  }
  .chip-active  { color: var(--pass);     border-color: var(--pass); }
  .chip-retired { color: var(--text-dim); }
  .chip-extinct { color: var(--fail);     border-color: var(--fail); }
</style>
