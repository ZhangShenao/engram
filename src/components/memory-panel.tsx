"use client";

import { useCallback, useEffect, useState } from "react";
import type { MemoryRecord, MemoryType } from "@/lib/memory/types";
import { MEMORY_TYPES } from "@/lib/memory/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";

export function MemoryPanel({ characterId }: { characterId: string }) {
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await fetch(`/api/memories/${characterId}`);
    const data = await res.json();
    setMemories(
      (data.memories as MemoryRecord[]).filter(
        (m) => !m.deletedAt && !m.supersededById
      )
    );
    setLoading(false);
  }, [characterId]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (m: MemoryRecord) => {
    await fetch(`/api/memories/${characterId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: m.id,
        text: m.text,
        type: m.type,
        salience: m.salience,
      }),
    });
    await load();
  };

  const remove = async (id: string) => {
    await fetch(`/api/memories/${characterId}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    await load();
  };

  if (loading) return <p className="text-sm text-muted-foreground">Loading memories…</p>;

  return (
    <ScrollArea className="h-[min(60vh,520px)]">
      <div className="space-y-3 pr-2">
        {memories.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No memories yet. Try saying &quot;My name is …&quot; in chat.
          </p>
        )}
        {memories.map((m) => (
          <div key={m.id} className="rounded-lg border p-3 space-y-2">
            <div className="flex items-center gap-2">
              <select
                className="text-xs border rounded px-2 py-1 bg-background"
                value={m.type}
                onChange={(e) =>
                  setMemories((prev) =>
                    prev.map((x) =>
                      x.id === m.id
                        ? { ...x, type: e.target.value as MemoryType }
                        : x
                    )
                  )
                }
              >
                {MEMORY_TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <Badge variant="outline">salience {m.salience.toFixed(2)}</Badge>
            </div>
            <Input
              value={m.text}
              onChange={(e) =>
                setMemories((prev) =>
                  prev.map((x) =>
                    x.id === m.id ? { ...x, text: e.target.value } : x
                  )
                )
              }
            />
            <Input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={m.salience}
              onChange={(e) =>
                setMemories((prev) =>
                  prev.map((x) =>
                    x.id === m.id
                      ? { ...x, salience: parseFloat(e.target.value) }
                      : x
                  )
                )
              }
            />
            <div className="flex gap-2">
              <Button size="sm" onClick={() => save(m)}>Save</Button>
              <Button size="sm" variant="destructive" onClick={() => remove(m.id)}>
                Delete
              </Button>
            </div>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}
