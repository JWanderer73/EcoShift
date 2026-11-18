import type { Metadata } from "next";
import { Dashboard } from "@/components/dashboard/dashboard";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

export const metadata: Metadata = {
  title: "Dashboard",
  description: "Forecast grid carbon intensity for the next 48 hours and find the cleanest time to run your job.",
};

export default function DashboardPage() {
  return (
    <>
      <SiteHeader current="dashboard" />
      <div className="relative flex flex-1 flex-col">
        {/* Graph paper behind the title, fading out before the cards; the cards stay solid. */}
        <div className="bg-graph-paper mask-fade-down pointer-events-none absolute inset-x-0 top-0 h-96" aria-hidden />
        <div className="relative flex flex-1 flex-col">
          <Dashboard />
        </div>
      </div>
      <SiteFooter />
    </>
  );
}
