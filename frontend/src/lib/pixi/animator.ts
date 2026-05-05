import { Container, Graphics, Text, Ticker } from 'pixi.js';
import type { WsFightEvent } from '../schemas/ws';
import type { ArenaInstance } from './arena';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

interface TweenProps {
  x?: number;
  y?: number;
  alpha?: number;
}

function tweenTo(
  obj: { x: number; y: number; alpha: number },
  to: TweenProps,
  ms: number,
): Promise<void> {
  const fx = obj.x, fy = obj.y, fa = obj.alpha;
  const tx = to.x ?? fx, ty = to.y ?? fy, ta = to.alpha ?? fa;
  if (ms <= 0) {
    if (to.x !== undefined) obj.x = tx;
    if (to.y !== undefined) obj.y = ty;
    if (to.alpha !== undefined) obj.alpha = ta;
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    let elapsed = 0;
    const fn = (ticker: Ticker) => {
      elapsed += ticker.deltaMS;
      const t = Math.min(elapsed / ms, 1);
      obj.x = fx + (tx - fx) * t;
      obj.y = fy + (ty - fy) * t;
      obj.alpha = fa + (ta - fa) * t;
      if (t >= 1) {
        Ticker.shared.remove(fn);
        resolve();
      }
    };
    Ticker.shared.add(fn);
  });
}

function tweenScale(obj: Container, toScale: number, ms: number): Promise<void> {
  // Preserve facing mirror (scale.x may be -1)
  const sign = obj.scale.x < 0 ? -1 : 1;
  const fromS = Math.abs(obj.scale.x);
  return new Promise((resolve) => {
    let elapsed = 0;
    const fn = (ticker: Ticker) => {
      elapsed += ticker.deltaMS;
      const t = Math.min(elapsed / ms, 1);
      const s = fromS + (toScale - fromS) * t;
      obj.scale.set(sign * s, s);
      if (t >= 1) {
        Ticker.shared.remove(fn);
        resolve();
      }
    };
    Ticker.shared.add(fn);
  });
}

async function flashOverlay(
  target: Container,
  color: number,
  ms: number,
): Promise<void> {
  const overlay = new Graphics();
  overlay.circle(0, 0, 70).fill({ color, alpha: 0 });
  target.addChild(overlay);
  await tweenTo(overlay, { alpha: 0.55 }, ms / 2);
  await tweenTo(overlay, { alpha: 0 }, ms / 2);
  target.removeChild(overlay);
  overlay.destroy();
}

async function flashStage(
  stage: Container,
  color: number,
  ms: number,
  w = 800,
  h = 450,
): Promise<void> {
  const overlay = new Graphics();
  overlay.rect(0, 0, w, h).fill({ color, alpha: 0 });
  stage.addChild(overlay);
  await tweenTo(overlay, { alpha: 0.28 }, ms / 2);
  await tweenTo(overlay, { alpha: 0 }, ms / 2);
  stage.removeChild(overlay);
  overlay.destroy();
}

async function emitParticles(
  stage: Container,
  from: { x: number; y: number },
  to: { x: number; y: number },
  count: number,
  color: number,
): Promise<void> {
  const particles = Array.from({ length: count }, () => {
    const p = new Graphics();
    p.circle(0, 0, 3).fill({ color, alpha: 0.9 });
    p.x = from.x;
    p.y = from.y;
    p.alpha = 0.9;
    stage.addChild(p);
    return p;
  });

  const spread = 24;
  await Promise.all(
    particles.map((p) => {
      const dx = (Math.random() - 0.5) * spread;
      const dy = (Math.random() - 0.5) * spread;
      return tweenTo(p, { x: to.x + dx, y: to.y + dy, alpha: 0 }, 300);
    }),
  );

  particles.forEach((p) => {
    stage.removeChild(p);
    p.destroy();
  });
}

