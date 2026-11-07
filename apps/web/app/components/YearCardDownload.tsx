"use client";

// Downloads for the share card. The SVG comes straight from the server route;
// the PNG is that same SVG drawn onto a canvas at its own size (1080 x 1350)
// in the browser, so nothing leaves this machine and no image library is
// needed on the server.

import { useState } from "react";

const WIDTH = 1080;
const HEIGHT = 1350;

async function svgToPng(url: string): Promise<Blob> {
  const image = new Image();
  image.decoding = "async";
  image.src = url;
  await image.decode();
  const canvas = document.createElement("canvas");
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("canvas unavailable");
  context.drawImage(image, 0, 0, WIDTH, HEIGHT);
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("PNG encode failed"))), "image/png"),
  );
}

export function YearCardDownload({ year, query }: { year: number; query: string }) {
  const [state, setState] = useState<"idle" | "working" | "failed">("idle");
  const svgUrl = `/year/${year}/card${query}`;
  const downloadSvg = `${svgUrl}${query ? "&" : "?"}download=1`;

  async function downloadPng() {
    setState("working");
    try {
      const blob = await svgToPng(svgUrl);
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = `year-in-health-${year}.png`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
      setState("idle");
    } catch {
      setState("failed");
    }
  }

  return (
    <div className="yr-share-actions">
      <button type="button" className="btn" onClick={downloadPng} disabled={state === "working"}>
        {state === "working" ? "Preparing PNG…" : "Download PNG"}
      </button>
      <a className="btn btn-ghost" href={downloadSvg}>
        Download SVG
      </a>
      {state === "failed" && (
        <p className="yr-share-error" role="status">
          This browser could not draw the PNG. Download the SVG instead.
        </p>
      )}
    </div>
  );
}
