// A saved view with no panels (an older save of an emptied Explore dashboard)
// used to render nothing on Today: an invisible card that took a slot and
// could not be removed.
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";

import { ExplorePanelCard } from "./ExplorePanelCard";

describe("saved Explore view on Today", () => {
  test("a view with no panels still shows, says so, and can be removed", async () => {
    const html = renderToStaticMarkup(
      await ExplorePanelCard({
        id: "panel_1",
        label: "Emptied",
        encodedState: "range=30d&grain=day&stat=mean&panels=",
        emptyNote: "This saved view has no panels.",
      }),
    );
    expect(html).toContain("Emptied");
    expect(html).toContain("This saved view has no panels.");
    expect(html).toContain("Remove");
  });
});
