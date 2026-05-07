import { z } from 'zod';
import { CreatureSummarySchema } from './creature';

const FightPreviewSchema = z.object({
  type: z.literal('fight_preview'),
  fight_id: z.string(),
  creature_a: z.record(z.unknown()),
  creature_b: z.record(z.unknown()),
  prob_a: z.number(),
  prob_b: z.number(),
});

const FightStartSchema = z.object({
  type: z.literal('fight_start'),
  fight_id: z.string(),
  creature_a: z.record(z.unknown()),
  creature_b: z.record(z.unknown()),
  prob_a: z.number(),
  prob_b: z.number(),
});

const FightEventSchema = z.object({
  type: z.literal('fight_event'),
  fight_id: z.string(),
  turn: z.number(),
  event_type: z.string(),
  actor_id: z.string().nullable(),
  target_id: z.string().nullable(),
  ability_name: z.string().nullable(),
  damage: z.number().nullable(),
  hp_remaining: z.record(z.number()),
});

const FightEndSchema = z.object({
  type: z.literal('fight_end'),
  fight_id: z.string(),
  winner_id: z.string(),
});

const LeaderboardUpdateSchema = z.object({
  type: z.literal('leaderboard_update'),
  data: z.array(CreatureSummarySchema),
});

const CommentarySchema = z.object({
  type: z.literal('commentary'),
  lines: z.array(z.string()),
  trigger: z.string(),
  threads: z.array(z.unknown()),
});

// All WS payloads pass through this before touching any store.
export const WsEventSchema = z.discriminatedUnion('type', [
  FightPreviewSchema,
  FightStartSchema,
  FightEventSchema,
  FightEndSchema,
  LeaderboardUpdateSchema,
  CommentarySchema,
]);

export type WsEvent        = z.infer<typeof WsEventSchema>;
export type WsFightPreview = z.infer<typeof FightPreviewSchema>;
export type WsFightStart   = z.infer<typeof FightStartSchema>;
export type WsFightEvent   = z.infer<typeof FightEventSchema>;
export type WsFightEnd     = z.infer<typeof FightEndSchema>;
export type WsLeaderboard  = z.infer<typeof LeaderboardUpdateSchema>;
export type WsCommentary   = z.infer<typeof CommentarySchema>;
