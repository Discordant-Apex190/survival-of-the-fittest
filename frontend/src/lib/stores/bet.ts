import { writable, get } from 'svelte/store';
import type { WsFightEnd, WsFightStart } from '../schemas/ws';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PlacedBet {
  fightId:    string;   // fight_id from /betting/current (pre-fight slug)
  creatureId: string;
  amount:     number;
  odds:       number;   // 1 / probability of that creature winning
  status:     'pending' | 'locked' | 'won' | 'lost' | 'void';
  payout?:    number;
}

export interface BetHistoryEntry {
  creatureName: string;
  amount:       number;
  payout:       number;
  result:       'won' | 'lost' | 'void';
}

interface BetState {
  tokens:  number;
  active:  PlacedBet | null;
  history: BetHistoryEntry[];
}

// ---------------------------------------------------------------------------
// localStorage persistence
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'sotf_bet_state';
const STARTING_TOKENS = 1000;

function load(): BetState {
  if (typeof localStorage === 'undefined') {
    return { tokens: STARTING_TOKENS, active: null, history: [] };
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { tokens: STARTING_TOKENS, active: null, history: [] };
    const parsed = JSON.parse(raw) as BetState;
    // Void any in-flight pending/locked bets that survived a page reload
    if (parsed.active?.status === 'pending' || parsed.active?.status === 'locked') {
      parsed.active = null;
    }
    return parsed;
  } catch {
    return { tokens: STARTING_TOKENS, active: null, history: [] };
  }
}

function save(state: BetState): void {
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

function createBetStore() {
  const { subscribe, update, set } = writable<BetState>(load());

  function persist(state: BetState): BetState {
    save(state);
    return state;
  }

  return {
    subscribe,

    /** Place a bet before a fight starts. Returns false if balance is too low or a bet is active. */
    place(
      fightId: string,
      creatureId: string,
      amount: number,
      odds: number,
    ): boolean {
      let ok = false;
      update((s) => {
        if (s.active || s.tokens < amount || amount <= 0) return s;
        ok = true;
        return persist({
          ...s,
          tokens: s.tokens - amount,
          active: { fightId, creatureId, amount, odds, status: 'pending' },
        });
      });
      return ok;
    },

    /** Called when fight_start arrives. Lock or void the bet based on actual fighters. */
    onFightStart(ev: WsFightStart): void {
      update((s) => {
        if (!s.active || s.active.status !== 'pending') return s;
        const fighters = [
          (ev.creature_a as Record<string, unknown>).id as string,
          (ev.creature_b as Record<string, unknown>).id as string,
        ];
        if (fighters.includes(s.active.creatureId)) {
          return persist({ ...s, active: { ...s.active, status: 'locked' } });
        }
        // Matchup changed — return tokens, void bet
        return persist({
          ...s,
          tokens: s.tokens + s.active.amount,
          active: null,
        });
      });
    },

    /** Called when fight_end arrives. Resolves the active locked bet. */
    onFightEnd(ev: WsFightEnd, creatureNames: Record<string, string>): void {
      update((s) => {
        if (!s.active || s.active.status !== 'locked') return s;

        const won = ev.winner_id === s.active.creatureId;
        const payout = won ? Math.floor(s.active.amount * s.active.odds) : 0;
        const result: 'won' | 'lost' = won ? 'won' : 'lost';
        const entry: BetHistoryEntry = {
          creatureName: creatureNames[s.active.creatureId] ?? s.active.creatureId,
          amount:       s.active.amount,
          payout,
          result,
        };

        return persist({
          ...s,
          tokens:  s.tokens + payout,
          active:  { ...s.active, status: result, payout },
          history: [entry, ...s.history].slice(0, 10),
        });
      });
    },

    /** Cancel a pending (not yet locked) bet and refund. */
    cancel(): void {
      update((s) => {
        if (!s.active || s.active.status !== 'pending') return s;
        return persist({
          ...s,
          tokens: s.tokens + s.active.amount,
          active: null,
        });
      });
    },

    /** Clear the resolved bet display (after user sees result). */
    dismiss(): void {
      update((s) => {
        if (!s.active || (s.active.status !== 'won' && s.active.status !== 'lost')) return s;
        return persist({ ...s, active: null });
      });
    },

    reset(): void {
      const fresh = { tokens: STARTING_TOKENS, active: null, history: [] };
      set(persist(fresh));
    },
  };
}

export const betStore = createBetStore();
