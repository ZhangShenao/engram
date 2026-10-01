export interface ExampleDialogue {
  user: string;
  assistant: string;
}

export interface CharacterCard {
  id: string;
  name: string;
  tagline: string;
  description: string;
  personality: string;
  scenario: string;
  exampleDialogues: ExampleDialogue[];
  greeting: string;
  speechStyle: string;
  boundaries: string;
  createdAt: string;
  updatedAt: string;
}

export type CharacterInput = Omit<CharacterCard, "id" | "createdAt" | "updatedAt">;
