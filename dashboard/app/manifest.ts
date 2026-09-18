import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "AURA 2 AI Trading Control Room",
    short_name: "AURA 2",
    description: "Local-first owner dashboard for AURA AI OS.",
    start_url: "/",
    display: "standalone",
    background_color: "#050912",
    theme_color: "#050912",
    icons: [{ src: "/aura.svg", sizes: "any", type: "image/svg+xml" }],
  };
}
