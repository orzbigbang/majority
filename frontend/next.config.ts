import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

export default (phase: string): NextConfig => ({
  // `next dev` and `next build` must not write to the same directory. A build
  // replaces manifests and chunks while the dev server is still reading them,
  // which causes intermittent MODULE_NOT_FOUND / routes-manifest ENOENT errors.
  // Production builds keep the standard `.next` directory expected by Vercel.
  distDir: phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : ".next",
});
