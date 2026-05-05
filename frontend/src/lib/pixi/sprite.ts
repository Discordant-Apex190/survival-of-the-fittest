import { Container, Graphics } from 'pixi.js';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CreatureData {
  id: string;
  name: string;
  element: string;
  tier: string;
  stats: { health: number; attack: number; defense: number; speed: number };
}

type Facing = 'left' | 'right';

// ---------------------------------------------------------------------------
// Color tables
// ---------------------------------------------------------------------------

const TIER_MAX: Record<string, number> = {
  common: 25, uncommon: 30, rare: 38, legendary: 50,
};

const ELEMENT_COLORS: Record<string, { primary: number; secondary: number; glow: number }> = {
  fire:     { primary: 0xf05a28, secondary: 0xcc3300, glow: 0xffaa00 },
  void:     { primary: 0x9b59d4, secondary: 0x5a1a8a, glow: 0xaaddff },
  nature:   { primary: 0x2ecc71, secondary: 0x1a7a44, glow: 0xeeffcc },
  ice:      { primary: 0x4fc3f7, secondary: 0x0077aa, glow: 0xccffff },
  electric: { primary: 0xf5c518, secondary: 0xcc9900, glow: 0xffffaa },
};

const DEFAULT_COLORS = { primary: 0x8a8fa8, secondary: 0x555777, glow: 0xaaaacc };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function hashId(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (Math.imul(h, 31) + id.charCodeAt(i)) >>> 0;
  }
  return h;
}

// ---------------------------------------------------------------------------
// Main builder
// ---------------------------------------------------------------------------

