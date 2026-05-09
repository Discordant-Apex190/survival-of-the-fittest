import { Container, Graphics, Text, Ticker } from 'pixi.js';
import type { WsFightEvent } from '../schemas/ws';
import type { ArenaInstance } from './arena';
import type { ElementEmitter } from './particles';
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

type EasingFn = (t: number) => number;

const linear: EasingFn = (t) => t;
const easeOutQuad: EasingFn = (t) => 1 - (1 - t) * (1 - t);
const easeInOutQuad: EasingFn = (t) => (t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2);
const easeOutBack: EasingFn = (t) => {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * ((t - 1) ** 3) + c1 * ((t - 1) ** 2);
};

function tweenTo(
  obj: { x: number; y: number; alpha: number },
  to: TweenProps,
  ms: number,
  easing: EasingFn = linear,
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
      const e = easing(t);
      obj.x = fx + (tx - fx) * e;
      obj.y = fy + (ty - fy) * e;
      obj.alpha = fa + (ta - fa) * e;
      if (t >= 1) {
        Ticker.shared.remove(fn);
        resolve();
      }
    };
    Ticker.shared.add(fn);
  });
}

function tweenScale(
  obj: Container,
  toScale: number,
  ms: number,
  easing: EasingFn = linear,
): Promise<void> {
  const sign = obj.scale.x < 0 ? -1 : 1;
  const fromS = Math.abs(obj.scale.x);
  return new Promise((resolve) => {
    let elapsed = 0;
    const fn = (ticker: Ticker) => {
      elapsed += ticker.deltaMS;
      const t = Math.min(elapsed / ms, 1);
      const e = easing(t);
      const s = fromS + (toScale - fromS) * e;
      obj.scale.set(sign * s, s);
      if (t >= 1) {
        Ticker.shared.remove(fn);
        resolve();
      }
    };
    Ticker.shared.add(fn);
  });
}

