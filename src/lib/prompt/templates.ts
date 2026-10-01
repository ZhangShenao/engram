export const PROMPT_VERSION = "1.0.0";

export const PROMPT_SECTION_ORDER = [
  "persona_identity",
  "boundaries",
  "style_anchors",
  "output_shape",
  "memories",
  "rolling_summary",
  "reanchor",
  "recent_turns",
  "generation_hint",
] as const;

export type PromptSectionId = (typeof PROMPT_SECTION_ORDER)[number];

export const TEMPLATE_META = {
  version: PROMPT_VERSION,
  description: "Phase 1 roleplay system prompt assembly",
};
