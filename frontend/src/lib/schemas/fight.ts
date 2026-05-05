import { z } from 'zod';

export const FightSummarySchema = z.object({
  id: z.string(),
  creature_a_id: z.string(),
  creature_b_id: z.string(),
  winner_id: z.string().nullable(),
  tier: z.string(),
  duration_turns: z.number(),
  created_at: z.string(),
});

export const FightDetailSchema = FightSummarySchema.extend({
  creature_a_name: z.string(),
  creature_a_element: z.string(),
  creature_b_name: z.string(),
  creature_b_element: z.string(),
  fight_log: z.record(z.unknown()),
});

export const FightEventSchema = z.object({
  id: z.string(),
  fight_id: z.string(),
  turn: z.number(),
  event_type: z.string(),
  actor_id: z.string().nullable(),
  target_id: z.string().nullable(),
  ability_name: z.string().nullable(),
  damage: z.number().nullable(),
  hp_remaining: z.record(z.number()),
});

export const UpcomingFightSchema = z.union([
  z.object({
    creature_a: z.record(z.unknown()),
    creature_b: z.record(z.unknown()),
    prob_a: z.number(),
    prob_b: z.number(),
  }),
  z.object({ message: z.string() }),
]);

export type FightSummary  = z.infer<typeof FightSummarySchema>;
export type FightDetail   = z.infer<typeof FightDetailSchema>;
export type FightEvent    = z.infer<typeof FightEventSchema>;
export type UpcomingFight = z.infer<typeof UpcomingFightSchema>;
