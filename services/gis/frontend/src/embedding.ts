/**
 * Running inside the main platform's page.
 *
 * The main platform (Dialog Smart Alerts) shows this application in a frame on its own origin (its
 * `/gis` page, served at `/gis-app/`). Inside a frame the application leaves out its own header; what is
 * clicked is shown in the map's own popup.
 */

/** Whether the application runs inside another page's frame. */
export function isEmbedded(view: Window = window): boolean {
  try {
    return view.parent !== view;
  } catch {
    // A parent of another origin cannot even be compared in some browsers: still a frame.
    return true;
  }
}
