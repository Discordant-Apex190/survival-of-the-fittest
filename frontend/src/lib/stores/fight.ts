import { writable } from 'svelte/store';
import type { WsFightEnd, WsFightEvent, WsFightPreview, WsFightStart } from '../schemas/ws';
import type { FightCreature } from '../schemas/creature';

const MAX_STORED_EVENTS = 120;

interface FightState {
  active:     boolean;
  previewing: boolean;   // true during the 3-second betting window before fight_start
  fight_id:   string | null;
  creature_a: FightCreature | null;
  creature_b: FightCreature | null;
  prob_a:     number;
  prob_b:     number;
  events:     WsFightEvent[];
  winner_id:  string | null;
  settled:    boolean;
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
  settled:    false,
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
        settled:    false,
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
        events:     s.fight_id === ev.fight_id ? s.events : [],
        winner_id:  null,
        settled:    false,
      })),
    addEvent: (ev: WsFightEvent) =>
      update((s) => {
        if (!s.fight_id || s.fight_id !== ev.fight_id) return s;
        return { ...s, events: [...s.events, ev].slice(-MAX_STORED_EVENTS) };
      }),
    end: (ev: WsFightEnd) =>
      update((s) => {
        if (!s.fight_id || s.fight_id !== ev.fight_id) return s;
        return { ...s, active: false, previewing: false, winner_id: ev.winner_id, settled: false };
      }),
    settle: (fightId: string) =>
      update((s) => {
        if (!s.fight_id || s.fight_id !== fightId) return s;
        return { ...s, settled: true };
      }),
    reset: () => set(initial),
  };
}

export const fightStore = createFightStore();
