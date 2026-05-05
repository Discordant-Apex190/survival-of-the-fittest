import { writable } from 'svelte/store';

const MAX_LINES = 50;

function createCommentaryStore() {
  const { subscribe, update } = writable<string[]>([]);
  return {
    subscribe,
    add:   (lines: string[]) => update((prev) => [...lines, ...prev].slice(0, MAX_LINES)),
    clear: ()                => update(() => []),
  };
}

export const commentaryStore = createCommentaryStore();
