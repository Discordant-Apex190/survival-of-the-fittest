import { writable, get } from 'svelte/store';
import type { WsFightEnd, WsFightPreview, WsFightStart, WsTokenEarned } from '../schemas/ws';

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
  tokens: number;
  active: PlacedBet | null;
  history: BetHistoryEntry[];
  daily_earned_today: number;
  daily_earned_date: string;
  last_token_earned: number;
}

// ---------------------------------------------------------------------------
// localStorage persistence
// ---------------------------------------------------------------------------

const STORAGE_KEY = 'sotf_bet_state';
const STARTING_TOKENS = 1000;

function todayIsoDate(): string {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function normalizeState(state: BetState): BetState {
  const today = todayIsoDate();
  if (state.daily_earned_date !== today) {
    return {
      ...state,
      daily_earned_today: 0,
      daily_earned_date: today,
      last_token_earned: 0,
    };
  }
  return state;
}

function load(): BetState {
  const today = todayIsoDate();
  const fallback: BetState = {
    tokens: STARTING_TOKENS,
    active: null,
    history: [],
    daily_earned_today: 0,
    daily_earned_date: today,
    last_token_earned: 0,
  };

  if (typeof localStorage === 'undefined') {
    return fallback;
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<BetState>;
    const hydrated: BetState = {
      tokens: typeof parsed.tokens === 'number' ? parsed.tokens : STARTING_TOKENS,
      active: parsed.active ?? null,
      history: parsed.history ?? [],
      daily_earned_today: parsed.daily_earned_today ?? 0,
      daily_earned_date: parsed.daily_earned_date ?? today,
      last_token_earned: 0,
    };
    // Void any in-flight pending/locked bets that survived a page reload
    if (hydrated.active?.status === 'pending' || hydrated.active?.status === 'locked') {
      hydrated.active = null;
    }
    return normalizeState(hydrated);
  } catch {
    return fallback;
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

    /** Called when fight_preview arrives — clear any stale resolved bet so UI is fresh. */
    onFightPreview(_ev: WsFightPreview): void {
      update((s) => {
        // Auto-dismiss a resolved bet from the previous fight before opening new betting window
        if (s.active?.status === 'won' || s.active?.status === 'lost') {
          return persist({ ...s, active: null });
        }
        return s;
      });
    },

    /** Called when fight_start arrives. Lock or void the pending bet. */
    onFightStart(ev: WsFightStart): void {
      update((s) => {
        if (!s.active || s.active.status !== 'pending') return s;
        const fighters = [
          ev.creature_a.id,
          ev.creature_b.id,
        ];
        if (fighters.includes(s.active.creatureId)) {
          return persist({ ...s, active: { ...s.active, status: 'locked' } });
        }
        // Matchup mismatch — return tokens
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

    /** Called when simulation broadcasts a fight completion token reward. */
    onTokenEarned(ev: WsTokenEarned): void {
      update((s) => {
        const normalized = normalizeState(s);
        return persist({
          ...normalized,
          tokens: normalized.tokens + ev.amount,
          daily_earned_today: normalized.daily_earned_today + ev.amount,
          last_token_earned: ev.amount,
        });
      });
    },

    clearTokenEarnedToast(): void {
      update((s) => {
        if (s.last_token_earned === 0) return s;
        return persist({ ...s, last_token_earned: 0 });
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
      const fresh = {
        tokens: STARTING_TOKENS,
        active: null,
        history: [],
        daily_earned_today: 0,
        daily_earned_date: todayIsoDate(),
        last_token_earned: 0,
      };
      set(persist(fresh));
    },
  };
}

export const betStore = createBetStore();