export function buildSprite(creature: CreatureData, facing: Facing): Container {
  const colors = ELEMENT_COLORS[creature.element] ?? DEFAULT_COLORS;
  const max = TIER_MAX[creature.tier] ?? 25;
  const { health, attack, defense, speed } = creature.stats;
  const n = {
    health:  Math.min(health  / max, 1),
    attack:  Math.min(attack  / max, 1),
    defense: Math.min(defense / max, 1),
    speed:   Math.min(speed   / max, 1),
  };
  const h = hashId(creature.id);
  const r = 30 + n.health * 18; // body radius 30–48 px

  const root = new Container();

  // --- Aura (behind everything) ---
  if (n.attack > 0.5) {
    const aura = new Graphics();
    aura.circle(0, 0, r * 1.4).fill({ color: colors.glow, alpha: 0.12 + n.attack * 0.1 });
    root.addChild(aura);
  }

  // --- Layer 6a: Wings (speed creatures, behind body) ---
  if (n.speed > 0.7) {
    const wings = new Graphics();
    wings
      .ellipse(-r * 1.5, -r * 0.25, r * 0.85, r * 0.38)
      .fill({ color: colors.secondary, alpha: 0.55 });
    wings
      .ellipse(r * 1.5, -r * 0.25, r * 0.85, r * 0.38)
      .fill({ color: colors.secondary, alpha: 0.55 });
    root.addChild(wings);
  }

  // --- Layer 1: Body base ---
  const body = new Graphics();
  if (n.health > 0.6) {
    body.circle(0, 0, r).fill(colors.primary);
  } else if (n.speed > 0.6) {
    body.ellipse(0, 0, r * 1.65, r * 0.7).fill(colors.primary);
  } else if (n.defense > 0.6) {
    body.roundRect(-r * 1.1, -r * 0.9, r * 2.2, r * 1.8, r * 0.28).fill(colors.primary);
  } else {
    // Angular hexagon
    const pts: number[] = [];
    for (let i = 0; i < 6; i++) {
      const a = (i * Math.PI) / 3 - Math.PI / 6;
      pts.push(Math.cos(a) * r, Math.sin(a) * r);
    }
    body.poly(pts).fill(colors.primary);
  }
  root.addChild(body);

  // --- Layer 5: Texture overlay ---
  const tex = new Graphics();
  if (n.defense > 0.6) {
    // Scale texture: grid of small circles
    for (let row = -2; row <= 2; row++) {
      for (let col = -3; col <= 3; col++) {
        const tx = col * 12 + (row % 2 === 0 ? 0 : 6);
        const ty = row * 10;
        if (tx * tx + ty * ty < r * r * 0.9) {
          tex.circle(tx, ty, 6).fill({ color: colors.secondary, alpha: 0.3 });
        }
      }
    }
  } else if (n.attack > 0.6) {
    // Facet shards
    for (let i = 0; i < 4; i++) {
      const a = (i / 4) * Math.PI * 2;
      const b = a + 0.7;
      tex
        .poly([0, 0, Math.cos(a) * r * 0.55, Math.sin(a) * r * 0.55, Math.cos(b) * r * 0.38, Math.sin(b) * r * 0.38])
        .fill({ color: 0xffffff, alpha: 0.1 });
    }
  }
  root.addChild(tex);

  // --- Layer 2: Limbs ---
  const limbCount = n.speed > 0.6 ? 2 : n.attack > 0.6 ? 6 : 4;
  const limbLen = 16 + n.attack * 18;
  const limbs = new Graphics();
  for (let i = 0; i < limbCount; i++) {
    const angle = (i / limbCount) * Math.PI * 2 + Math.PI * 0.1;
    const bx = Math.cos(angle) * r * 0.82;
    const by = Math.sin(angle) * r * 0.82;
    const ex = bx + Math.cos(angle) * limbLen;
    const ey = by + Math.sin(angle) * limbLen;
    if (n.attack > 0.6) {
      // Claw: tapered triangle
      const px = -Math.sin(angle) * 4;
      const py =  Math.cos(angle) * 4;
      limbs.poly([bx + px, by + py, bx - px, by - py, ex, ey]).fill(colors.secondary);
    } else {
      const w = n.defense > 0.6 ? 9 : 5;
      const px = -Math.sin(angle) * (w / 2);
      const py =  Math.cos(angle) * (w / 2);
      limbs
        .poly([bx + px, by + py, bx - px, by - py, ex - px, ey - py, ex + px, ey + py])
        .fill(colors.secondary);
    }
  }
  root.addChild(limbs);

  // --- Layer 3: Head ---
  const headY = -r * 0.62;
  const headR = r * 0.38;
  const head = new Graphics();
  switch (h % 4) {
    case 0: {
      // Skull: pentagon
      const pts: number[] = [];
      for (let i = 0; i < 5; i++) {
        const a = (i * Math.PI * 2) / 5 - Math.PI / 2;
        pts.push(Math.cos(a) * headR, headY + Math.sin(a) * headR);
      }
      head.poly(pts).fill(colors.primary);
      break;
    }
    case 1:
      head.circle(0, headY, headR).fill(colors.primary);
      break;
    case 2:
      head.ellipse(0, headY, headR * 1.5, headR * 0.8).fill(colors.primary);
      break;
    default:
      head.ellipse(0, headY, headR * 1.3, headR * 0.45).fill(colors.primary);
  }
  root.addChild(head);

  // --- Layer 4: Eyes ---
  const eyeCount = Math.max(1, Math.round(n.attack * 3));
  const eyes = new Graphics();
  for (let i = 0; i < eyeCount; i++) {
    const offset = (i - (eyeCount - 1) / 2) * headR * 0.6;
    eyes.circle(offset, headY - headR * 0.08, 5).fill(0xffffff);
    eyes.circle(offset, headY - headR * 0.08, 2.5).fill(colors.glow);
  }
  root.addChild(eyes);

  // --- Layer 6b: Horns & plating ---
  const acc = new Graphics();
  if (n.attack > 0.7) {
    const hb = headY - headR;
    acc.poly([-7, hb, 7, hb, 0, hb - r * 0.55]).fill(colors.secondary);
    acc.poly([-18, hb + 2, -5, hb + 2, -12, hb - r * 0.38]).fill(colors.secondary);
    acc.poly([5,  hb + 2, 18, hb + 2, 12,  hb - r * 0.38]).fill(colors.secondary);
  }
  if (n.defense > 0.7) {
    acc.rect(-r * 0.5, -r * 0.15, r, r * 0.32).fill({ color: colors.secondary, alpha: 0.7 });
    acc.rect(-r * 0.32, r * 0.14, r * 0.64, r * 0.28).fill({ color: colors.secondary, alpha: 0.5 });
  }
  root.addChild(acc);

  // Mirror right-facing sprites
  if (facing === 'right') root.scale.x = -1;

  return root;
}
