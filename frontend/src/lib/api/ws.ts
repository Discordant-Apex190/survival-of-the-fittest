import { match } from 'ts-pattern';
import { get, writable } from 'svelte/store';
import { env } from '../../env';
import { WsEventSchema } from '../schemas/ws';
import { fightStore } from '../stores/fight';
import { leaderboardStore } from '../stores/leaderboard';
import { betStore } from '../stores/bet';
import { voteStore } from '../stores/votes';

let socket: WebSocket | null = null;
let pingInterval: ReturnType<typeof setInterval> | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

/** True when the WebSocket connection is open and ready. */
export const wsConnected = writable(false);

interface WsConnectionState {
  connected: boolean;
  reconnecting: boolean;
  retryCount: number;
  lastError: string | null;
}

const initialConnectionState: WsConnectionState = {
  connected: false,
  reconnecting: false,
  retryCount: 0,
  lastError: null,
};

export const wsConnectionState = writable<WsConnectionState>(initialConnectionState);

export function connect(): void {
  if (socket?.readyState === WebSocket.OPEN) return;

  socket = new WebSocket(env.VITE_WS_URL);

  socket.onopen = () => {
    wsConnected.set(true);
    wsConnectionState.set({
      connected: true,
      reconnecting: false,
      retryCount: 0,
      lastError: null,
    });
    pingInterval = setInterval(() => socket?.send('ping'), 25_000);
  };

  socket.onmessage = (e) => {
    if (e.data === '{"type":"pong"}') return;

    let raw: unknown;
    try {
      raw = JSON.parse(e.data as string);
    } catch {
      return;
    }

    const result = WsEventSchema.safeParse(raw);
    if (!result.success) return;

    const event = result.data;

    match(event)
      .with({ type: 'fight_preview' }, (ev) => {
        fightStore.preview(ev);
        voteStore.clear();
        betStore.onFightPreview(ev);
      })
      .with({ type: 'fight_start' }, (ev) => {
        fightStore.start(ev);
        betStore.onFightStart(ev);
      })
      .with({ type: 'fight_event' }, (ev) => fightStore.addEvent(ev))
      .with({ type: 'fight_end' }, (ev) => {
        const fs = get(fightStore);
        const names: Record<string, string> = {};
        if (fs.creature_a) {
          names[fs.creature_a.id] = fs.creature_a.name;
        }
        if (fs.creature_b) {
          names[fs.creature_b.id] = fs.creature_b.name;
        }
        fightStore.end(ev);
        betStore.onFightEnd(ev, names);
      })
      .with({ type: 'leaderboard_update' }, (ev) => leaderboardStore.set(ev.data))
      .with({ type: 'vote_update' },        (ev) => voteStore.update(ev.fight_id, ev.votes))
      .with({ type: 'commentary' },         () => { /* commentary removed */ })
      .exhaustive();
  };

  socket.onclose = () => {
    wsConnected.set(false);
    wsConnectionState.update((s) => ({
      connected: false,
      reconnecting: true,
      retryCount: s.retryCount + 1,
      lastError: s.lastError,
    }));
    if (pingInterval) {
      clearInterval(pingInterval);
      pingInterval = null;
    }
    reconnectTimer = setTimeout(connect, 3_000);
  };

  socket.onerror = () => {
    wsConnectionState.update((s) => ({
      ...s,
      lastError: 'WebSocket error. Retrying…',
    }));
    socket?.close();
  };
}

export function disconnect(): void {
  wsConnected.set(false);
  wsConnectionState.set({
    connected: false,
    reconnecting: false,
    retryCount: 0,
    lastError: null,
  });
  if (pingInterval) clearInterval(pingInterval);
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  socket?.close();
  socket = null;
}
