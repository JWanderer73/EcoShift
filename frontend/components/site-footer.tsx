import { GITHUB_URL } from "@/lib/config";

const SOURCES = [
  { label: "CAISO OASIS", href: "https://oasis.caiso.com/" },
  { label: "Open-Meteo", href: "https://open-meteo.com/" },
];

export function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-8 text-sm text-muted sm:flex-row sm:items-center sm:justify-between">
        <p>
          EcoShift · a UC San Diego DS3 project ·{" "}
          <a href={GITHUB_URL} className="underline underline-offset-4 hover:text-ink">
            GitHub
          </a>
        </p>
        <p>
          Data:{" "}
          {SOURCES.map((s, i) => (
            <span key={s.href}>
              {i > 0 && ", "}
              <a href={s.href} className="underline underline-offset-4 hover:text-ink">
                {s.label}
              </a>
            </span>
          ))}
        </p>
      </div>
    </footer>
  );
}