function tweenRotation(
  obj: Container,
  toAngle: number,
  ms: number,
  easing: EasingFn = linear,
): Promise<void> {
  const from = obj.rotation;
  return new Promise((resolve) => {
    let elapsed = 0;
    const fn = (ticker: Ticker) => {
      elapsed += ticker.deltaMS;
      const t = Math.min(elapsed / ms, 1);
      const e = easing(t);
      obj.rotation = from + (toAngle - from) * e;
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
  const startX = homeX;
  const startY = homeY;
  const endX = homeX + nudgeX;
  const endY = homeY;
  const ctrlX = homeX + nudgeX * 0.55;
  const ctrlY = homeY - Math.min(38, Math.max(20, Math.abs(nudgeX) * 0.35));

  await new Promise<void>((resolve) => {
    let elapsed = 0;
    const fn = (ticker: Ticker) => {
      elapsed += ticker.deltaMS;
      const t = Math.min(elapsed / ms, 1);
      const e = easeOutQuad(t);
      const u = 1 - e;
      sprite.x = u * u * startX + 2 * u * e * ctrlX + e * e * endX;
      sprite.y = u * u * startY + 2 * u * e * ctrlY + e * e * endY;
      if (t >= 1) {
        Ticker.shared.remove(fn);
        resolve();
      }
    };
    Ticker.shared.add(fn);
  });

  await tweenTo(sprite, { x: homeX, y: homeY }, Math.max(90, ms * 0.4), easeInOutQuad);
}

async function hitStop(ms: number): Promise<void> {
  await sleep(ms);
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

function showAbilityBanner(
  stage: Container,
  x: number,
  y: number,
  name: string,
  color: number,
): void {
  const label = new Text({
    text: name.toUpperCase(),
    style: {
      fill: `#${color.toString(16).padStart(6, '0')}`,
      fontSize: 17,
      fontWeight: '700',
      letterSpacing: 3,
      fontFamily: 'DM Mono, Courier New, monospace',
    },
  });
  label.anchor.set(0.5, 0.5);
  label.x = x;
  label.y = y - 70;
  label.alpha = 0;
  label.scale.set(0.7);
  stage.addChild(label);

  void (async () => {
    await Promise.all([
      tweenTo(label, { alpha: 1 }, 180, easeOutQuad),
      tweenScale(label, 1.0, 180, easeOutBack),
    ]);
    await sleep(480);
    await tweenTo(label, { y: label.y - 18, alpha: 0 }, 280, easeOutQuad);
    stage.removeChild(label);
    if (!label.destroyed) label.destroy();
  })();
}

function showDamageNumber(
  stage: Container,
  x: number,
  y: number,
  damage: number,
): void {
  const color = damage >= 20 ? '#ef4444' : damage >= 10 ? '#f5c518' : '#e8eaf0';
  const fontSize = damage >= 20 ? 22 : 17;
  const label = new Text({
    text: String(damage),
    style: {
      fill: color,
      fontSize,
      fontWeight: '700',
      fontFamily: 'DM Mono, Courier New, monospace',
    },
  });
  label.anchor.set(0.5, 0.5);
  label.x = x + (Math.random() - 0.5) * 30;
  label.y = y - 50;
  label.alpha = 1;
  label.scale.set(0.5);
  stage.addChild(label);

  void (async () => {
    await tweenScale(label, 1.3, 140, easeOutBack);
    await tweenScale(label, 1.0, 80, easeInOutQuad);
    await tweenTo(label, { y: label.y - 45, alpha: 0 }, 650, easeOutQuad);
    stage.removeChild(label);
    if (!label.destroyed) label.destroy();
  })();
}

function showEffectStatus(
  stage: Container,
  x: number,
  y: number,
  effect: string,
): void {
  const byEffect: Record<string, { text: string; color: string }> = {
    stun: { text: '* STUNNED', color: '#f5c518' },
    slow: { text: '* SLOWED', color: '#4fc3f7' },
    shield_break: { text: '* GUARD BREAK', color: '#f05a28' },
  };
  const cfg = byEffect[effect];
  if (!cfg) return;

  const label = new Text({
    text: cfg.text,
    style: {
      fill: cfg.color,
      fontSize: 11,
      fontWeight: '700',
      letterSpacing: 1.5,
      fontFamily: 'DM Mono, Courier New, monospace',
    },
  });
  label.anchor.set(0.5, 0.5);
  label.x = x;
  label.y = y - 90;
  label.alpha = 1;
  stage.addChild(label);

  void tweenTo(label, { y: label.y - 25, alpha: 0 }, 900, easeOutQuad).then(() => {
    stage.removeChild(label);
    if (!label.destroyed) label.destroy();
  });
}

// ---------------------------------------------------------------------------
// New visual effects
// ---------------------------------------------------------------------------

async function shockwaveRing(
  stage: Container,
  x: number,
  y: number,
  color: number,
  maxRadius = 80,
  ms = 350,
): Promise<void> {
  const ring = new Graphics();
  stage.addChild(ring);
  let elapsed = 0;
  return new Promise((resolve) => {
    const fn = (ticker: Ticker) => {
      elapsed += ticker.deltaMS;
      const t = Math.min(elapsed / ms, 1);
      const r = t * maxRadius;
      const alpha = (1 - t) * 0.70;
      const sw = Math.max(0.5, 3 - t * 2.2);
      ring.clear();
      ring.circle(x, y, r).stroke({ width: sw, color, alpha });
      if (t >= 1) {
        stage.removeChild(ring);
        ring.destroy();
        Ticker.shared.remove(fn);
        resolve();
      }
    };
    Ticker.shared.add(fn);
  });
}

async function groundDust(
  stage: Container,
  x: number,
  groundY: number,
  color: number,
): Promise<void> {
  const puffs = Array.from({ length: 4 }, (_, i) => {
    const g = new Graphics();
    const w = 8 + Math.random() * 7;
    const h = 3 + Math.random() * 3;
    g.ellipse(0, 0, w, h).fill({ color, alpha: 0.45 });
    const spread = (i - 1.5) * 15;
    g.x = x + spread;
    g.y = groundY;
    g.alpha = 0.45;
    stage.addChild(g);
    return { g, targetX: x + spread * 1.9 };
  });
  await Promise.all(puffs.map(({ g, targetX }) =>
    tweenTo(g, { x: targetX, y: groundY - 5, alpha: 0 }, 380),
  ));
  puffs.forEach(({ g }) => {
    stage.removeChild(g);
    if (!g.destroyed) g.destroy();
  });
}

function spawnTrail(stage: Container, x: number, y: number, color: number): void {
  const trail = new Graphics();
  trail.circle(0, 0, 3 + Math.random() * 2).fill({ color, alpha: 0.38 });
  trail.x = x;
  trail.y = y;
  stage.addChild(trail);
  void tweenTo(trail, { alpha: 0, y: y - 8 }, 180, easeOutQuad).then(() => {
    stage.removeChild(trail);
    if (!trail.destroyed) trail.destroy();
  });
}

async function fireProjectile(
  stage: Container,
  from: { x: number; y: number },
  to: { x: number; y: number },
  color: number,
  ms = 210,
): Promise<void> {
  const g = new Graphics();
  // Arrowhead shape
  g.poly([0, -7, 5, 5, 0, 2, -5, 5]).fill({ color, alpha: 0.92 });
  g.x = from.x;
  g.y = from.y;
  stage.addChild(g);

  const midX = (from.x + to.x) / 2;
  const midY = (from.y + to.y) / 2 - 42;

  return new Promise((resolve) => {
    let elapsed = 0;
    let sinceTrail = 0;
    const fn = (ticker: Ticker) => {
      elapsed += ticker.deltaMS;
      sinceTrail += ticker.deltaMS;
      const t = Math.min(elapsed / ms, 1);
      const u = 1 - t;
      // Quadratic bezier
      g.x = u * u * from.x + 2 * u * t * midX + t * t * to.x;
      g.y = u * u * from.y + 2 * u * t * midY + t * t * to.y;
      if (sinceTrail >= 24) {
        sinceTrail = 0;
        spawnTrail(stage, g.x, g.y, color);
      }
      // Rotate to face direction of travel
      if (t < 0.95) {
        const t2 = Math.min(t + 0.06, 1);
        const u2 = 1 - t2;
        const nx = u2 * u2 * from.x + 2 * u2 * t2 * midX + t2 * t2 * to.x;
        const ny = u2 * u2 * from.y + 2 * u2 * t2 * midY + t2 * t2 * to.y;
        g.rotation = Math.atan2(ny - g.y, nx - g.x) + Math.PI / 2;
      }
      if (t >= 1) {
        stage.removeChild(g);
        if (!g.destroyed) g.destroy();
        Ticker.shared.remove(fn);
        resolve();
      }
    };
    Ticker.shared.add(fn);
  });
}

async function lightningBolt(
  stage: Container,
  from: { x: number; y: number },
  to: { x: number; y: number },
  color: number,
): Promise<void> {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const nx = -dy / length;
  const ny = dx / length;
  const segments = 9;
  const jitter = length * 0.18;

  const points: Array<{ x: number; y: number }> = [{ x: from.x, y: from.y }];
  for (let i = 1; i < segments; i += 1) {
    const t = i / segments;
    const bx = from.x + dx * t;
    const by = from.y + dy * t;
    const j = (Math.random() - 0.5) * jitter;
    points.push({ x: bx + nx * j, y: by + ny * j });
  }
  points.push({ x: to.x, y: to.y });

  const outer = new Graphics();
  const inner = new Graphics();
  outer.moveTo(points[0].x, points[0].y);
  inner.moveTo(points[0].x, points[0].y);
  for (let i = 1; i < points.length; i += 1) {
    outer.lineTo(points[i].x, points[i].y);
    inner.lineTo(points[i].x, points[i].y);
  }
  outer.stroke({ width: 3.5, color, alpha: 0.95 });
  inner.stroke({ width: 1.5, color: 0xffffff, alpha: 0.8 });
  stage.addChild(outer);
  stage.addChild(inner);

  await sleep(55);
  await Promise.all([
    tweenTo(outer, { alpha: 0 }, 100, easeOutQuad),
    tweenTo(inner, { alpha: 0 }, 100, easeOutQuad),
  ]);

  stage.removeChild(outer);
  stage.removeChild(inner);
  if (!outer.destroyed) outer.destroy();
  if (!inner.destroyed) inner.destroy();
}

async function implodeRing(
  stage: Container,
  x: number,
  y: number,
  color: number,
  startRadius = 100,
  ms = 350,
): Promise<void> {
  const ring = new Graphics();
  stage.addChild(ring);
  let elapsed = 0;

  return new Promise((resolve) => {
    const fn = (ticker: Ticker) => {
      elapsed += ticker.deltaMS;
      const t = Math.min(elapsed / ms, 1);
      const e = easeInOutQuad(t);
      const radius = (1 - e) * startRadius + 1;
      const alpha = t < 0.7 ? 0.75 : ((1 - t) / 0.3) * 0.75;
      const sw = Math.max(0.5, 2 + (1 - t) * 2);
      ring.clear();
      ring.circle(x, y, radius).stroke({ width: sw, color, alpha: Math.max(0, alpha) });

      if (t >= 1) {
        stage.removeChild(ring);
        if (!ring.destroyed) ring.destroy();
        Ticker.shared.remove(fn);
        resolve();
      }
    };
    Ticker.shared.add(fn);
  });
}

async function iceShardsAttack(
  stage: Container,
  from: { x: number; y: number },
  to: { x: number; y: number },
  ms = 220,
): Promise<void> {
  const baseAngle = Math.atan2(to.y - from.y, to.x - from.x);
  const spread = 0.4;

  const shards = Array.from({ length: 4 }, (_, i) => {
    const t = i / 3;
    const offset = (t - 0.5) * spread;
    const angle = baseAngle + offset;
    const size = 5 + Math.random() * 3;
    const dist = Math.hypot(to.x - from.x, to.y - from.y) * (0.92 + Math.random() * 0.16);
    const g = new Graphics();
    g.poly([0, -size, size * 0.65, size, -size * 0.65, size]).fill({ color: 0x4fc3f7, alpha: 0.95 });
    g.x = from.x;
    g.y = from.y;
    g.rotation = angle + Math.PI / 2;
    stage.addChild(g);
    return {
      g,
      tx: from.x + Math.cos(angle) * dist,
      ty: from.y + Math.sin(angle) * dist,
    };
  });

  await Promise.all(shards.map(({ g, tx, ty }) => tweenTo(g, { x: tx, y: ty, alpha: 0.2 }, ms, easeOutQuad)));
  for (const { g } of shards) {
    stage.removeChild(g);
    if (!g.destroyed) g.destroy();
  }
}

type SlotLike = {
  sprite: Container;
  homeX: number;
  homeY: number;
  element: string;
};

async function playElementalProjectile(
  element: string,
  stage: Container,
  actorSlot: SlotLike,
  targetSlot: SlotLike,
  aColor: number,
): Promise<void> {
  if (element === 'electric') {
    await Promise.all([
      lightningBolt(
        stage,
        { x: actorSlot.homeX, y: actorSlot.homeY - 20 },
        { x: targetSlot.homeX, y: targetSlot.homeY - 20 },
        aColor,
      ),
      tweenScale(actorSlot.sprite, 1, 120, easeInOutQuad),
      flashStage(stage, aColor, 120),
      cameraShake(stage, 5.5, 150),
    ]);
    return;
  }

  if (element === 'void') {
    await Promise.all([
      implodeRing(stage, actorSlot.homeX, actorSlot.homeY - 20, aColor, 90, 280),
      tweenScale(actorSlot.sprite, 1, 180, easeInOutQuad),
      cameraShake(stage, 4.5, 160),
    ]);
    await Promise.all([
      fireProjectile(
        stage,
        { x: actorSlot.homeX, y: actorSlot.homeY - 20 },
        { x: targetSlot.homeX, y: targetSlot.homeY - 20 },
        aColor,
        280,
      ),
      cameraShake(stage, 3.5, 100),
    ]);
    return;
  }

  if (element === 'ice') {
    await Promise.all([
      iceShardsAttack(
        stage,
        { x: actorSlot.homeX, y: actorSlot.homeY - 20 },
        { x: targetSlot.homeX, y: targetSlot.homeY - 20 },
        220,
      ),
      tweenScale(actorSlot.sprite, 1, 200, easeInOutQuad),
      cameraShake(stage, 4.0, 140),
    ]);
    return;
  }

  await Promise.all([
    fireProjectile(
      stage,
      { x: actorSlot.homeX, y: actorSlot.homeY - 20 },
      { x: targetSlot.homeX, y: targetSlot.homeY - 20 },
      aColor,
      260,
    ),
    tweenScale(actorSlot.sprite, 1, 200, easeInOutQuad),
    cameraShake(stage, 5.2, 170),
  ]);
}

// ---------------------------------------------------------------------------
// Element color map (for debris tint)
// ---------------------------------------------------------------------------

const ELEMENT_DEBRIS: Record<string, number> = {
  fire:     0xf05a28,
  void:     0x9b59d4,
  nature:   0x2ecc71,
  ice:      0x4fc3f7,
  electric: 0xf5c518,
};

function debrisColor(element: string | undefined): number {
  return ELEMENT_DEBRIS[String(element)] ?? 0x8a8fa8;
}

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface AnimatorInstance {
  enqueue(evt: WsFightEvent): void;
  reset(): void;
}

/**
 * elementEmitters is passed by reference — mutate it externally (per fight)
 * and playEvent will always see the current creature emitters.
 */
export function createAnimator(
  arena: ArenaInstance,
  physics: DebrisSystem,
  elementEmitters: Map<string, ElementEmitter>,
): AnimatorInstance {
  const queue: WsFightEvent[] = [];
  let running = false;

  function spacingForEvent(eventType: string): number {
    switch (eventType) {
      case 'attack':
        return 130;
      case 'ability':
        return 190;
      case 'dodge':
        return 120;
      case 'taunt':
        return 145;
      case 'ko':
        return 360;
      default:
        return 150;
    }
  }

  async function drain() {
    running = true;
    while (queue.length > 0) {
      const evt = queue.shift()!;
      await playEvent(evt);
      await sleep(spacingForEvent(evt.event_type));
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
        const aColor = debrisColor(actorSlot.element);
        const tColor = debrisColor(targetSlot.element);
        const lungeScaleByElement: Record<string, number> = {
          fire: 0.38,
          electric: 0.36,
          ice: 0.32,
          nature: 0.33,
          void: 0.35,
        };
        const lungeScale = lungeScaleByElement[actorSlot.element] ?? 0.34;

        // Attacker lunges
        await tweenTo(actorSlot.sprite, { x: actorSlot.homeX + dx * lungeScale }, 150, easeOutQuad);
        await hitStop(42);

        // Impact — all in parallel
        await Promise.all([
          tweenTo(actorSlot.sprite, { x: actorSlot.homeX }, 150, easeInOutQuad),
          flashOverlay(targetSlot.sprite, 0xff2222, 180),
          // Knockback arc then ground dust at landing
          (async () => {
            await arcKnockback(targetSlot.sprite, targetSlot.homeX, targetSlot.homeY, dx * -0.38, 330);
            groundDust(arena.stage, targetSlot.homeX, targetSlot.homeY, tColor);
          })(),
          cameraShake(arena.stage, 4.3, 170),
          Promise.resolve(physics.emit(targetSlot.homeX, targetSlot.homeY - 20, 7, tColor, 1.2)),
          Promise.resolve(elementEmitters.get(evt.actor_id!)?.burst(
            targetSlot.homeX, targetSlot.homeY - 20, 5, 1.0,
          )),
          shockwaveRing(arena.stage, targetSlot.homeX, targetSlot.homeY - 18, aColor, 56, 250),
        ]);

        for (const [id, hp] of Object.entries(evt.hp_remaining)) {
          arena.updateHp(id, hp);
        }
        if (evt.damage != null && evt.damage > 0) {
          showDamageNumber(arena.stage, targetSlot.homeX, targetSlot.homeY - 25, evt.damage);
        }
        break;
      }

      case 'ability': {
        if (!actorSlot) break;
        const aColor = debrisColor(actorSlot.element);
        const abilityName = evt.ability_name;
        const abilityEffect = evt.ability_effect;

        if (abilityName) {
          showAbilityBanner(arena.stage, actorSlot.homeX, actorSlot.homeY, abilityName, aColor);
        }

        await tweenScale(actorSlot.sprite, 1.25, 240, easeOutBack);

        if (targetSlot) {
          const dx = targetSlot.homeX - actorSlot.homeX;
          await playElementalProjectile(
            actorSlot.element,
            arena.stage,
            actorSlot,
            targetSlot,
            aColor,
          );
          await hitStop(55);
          await Promise.all([
            flashOverlay(targetSlot.sprite, aColor, 180),
            (async () => {
              await arcKnockback(targetSlot.sprite, targetSlot.homeX, targetSlot.homeY, dx * -0.5, 380);
              groundDust(arena.stage, targetSlot.homeX, targetSlot.homeY, debrisColor(targetSlot.element));
            })(),
            Promise.resolve(physics.emit(targetSlot.homeX, targetSlot.homeY - 15, 10, aColor, 1.8)),
            Promise.resolve(elementEmitters.get(evt.actor_id!)?.burst(
              targetSlot.homeX, targetSlot.homeY - 15, 7, 1.5,
            )),
            shockwaveRing(arena.stage, targetSlot.homeX, targetSlot.homeY - 20, aColor, 92, 420),
          ]);
          if (abilityEffect && abilityEffect !== 'damage') {
            showEffectStatus(arena.stage, targetSlot.homeX, targetSlot.homeY - 15, abilityEffect);
          }
        } else {
          await tweenScale(actorSlot.sprite, 1, 200, easeInOutQuad);
        }

        for (const [id, hp] of Object.entries(evt.hp_remaining)) {
          arena.updateHp(id, hp);
        }
        if (targetSlot && evt.damage != null && evt.damage > 0) {
          showDamageNumber(arena.stage, targetSlot.homeX, targetSlot.homeY - 30, evt.damage);
        }
        break;
      }

      case 'dodge': {
        const defSlot = targetSlot ?? actorSlot;
        if (!defSlot) break;
        const nudge = defSlot.homeX > 400 ? 20 : -20;
        await tweenTo(defSlot.sprite, { x: defSlot.homeX + nudge, y: defSlot.homeY - 3 }, 105, easeOutQuad);
        await Promise.all([
          tweenTo(defSlot.sprite, { x: defSlot.homeX, y: defSlot.homeY }, 145, easeInOutQuad),
          cameraShake(arena.stage, 1.8, 85),
        ]);
        break;
      }

      case 'taunt': {
        if (!actorSlot) break;
        await tweenTo(actorSlot.sprite, { y: actorSlot.homeY - 16 }, 125, easeOutBack);
        await Promise.all([
          tweenTo(actorSlot.sprite, { y: actorSlot.homeY }, 135, easeInOutQuad),
          cameraShake(arena.stage, 2.3, 95),
        ]);
        emitTextParticle(arena.stage, '+momentum', actorSlot.homeX, actorSlot.homeY - 60);
        break;
      }

      case 'ko': {
        const loserId = Object.entries(evt.hp_remaining).find(([, hp]) => hp <= 0)?.[0];
        const ls = loserId ? arena.getSlot(loserId) : undefined;

        if (ls) {
          const spinDir = ls.homeX < 400 ? -1 : 1;
          const koColor = debrisColor(ls.element);

          // Fire all burst effects before the tween
          physics.emit(ls.homeX, ls.homeY - 10, 14, 0xff3333, 2.2);
          physics.emitLarge(ls.homeX, ls.homeY - 10, 6, koColor, 1.8);
          elementEmitters.get(loserId!)?.burst(ls.homeX, ls.homeY - 20, 8, 2.0);

          await Promise.all([
            tweenTo(ls.sprite, { y: ls.homeY + 90, alpha: 0 }, 820, easeInOutQuad),
            tweenRotation(ls.sprite, Math.PI * 2.9 * spinDir, 820, easeInOutQuad),
            flashStage(arena.stage, 0x220000, 380),
            cameraShake(arena.stage, 9.2, 320),
            shockwaveRing(arena.stage, ls.homeX, ls.homeY - 20, 0xff3333, 160, 620),
          ]);

          await sleep(220);

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
