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

export function briefParagraphs(narrative: string): string[] {
  return narrative
    .replace(/\r\n/g, "\n")
    .split(/\n{2,}|\n/)
    .map(stripInlineMarkdown)
    .filter((paragraph) => Boolean(paragraph) && !GENERIC_BRIEF_TITLES.has(paragraph.toLowerCase()));
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
