import { writable } from 'svelte/store';
import type { CreatureSummary } from '../schemas/creature';

function createLeaderboardStore() {
  const { subscribe, set } = writable<CreatureSummary[]>([]);
  return { subscribe, set };
}

export const leaderboardStore = createLeaderboardStore();
