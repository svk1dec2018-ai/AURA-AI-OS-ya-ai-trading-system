import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AURA 2 — AI Trading Control Room",
  description: "Local owner dashboard for AURA AI OS and protected MT5 DEMO execution.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
