const GENERIC_BRIEF_TITLES = new Set([
  "daily brief",
  "daily briefing",
  "health summary",
  "weekly brief",
  "weekly health summary",
]);

function stripInlineMarkdown(line: string): string {
  return line
    .replace(/^#{1,6}\s+/, "")
    .replace(/^\s*[-*]\s+/, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/_([^_]+)_/g, "$1")
    .replace(/\s+[\u2013\u2014-]\s+/g, ": ")
    .replace(/([A-Za-z)])[\u2013\u2014-]([A-Za-z(])/g, "$1, $2")
    .replace(/\s+-{2,}\s+/g, ": ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/[ \t]+/g, " ")
    .trim();
}

// The medical note the narrator appends (and the longer one older briefs carry)
// is shown once, as a small caption under the brief, not as a paragraph of it.
export const BRIEF_NOTE = "General wellness information, not medical advice.";

function isMedicalNote(paragraph: string): boolean {
  return /not medical advice/i.test(paragraph);
}

export function briefParagraphs(narrative: string): string[] {
  return narrative
    .replace(/\r\n/g, "\n")
    .split(/\n{2,}|\n/)
    .map(stripInlineMarkdown)
    .filter(
      (paragraph) =>
        Boolean(paragraph) && !GENERIC_BRIEF_TITLES.has(paragraph.toLowerCase()) && !isMedicalNote(paragraph),
    );
}

export function briefLeadSentence(narrative: string | null | undefined): string | null {
  if (!narrative) return null;

  const text = briefParagraphs(narrative)
    .filter((paragraph) => !GENERIC_BRIEF_TITLES.has(paragraph.toLowerCase()))
    .join(" ");

  if (!text) return null;

  const sentence = text.match(/^.+?[.!?](?=\s|$)/)?.[0] ?? text.slice(0, 180);
  return sentence.trim();
}

// A brief broken into what the card shows: the main read, up to two supporting
// points, and the closing suggestion. Headings the narrator writes on their
// own line ("Recovery", "Activity:") are never a sentence.
export type BriefRead = { lead: string | null; takeaways: string[]; suggestion: string | null };

const SUGGESTION =
  /\b(try|consider|take|taking|aim|start|add|keep|walk|stroll|stretch|bedtime|wind down|could|might|small step|one thing)\b/i;

function stripBriefLabel(text: string): string {
  return text.replace(/^(Recovery|Summary|Today|This week|Weekly brief):\s*/i, "").trim();
}

function isSentence(text: string): boolean {
  return text.split(/\s+/).filter(Boolean).length >= 4;
}

// "Additionally, try ..." reads oddly once it stands alone on the card.
function dropConnector(text: string): string {
  const trimmed = text.replace(/^(additionally|also|finally|lastly|plus|in addition|on top of that),?\s+/i, "");
  return (trimmed[0]?.toUpperCase() ?? "") + trimmed.slice(1);
}

export function briefRead(narrative: string): BriefRead {
  const sentences = briefParagraphs(narrative)
    .flatMap((paragraph) => stripBriefLabel(paragraph).split(/(?<=[.!?])\s+/))
    .map((sentence) => sentence.trim())
    .filter(isSentence);
  // The narrator is asked to end with one or two small suggestions: take the
  // trailing sentences that read like one, at most two.
  const tail: string[] = [];
  for (let i = sentences.length - 1; i > 0 && tail.length < 2; i--) {
    if (!SUGGESTION.test(sentences[i])) break;
    tail.unshift(sentences[i]);
  }
  const body = sentences.slice(0, sentences.length - tail.length);
  return {
    lead: body[0] ?? null,
    takeaways: body.slice(1, 3),
    suggestion: tail.length > 0 ? dropConnector(tail.join(" ")) : null,
  };
}

