import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HR Portal - AURA Pilot Sandbox",
  description: "Autonomous Unified Response Agent HR Onboarding Sandbox",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
