import { describe, expect, test } from "bun:test";

import { agreeDirectionAndMagnitude, briefLeadSentence, briefParagraphs } from "./textPresentation";

describe("text presentation", () => {
  test("turns narrator markdown into readable plain paragraphs", () => {
    expect(
      briefParagraphs(
        "**Weekly Health Summary**\n\n**Recovery** -- resting heart rate averaged 45.5 bpm.\n- Keep an eye on fatigue.",
      ),
    ).toEqual([
      "Recovery: resting heart rate averaged 45.5 bpm.",
      "Keep an eye on fatigue.",
    ]);
  });

  test("uses the first useful sentence instead of a generic brief title", () => {
    expect(
      briefLeadSentence(
        "**Weekly Health Summary**\n\n**Recovery** -- resting heart rate averaged 45.5 bpm. HRV improved.",
      ),
    ).toBe("Recovery: resting heart rate averaged 45.5 bpm.");
  });

  test("normalizes narrator dash punctuation", () => {
    expect(briefParagraphs("Recovery - HRV moved back into range.")).toEqual([
      "Recovery: HRV moved back into range.",
    ]);
    expect(briefParagraphs("Recovery \u2013 resting heart rate fell.")).toEqual([
      "Recovery: resting heart rate fell.",
    ]);
    expect(briefParagraphs("Attention-especially after poor sleep.")).toEqual([
      "Attention, especially after poor sleep.",
    ]);
    expect(briefParagraphs("Recovery was compared with your 30-day baseline.")).toEqual([
      "Recovery was compared with your 30-day baseline.",
    ]);
  });

  test("direction words and percent magnitudes agree", () => {
    expect(agreeDirectionAndMagnitude("HRV decreased by -1.7% this week.")).toBe(
      "HRV decreased by 1.7% this week.",
    );
    expect(agreeDirectionAndMagnitude("Steps increased by +4.2%.")).toBe("Steps increased by 4.2%.");
    expect(agreeDirectionAndMagnitude("Weight changed by -1.7%.")).toBe("Weight changed by -1.7%.");
    expect(agreeDirectionAndMagnitude("HRV was unchanged (0.0%).")).toBe("HRV was unchanged (0.0%).");
    expect(briefParagraphs("HRV decreased by -1.7% this week.")).toEqual([
      "HRV decreased by 1.7% this week.",
    ]);
    expect(briefParagraphs("HRV decreased by - 1.7% this week.")).toEqual([
      "HRV decreased by 1.7% this week.",
    ]);
    expect(briefParagraphs("Steps increased by +4.2% and weight changed by -0.4%.")).toEqual([
      "Steps increased by 4.2% and weight changed by -0.4%.",
    ]);
  });
});
