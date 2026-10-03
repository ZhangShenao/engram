"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { deleteMemory, listMemories, saveMemory } from "@/lib/api";
import { MEMORY_TYPES, type Inspector, type Memory, type MemoryType, type TurnTimings } from "@/lib/types";

export function MemorySheet({
  characterId,
  open,
  onOpenChange,
}: {
  characterId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    listMemories(characterId)
      .then((rows) => {
        if (!cancelled) {
          setMemories(rows.filter((row) => !row.deletedAt && !row.supersededById));
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load memories");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, characterId]);

  const updateLocal = (id: string, patch: Partial<Memory>) => {
    setMemories((current) => current.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md!">
        <SheetHeader>
          <SheetTitle>Memories</SheetTitle>
          <SheetDescription>
            Facts Engram kept from this scene. Deleted memories stay gone.
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-6">
          {loading && <p className="text-sm text-muted-foreground">Loading memories…</p>}
          {error && <p className="text-sm text-destructive">{error}</p>}
          {!loading && !error && memories.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No memories yet. Try saying “My name is …” in the scene.
            </p>
          )}
          <div className="space-y-3">
            {memories.map((memory) => (
              <div key={memory.id} className="space-y-2 rounded-xl border border-border p-3">
                <div className="flex items-center gap-2">
                  <select
                    id={`memory-type-${memory.id}`}
                    name={`memory-type-${memory.id}`}
                    className="h-8 rounded-lg border border-input bg-transparent px-2 text-xs"
                    value={memory.type}
                    onChange={(event) =>
                      updateLocal(memory.id, { type: event.target.value as MemoryType })
                    }
                  >
                    {MEMORY_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                  <Badge variant="outline">salience {memory.salience.toFixed(2)}</Badge>
                  {memory.slot && <Badge variant="secondary">{memory.slot}</Badge>}
                </div>
                <Input
                  id={`memory-text-${memory.id}`}
                  name={`memory-text-${memory.id}`}
                  value={memory.text}
                  onChange={(event) => updateLocal(memory.id, { text: event.target.value })}
                />
                <Input
                  id={`memory-salience-${memory.id}`}
                  name={`memory-salience-${memory.id}`}
                  type="number"
                  min={0}
                  max={1}
                  step={0.05}
                  value={memory.salience}
                  onChange={(event) =>
                    updateLocal(memory.id, { salience: Number(event.target.value) })
                  }
                />
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    disabled={pendingId === memory.id}
                    onClick={async () => {
                      setPendingId(memory.id);
                      setError(null);
                      try {
                        await saveMemory(memory);
                      } catch (err) {
                        setError(err instanceof Error ? err.message : "Could not save");
                      } finally {
                        setPendingId(null);
                      }
                    }}
                  >
                    Save
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={pendingId === memory.id}
                    onClick={async () => {
                      setPendingId(memory.id);
                      setError(null);
                      try {
                        await deleteMemory(memory.id);
                        setMemories((current) => current.filter((row) => row.id !== memory.id));
                      } catch (err) {
                        setError(err instanceof Error ? err.message : "Could not delete");
                      } finally {
                        setPendingId(null);
                      }
                    }}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function formatMs(value: number | null) {
  if (value == null) return "—";
  return `${value} ms`;
}

const STAGE_LABELS: Record<string, string> = {
  character: "Character card",
  session: "Session",
  rank: "Memory rank",
  prefetch: "Prefetch, wall",
  writeUser: "Write user message",
  readHistory: "Read history",
  summary: "Read summary",
  contextLoad: "Context load, wall",
  assemble: "Assemble prompt",
  saveInspection: "Save inspector",
  modelFirstToken: "Model, first token",
  modelTotal: "Model, full reply",
  saveAssistant: "Save assistant",
  replaceAssistant: "Replace assistant",
  discardMemories: "Discard old memories",
  summaryAppend: "Append summary",
  extract: "Memory extract",
};

function TurnTimingsList({ timings }: { timings: TurnTimings }) {
  const rows =
    timings.stages && timings.stages.length > 0
      ? timings.stages.map((stage) => [STAGE_LABELS[stage.name] ?? stage.name, formatMs(stage.ms)] as const)
      : ([
          ["Before the model", formatMs(timings.orchestrationMs)],
          ["Model, first token", formatMs(timings.modelFirstTokenMs)],
          ["Model, full reply", formatMs(timings.modelTotalMs)],
          ["Memory extract", formatMs(timings.extractMs)],
        ] as const);
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-1 rounded-xl border border-border px-3 py-2 text-xs">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="text-right font-mono text-foreground/90">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function InspectorSheet({
  open,
  onOpenChange,
  inspector,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  inspector: Inspector | null;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-xl!">
        <SheetHeader>
          <SheetTitle>Context</SheetTitle>
          <SheetDescription>
            The layers from the latest turn, with token estimates and anything that was trimmed.
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-6">
          {!inspector && (
            <p className="text-sm text-muted-foreground">
              Send a message to see the layers Engram actually sent.
            </p>
          )}
          {inspector && (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">
                  {inspector.totalTokens} / {inspector.budget} tokens (est.)
                </Badge>
                {inspector.trimLog.length > 0 && <Badge variant="outline">Trimmed this turn</Badge>}
              </div>
              {inspector.timings && <TurnTimingsList timings={inspector.timings} />}
              {inspector.trimLog.length > 0 && (
                <ul className="list-disc space-y-1 pl-4 text-xs text-amber-200/90">
                  {inspector.trimLog.map((entry, index) => (
                    <li key={`${entry}-${index}`}>{entry}</li>
                  ))}
                </ul>
              )}
              {inspector.layers.map((layer) => (
                <section key={layer.id} className="rounded-xl border border-border p-3">
                  <div className="mb-2 flex items-center justify-between gap-2 text-sm">
                    <h3 className="font-medium">{layer.label}</h3>
                    <span className="text-xs text-muted-foreground">
                      ~{layer.tokenEstimate} tok{layer.trimmed ? " · trimmed" : ""}
                    </span>
                  </div>
                  {layer.trimReason && (
                    <p className="mb-2 text-xs text-muted-foreground">{layer.trimReason}</p>
                  )}
                  <pre className="whitespace-pre-wrap font-mono text-xs text-foreground/90">
                    {layer.content}
                  </pre>
                </section>
              ))}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
