import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HoldToConfirmButton } from "./HoldToConfirmButton";

describe("HoldToConfirmButton", () => {
  it("does not confirm on a plain click without holding", () => {
    const onConfirm = vi.fn();
    render(<HoldToConfirmButton label="즉시 청산" onConfirm={onConfirm} durationMs={50} />);

    fireEvent.click(screen.getByRole("button", { name: "즉시 청산" }));

    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("confirms only after the hold duration completes", async () => {
    const onConfirm = vi.fn();
    render(<HoldToConfirmButton label="즉시 청산" onConfirm={onConfirm} durationMs={30} />);

    fireEvent.mouseDown(screen.getByRole("button", { name: "즉시 청산" }));
    expect(onConfirm).not.toHaveBeenCalled();

    await waitFor(() => expect(onConfirm).toHaveBeenCalledOnce());
  });

  it("cancels the hold when released early", async () => {
    const onConfirm = vi.fn();
    render(<HoldToConfirmButton label="즉시 청산" onConfirm={onConfirm} durationMs={200} />);

    const button = screen.getByRole("button", { name: "즉시 청산" });
    fireEvent.mouseDown(button);
    fireEvent.mouseUp(button);

    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("does not start holding when disabled", async () => {
    const onConfirm = vi.fn();
    render(<HoldToConfirmButton label="즉시 청산" onConfirm={onConfirm} durationMs={20} disabled />);

    fireEvent.mouseDown(screen.getByRole("button", { name: "즉시 청산" }));

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
