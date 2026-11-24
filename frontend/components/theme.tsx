"use client";

import { Moon, Sun } from "lucide-react";
import { ThemeProvider as NextThemesProvider, useTheme } from "next-themes";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { useIsClient } from "@/lib/hooks/use-clock";

/** Follows the OS theme until the viewer picks one; the choice is stored per browser. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <NextThemesProvider attribute="data-theme" defaultTheme="system" enableSystem disableTransitionOnChange>
      {children}
    </NextThemesProvider>
  );
}

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  // The resolved theme is only known in the browser; render a same-size placeholder until then.
  const isClient = useIsClient();
  const isDark = isClient && resolvedTheme === "dark";
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      {!isClient ? <span className="size-4" /> : isDark ? <Sun aria-hidden /> : <Moon aria-hidden />}
    </Button>
  );
}
