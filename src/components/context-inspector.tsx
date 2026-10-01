"use client";

import type { AssembledContext } from "@/lib/context/assembler";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";

export function ContextInspector({
  inspector,
}: {
  inspector: AssembledContext | null;
}) {
  if (!inspector) {
    return (
      <p className="text-sm text-muted-foreground">
        Send a message to see the exact context layers for that turn.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 text-sm">
        <Badge variant="secondary">
          {inspector.totalTokens} / {inspector.budget} tokens (est.)
        </Badge>
        {inspector.trimLog.length > 0 && (
          <Badge variant="outline">Trimmed this turn</Badge>
        )}
      </div>
      {inspector.trimLog.length > 0 && (
        <ul className="text-xs text-amber-700 dark:text-amber-400 list-disc pl-4 space-y-1">
          {inspector.trimLog.map((t, i) => (
            <li key={i}>{t}</li>
          ))}
        </ul>
      )}
      <ScrollArea className="h-[min(60vh,520px)] pr-3">
        <div className="space-y-3">
          {inspector.layers.map((layer) => (
            <Card key={layer.id} className="shadow-none">
              <CardHeader className="py-3">
                <CardTitle className="text-sm flex items-center justify-between gap-2">
                  <span>{layer.label}</span>
                  <span className="text-muted-foreground font-normal">
                    ~{layer.tokenEstimate} tok
                    {layer.trimmed ? " · trimmed" : ""}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                {layer.trimReason && (
                  <p className="text-xs text-muted-foreground mb-2">
                    {layer.trimReason}
                  </p>
                )}
                <pre className="text-xs whitespace-pre-wrap font-mono bg-muted/50 rounded-md p-2">
                  {layer.content}
                </pre>
              </CardContent>
            </Card>
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
