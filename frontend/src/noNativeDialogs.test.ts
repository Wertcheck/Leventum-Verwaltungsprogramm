import { describe, expect, it } from "vitest";

const sources = import.meta.glob(["./**/*.ts", "./**/*.tsx", "!./**/*.test.ts", "!./**/*.test.tsx", "!./components/Dialogs.tsx"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;

describe("Browser-Dialoge", () => {
  it("der Anwendungscode nutzt weder window.prompt/confirm/alert noch alert()/prompt()", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(10);
    const hits = Object.entries(sources).filter(([, src]) => /\b(window\.(prompt|confirm|alert)|(?<![.\w])(alert|prompt))\s*\(/.test(src.replace(/\/\/.*$/gm, ""))).map(([f]) => f);
    expect(hits).toEqual([]);
  });
});
