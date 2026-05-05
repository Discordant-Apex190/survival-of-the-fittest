import { z } from 'zod';

export const StatsSchema = z.object({
  health: z.number(),
  attack: z.number(),
  defense: z.number(),
  speed: z.number(),
});

export const AbilitySchema = z.object({
  id: z.string(),
  name: z.string(),
  type: z.string(),
  energy_cost: z.number(),
  cooldown: z.number(),
  effect: z.string(),
  description: z.string(),
});

export const TauntSchema = z.object({
  id: z.string(),
  trigger: z.string(),
  text: z.string(),
  audio_path: z.string().nullable(),
});

export const CreatureSummarySchema = z.object({
  id: z.string(),
  name: z.string(),
  tier: z.string(),
  element: z.string(),
  generation: z.number(),
  wins: z.number(),
  losses: z.number(),
  status: z.string(),
  stats: StatsSchema,
  fighting_style: z.string(),
});

export const CreatureDetailSchema = CreatureSummarySchema.extend({
  lore: z.string(),
  personality: z.string(),
  visual_descriptor: z.record(z.unknown()),
  behavior_weights: z.record(z.number()),
  abilities: z.array(AbilitySchema),
  taunts: z.array(TauntSchema),
});

export type Stats           = z.infer<typeof StatsSchema>;
export type Ability         = z.infer<typeof AbilitySchema>;
export type Taunt           = z.infer<typeof TauntSchema>;
export type CreatureSummary = z.infer<typeof CreatureSummarySchema>;
export type CreatureDetail  = z.infer<typeof CreatureDetailSchema>;
