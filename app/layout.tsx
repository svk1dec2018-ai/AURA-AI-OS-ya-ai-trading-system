import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AURA AI OS",
  description: "AURA AI OS owner command center for governed multi-market intelligence, research, learning and protected DEMO execution.",
  openGraph: {
    title: "AURA AI OS",
    description: "AURA AI OS owner command center for governed multi-market intelligence, research, learning and protected DEMO execution.",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
