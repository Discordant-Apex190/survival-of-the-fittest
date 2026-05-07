import { writable } from 'svelte/store';

interface VoteState {
  fight_id: string | null;
  votes:    Record<string, number>;
}

function createVoteStore() {
  const { subscribe, set, update } = writable<VoteState>({ fight_id: null, votes: {} });
  return {
    subscribe,
    update(fight_id: string, votes: Record<string, number>) {
      set({ fight_id, votes });
    },
    clear() {
      set({ fight_id: null, votes: {} });
    },
    total(): number {
      return 0; // computed in reactive template via $voteStore.votes
    },
  };
}

export const voteStore = createVoteStore();
