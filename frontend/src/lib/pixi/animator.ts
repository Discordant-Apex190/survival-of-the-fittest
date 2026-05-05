import { Container, Graphics, Text, Ticker } from 'pixi.js';
import type { WsFightEvent } from '../schemas/ws';
import type { ArenaInstance } from './arena';
import { cameraShake, type DebrisSystem } from './physics';

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

function tweenRotation(obj: Container, toAngle: number, ms: number): Promise<void> {
  const from = obj.rotation;
  return new Promise((resolve) => {
    let elapsed = 0;
    const fn = (ticker: Ticker) => {
      elapsed += ticker.deltaMS;
      const t = Math.min(elapsed / ms, 1);
      obj.rotation = from + (toAngle - from) * t;
      if (t >= 1) {
        Ticker.shared.remove(fn);
        resolve();
      }
    };
    Ticker.shared.add(fn);
  });
}

async function arcKnockback(
  sprite: { x: number; y: number; alpha: number },
  homeX: number,
  homeY: number,
  nudgeX: number,
  ms: number,
): Promise<void> {
  await tweenTo(sprite, { x: homeX + nudgeX, y: homeY - 22 }, ms * 0.42);
  await tweenTo(sprite, { x: homeX, y: homeY }, ms * 0.58);
}

async function flashOverlay(target: Container, color: number, ms: number): Promise<void> {
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
  const spread = 24;
  const particles = Array.from({ length: count }, () => {
    const p = new Graphics();
    p.circle(0, 0, 3).fill({ color, alpha: 0.9 });
    p.x = from.x;
    p.y = from.y;
    p.alpha = 0.9;
    stage.addChild(p);
    return p;
  });

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

// Element → debris color mapping
const ELEMENT_DEBRIS: Record<string, number> = {
  fire:     0xf05a28,
  void:     0x9b59d4,
  nature:   0x2ecc71,
  ice:      0x4fc3f7,
  electric: 0xf5c518,
};

function debrisColor(element: unknown): number {
  return ELEMENT_DEBRIS[String(element)] ?? 0x8a8fa8;
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface AnimatorInstance {
  enqueue(evt: WsFightEvent): void;
  reset(): void;
}

export function createAnimator(arena: ArenaInstance, physics: DebrisSystem): AnimatorInstance {
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
        const targetElement = targetSlot.sprite.parent
          ? debrisColor(undefined)   // fallback; real element isn't stored on sprite
          : 0xff4444;

        // Attacker lunges
        await tweenTo(actorSlot.sprite, { x: actorSlot.homeX + dx * 0.32 }, 130);

        // Impact: flash + physics debris + arc knockback + shake — all in parallel
        await Promise.all([
          tweenTo(actorSlot.sprite, { x: actorSlot.homeX }, 130),
          flashOverlay(targetSlot.sprite, 0xff2222, 160),
          arcKnockback(targetSlot.sprite, targetSlot.homeX, targetSlot.homeY, dx * -0.35, 280),
          cameraShake(arena.stage, 3, 120),
          Promise.resolve(physics.emit(targetSlot.homeX, targetSlot.homeY - 20, 5, 0xff4444, 1.0)),
        ]);

        for (const [id, hp] of Object.entries(evt.hp_remaining)) {
          arena.updateHp(id, hp);
        }
        break;
      }

      case 'ability': {
        if (!actorSlot) break;
        const abilityColor = 0xb56cf5;

        await tweenScale(actorSlot.sprite, 1.18, 180);

        if (targetSlot) {
          const dx = targetSlot.homeX - actorSlot.homeX;
          await Promise.all([
            emitParticles(
              arena.stage,
              { x: actorSlot.homeX, y: actorSlot.homeY - 20 },
              { x: targetSlot.homeX, y: targetSlot.homeY - 20 },
              6,
              abilityColor,
            ),
            tweenScale(actorSlot.sprite, 1, 180),
            cameraShake(arena.stage, 4, 140),
          ]);
          await Promise.all([
            flashOverlay(targetSlot.sprite, 0xaa44ff, 120),
            arcKnockback(targetSlot.sprite, targetSlot.homeX, targetSlot.homeY, dx * -0.45, 320),
            Promise.resolve(physics.emit(targetSlot.homeX, targetSlot.homeY - 15, 7, abilityColor, 1.4)),
          ]);
        } else {
          await tweenScale(actorSlot.sprite, 1, 180);
        }

        for (const [id, hp] of Object.entries(evt.hp_remaining)) {
          arena.updateHp(id, hp);
        }
        break;
      }

      case 'dodge': {
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
        emitTextParticle(arena.stage, '+momentum', actorSlot.homeX, actorSlot.homeY - 60);
        break;
      }

      case 'ko': {
        const loserId = Object.entries(evt.hp_remaining).find(([, hp]) => hp <= 0)?.[0];
        const ls = loserId ? arena.getSlot(loserId) : undefined;

        if (ls) {
          // Direction: creatures on the left spin one way, right the other
          const spinDir = ls.homeX < 400 ? -1 : 1;

          // Trigger all KO effects simultaneously
          physics.emit(ls.homeX, ls.homeY - 10, 14, 0xff3333, 2.2);

          await Promise.all([
            tweenTo(ls.sprite, { y: ls.homeY + 90, alpha: 0 }, 650),
            tweenRotation(ls.sprite, Math.PI * 2.5 * spinDir, 650),
            flashStage(arena.stage, 0x220000, 300),
            cameraShake(arena.stage, 8, 250),
          ]);

          arena.updateHp(loserId!, 0);
        }

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
