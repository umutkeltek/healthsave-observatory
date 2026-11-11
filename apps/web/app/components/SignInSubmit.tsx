"use client";

import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

// The sign-in form is a plain post (it works before any script loads). On a
// slow link that gives no sign it is under way, and a second tap posts the
// password again - each wrong one counts toward the lockout. Once the form
// submits, the button stays disabled until the next page; a page restored
// from the back/forward cache starts enabled again.
export function SignInSubmit({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLButtonElement>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    const form = ref.current?.form;
    if (!form) return;
    const onSubmit = () => setPending(true);
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) setPending(false);
    };
    form.addEventListener("submit", onSubmit);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      form.removeEventListener("submit", onSubmit);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, []);

  return (
    <button ref={ref} className="btn" type="submit" disabled={pending} aria-busy={pending || undefined}>
      {children}
    </button>
  );
}
