<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { fightStore } from '$lib/stores/fight';
  import { createArena, type ArenaInstance } from '$lib/pixi/arena';
  import { createAnimator, type AnimatorInstance } from '$lib/pixi/animator';
  import { createDebrisSystem, type DebrisSystem } from '$lib/pixi/physics';
  import type { CreatureData } from '$lib/pixi/sprite';

  let mountEl: HTMLDivElement;
  let arena: ArenaInstance | null = null;
  let animator: AnimatorInstance | null = null;
  let physics: DebrisSystem | null = null;

  // Track which fight we've loaded so we only call setCreatures once per fight
  let loadedFightId: string | null = null;
  // Track how many events we've already enqueued
  let lastEventCount = 0;

  // Recording state
  let recording = false;
  let mediaRecorder: MediaRecorder | null = null;
  let chunks: BlobPart[] = [];

  onMount(async () => {
    arena = await createArena(mountEl);
    physics = createDebrisSystem(arena.stage);
    animator = createAnimator(arena, physics);
  });

  onDestroy(() => {
    physics?.destroy();
    arena?.destroy();
  });

  // New fight started — build sprites
  $: if (arena && animator) {
    const { fight_id, creature_a, creature_b } = $fightStore;
    if (fight_id && fight_id !== loadedFightId && creature_a && creature_b) {
      loadedFightId = fight_id;
      lastEventCount = 0;
      animator.reset();
      arena.setCreatures(creature_a as CreatureData, creature_b as CreatureData);
    }
  }

  // New events arrived — enqueue them for animation
  $: if (animator) {
    const events = $fightStore.events;
    if (events.length > lastEventCount) {
      events.slice(lastEventCount).forEach((ev) => animator!.enqueue(ev));
      lastEventCount = events.length;
    }
  }

  function toggleRecord() {
    if (recording) {
      mediaRecorder?.stop();
      recording = false;
      return;
    }
    const canvas = mountEl?.querySelector('canvas') as HTMLCanvasElement | null;
    if (!canvas) return;

    const stream = canvas.captureStream(30);
    chunks = [];
    mediaRecorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
    mediaRecorder.ondataavailable = (e) => chunks.push(e.data);
    mediaRecorder.onstop = () => {
      const blob = new Blob(chunks, { type: 'video/webm' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `fight-${loadedFightId ?? 'unknown'}.webm`;
      a.click();
      URL.revokeObjectURL(url);
    };
    mediaRecorder.start();
    recording = true;
  }
</script>

<div class="arena-wrap">
  <div bind:this={mountEl} class="canvas-mount"></div>
  <button class="record-btn" class:active={recording} on:click={toggleRecord}>
    {recording ? '⏹ Stop' : '⏺ Rec'}
  </button>
</div>

<style>
  .arena-wrap {
    position: relative;
    width: 100%;
  }

  .canvas-mount {
    width: 100%;
    aspect-ratio: 16 / 9;
    background: #0d0e12;
    border: 1px solid #363a50;
    border-radius: 8px;
    overflow: hidden;
  }

  .canvas-mount :global(canvas) {
    width: 100% !important;
    height: 100% !important;
    display: block;
  }

  .record-btn {
    position: absolute;
    bottom: 8px;
    right: 8px;
    font-size: 10px;
    padding: 4px 10px;
    background: #13151e;
    border: 1px solid #363a50;
    color: #8a8fa8;
    border-radius: 4px;
    opacity: 0.7;
    transition: opacity 0.15s;
  }

  .record-btn:hover {
    opacity: 1;
  }

  .record-btn.active {
    border-color: #ef4444;
    color: #ef4444;
    opacity: 1;
  }
</style>
