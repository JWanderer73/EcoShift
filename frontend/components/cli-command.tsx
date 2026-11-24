"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const COPIED_FEEDBACK_MS = 2000;

/** A shell command with a copy button. */
export function CliCommand({ command, className }: { command: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const [program, ...flags] = command.split(" --");

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), COPIED_FEEDBACK_MS);
    } catch {
      // Clipboard can be blocked (insecure origin, permissions); the command stays selectable.
    }
  }

  return (
    <div className={cn("flex items-center gap-2 rounded-lg border border-border bg-surface-2 py-1 pr-1 pl-3", className)}>
      <code className="min-w-0 flex-1 overflow-x-auto py-1.5 font-mono text-xs text-ink">
        <span className="text-muted select-none">$ </span>
        {/* Wrap between flags, never inside one ("--region CISO" stays together). */}
        {program}
        {flags.map((flag) => (
          <span key={flag}>
            {" "}
            <span className="whitespace-nowrap">--{flag}</span>
          </span>
        ))}
      </code>
      <Button variant="ghost" size="icon" onClick={copy} aria-label={copied ? "Copied" : "Copy command"}>
        {copied ? <Check className="text-good" aria-hidden /> : <Copy aria-hidden />}
      </Button>
      <span className="sr-only" aria-live="polite">
        {copied ? "Command copied" : ""}
      </span>
    </div>
  );
}
