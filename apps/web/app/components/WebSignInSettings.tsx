"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { setWebPasswordAction, turnOffWebSignInAction } from "../lib/webAuthActions";

type Props = {
  mode: "password" | "off";
  source: "settings" | "env" | "none";
  minLength: number;
};

// Settings -> Web sign-in: set or change the dashboard password, or turn sign-in
// off. The server does every check; this only collects the fields.
export function WebSignInSettingsForm({ mode, source, minLength }: Props) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [pending, startTransition] = useTransition();
  const router = useRouter();
  const hasPassword = mode === "password";

  const run = (action: () => Promise<{ ok: boolean; error?: string }>, success: string) =>
    startTransition(async () => {
      const result = await action();
      setStatus(result.ok ? { ok: true, text: success } : { ok: false, text: result.error ?? "Could not save." });
      if (result.ok) {
        setCurrent("");
        setNext("");
        setConfirm("");
        router.refresh();
      }
    });

  return (
    <article className="card">
      <h2>Web sign-in</h2>
      {hasPassword ? (
        <p className="set-hint">
          This dashboard asks for a password.{" "}
          {source === "env"
            ? "It is WEB_PASSWORD from the .env file. Saving a new one here replaces it."
            : "It was set here in Settings."}
        </p>
      ) : (
        <p className="set-hint">
          Sign-in is off: anyone who can open this page sees your health data. That is fine when the
          dashboard only listens on this machine (WEB_BIND=127.0.0.1). Set a password before you open it
          to your network.
        </p>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          run(
            () => setWebPasswordAction({ current, next, confirm }),
            hasPassword ? "Password changed. Other browsers are signed out." : "Sign-in is on.",
          );
        }}
      >
        {hasPassword && (
          <label className="field">
            <span className="field-label">Current password</span>
            <input
              className="field-input"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
              required
            />
          </label>
        )}
        <label className="field">
          <span className="field-label">{hasPassword ? "New password" : "Password"}</span>
          <input
            className="field-input"
            type="password"
            autoComplete="new-password"
            minLength={minLength}
            value={next}
            onChange={(event) => setNext(event.target.value)}
            required
          />
          <span className="field-hint">At least {minLength} characters.</span>
        </label>
        <label className="field">
          <span className="field-label">Repeat password</span>
          <input
            className="field-input"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            required
          />
        </label>
        <div className="exp-action">
          <button className="btn" type="submit" disabled={pending}>
            {pending ? "Saving…" : hasPassword ? "Change password" : "Turn on sign-in"}
          </button>
          {hasPassword && (
            <button
              className="btn btn-ghost"
              type="button"
              disabled={pending || !current}
              onClick={() => run(() => turnOffWebSignInAction({ current }), "Sign-in is off.")}
            >
              Turn off sign-in
            </button>
          )}
          {status && (
            <span className={status.ok ? "meta" : "exp-error"} role="status">
              {status.text}
            </span>
          )}
        </div>
      </form>
      <p className="meta">Forgot it? Run healthsave web-password reset on the server.</p>
    </article>
  );
}
