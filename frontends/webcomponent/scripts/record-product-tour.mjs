import { execFile } from "node:child_process";
import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { chromium } from "@playwright/test";

const run = promisify(execFile);
const storyBase = process.env.VANNA_TOUR_URL || "http://127.0.0.1:8123";
const tourUrl = `${storyBase}/iframe.html?id=product-vanna-3-workbench--product-tour&viewMode=story`;
const overviewUrl = `${storyBase}/iframe.html?id=product-vanna-3-workbench--product-overview&viewMode=story`;
const mediaDir = path.resolve(process.env.VANNA_MEDIA_DIR || "../../media");
const webmPath = path.join(mediaDir, "vanna-3.3-product-tour.webm");
const mp4Path = path.join(mediaDir, "vanna-3.3-product-tour.mp4");
const posterPath = path.join(mediaDir, "vanna-3.3-workbench.png");

await mkdir(mediaDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const videoContext = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  screen: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  colorScheme: "light",
  locale: "en-US",
  recordVideo: {
    dir: mediaDir,
    size: { width: 1920, height: 1080 },
  },
});

const videoPage = await videoContext.newPage();
await videoPage.goto(tourUrl, { waitUntil: "networkidle" });
await videoPage.locator("#vanna-product-tour").waitFor({ state: "visible" });
await videoPage.waitForTimeout(13_000);

const video = videoPage.video();
await videoPage.close();
if (!video) throw new Error("Playwright did not create a video artifact");
const generatedVideoPath = await video.path();
await video.saveAs(webmPath);
await videoContext.close();
if (path.resolve(generatedVideoPath) !== path.resolve(webmPath)) {
  await rm(generatedVideoPath, { force: true });
}

const posterContext = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  colorScheme: "light",
  locale: "en-US",
});
const posterPage = await posterContext.newPage();
await posterPage.goto(overviewUrl, { waitUntil: "networkidle" });
await posterPage.locator("#vanna-product-tour").waitFor({ state: "visible" });
await posterPage.waitForTimeout(1_200);
await posterPage.screenshot({ path: posterPath, fullPage: true });
await posterContext.close();
await browser.close();

let mp4Created = false;
try {
  await run("ffmpeg", [
    "-y",
    "-i",
    webmPath,
    "-ss",
    "0.8",
    "-an",
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "20",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
    mp4Path,
  ]);
  mp4Created = true;
} catch {
  // WebM remains the portable output when ffmpeg is unavailable.
}

process.stdout.write(
  `${JSON.stringify({ webm: webmPath, mp4: mp4Created ? mp4Path : null, poster: posterPath })}\n`,
);
