import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AURA Prime — AI Trading OS",
  description: "Local-first multi-market AI trading control room with governed execution.",
  applicationName: "AURA Prime",
};

export const viewport: Viewport = {
  themeColor: "#03070d",
  colorScheme: "dark",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
