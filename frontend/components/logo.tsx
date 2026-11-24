import { cn } from "@/lib/utils";

/** EcoShift mark: an intensity curve dipping to its cleanest point. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("size-7", className)} aria-hidden>
      <rect width="24" height="24" rx="7" fill="var(--primary)" />
      <path
        d="M4 8.5c3.2 0 4.4 8 8 8s4.8-8 8-8"
        fill="none"
        stroke="var(--primary-ink)"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <circle cx="12" cy="16.5" r="2.1" fill="var(--primary-ink)" />
    </svg>
  );
}
