import { describe, expect, test } from "bun:test";

import { BRIEF_NOTE, briefLeadSentence, briefParagraphs, briefRead } from "./textPresentation";

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

  test("the medical note is a caption, not a paragraph of the brief", () => {
    const short = "Steps fell 9.4%.\n\nGeneral wellness information, not medical advice. If something worries you, talk to a doctor.";
    const long =
      "Steps fell 9.4%.\n\nThis is not medical advice. HealthSave analyses are informational only and cannot diagnose conditions.";
    expect(briefParagraphs(short)).toEqual(["Steps fell 9.4%."]);
    expect(briefParagraphs(long)).toEqual(["Steps fell 9.4%."]);
    expect(BRIEF_NOTE.length).toBeLessThan(60);
  });

  test("the card's read skips pillar headings and lifts the closing suggestion", () => {
    // Shape of a real llama3.1:8b weekly brief on the synthetic year (2026-11-16).
    const narrative = [
      "**Recovery**",
      "Your resting heart rate has decreased by 4.8% compared to your recent baseline. A lower resting heart rate can be a sign of improved cardiovascular health.",
      "**Activity**",
      "Steps decreased by 9.4% compared to your recent baseline.",
      "To address the dip, consider taking a short walk each day. Try taking the stairs instead of the elevator.",
      "",
      "General wellness information, not medical advice. If something worries you, talk to a doctor.",
    ].join("\n");
    const read = briefRead(narrative);
    expect(read.lead).toBe("Your resting heart rate has decreased by 4.8% compared to your recent baseline.");
    expect(read.takeaways).toEqual([
      "A lower resting heart rate can be a sign of improved cardiovascular health.",
      "Steps decreased by 9.4% compared to your recent baseline.",
    ]);
    expect(read.suggestion).toBe(
      "To address the dip, consider taking a short walk each day. Try taking the stairs instead of the elevator.",
    );
  });

  test("a suggestion standing alone drops its leading connector", () => {
    const read = briefRead("Steps fell 9.4% this week. Additionally, try taking the stairs at work.");
    expect(read.suggestion).toBe("Try taking the stairs at work.");
  });

  test("a brief without a closing suggestion shows none", () => {
    const read = briefRead("Steps fell 9.4% this week. Resting heart rate was steady at 55 bpm.");
    expect(read.suggestion).toBeNull();
    expect(read.lead).toBe("Steps fell 9.4% this week.");
  });
});

