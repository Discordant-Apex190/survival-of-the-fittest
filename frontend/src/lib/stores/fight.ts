import { writable } from 'svelte/store';
import type { WsFightEnd, WsFightEvent, WsFightStart } from '../schemas/ws';

interface FightState {
  active: boolean;
  fight_id: string | null;
  creature_a: Record<string, unknown> | null;
  creature_b: Record<string, unknown> | null;
  prob_a: number;
  prob_b: number;
  events: WsFightEvent[];
  winner_id: string | null;
}

const initial: FightState = {
  active: false,
  fight_id: null,
  creature_a: null,
  creature_b: null,
  prob_a: 0.5,
  prob_b: 0.5,
  events: [],
  winner_id: null,
};

function createFightStore() {
  const { subscribe, update, set } = writable<FightState>(initial);
  return {
    subscribe,
    start: (ev: WsFightStart) =>
      set({
        active: true,
        fight_id: ev.fight_id,
        creature_a: ev.creature_a,
        creature_b: ev.creature_b,
        prob_a: ev.prob_a,
        prob_b: ev.prob_b,
        events: [],
        winner_id: null,
      }),
    addEvent: (ev: WsFightEvent) =>
      update((s) => ({ ...s, events: [...s.events, ev] })),
    end: (ev: WsFightEnd) =>
      update((s) => ({ ...s, active: false, winner_id: ev.winner_id })),
    reset: () => set(initial),
  };
}

export const fightStore = createFightStore();
