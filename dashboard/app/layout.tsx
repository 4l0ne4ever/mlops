import type { Metadata } from "next";
import { IBM_Plex_Mono, Space_Grotesk } from "next/font/google";

import { AppNav } from "@/components/app-nav";

import "@/app/globals.css";

const headingFont = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-heading",
});

const monoFont = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "AgentOps Dashboard",
  description:
    "Production dashboard for prompt versions, eval runs, and deployment decisions.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${headingFont.variable} ${monoFont.variable}`}>
      <body style={{ fontFamily: "var(--font-heading), sans-serif" }}>
        <main className="shell">
          <AppNav />
          {children}
        </main>
      </body>
    </html>
  );
}
