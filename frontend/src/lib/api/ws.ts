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

/** True when the WebSocket connection is open and ready. */
export const wsConnected = writable(false);

export function connect(): void {
  if (socket?.readyState === WebSocket.OPEN) return;

  socket = new WebSocket(env.VITE_WS_URL);

  socket.onopen = () => {
    wsConnected.set(true);
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
          const a = fs.creature_a as Record<string, unknown>;
          names[a.id as string] = a.name as string;
        }
        if (fs.creature_b) {
          const b = fs.creature_b as Record<string, unknown>;
          names[b.id as string] = b.name as string;
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
    if (pingInterval) {
      clearInterval(pingInterval);
      pingInterval = null;
    }
    setTimeout(connect, 3_000);
  };

  socket.onerror = () => socket?.close();
}

export function disconnect(): void {
  wsConnected.set(false);
  if (pingInterval) clearInterval(pingInterval);
  socket?.close();
  socket = null;
}
