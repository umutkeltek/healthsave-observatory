"use client";

import { type TransitionStartFunction, useState } from "react";

import { testConnectionAction } from "../../lib/actions";
import type { ConnectionInputPayload, TestConnectionResult } from "../../lib/api";

// Test-connection probe state. Takes the form's startTransition so the
// shared `pending` flag keeps disabling every button while a test runs
// (same joint-pending behavior as the pre-split monolith).
export function useConnectionTest(startTransition: TransitionStartFunction) {
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null);
  const [testErr, setTestErr] = useState<string | null>(null);

  function runTest(input: ConnectionInputPayload) {
    setTestResult(null);
    setTestErr(null);
    startTransition(async () => {
      const result = await testConnectionAction(input);
      if (result.ok && result.result) setTestResult(result.result);
      else setTestErr(result.error ?? "Test failed.");
    });
  }

  return { testResult, testErr, runTest };
}

export type ConnectionTest = ReturnType<typeof useConnectionTest>;
