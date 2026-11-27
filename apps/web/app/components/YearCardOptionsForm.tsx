"use client";

import type { CardOptions } from "../lib/yearCard";

// The share card's opt-ins live in the URL: the preview and the download both
// read it. A box applies the moment it changes (the same GET the "Update
// preview" button sends, which stays for browsers without JavaScript), so a
// ticked box can never sit ahead of the card it describes. autoComplete off
// stops a reload from restoring boxes the URL does not hold.
export function YearCardOptionsForm({ year, options }: { year: number; options: CardOptions }) {
  const apply = (event: { currentTarget: HTMLInputElement }) => event.currentTarget.form?.requestSubmit();
  return (
    <form method="get" action={`/year/${year}#yr-share-title`} className="yr-share-form" autoComplete="off">
      <label>
        <input type="checkbox" name="numbers" value="1" defaultChecked={options.numbers} onChange={apply} /> Show my
        numbers (days with data, sources, longest gap)
      </label>
      <label>
        <input type="checkbox" name="devices" value="1" defaultChecked={options.devices} onChange={apply} /> Show device
        names
      </label>
      <button type="submit" className="btn btn-ghost">
        Update preview
      </button>
    </form>
  );
}
