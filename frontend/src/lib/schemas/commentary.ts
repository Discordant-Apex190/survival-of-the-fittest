import { z } from 'zod';

export const CommentaryItemSchema = z.object({
  id: z.string(),
  text: z.string(),
  trigger: z.string(),
  sequence_index: z.number(),
  created_at: z.string(),
});

export type CommentaryItem = z.infer<typeof CommentaryItemSchema>;
