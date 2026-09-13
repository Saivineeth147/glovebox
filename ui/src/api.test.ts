import { describe, expect, it } from "vitest";
import { duration, fmtDate, fmtTime } from "./api";

describe("duration", () => {
  it("reads sub-second runs in milliseconds, where the difference is the story", () => {
    expect(duration("2026-09-13T10:00:00Z", "2026-09-13T10:00:00.033Z")).toBe("33 ms");
  });

  it("reads longer runs in seconds to one decimal", () => {
    expect(duration("2026-09-13T10:00:00Z", "2026-09-13T10:00:02.800Z")).toBe("2.8 s");
  });

  it("says nothing at all while a run is still going", () => {
    expect(duration("2026-09-13T10:00:00Z", null)).toBe("");
    expect(duration(null, null)).toBe("");
  });
});

describe("timestamps", () => {
  it("returns an empty string rather than 'Invalid Date' for a missing time", () => {
    expect(fmtTime(null)).toBe("");
    expect(fmtDate(undefined)).toBe("");
  });

  it("passes unparseable input through instead of throwing in a render", () => {
    expect(fmtTime("not-a-time")).toBe("not-a-time");
  });
});
