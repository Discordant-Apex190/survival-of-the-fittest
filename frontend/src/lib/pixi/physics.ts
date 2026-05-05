import Matter from 'matter-js';
import { Container, Graphics, Ticker } from 'pixi.js';

const { Engine, Bodies, Body, World } = Matter;

// ---------------------------------------------------------------------------
// Camera shake (stage-level effect, no Matter.js needed)
// ---------------------------------------------------------------------------

export async function cameraShake(
  stage: Container,
  intensity: number,
  ms: number,
): Promise<void> {
  const origX = stage.x;
  const origY = stage.y;
  let elapsed = 0;

  return new Promise((resolve) => {
    const fn = (ticker: Ticker) => {
      elapsed += ticker.deltaMS;
      const decay = Math.max(0, 1 - elapsed / ms);
      stage.x = origX + (Math.random() - 0.5) * intensity * 2 * decay;
      stage.y = origY + (Math.random() - 0.5) * intensity * 2 * decay;
      if (elapsed >= ms) {
        stage.x = origX;
        stage.y = origY;
        Ticker.shared.remove(fn);
        resolve();
      }
    };
    Ticker.shared.add(fn);
  });
}

// ---------------------------------------------------------------------------
// Debris particle system
// ---------------------------------------------------------------------------

export interface DebrisSystem {
  emit(x: number, y: number, count: number, color: number, strength?: number): void;
  destroy(): void;
}

export function createDebrisSystem(stage: Container): DebrisSystem {
  const engine = Engine.create({ gravity: { x: 0, y: 4.0 } });

  // Invisible floor — debris bounces off this
  const floor = Bodies.rectangle(400, 475, 900, 50, { isStatic: true, label: 'floor' });
  World.add(engine.world, floor);

  // Track live particles: body → Pixi Graphics
  const active = new Map<Matter.Body, Graphics>();

  const tickerFn = (ticker: Ticker) => {
    Engine.update(engine, ticker.deltaMS);

    for (const [body, g] of active) {
      g.x = body.position.x;
      g.y = body.position.y;
      g.rotation = body.angle;
      g.alpha -= ticker.deltaMS * 0.0026; // ~380 ms lifetime

      if (g.alpha <= 0) {
        stage.removeChild(g);
        g.destroy();
        World.remove(engine.world, body);
        active.delete(body);
      }
    }
  };

  Ticker.shared.add(tickerFn);

  let particleIndex = 0;

  return {
    emit(x, y, count, color, strength = 1) {
      for (let i = 0; i < count; i++) {
        const size = 2.5 + Math.random() * 3.5;
        const body = Bodies.circle(x, y, size, {
          restitution: 0.42,
          friction: 0.08,
          frictionAir: 0.022,
          mass: 0.08,
        });

        const angle = Math.random() * Math.PI * 2;
        const speed = (2.5 + Math.random() * 4.5) * strength;
        Body.setVelocity(body, {
          x: Math.cos(angle) * speed,
          y: Math.sin(angle) * speed - 4.5, // upward bias so debris arcs
        });
        Body.setAngularVelocity(body, (Math.random() - 0.5) * 0.5);

        World.add(engine.world, body);

        const g = new Graphics();
        // Alternate squares and triangles for visual variety
        if (particleIndex % 3 === 0) {
          const s = size * 1.2;
          g.poly([0, -s, s, s * 0.6, -s, s * 0.6]).fill({ color, alpha: 1 });
        } else {
          g.rect(-size, -size, size * 2, size * 2).fill({ color, alpha: 1 });
        }
        particleIndex++;

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
