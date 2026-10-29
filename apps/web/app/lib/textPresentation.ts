const GENERIC_BRIEF_TITLES = new Set([
  "daily brief",
  "daily briefing",
  "health summary",
  "weekly brief",
  "weekly health summary",
]);

const DIRECTION_WORD =
  "decreased|decreases|decreasing|decrease|dropped|drops|dropping|drop|fell|falls|falling|fall|declined|declines|declining|decline|reduced|reduces|reducing|reduction|lowered|lowers|lowering|lower|increased|increases|increasing|increase|rose|rises|rising|rise|grew|grows|growing|growth|gained|gains|gaining|gain|improved|improves|improving|improvement|higher|lost|loss|down|up";

const SIGN = "[-+\\u2212\\u2013]";
const NUMBER = "\\d+(?:\\.\\d+)?";
const UNIT = "(?:%|\\s+percent(?:age)?\\b)";

// Mirrors analysis.change_phrasing.normalize_direction_magnitude. Direction
// words take an absolute magnitude; "changed by -1.7%" is left alone.
export function agreeDirectionAndMagnitude(text: string): string {
  const wordThenSigned = new RegExp(
    `\\b(${DIRECTION_WORD})\\b(\\s+(?:by|of))?\\s*${SIGN}\\s*(${NUMBER})\\s*(${UNIT})`,
    "gi",
  );
  const signedThenWord = new RegExp(
    `${SIGN}\\s*(${NUMBER})\\s*(${UNIT})\\s+(${DIRECTION_WORD})\\b`,
    "gi",
  );
  const afterWord = text.replace(
    wordThenSigned,
    (_match, word: string, mid: string | undefined, num: string, unit: string) => {
      const glue = mid ? `${mid} ` : " ";
      return `${word}${glue}${num}${unit}`;
    },
  );
  return afterWord.replace(signedThenWord, (_match, num: string, unit: string, word: string) => {
    return `${num}${unit} ${word}`;
  });
}

function stripInlineMarkdown(line: string): string {
  return agreeDirectionAndMagnitude(line)
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
