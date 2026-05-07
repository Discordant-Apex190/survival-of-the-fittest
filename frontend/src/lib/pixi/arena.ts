import { Application, Container, Graphics, Text } from 'pixi.js';
import { applyBattleScars, buildSprite, type CreatureData } from './sprite';
import { elementColor } from '../theme';

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

const W = 800;
const H = 450;
const GROUND_Y = H * 0.72;
const POS_A = { x: W * 0.25, y: GROUND_Y };
const POS_B = { x: W * 0.75, y: GROUND_Y };
const HP_W = 160;
const HP_H = 10;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SlotData {
  sprite:     Container;
  maxHp:      number;
  hpBar:      Graphics;
  hpLabel:    Text;
  nameLabel:  Text;
  homeX:      number;
  homeY:      number;
  element:    string;
  creatureId: string;
}

export interface ArenaInstance {
  app:          Application;
  stage:        Container;
  setCreatures(a: CreatureData, b: CreatureData): void;
  updateHp(id: string, currentHp: number): void;
  getSlot(id: string): SlotData | undefined;
  destroy(): void;
}

// ---------------------------------------------------------------------------
// HP bar
// ---------------------------------------------------------------------------

function hpColor(pct: number): number {
  if (pct > 0.5) return 0x22c55e;
  if (pct > 0.25) return 0xf5c518;
  return 0xef4444;
}

function drawHpBar(g: Graphics, pct: number): void {
  const clamped = Math.max(0, Math.min(1, pct));
  g.clear();
  g.rect(0, 0, HP_W, HP_H).fill(0x111122);
  if (clamped > 0) {
    g.rect(0, 0, HP_W * clamped, HP_H).fill(hpColor(clamped));
  }
  g.rect(0, 0, HP_W, HP_H).stroke({ width: 1, color: 0x333355 });
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export async function createArena(mountEl: HTMLElement): Promise<ArenaInstance> {
  const app = new Application();
  await app.init({
    width: W,
    height: H,
    background: 0x0d0e12,
    antialias: true,
    autoDensity: true,
  });

  mountEl.appendChild(app.canvas as HTMLCanvasElement);

  // Background layers
  const bgLayer = new Graphics();
  bgLayer.rect(0, 0, W, H).fill(0x0d0e12);
  // Subtle ground line
  bgLayer.rect(40, GROUND_Y + 2, W - 80, 1).fill({ color: 0x252836, alpha: 0.8 });
  app.stage.addChild(bgLayer);

  const spritesLayer = new Container();
  app.stage.addChild(spritesLayer);

  const uiLayer = new Container();
  app.stage.addChild(uiLayer);

  // --- Internal creature map ---
  const slots = new Map<string, SlotData>();

  function setCreatures(a: CreatureData, b: CreatureData): void {
    // Clear previous
    spritesLayer.removeChildren();
    uiLayer.removeChildren();
    slots.clear();

    for (const [creature, pos, facing] of [
      [a, POS_A, 'left'] as const,
      [b, POS_B, 'right'] as const,
    ]) {
      const sprite = buildSprite(creature, facing);
      sprite.x = pos.x;
      sprite.y = pos.y;
      spritesLayer.addChild(sprite);

      // HP bar
      const hpBar = new Graphics();
      const barX = facing === 'left' ? pos.x - HP_W / 2 : pos.x - HP_W / 2;
      const barY = 18;
      hpBar.x = barX;
      hpBar.y = barY;
      drawHpBar(hpBar, 1);
      uiLayer.addChild(hpBar);

      // HP text
      const hpLabel = new Text({
        text: `${creature.stats.health}`,
        style: { fill: '#8a8fa8', fontSize: 9, fontFamily: 'DM Mono, monospace' },
      });
      hpLabel.x = barX + HP_W + 4;
      hpLabel.y = barY;
      uiLayer.addChild(hpLabel);

      // Name label
      const col = elementColor(creature.element);
      const nameLabel = new Text({
        text: creature.name,
        style: { fill: col, fontSize: 11, fontFamily: 'DM Mono, monospace', fontWeight: '500' },
      });
      nameLabel.x = barX;
      nameLabel.y = 4;
      uiLayer.addChild(nameLabel);

      slots.set(creature.id, {
        sprite,
        maxHp: creature.stats.health,
        hpBar,
        hpLabel,
        nameLabel,
        homeX: pos.x,
        homeY: pos.y,
        element:    creature.element,
        creatureId: creature.id,
      });
    }
  }

  function updateHp(id: string, currentHp: number): void {
    const slot = slots.get(id);
    if (!slot) return;
    const pct = Math.max(0, currentHp) / slot.maxHp;
    drawHpBar(slot.hpBar, pct);
    slot.hpLabel.text = String(Math.max(0, Math.round(currentHp)));
    applyBattleScars(slot.sprite, pct, slot.creatureId);
  }

  function getSlot(id: string): SlotData | undefined {
    return slots.get(id);
  }

  function destroy(): void {
    app.destroy(true, { children: true });
  }

  return { app, stage: app.stage, setCreatures, updateHp, getSlot, destroy };
}
