import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Chip, KV, STATUS } from "./ui";

describe("Chip", () => {
  it("reads a status as a sentence, not as tracked-out capitals", () => {
    render(<Chip value="business_outcome" />);
    expect(screen.getByText("Business outcome")).toBeTruthy();
  });

  it("renders nothing for an absent status rather than an empty pill", () => {
    const { container } = render(<Chip value={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("gives an unknown status a neutral treatment instead of crashing", () => {
    render(<Chip value="something_new" />);
    expect(screen.getByText("Something new")).toBeTruthy();
  });
});

describe("status colours", () => {
  it("keeps every failing state in the same red, so a scan reads one way", () => {
    const failing = ["failed", "error", "blocked", "max_steps", "timeout"];
    expect(new Set(failing.map((s) => STATUS[s])).size).toBe(1);
  });

  it("keeps every state that wants a person in the same amber", () => {
    const human = ["human", "escalated", "stuck", "draft"];
    expect(new Set(human.map((s) => STATUS[s])).size).toBe(1);
  });
});

describe("KV", () => {
  it("pairs each label with its value", () => {
    render(<KV rows={[["model", "sonnet-5"], ["tenant", "alpha"]]} />);
    expect(screen.getByText("model")).toBeTruthy();
    expect(screen.getByText("sonnet-5")).toBeTruthy();
  });
});
