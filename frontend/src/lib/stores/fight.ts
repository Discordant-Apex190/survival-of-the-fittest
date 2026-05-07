import { writable } from 'svelte/store';
import type { WsFightEnd, WsFightEvent, WsFightPreview, WsFightStart } from '../schemas/ws';

interface FightState {
  active:     boolean;
  previewing: boolean;   // true during the 3-second betting window before fight_start
  fight_id:   string | null;
  creature_a: Record<string, unknown> | null;
  creature_b: Record<string, unknown> | null;
  prob_a:     number;
  prob_b:     number;
  events:     WsFightEvent[];
  winner_id:  string | null;
}

const initial: FightState = {
  active:     false,
  previewing: false,
  fight_id:   null,
  creature_a: null,
  creature_b: null,
  prob_a:     0.5,
  prob_b:     0.5,
  events:     [],
  winner_id:  null,
};

function createFightStore() {
  const { subscribe, update, set } = writable<FightState>(initial);
  return {
    subscribe,
    preview: (ev: WsFightPreview) =>
      set({
        active:     false,
        previewing: true,
        fight_id:   ev.fight_id,
        creature_a: ev.creature_a,
        creature_b: ev.creature_b,
        prob_a:     ev.prob_a,
        prob_b:     ev.prob_b,
        events:     [],
        winner_id:  null,
      }),
    start: (ev: WsFightStart) =>
      update((s) => ({
        ...s,
        active:     true,
        previewing: false,
        fight_id:   ev.fight_id,
        creature_a: ev.creature_a,
        creature_b: ev.creature_b,
        prob_a:     ev.prob_a,
        prob_b:     ev.prob_b,
      })),
    addEvent: (ev: WsFightEvent) =>
      update((s) => ({ ...s, events: [...s.events, ev] })),
    end: (ev: WsFightEnd) =>
      update((s) => ({ ...s, active: false, previewing: false, winner_id: ev.winner_id })),
    reset: () => set(initial),
  };
}

export const fightStore = createFightStore();
