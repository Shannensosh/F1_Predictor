CUSTOM DRIVER PHOTOS  —  Drivers' Championship cards (main dashboard)
====================================================================

Drop a photo here to use it as the background of a driver's championship card
(e.g. the cockpit / candid close-up shots). It fills the card edge-to-edge.

FILENAME = the driver's id, lowercase, e.g.:
    antonelli.jpg     hamilton.jpg     russell.jpg     leclerc.jpg
    norris.jpg        piastri.jpg      verstappen.jpg   ...
(accepted: .jpg .jpeg .png .webp .avif)

• Use landscape images for the best fit (they're cropped to ~16:9).
• If no file is here for a driver, the card falls back to the official F1 headshot.
• After adding files, run:  python3 build.py   (the daily GitHub build also picks them up once committed).

Driver ids match the Ergast/Jolpica driverId — if unsure, check data/standings.json.
Only the top-3 in the championship show a card image, so antonelli / hamilton / russell
are the ones currently visible.
