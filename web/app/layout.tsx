import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "substrate — protocol-based report generator",
  description:
    "Deterministic evidence engine, retrieval-cited method sections, and an AI summary that is only ever a draft.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        {/* self-hosted-quality mono; falls back to system mono instantly */}
        <link
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
