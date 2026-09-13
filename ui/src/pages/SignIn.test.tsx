import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const signIn = vi.fn();
const register = vi.fn();

vi.mock("../api", () => ({
  api: {
    signIn: (...args: unknown[]) => signIn(...args),
    register: (...args: unknown[]) => register(...args),
  },
}));

import SignIn from "./SignIn";

describe("SignIn", () => {
  beforeEach(() => {
    signIn.mockReset();
    register.mockReset();
  });

  it("signs in with what was typed and hands the account back to the shell", async () => {
    signIn.mockResolvedValue({ email: "a@b.com", role: "admin" });
    const onSignedIn = vi.fn();
    render(<SignIn onSignedIn={onSignedIn} />);

    await userEvent.type(screen.getByLabelText(/email/i), "a@b.com");
    await userEvent.type(screen.getByLabelText(/password/i), "a-long-enough-password");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith({ email: "a@b.com", role: "admin" }));
    expect(signIn).toHaveBeenCalledWith("a@b.com", "a-long-enough-password");
  });

  it("shows what the server said rather than a generic failure", async () => {
    signIn.mockRejectedValue(new Error("too many sign-in attempts; try again in 300 seconds"));
    render(<SignIn onSignedIn={vi.fn()} />);

    await userEvent.type(screen.getByLabelText(/email/i), "a@b.com");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong-password-here");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText(/too many sign-in attempts/i)).toBeTruthy();
  });

  it("explains what registering actually gets you before you do it", async () => {
    render(<SignIn onSignedIn={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /create the first account/i }));

    expect(screen.getByText(/first account created becomes the administrator/i)).toBeTruthy();
    expect(screen.getByText(/at least 12 characters/i)).toBeTruthy();
  });

  it("registers instead of signing in once switched", async () => {
    register.mockResolvedValue({ email: "a@b.com", role: "admin" });
    render(<SignIn onSignedIn={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /create the first account/i }));
    await userEvent.type(screen.getByLabelText(/email/i), "a@b.com");
    await userEvent.type(screen.getByLabelText(/password/i), "a-long-enough-password");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() => expect(register).toHaveBeenCalled());
    expect(signIn).not.toHaveBeenCalled();
  });

  it("clears a previous error when switching mode, so it cannot linger misleadingly", async () => {
    signIn.mockRejectedValue(new Error("invalid email or password"));
    render(<SignIn onSignedIn={vi.fn()} />);

    await userEvent.type(screen.getByLabelText(/email/i), "a@b.com");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong-password-here");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await screen.findByText(/invalid email or password/i);

    await userEvent.click(screen.getByRole("button", { name: /create the first account/i }));

    expect(screen.queryByText(/invalid email or password/i)).toBeNull();
  });
});
