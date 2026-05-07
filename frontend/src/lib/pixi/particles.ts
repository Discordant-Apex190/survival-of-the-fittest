import Matter from 'matter-js';
import { Container, Graphics, Ticker } from 'pixi.js';

const { Engine, Bodies, Body, World } = Matter;

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface ElementEmitter {
  burst(x: number, y: number, count: number, strength?: number): void;
  destroy(): void;
}

// ---------------------------------------------------------------------------
// Per-element config
// ---------------------------------------------------------------------------

interface ElementConfig {
  gravity: number;
  alphaDecay: number;   // per ms
  makeShape(g: Graphics, size: number): void;
  makeBody(x: number, y: number, size: number): Matter.Body;
  velocity(angle: number, speed: number): { x: number; y: number };
  minSize: number;
  maxSize: number;
}

const CONFIGS: Record<string, ElementConfig> = {
  fire: {
    gravity: 4.0,
    alphaDecay: 0.0032,
    makeShape(g, size) {
      g.circle(0, 0, size * 1.6).fill({ color: 0xffaa00, alpha: 0.28 });
      g.circle(0, 0, size).fill({ color: 0xf05a28, alpha: 1 });
    },
    makeBody(x, y, size) {
      return Bodies.circle(x, y, size, { restitution: 0.3, friction: 0.05, frictionAir: 0.03, mass: 0.06 });
    },
    velocity(angle, speed) {
      return { x: Math.cos(angle) * speed, y: Math.sin(angle) * speed - 5.5 };
    },
    minSize: 2, maxSize: 5,
  },

  ice: {
    gravity: 2.0,
    alphaDecay: 0.0018,
    makeShape(g, size) {
      const s = size * 1.2;
      g.poly([0, -s, s, s * 0.6, -s, s * 0.6]).fill({ color: 0x4fc3f7, alpha: 1 });
    },
    makeBody(x, y, size) {
      return Bodies.circle(x, y, size, { restitution: 0.55, friction: 0.03, frictionAir: 0.014, mass: 0.07 });
    },
    velocity(angle, speed) {
      return { x: Math.cos(angle) * speed * 1.4, y: Math.sin(angle) * speed - 3.5 };
    },
    minSize: 3, maxSize: 6,
  },

  electric: {
    gravity: 0.5,
    alphaDecay: 0.006,
    makeShape(g, size) {
      g.rect(-size * 2.2, -size * 0.4, size * 4.4, size * 0.8).fill({ color: 0xf5c518, alpha: 1 });
    },
    makeBody(x, y, size) {
      return Bodies.rectangle(x, y, size * 4.4, size * 0.8, {
        restitution: 0.1, friction: 0.0, frictionAir: 0.05, mass: 0.04,
      });
    },
    velocity(angle, speed) {
      // Wide horizontal burst
      return { x: Math.cos(angle) * speed * 2.2, y: Math.sin(angle) * speed * 0.25 - 1.8 };
    },
    minSize: 1.5, maxSize: 3,
  },

  void: {
    gravity: 3.0,
    alphaDecay: 0.0022,
    makeShape(g, size) {
      const pts: number[] = [];
      for (let i = 0; i < 5; i++) {
        const a = (i * Math.PI * 2) / 5 - Math.PI / 2;
        pts.push(Math.cos(a) * size, Math.sin(a) * size);
      }
      g.poly(pts).fill({ color: 0x9b59d4, alpha: 1 });
    },
    makeBody(x, y, size) {
      return Bodies.circle(x, y, size, { restitution: 0.4, friction: 0.1, frictionAir: 0.025, mass: 0.09 });
    },
    velocity(angle, speed) {
      return { x: Math.cos(angle) * speed * 0.75, y: Math.sin(angle) * speed - 3.8 };
    },
    minSize: 3, maxSize: 6,
  },

  nature: {
    gravity: 3.5,
    alphaDecay: 0.0025,
    makeShape(g, size) {
      // Diamond leaf
      g.poly([0, -size * 1.5, size * 0.7, 0, 0, size * 1.0, -size * 0.7, 0]).fill({ color: 0x2ecc71, alpha: 1 });
    },
    makeBody(x, y, size) {
      return Bodies.circle(x, y, size, { restitution: 0.35, friction: 0.08, frictionAir: 0.028, mass: 0.07 });
    },
    velocity(angle, speed) {
      return { x: Math.cos(angle) * speed, y: Math.sin(angle) * speed - 4.2 };
    },
    minSize: 2.5, maxSize: 5.5,
  },
};

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createElementEmitter(stage: Container, element: string): ElementEmitter {
  const cfg = CONFIGS[element] ?? CONFIGS.void;
  const engine = Engine.create({ gravity: { x: 0, y: cfg.gravity } });

  const floor = Bodies.rectangle(400, 475, 900, 50, { isStatic: true, label: 'floor' });
  World.add(engine.world, floor);

  const active = new Map<Matter.Body, Graphics>();

  const tickerFn = (ticker: Ticker) => {
    Engine.update(engine, ticker.deltaMS);
    for (const [body, g] of active) {
      g.x = body.position.x;
      g.y = body.position.y;
      g.rotation = body.angle;
      g.alpha -= ticker.deltaMS * cfg.alphaDecay;
      if (g.alpha <= 0) {
        stage.removeChild(g);
        if (!g.destroyed) g.destroy();
        World.remove(engine.world, body);
        active.delete(body);
      }
    }
  };
  Ticker.shared.add(tickerFn);

  return {
    burst(x, y, count, strength = 1.0) {
      for (let i = 0; i < count; i++) {
        const size = cfg.minSize + Math.random() * (cfg.maxSize - cfg.minSize);
        const body = cfg.makeBody(x, y, size);

        const angle = Math.random() * Math.PI * 2;
        const speed = (2.0 + Math.random() * 3.5) * strength;
        Body.setVelocity(body, cfg.velocity(angle, speed));
        Body.setAngularVelocity(body, (Math.random() - 0.5) * 0.9);
        World.add(engine.world, body);

        const g = new Graphics();
        cfg.makeShape(g, size);
        g.x = x;
        g.y = y;
        g.alpha = 1;
        stage.addChild(g);
        active.set(body, g);
      }
    },

    destroy() {
      Ticker.shared.remove(tickerFn);
      for (const [, g] of active) {
        if (!g.destroyed) g.destroy();
      }
      active.clear();
      Engine.clear(engine);
    },
  };
}