async function emitTextParticle(
  stage: Container,
  text: string,
  x: number,
  y: number,
): Promise<void> {
  const label = new Text({
    text,
    style: { fill: '#f5c518', fontSize: 10, fontFamily: 'DM Mono, monospace' },
  });
  label.x = x - 20;
  label.y = y;
  label.alpha = 1;
  stage.addChild(label);
  await tweenTo(label, { y: y - 30, alpha: 0 }, 500);
  stage.removeChild(label);
  label.destroy();
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface AnimatorInstance {
  enqueue(evt: WsFightEvent): void;
  reset(): void;
}

export function createAnimator(arena: ArenaInstance): AnimatorInstance {
  const queue: WsFightEvent[] = [];
  let running = false;

  async function drain() {
    running = true;
    while (queue.length > 0) {
      const evt = queue.shift()!;
      await playEvent(evt);
      await sleep(160);
    }
    running = false;
  }

  async function playEvent(evt: WsFightEvent): Promise<void> {
    const actorSlot  = evt.actor_id  ? arena.getSlot(evt.actor_id)  : undefined;
    const targetSlot = evt.target_id ? arena.getSlot(evt.target_id) : undefined;

    switch (evt.event_type) {
      case 'attack': {
        if (!actorSlot || !targetSlot) break;
        const dx = targetSlot.homeX - actorSlot.homeX;
        // Lunge toward target
        await tweenTo(actorSlot.sprite, { x: actorSlot.homeX + dx * 0.32 }, 140);
        await Promise.all([
          tweenTo(actorSlot.sprite, { x: actorSlot.homeX }, 140),
          flashOverlay(targetSlot.sprite, 0xff2222, 160),
        ]);
        // Update HP bars
        for (const [id, hp] of Object.entries(evt.hp_remaining)) {
          arena.updateHp(id, hp);
        }
        break;
      }

      case 'ability': {
        if (!actorSlot) break;
        await tweenScale(actorSlot.sprite, 1.18, 180);
        if (targetSlot) {
          const slotColor = 0xb56cf5; // rare/ability color
          await Promise.all([
            emitParticles(
              arena.stage,
              { x: actorSlot.homeX, y: actorSlot.homeY - 20 },
              { x: targetSlot.homeX, y: targetSlot.homeY - 20 },
              6,
              slotColor,
            ),
            tweenScale(actorSlot.sprite, 1, 180),
          ]);
          await flashOverlay(targetSlot.sprite, 0xaa44ff, 120);
        } else {
          await tweenScale(actorSlot.sprite, 1, 180);
        }
        for (const [id, hp] of Object.entries(evt.hp_remaining)) {
          arena.updateHp(id, hp);
        }
        break;
      }

      case 'dodge': {
        // The defender slides away briefly
        const defSlot = targetSlot ?? actorSlot;
        if (!defSlot) break;
        const nudge = defSlot.homeX > 400 ? 20 : -20;
        await tweenTo(defSlot.sprite, { x: defSlot.homeX + nudge }, 90);
        await tweenTo(defSlot.sprite, { x: defSlot.homeX }, 130);
        break;
      }

      case 'taunt': {
        if (!actorSlot) break;
        await tweenTo(actorSlot.sprite, { y: actorSlot.homeY - 14 }, 110);
        await tweenTo(actorSlot.sprite, { y: actorSlot.homeY }, 110);
        emitTextParticle(
          arena.stage,
          '+momentum',
          actorSlot.homeX,
          actorSlot.homeY - 60,
        );
        break;
      }

      case 'ko': {
        // The loser falls and fades — actor_id is the winner, target_id the loser
        const loserSlot = targetSlot ?? (actorSlot ? undefined : undefined);
        // Both IDs are present in hp_remaining; find the one at 0 HP
        const loserId = Object.entries(evt.hp_remaining).find(([, hp]) => hp <= 0)?.[0];
        const ls = loserId ? arena.getSlot(loserId) : undefined;
        if (ls) {
          await Promise.all([
            tweenTo(ls.sprite, { y: ls.homeY + 70, alpha: 0 }, 550),
            flashStage(arena.stage, 0x220000, 300),
          ]);
          arena.updateHp(loserId!, 0);
        }
        // Update all HP bars from the event
        for (const [id, hp] of Object.entries(evt.hp_remaining)) {
          arena.updateHp(id, hp);
        }
        break;
      }
    }
  }

  return {
    enqueue(evt: WsFightEvent) {
      queue.push(evt);
      if (!running) drain();
    },
    reset() {
      queue.length = 0;
      running = false;
    },
  };
}
