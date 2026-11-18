import Link from "next/link";
import { LogoMark } from "@/components/logo";
import { ThemeToggle } from "@/components/theme";
import { buttonVariants } from "@/components/ui/button";
import { GITHUB_URL } from "@/lib/config";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#cli", label: "CLI" },
];

/** GitHub's mark (lucide no longer ships brand icons). */
function GitHubIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M12 .5a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.7-.3-5.5-1.3-5.5-6 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17.3 4.7 18.3 5 18.3 5c.7 1.7.3 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0 0 12 .5Z" />
    </svg>
  );
}

export function SiteHeader({ current }: { current?: "home" | "dashboard" }) {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-page/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight text-ink">
          <LogoMark />
          EcoShift
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-1 text-sm sm:flex">
          {NAV.map((item) => (
            <Link key={item.href} href={item.href} className="rounded-md px-2.5 py-1.5 text-ink-2 hover:bg-surface-2 hover:text-ink">
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <a href={GITHUB_URL} className={buttonVariants({ variant: "ghost", size: "icon" })} aria-label="EcoShift on GitHub">
            <GitHubIcon />
          </a>
          <ThemeToggle />
          <Link
            href="/dashboard"
            aria-current={current === "dashboard" ? "page" : undefined}
            className={cn(buttonVariants({ variant: current === "dashboard" ? "secondary" : "primary", size: "sm" }), "ml-1")}
          >
            Dashboard
          </Link>
        </div>
      </div>
    </header>
  );
}
