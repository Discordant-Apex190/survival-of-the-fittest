import { match } from 'ts-pattern';
import { env } from '../../env';
import { WsEventSchema } from '../schemas/ws';
import { commentaryStore } from '../stores/commentary';
import { fightStore } from '../stores/fight';
import { leaderboardStore } from '../stores/leaderboard';

let socket: WebSocket | null = null;
let pingInterval: ReturnType<typeof setInterval> | null = null;

export function connect(): void {
  if (socket?.readyState === WebSocket.OPEN) return;

  socket = new WebSocket(env.VITE_WS_URL);

  socket.onopen = () => {
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
      .with({ type: 'fight_start' },       (ev) => fightStore.start(ev))
      .with({ type: 'fight_event' },       (ev) => fightStore.addEvent(ev))
      .with({ type: 'fight_end' },         (ev) => fightStore.end(ev))
      .with({ type: 'leaderboard_update' },(ev) => leaderboardStore.set(ev.data))
      .with({ type: 'commentary' },        (ev) => commentaryStore.add(ev.lines))
      .exhaustive();
  };

  socket.onclose = () => {
    if (pingInterval) {
      clearInterval(pingInterval);
      pingInterval = null;
    }
    setTimeout(connect, 3_000);
  };

  socket.onerror = () => socket?.close();
}

export function disconnect(): void {
  if (pingInterval) clearInterval(pingInterval);
  socket?.close();
  socket = null;
}
