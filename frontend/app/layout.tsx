import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "@/components/theme";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "EcoShift: run heavy jobs when the grid is cleanest",
    template: "%s · EcoShift",
  },
  description:
    "CAISO day-ahead electricity price forecasts and the cheapest time windows for training runs, batch jobs, and builds at California datacenters.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // next-themes sets data-theme before React hydrates, which React would otherwise flag.
    <html lang="en" suppressHydrationWarning className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
