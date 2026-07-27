import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { RecoveryHero } from "./RecoveryHero";

describe("RecoveryHero", () => {
  test("shows the headline and dek split from the summary", () => {
    const html = renderToStaticMarkup(
      <RecoveryHero
        freshness="fresh"
        score={82}
        summary="Recovery is solid. Sleep was restorative and HRV is above baseline."
        ribbon={null}
      />,
    );
    expect(html).toContain("Recovery is solid.");
    expect(html).toContain("Sleep was restorative");
  });

  test("maps score 82 to the Prime state with the corresponding CSS hook", () => {
    const html = renderToStaticMarkup(
      <RecoveryHero
        freshness="fresh"
        score={82}
        summary="Recovery is solid. Sleep was restorative."
        ribbon={null}
      />,
    );
    expect(html).toContain("state-prime");
    expect(html).toContain("Prime");
  });

  test("maps score 65 to Steady and score 50 to Caution", () => {
    const html65 = renderToStaticMarkup(
      <RecoveryHero freshness="fresh" score={65} summary="Steady day. Nothing dramatic." ribbon={null} />,
    );
    const html50 = renderToStaticMarkup(
      <RecoveryHero freshness="fresh" score={50} summary="Caution day. Watch your load." ribbon={null} />,
    );
    expect(html65).toContain("Steady");
    expect(html50).toContain("Caution");
  });

  test("renders 'Building' chip and muted tone when score is null", () => {
    const html = renderToStaticMarkup(
      <RecoveryHero freshness="fresh" score={null} summary="Building…" ribbon={null} />,
    );
    expect(html).toContain("Building");
    expect(html).toContain("dial-tone-muted");
  });

  test("shows evidence label only when provided", () => {
    const without = renderToStaticMarkup(
      <RecoveryHero freshness="fresh" score={70} summary="Steady. Calm baseline." ribbon={null} />,
    );
    const withEvidence = renderToStaticMarkup(
      <RecoveryHero
        freshness="fresh"
        score={70}
        summary="Steady. Calm baseline."
        ribbon={null}
        evidenceLabel="3 of 5 inputs · partial"
      />,
    );
    expect(without).not.toContain("hero-evidence");
    expect(withEvidence).toContain("hero-evidence");
    expect(withEvidence).toContain("3 of 5 inputs");
  });

  test("formats a negative delta with the en-dash character and abs()", () => {
    const html = renderToStaticMarkup(
      <RecoveryHero
        freshness="fresh"
        score={70}
        summary="Slightly down. Watch HRV."
        ribbon={null}
        deltaPct={-12.4}
      />,
    );
    expect(html).toContain("−12% vs baseline");
    expect(html).not.toContain("-12%");
  });
});
