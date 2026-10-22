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
      <Dashboard />
      <SiteFooter />
    </>
  );
}
